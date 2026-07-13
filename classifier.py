import os
import re
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

_openai_key = os.getenv("AZURE_OPENAI_API_KEY")
_openai_base_url = os.getenv("AZURE_OPENAI_BASE_URL")
_openai_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")

CLASSIFICATION_PROMPT = """
You are a contract classification assistant for the University of Auckland Research Grants and Contracts (RGC) team.

Classify the contract into exactly ONE of the following allowed contract types:

- Research Contracts
- Consulting Contracts
- Student Research Agreements
- Clinical Trial Agreements
- Subcontracts
- Material Transfer Agreements
- Data Transfer Agreements
- Collaboration Agreements
- Confidential Disclosure Agreements
- Memorandum of Understanding
- Variation / Amendment
- Unknown / Escalate

Definitions and decision rules:

- Material Transfer Agreements: the core purpose is the transfer of PHYSICAL research materials (e.g. biological samples, cell lines, reagents, compounds, chemicals, specimens). Markers: a defined "Materials", restrictions on use to a stated research purpose, no transfer to third parties, return or destruction of materials. No dataset sharing and no delivery of services.

- Data Transfer Agreements: the core purpose is sharing, transferring, or providing access to a DATASET or database. Markers: a defined "Data", a Provider supplying data to the University, an Approved Purpose, data protection/privacy obligations, secure transfer or access, return or destruction of data. Treat a "Data Access Agreement" (access to data in place) as a Data Transfer Agreement.

- Confidential Disclosure Agreements: the SOLE substantive purpose is protecting confidential information exchanged for discussions or evaluation (one-way or two-way). Markers: a defined "Confidential Information", non-disclosure and non-use obligations, AND no deliverables, fees, transfer of materials, data-for-a-project, or joint research.

- Collaboration Agreements: two or more parties JOINTLY carry out research as peers. Markers: each party carries out the Research, respective Contributions/Inputs, a shared Research Plan, Background versus foreground IP held per party, joint ownership or cross-licensing of Results, joint governance. May be multi-party.

- Subcontracts: the University has been funded by a Funder for a Research Project and engages a Subcontractor (or is itself engaged under a prime/head agreement) to perform a defined scope. Markers: reference to a Funder or prime/head contract, flow-down obligations, a Statement of Work / Services / Deliverables / milestones delivered under that funded project.

- Clinical Trial Agreements: a sponsored or investigator-initiated CLINICAL TRIAL. Markers: "clinical trial", a CTRA, trial participants/subjects, ethics approval, recruitment/sites, indemnity and compensation, the NZACRes template.

- Student Research Agreements: a THREE-PARTY agreement (University, Client, and a named Student) where a student undertakes research as part of their academic course of study, the client supports it, and the University supervises. Markers: a named "Student", "academic course of study", University-provided supervision.

- Consulting Contracts: the University provides ACADEMIC EXPERTISE, advice, opinion, or professional services as a service to a client - rather than conducting a research project. Markers: "consultancy"/"consulting" services, expert advice/opinion/assessment, a deliverable that is advice or a report, fees; typically NOT generating new research knowledge and no student thesis.

- Research Contracts: a funded RESEARCH agreement where the University conducts research, funded or commissioned by a government body, an industry/commercial entity, or another institution. Markers: a Funder or Client funding the University to perform research, a defined research scope/Results, Fees or funding, Background IP and Publication clauses. (The funder may be public-good or commercial - this does NOT change the type. If the engagement is advice/expertise rather than conducting research, use Consulting Contracts instead.)

- Memorandum of Understanding: a broad, high-level statement of intent to collaborate, usually NON-BINDING or with only limited binding terms and no detailed obligations or fees. Markers: "Memorandum of Understanding"/"MOU", "non-binding", "statement of intent", aspirational language.

- Variation / Amendment: ONLY use this when the document EXPLICITLY states it varies or amends a NAMED existing/principal agreement (e.g. titled "Deed of Variation"/"Amendment", or "This Variation amends the Agreement dated ..."). It changes specific terms of that prior agreement rather than being a standalone contract. Do NOT infer Variation from sparse, ambiguous, or incomplete text - if unsure, it is NOT a Variation.

- Unknown / Escalate: use when the contract does not clearly fit a single type above, mixes several, is a pure goods/procurement contract with no research element, or is otherwise outside this framework.

Apply these tests IN ORDER and pick the FIRST that matches:
1. Document EXPLICITLY varies/amends a named existing agreement -> Variation / Amendment
2. Broad, non-binding statement of intent -> Memorandum of Understanding
3. Core subject is physical materials -> Material Transfer Agreements
4. Core subject is a dataset or data access -> Data Transfer Agreements
5. Only confidentiality, with no other substantive obligations -> Confidential Disclosure Agreements
6. A clinical trial -> Clinical Trial Agreements
7. Three-party Client / University / Student academic-study arrangement -> Student Research Agreements
8. Performed under a Funder / prime / head contract with flow-down -> Subcontracts
9. Multiple parties jointly conduct research with shared contributions/IP -> Collaboration Agreements
10. Provides academic expertise/advice as a service (not conducting a research project) -> Consulting Contracts
11. Conducts funded research (government, industry, or other institution) -> Research Contracts
12. None of the above clearly apply, or it is mixed -> Unknown / Escalate

Rules:
- Choose exactly ONE type from the allowed list above. Do NOT invent new types.
- Base your answer ONLY on the contract text.
- You MUST include 1-3 short direct quotes from the contract in "evidence" (each 5-15 words).
- Do NOT leave the evidence field empty and do NOT use placeholders like "quote from contract".
- If the type is genuinely unclear, mixed, or pure procurement, return "Unknown / Escalate".

Return JSON only:

{
  "contract_type": "",
  "confidence": "high | medium | low",
  "evidence": [
    ""
  ],
  "reason": ""
}

Worked examples (study these, then classify the NEW contract in the same JSON format):
{fewshot}

Now classify the following contract.

Contract text:
{text}
"""

_FEWSHOT_PATH = os.path.join(os.path.dirname(__file__), "fewshot_examples.jsonl")


def _build_fewshot_block() -> str:
    """Load few-shot exemplars (if present) into a prompt block.

    Returns an empty-equivalent note if the file is missing, so the classifier
    gracefully degrades to zero-shot.
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
            excerpt = ex.get("contract_excerpt", "").strip()
            output = json.dumps(ex.get("output", {}), ensure_ascii=False, indent=2)
            blocks.append(
                f"--- Example ---\nContract text:\n{excerpt}\n\nCorrect output:\n{output}"
            )
    return "\n\n".join(blocks) if blocks else "(none provided)"


_FEWSHOT_BLOCK = _build_fewshot_block()


def _extract_json_object(text: str) -> str:
    """Return the JSON object from a model reply, tolerating code fences or
    surrounding prose. Falls back to the raw text if no object is found."""
    if not text:
        return text
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        return cleaned[start:end + 1]
    return cleaned


def classify_contract_type(text: str) -> str:
    client = OpenAI(api_key=_openai_key, base_url=_openai_base_url)
    prompt = CLASSIFICATION_PROMPT.replace("{fewshot}", _FEWSHOT_BLOCK).replace(
        "{text}", text[:16000]
    )
    # Retry transient blips (empty / non-JSON output, momentary API errors).
    last = ""
    for _ in range(3):
        try:
            response = client.responses.create(model=_openai_deployment, input=prompt)
            candidate = _extract_json_object(response.output_text)
            obj = json.loads(candidate)
            if isinstance(obj, dict) and obj.get("contract_type"):
                return candidate
            last = candidate
        except Exception:
            continue
    return last
