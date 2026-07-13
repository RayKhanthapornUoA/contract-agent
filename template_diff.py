"""
Template diff (issue #7): compare an uploaded contract against the matching UoA
standard template to surface MISSING and MODIFIED standard clauses.

Approach (embedding-based, uses text-embedding-3-small):
  1. Map the classified contract type -> the matching UoA template.
  2. Segment both the template and the contract into clauses.
  3. Embed every clause; for each TEMPLATE clause find its best-matching CONTRACT
     clause by cosine similarity.
  4. Classify each standard clause as:
        - missing  : no contract clause is similar (risk - a standard protection absent)
        - modified : present but materially different (review)
        - aligned  : present and close to the standard
This restores the "missing standard clause = risk" detection that was removed
from the flagger (which now only grades clauses actually present).

Requires a deployed embedding model; set AZURE_OPENAI_EMBED_DEPLOYMENT in .env
(defaults to "text-embedding-3-small").
"""
import os
import re
import math

from dotenv import load_dotenv
from openai import OpenAI

from extractor import extract_text
from chunking import segment_text  # fixed-size fallback for poorly-structured contracts

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), override=True)

# Embeddings live at the ACCOUNT-level endpoint, not the project-scoped one the
# chat/responses API uses. Derive it by stripping the "/api/projects/<name>" path
# (override with AZURE_OPENAI_EMBED_BASE_URL if your setup differs).
_proj_base = os.getenv("AZURE_OPENAI_BASE_URL", "").rstrip("/")
_embed_base = os.getenv("AZURE_OPENAI_EMBED_BASE_URL") or (
    _proj_base.split("/api/projects")[0].rstrip("/") + "/openai/v1"
)
_client = OpenAI(api_key=os.getenv("AZURE_OPENAI_API_KEY"), base_url=_embed_base)
_EMBED_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBED_DEPLOYMENT", "text-embedding-3-small")

_HERE = os.path.dirname(__file__)
_TEMPLATES_DIR = os.path.join(_HERE, "Contracts")

# classified type -> representative UoA standard template
_TYPE_TEMPLATE_MAP = {
    "Material Transfer Agreements": "UoA-Material_Transfer_Agreement incoming-Aug 2024.docx",
    "Data Transfer Agreements": "UoA-Data Transfer Agreement Template (incoming) April 2024 .docx",
    "Confidential Disclosure Agreements": "UoA-CDA Two Way Template.docx",
    "Collaboration Agreements": "UoA-Research Collaboration Agreement Template (1).docx",
    "Subcontracts": "UoA-Template Subcontractor Agreement_2025 (1) (1).docx",
    "Research Contracts": "UoA-Research Services Agreement (Agency) _June 2024 .docx",
    "Consulting Contracts": "UoA-Provision of Services Agreement (Agency)_June 2024.docx",
    "Student Research Agreements": "UoA-Student Research Agreement Template (April 2018).docx",
    # Clinical Trial Agreements, Memorandum of Understanding, Variation / Amendment,
    # and Unknown / Escalate have no mapped template here -> compare() returns None.
}

# Cosine-similarity thresholds, calibrated on real data with text-embedding-3-small.
# Legal text has a high similarity baseline (even unrelated clauses ~0.45), so a
# present/aligned clause scores >=0.62 while a genuinely absent one scores <0.52.
# These are heuristic and advisory (a human reviews the result).
_ALIGNED_AT = 0.62
_MISSING_BELOW = 0.52

# Structural / administrative sections that are NOT substantive risk clauses; we
# do not report these as "missing" (every contract has parties, a signature block,
# schedules, etc., and matching them adds noise rather than risk signal).
_STRUCTURAL_HEADINGS = {
    "parties", "the parties", "introduction", "agreement", "background", "recitals",
    "contract details", "executed", "execution", "signed", "signature", "general terms",
    "definitions and interpretation", "interpretation", "definitions", "contents",
    "table of contents", "commencement", "preamble",
}


def _is_structural(heading: str) -> bool:
    h = re.sub(r"[^a-z ]", "", heading.lower()).strip()
    if any(h == s or h.startswith(s + " ") for s in _STRUCTURAL_HEADINGS):
        return True
    if re.search(r"\b(schedule|appendix|annex|exhibit)\b", h):  # doc-specific fill-ins
        return True
    return False


