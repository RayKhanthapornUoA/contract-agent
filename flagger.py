import os
import re
import json
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

from chunking import segment_text, merge_gradings

load_dotenv()

_openai_key = os.getenv("AZURE_OPENAI_API_KEY")
_openai_base_url = os.getenv("AZURE_OPENAI_BASE_URL")
_openai_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")

COLOUR_FLAG_PROMPT = """
You are a contract review assistant.

Your task is to analyse a contract and compare it against a predefined contract positions matrix.

You must review the contract carefully and identify all major clauses that ACTUALLY APPEAR in the contract text below, not just obvious matches.

---

### TASK

For each clause you identify:

1. Determine the clause topic
2. Extract the exact relevant wording from the contract
3. Compare the wording against the contract positions provided
4. Assign a colour flag based on the clause's OUTCOME/EFFECT (not its exact wording):
     - Green = the clause achieves the University's PREFERRED position (same practical effect, even if worded differently from the position text)
     - Amber = the clause achieves an ACCEPTABLE (but not preferred) position, or is a minor, manageable deviation worth a Contract Manager's review
     - Red = the clause genuinely CONFLICTS WITH, EXCEEDS, or BREACHES the acceptable position (e.g. a threshold exceeded, a required protection removed, a prohibited term included) and therefore requires escalation
     - Blue = the clause's topic is genuinely NOT addressed anywhere in the contract positions matrix
5. Provide a clear and specific reason based on comparison
6. Indicate whether escalation is required
7. Provide concise "next_steps" action guidance suited to the flag (e.g. Green: "No action required."; Amber: "Contract Manager to review."; Red: "Must be revised before signing."; Blue: "Escalate to the relevant office for a policy decision.")
8. For Amber and Red clauses only, provide "suggested_revision": replacement clause wording that would bring the clause into line with the UoA preferred position. Leave it as "" for Green and Blue.

---

### IMPORTANT RULES

- You MUST use only the provided contract text and contract positions
- Do NOT invent clause topics or positions
- Grade ONLY clauses that ACTUALLY APPEAR in the contract text. Do NOT output a grading for a position or topic that is not present in the contract text (detection of missing standard clauses is handled separately).
- Use Blue only when the clause exists but is outside the contract positions scope
- If a clause topic is NOT found in the contract positions, only return Blue when the clause exists in the contract but is outside the positions matrix
- Only assign Blue when such a clause is genuinely present; do NOT force a Blue clause if none applies
- Do NOT rely only on keywords - interpret meaning and context
- Judge by OUTCOME, not wording: if a clause achieves the preferred or an acceptable position, flag it Green or Amber even if its wording differs from the position text
- Reserve Red ONLY for genuine conflicts with the acceptable position: a threshold or limit is EXCEEDED (e.g. an embargo longer than 12 months, liability above the cap), a PROHIBITED term is present (e.g. 'hold harmless', uncapped liability), or a required protection is ENTIRELY removed/absent in a way that creates material risk
- If a clause SATISFIES the acceptable tier on its MAIN dimension (e.g. duration, amount, jurisdiction) but merely MISSES a preferred detail (e.g. a standard exclusion/carve-out or protective wording is not spelled out), flag it AMBER (Contract Manager to review and add the detail) and put the missing detail in suggested_revision - do NOT flag it Red
- Example: a confidentiality clause whose duration is within the acceptable 5-7 year range but lacks the standard exclusions is AMBER, not Red
- Consider risks, ambiguity, and conditions (not just numbers or thresholds)
- Be precise: distinguish between "exactly 60 days" vs "more than 60 days"
- Extract SHORT, relevant contract text only (not full paragraphs)
- Capture the clause's number or heading from the contract in "clause_reference" (e.g. "Clause 7.2" or the section title); use "" if there is no identifiable number or heading
- "suggested_revision" must be concrete replacement clause wording (a sentence or two) for Amber and Red clauses; keep it aligned to the UoA preferred position and "" for Green and Blue
- "next_steps" must be a short action line, not a restatement of the reason

---

### OUTPUT FORMAT (JSON ONLY)

Return a JSON array:

[
    {{
        "clause_reference": "",
        "clause_topic": "",
        "detected_text": "",
        "matched_position": "",
        "flag": "green | amber | red | blue",
        "reason": "",
        "next_steps": "",
        "suggested_revision": "",
        "escalation": "yes | no"
    }}
]

---

### WORKED EXAMPLES
Each example shows ONE clause and its correct grading. For the contract below, return an ARRAY of gradings covering all major clauses, using this same JSON shape per item.
{fewshot}

---

### CONTRACT TEXT:
{contract_text}

---

### CONTRACT POSITIONS:
{positions_json}
"""

