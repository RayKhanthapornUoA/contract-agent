"""
Foundry File Search knowledge base (issue: Phase B).

Builds a knowledge base from:
  - the UoA contracting positions matrix (the rules),
  - the UoA standard templates (the PREFERRED / green reference),
  - the anonymised example contracts (real precedent; all flag colours),

uploads them to a Foundry vector store via the key-based /openai/v1 endpoint
(no AAD required), and exposes a file_search-grounded query helper.

State (vector store id + file ids) is persisted to kb_state.json so the store
is reused across runs instead of rebuilt.

CLI:
  python knowledge_base.py build     # (re)build the vector store
  python knowledge_base.py query "your question"
"""
import os
import sys
import json
import time
import glob

from dotenv import load_dotenv
from openai import OpenAI

from extractor import extract_text

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), override=True)

_client = OpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    base_url=os.getenv("AZURE_OPENAI_BASE_URL"),
)
_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")

_HERE = os.path.dirname(__file__)
KB_DIR = os.path.join(_HERE, "kb_docs")
STATE_PATH = os.path.join(_HERE, "kb_state.json")
TEMPLATES_DIR = os.path.join(_HERE, "Contracts")
EXAMPLES_DIR = os.path.join(_HERE, "Contracts", "Redacted Examples")
VECTOR_STORE_NAME = "contract-knowledge-base"


# -- Build the knowledge-base source documents ---------------------------------

def _write_positions_doc() -> str:
    positions = json.load(open(os.path.join(_HERE, "contract_positions.json"), encoding="utf-8"))
    buf = ["UNIVERSITY OF AUCKLAND - PREFERRED CONTRACTING POSITIONS",
           "(The rules a contract is reviewed against. Green=preferred, Amber=acceptable, Red=outside/escalate.)\n"]
    for i, p in enumerate(positions, 1):
        buf += [f"## {i}. {p['clause_topic']}",
                f"Preferred (green): {p['green']}",
                f"Acceptable (amber): {p['amber']}",
                f"Outside / escalate (red): {p['red']}",
                f"Escalation route: {p.get('escalation_route', '')}",
                f"Reference: {p.get('reference_doc', '')}", ""]
    path = os.path.join(KB_DIR, "00_UoA_contracting_positions.md")
    open(path, "w", encoding="utf-8").write("\n".join(buf))
    return path


def build_kb_documents() -> list:
    """Extract all source docs to text files under kb_docs/. Returns file paths."""
    os.makedirs(KB_DIR, exist_ok=True)
    paths = [_write_positions_doc()]

    for docx in sorted(glob.glob(os.path.join(TEMPLATES_DIR, "*.docx"))):
        name = os.path.basename(docx)
        data = open(docx, "rb").read()
        text = extract_text(data, name)
        if not text.strip():
            continue
        out = os.path.join(KB_DIR, "template_" + name.replace(".docx", "").replace(" ", "_") + ".txt")
        header = f"[UoA STANDARD TEMPLATE - represents the PREFERRED (green) position]\nFile: {name}\n\n"
        open(out, "w", encoding="utf-8").write(header + text)
        paths.append(out)

    for pdf in sorted(glob.glob(os.path.join(EXAMPLES_DIR, "*.pdf"))):
        name = os.path.basename(pdf)
        data = open(pdf, "rb").read()
        try:
            text = extract_text(data, name)
        except Exception as e:
            print(f"  [skip] {name}: extraction failed ({type(e).__name__})")
            continue
        if not text.strip():
            print(f"  [skip] {name}: no text")
            continue
        out = os.path.join(KB_DIR, "example_" + name.replace(".pdf", "").replace(" ", "_") + ".txt")
        header = ("[ANONYMISED EXAMPLE CONTRACT - real precedent; may contain green/amber/red/blue clauses]\n"
                  f"File: {name}\n\n")
        open(out, "w", encoding="utf-8").write(header + text)
        paths.append(out)

    return paths


# -- Vector store --------------------------------------------------------------

def rebuild_knowledge_base() -> str:
    """Build docs, upload them, create a fresh vector store, persist state."""
    paths = build_kb_documents()
    print(f"Built {len(paths)} knowledge-base documents.")

    file_ids = []
    for p in paths:
        with open(p, "rb") as fh:
            f = _client.files.create(file=fh, purpose="assistants")
        file_ids.append(f.id)
    print(f"Uploaded {len(file_ids)} files.")

    vs = _client.vector_stores.create(name=VECTOR_STORE_NAME, file_ids=file_ids)
    print(f"Vector store {vs.id} created; processing...")
    for _ in range(60):
        cur = _client.vector_stores.retrieve(vs.id)
        fc = cur.file_counts
        if fc and fc.in_progress == 0:
            print(f"  done: completed={fc.completed} failed={fc.failed} total={fc.total}")
            break
        time.sleep(3)

    state = {"vector_store_id": vs.id, "file_ids": file_ids,
             "num_docs": len(paths), "name": VECTOR_STORE_NAME}
    json.dump(state, open(STATE_PATH, "w"), indent=2)
    print(f"Saved state to kb_state.json")
    return vs.id


def get_vector_store_id() -> str:
    if not os.path.exists(STATE_PATH):
        raise RuntimeError("No knowledge base built yet. Run: python knowledge_base.py build")
    return json.load(open(STATE_PATH))["vector_store_id"]


def query_kb(question: str, vector_store_id: str = None) -> str:
    vs_id = vector_store_id or get_vector_store_id()
    r = _client.responses.create(
        model=_deployment,
        input=question,
        tools=[{"type": "file_search", "vector_store_ids": [vs_id]}],
    )
    return r.output_text


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "build":
        rebuild_knowledge_base()
    elif len(sys.argv) >= 3 and sys.argv[1] == "query":
        print(query_kb(sys.argv[2]))
    else:
        print(__doc__)