def _is_placeholder(text: str) -> bool:
    """A template clause that is mostly fill-in placeholders ([insert ...], [X], Not Used)."""
    s = text.strip()
    if not s:
        return True
    bracketed = sum(len(m) for m in re.findall(r"\[[^\]]*\]", s))
    if bracketed / max(1, len(s)) > 0.5:
        return True
    low = re.sub(r"[^a-z ]", "", s.lower()).strip()
    if low in ("not used", "insert", "tbc", "tbd"):
        return True
    return False


def _is_substantive(heading: str, body: str) -> bool:
    return not _is_structural(heading) and not _is_placeholder(heading + " " + body)


def _is_heading(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if re.match(r"^\d+(\.\d+)*\.?\s+[A-Za-z]", s):  # "1. TERM", "2.3 Confidentiality"
        return True
    # ALL-CAPS section title (e.g. "CONFIDENTIALITY", "INTELLECTUAL PROPERTY")
    if 3 <= len(s) <= 60 and s == s.upper() and any(c.isalpha() for c in s):
        return True
    return False


def segment_clauses(text: str):
    """Split text into (heading, body) clause units using heading detection."""
    clauses, head, body = [], None, []
    for raw in text.split("\n"):
        s = raw.strip()
        if not s:
            continue
        if _is_heading(s):
            if head is not None or body:
                clauses.append((head or "(preamble)", "\n".join(body)))
            head, body = s, []
        else:
            body.append(s)
    if head is not None or body:
        clauses.append((head or "(preamble)", "\n".join(body)))
    # drop trivially short units
    return [(h, b) for h, b in clauses if len((h + " " + b).strip()) > 25]


def template_for_type(contract_type: str):
    name = _TYPE_TEMPLATE_MAP.get(contract_type)
    if not name:
        return None
    path = os.path.join(_TEMPLATES_DIR, name)
    return path if os.path.exists(path) else None


def _embed(texts):
    out = []
    # batch to keep requests modest
    for i in range(0, len(texts), 64):
        resp = _client.embeddings.create(model=_EMBED_DEPLOYMENT, input=texts[i:i + 64])
        out.extend(d.embedding for d in resp.data)
    return out


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def compare(contract_text: str, contract_type: str):
    """Return a list of {template_clause, status, similarity, contract_snippet}
    for each standard clause, or None if no template maps to this type."""
    tmpl_path = template_for_type(contract_type)
    if not tmpl_path:
        return None

    tmpl_text = extract_text(open(tmpl_path, "rb").read(), os.path.basename(tmpl_path))
    # Only check SUBSTANTIVE standard clauses; drop structural sections (parties,
    # signatures, schedules) and fill-in placeholders so we don't report them missing.
    tmpl_clauses = [(h, b) for h, b in segment_clauses(tmpl_text) if _is_substantive(h, b)]
    con_clauses = segment_clauses(contract_text)
    if len(con_clauses) < 3:  # poorly structured / OCR -> fall back to fixed chunks
        con_clauses = [("", c) for c in segment_text(contract_text, max_chars=1500, overlap=200)]
    if not tmpl_clauses or not con_clauses:
        return None

    tmpl_emb = _embed([f"{h}: {b}"[:2000] for h, b in tmpl_clauses])
    con_emb = _embed([f"{h}: {b}"[:2000] for h, b in con_clauses])

    results = []
    for (h, b), te in zip(tmpl_clauses, tmpl_emb):
        sims = [_cosine(te, ce) for ce in con_emb]
        best_i = max(range(len(sims)), key=lambda i: sims[i])
        best = sims[best_i]
        status = ("missing" if best < _MISSING_BELOW
                  else "aligned" if best >= _ALIGNED_AT else "modified")
        ch, cb = con_clauses[best_i]
        results.append({
            "template_clause": h,
            "status": status,
            "similarity": round(best, 3),
            "contract_snippet": (cb[:140] if status != "missing" else ""),
        })
    return {"template": os.path.basename(tmpl_path), "clauses": results}