_FEWSHOT_PATH = os.path.join(os.path.dirname(__file__), "colour_flag.jsonl")


def _build_fewshot_block() -> str:
    """Load clause-flagging exemplars (if present) into a prompt block.

    Falls back to a placeholder so the flagger degrades gracefully to zero-shot.
    """
    if not os.path.exists(_FEWSHOT_PATH):
        return "(none provided)"
    blocks = []
    with open(_FEWSHOT_PATH, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            ex = json.loads(line)
            clause = ex.get("clause_text", "").strip()
            output = json.dumps(ex.get("output", {}), ensure_ascii=False, indent=2)
            blocks.append(f"Clause text:\n{clause}\n\nCorrect grading:\n{output}")
    return "\n\n".join(blocks) if blocks else "(none provided)"


_FEWSHOT_BLOCK = _build_fewshot_block()


def _flag_one_chunk(client, chunk: str, positions_str: str) -> list:
    """Flag a single chunk; return a parsed list of gradings ([] on failure)."""
    prompt = COLOUR_FLAG_PROMPT.format(
        fewshot=_FEWSHOT_BLOCK,
        contract_text=chunk,
        positions_json=positions_str,
    )
    # NOTE: file_search is deliberately NOT attached here. Empirically, grounding
    # the structured-grading call with the KB made the model recite the positions
    # matrix (grading clauses not present in the contract) and intermittently
    # return no JSON. Structured grading stays rule-based + positions-in-context
    # (reliable); the KB is used for precedent/Q&A via separate, text-only calls.
    # Retry transient blips (empty / non-JSON output, momentary API errors).
    for _ in range(3):
        try:
            response = client.responses.create(model=_openai_deployment, input=prompt)
            raw = response.output_text or ""
            extracted = extract_json_array(raw)
            if extracted:
                data = json.loads(extracted)
                if isinstance(data, list):
                    return data
            elif raw.strip() == "[]":
                return []  # legitimately empty chunk - do not retry
        except Exception:
            continue
    return []


def flag_contract_clauses(contract_text: str, positions_json: list) -> str:
    """Segment the WHOLE contract, flag each chunk concurrently, and merge.

    Returns a JSON-array string (most-severe-per-topic) so existing callers that
    run extract_json_array + json.loads continue to work unchanged.
    """
    client = OpenAI(api_key=_openai_key, base_url=_openai_base_url)
    positions_str = json.dumps(positions_json, indent=2)
    chunks = segment_text(contract_text)
    if not chunks:
        return "[]"

    with ThreadPoolExecutor(max_workers=min(8, len(chunks))) as ex:
        per_chunk = list(
            ex.map(lambda c: _flag_one_chunk(client, c, positions_str), chunks)
        )

    merged = merge_gradings(per_chunk)
    return json.dumps(merged, ensure_ascii=False)


def extract_json_array(text: str):
    if not text:
        return None

    cleaned = text.strip()

    fenced_match = re.search(r"```json\s*(\[.*?\])\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    if fenced_match:
        return fenced_match.group(1)

    array_match = re.search(r"(\[\s*\{.*?\}\s*\])", cleaned, re.DOTALL)
    if array_match:
        return array_match.group(1)

    return None
