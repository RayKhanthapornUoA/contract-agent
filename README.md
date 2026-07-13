# Contract Reviewer Agent

Code adapted from Samnieng.

This branch reworks the starter into a University of Auckland (UoA) Research Grants
and Contracts (RGC) review agent. A user uploads a contract; the agent extracts the
text, classifies the contract type, reviews every clause against the University's
preferred contracting positions (Green / Amber / Red / Blue), suggests revised
wording for deviations, and compares the contract to the matching UoA standard
template. Reasoning runs on **Microsoft Foundry** (gpt-5-mini + text-embedding-3-small
+ a File Search knowledge base); OCR runs on **Azure Document Intelligence**; the UI
and orchestration are a local Python/Streamlit app.

> This document is a working record and is **subject to change** as the project evolves.

---

## How the project works

**Components**

- **Streamlit app (local UI)** — upload a contract; view the report; download a PDF; ask the knowledge base.
- **Python backend (local modules)** — orchestration and all analysis logic.
- **Local source data** — `contract_positions.json` (the 21 UoA positions = the rulebook), the UoA templates under `Contracts/`, and the few-shot exemplars (`fewshot_examples.jsonl`, `colour_flag.jsonl`).
- **Microsoft Foundry (cloud)** — `gpt-5-mini` (classification + clause flagging, via the Responses API), `text-embedding-3-small` (template-comparison embeddings), and a **File Search vector store** (the knowledge base).
- **Azure Document Intelligence (cloud)** — `prebuilt-read` OCR for scanned PDFs.

**Request flow (one contract review)**

1. User uploads a contract in the **Streamlit app**.
2. The **Python backend** extracts text — local extractors (`python-docx` / `PyPDF2`) first; **Azure Document Intelligence** OCR only for scanned PDFs.
3. The backend sends the text + the **local positions matrix** to **gpt-5-mini on Foundry** to (a) classify the contract type and (b) flag each clause Green/Amber/Red/Blue with reasons, next steps, and (for Amber/Red) suggested revisions.
4. The backend runs a **template comparison**: it embeds the contract's clauses and the matching **local UoA template** with **text-embedding-3-small on Foundry** and aligns them to find missing/modified standard clauses.
5. Results render in the **Streamlit app** and as a downloadable **PDF**.
6. Separately, the **knowledge base** (a Foundry File Search vector store built from the local source docs) powers the **"Ask the Knowledge Base"** Q&A.

So: **Streamlit (UI) → Python backend → { local data + Foundry gpt-5-mini + Foundry embeddings + Azure DI } → Streamlit / PDF**, with the **Foundry File Search knowledge base** built from local source and queried for Q&A.

---

## Code files

| File | What it does |
|---|---|
| `app.py` | Streamlit entry point / orchestrator: upload → extract → classify + flag → template diff → four-section report + PDF; hosts the "Ask the Knowledge Base" box and the confidentiality notice. |
| `extractor.py` | Text-extraction dispatcher — local extractors for TXT/DOCX/text PDFs; Azure Document Intelligence OCR fallback for scanned PDFs; content-hash OCR cache. |
| `classifier.py` | Contract-type classification (11-type prompt + ordered decision tree + few-shot exemplars; JSON-robust; retry). |
| `flagger.py` | Clause review: flags each clause against the positions matrix (Green/Amber/Red/Blue) with reason, next steps, suggested revision, escalation; chunked; retry. |
| `chunking.py` | `segment_text()` splits a contract into chunks (whole-doc coverage); `merge_gradings()` merges per-chunk results most-severe-per-topic. |
| `template_diff.py` | Embedding-based comparison of the contract to its matching UoA template → missing / modified standard clauses. |
| `knowledge_base.py` | Builds and queries the Foundry File Search knowledge base (powers the Q&A). |
| `report_export.py` | Generates the downloadable PDF report (`fpdf2`). |
| `ui_components.py` | Streamlit rendering: CSS, classification card, the four flag sections, the template-comparison block. |
| `eval_classification.py` | Classification-accuracy harness over the labelled example contracts. |
| `_visual_check.py` | Dev-only: renders the report with sample data (no API) for layout/CSS checks. |

**Data & config:** `contract_positions.json` (the 21 UoA positions = rulebook), `fewshot_examples.jsonl` (classification exemplars), `colour_flag.jsonl` (clause-flagging exemplars), `requirements.txt`, `.streamlit/config.toml` (telemetry off), `.env` (endpoints + keys — committed to this private team repo).

---

## Changes (per area: why → what → how)

### 1. Contracting positions — the rulebook
- **Why:** the starter encoded generic commercial positions (SaaS payment terms, etc.); the agent must review against the University's *actual* preferred positions.
- **What changed:** `contract_positions.json` rewritten as the **21 positions** transcribed from *Contracting Positions – Approvals and Escalation Protocol_Final_Sept_25.pdf*, each with `green`/`amber`/`red` text, `escalation_route`, `explanation_hint`, and `reference_doc`.
- **How it's effective:** loaded once and passed verbatim into the flagging prompt as the comparison baseline; `clause_topic` + `explanation_hint` + `escalation_route` + `reference_doc` also drive the on-card hints, escalation routing, and citations in the report.

### 2. Text extraction
- **Why:** inputs are PDF/DOCX/TXT, and many example contracts are scanned images; extraction must be reliable and low-cost.
- **What changed:** `extractor.py` gained an `extract_text(bytes, filename)` dispatcher, table-aware DOCX reading, a PDF "local-first, OCR-fallback" path (Azure `prebuilt-read` when local text is sparse, < 100 chars/page), a content-hash **OCR cache**, and a cost-guard log before any Azure call. `app.py` calls the dispatcher.
- **How it's effective:** TXT/DOCX and text PDFs are read **locally for free**; only scanned PDFs hit Azure DI; the cache means a given scan is never OCR'd twice. The whole pipeline downstream only sees plain text, so the source (local vs OCR vs, later, blob) is interchangeable.

### 3. Contract type classification
- **Why:** the first in-scope task is identifying the contract type; the starter used commercial/IT types.
- **What changed:** `classifier.py` prompt rewritten to the **11 webinar contract types** (Research, Consulting, Student Research, Clinical Trial, Subcontracts, Variations/Amendments, CDA, MTA, DTA, Collaboration, MOU) plus *Unknown / Escalate*, with per-type definitions and an **ordered decision tree**. Added few-shot exemplars (`fewshot_examples.jsonl`), JSON-robust output extraction, a 3× retry for transient blips, and a 16k-char input cap. (See the **knowledge base** note below — classification uses few-shot exemplars, not the File Search KB.)
- **How it's effective:** `classify_contract_type()` builds the prompt (rules + decision tree + exemplars), calls gpt-5-mini on Foundry, and returns JSON `{contract_type, confidence, evidence, reason}`. The decision tree resolves the hard pairs (MTA vs DTA, Consulting vs Research, etc.); the retry wrapper re-calls on empty/non-JSON output so transient failures self-recover.

### 4. Clause review / flagging — *the clause example*
- **Why:** we need a method to obtain each clause and compare it against the University's positions, then flag deviations.
- **What changed (files that cooperate):**
  - `flagger.py` — the colour-flag prompt: grade each clause Green/Amber/Red/Blue against the positions, with `reason`, `next_steps`, `escalation`, and (Amber/Red) `suggested_revision`. Calibrated so Red is reserved for genuine breaches (threshold exceeded, prohibited term, removed protection) and "acceptable-tier-but-missing-a-preferred-detail" is Amber.
  - `chunking.py` — `segment_text()` splits a long contract into chunks (so every clause is reviewed, no truncation) and `merge_gradings()` de-duplicates per-chunk results by `clause_topic`, keeping the most severe flag.
  - `colour_flag.jsonl` — graded clause exemplars (few-shot) including `next_steps`/`suggested_revision`.
  - `contract_positions.json` — the comparison baseline (area 1).
- **How it's effective (cooperation):** `flag_contract_clauses()` calls `chunking.segment_text()` to split the whole contract, flags each chunk **concurrently** against the positions matrix on gpt-5-mini, then `chunking.merge_gradings()` combines the chunks into one most-severe-per-topic list. The model identifies the clauses from the text; the positions matrix is the rulebook it compares against; the exemplars calibrate the colour and the suggested-revision wording; the retry wrapper protects each chunk call.

### 5. Template comparison (missing / modified standard clauses)
- **Why:** the brief is also in-scope for comparing against *standard templates*; this detects **missing** standard clauses (the "missing protection = risk" signal the flagger no longer infers) and **modified** ones.
- **What changed:** `template_diff.py` maps the classified type → matching UoA template, segments both the contract and the template into clauses, embeds them with `text-embedding-3-small`, and aligns them by cosine similarity (see the *sim* section below). `app.py` runs it after classification and renders it; `report_export.py` adds it to the PDF. It checks only **substantive** standard clauses: structural/administrative sections (parties, signature block, schedules, definitions) and fill-in placeholders (`SCHEDULE [X]`, `[Insert ...]`) are filtered out (`_is_substantive`), so they are never reported "missing."
- **How it's effective:** for each *substantive* standard (template) clause it finds the closest contract clause; if nothing is close it is reported **missing (risk)**, if close-but-different it is **modified**. Filtering removed the previous false positives (e.g. "PARTIES missing"): a complete contract now returns 0 missing, and the "missing" list contains only real clause topics worth review. This remains **advisory** (similarity-based) — see Known Limitations.

### 6. Report output
- **Why:** the deliverable is a report; the brief mandates four colour sections, and slide 11 of the webinar shows per-clause **Next steps** and **Suggested Revision** boxes.
- **What changed (cooperating files):** `ui_components.py` groups flags into the four brief-worded sections (Green/Amber/Red/Blue) and renders each card with rationale, **Next steps**, escalation route, a **Suggested Revision** box (Amber/Red), position guide, and source citation; it also renders the Template Comparison. `report_export.py` builds the same content as a downloadable **PDF** (`fpdf2`).
- **How it's effective:** `app.py` parses the flagger output and calls `render_flag_cards()` + `render_template_comparison()`; `build_pdf_report()` emits the PDF with all sections.

### 7. Knowledge base (Foundry File Search)
- **Why:** the webinar names the knowledge base as standard templates + the positions document + previously signed contracts (precedent); we use it for a grounded Q&A and as available precedent.
- **What changed:** `knowledge_base.py` builds KB documents from the local source (positions + templates + example contracts), uploads them to a **Foundry vector store**, persists the id to `kb_state.json`, and exposes `query_kb()` via the `file_search` tool. `app.py` adds an **"Ask the Knowledge Base"** box.
- **How KB is used / how it's effective:** built once with `python knowledge_base.py build`; at query time the app calls gpt-5-mini on Foundry with the `file_search` tool pointed at the vector store, so answers are grounded in the positions and real example contracts. In practice the File Search KB powers **exactly one feature today — the "Ask the Knowledge Base" Q&A box.** The contract-review pipeline (classification, flagging, template diff) does **not** touch it.

- **Why the KB is NOT in the review pipeline (summary):** attaching `file_search` to the grading call made the model recite the positions matrix and drop its JSON output, so we removed it; flagging keeps the positions **in-context** instead. **See the dedicated ["Knowledge base (File Search)"](#knowledge-base-file-search-how-its-used-how-to-query-it-why-its-separate) section below** for the full usage, the Q&A how-to, the mechanics, and the rationale.

### 8. Orchestration — `app.py`
- **Why:** tie the pipeline together with caching and a clean flow.
- **What changed:** extraction dispatch; parallel classify + flag; template-diff step; four-section render; template-comparison render; the Q&A box; PDF download; `st.session_state` caching keyed by file; graceful handling of extraction errors (e.g. oversized scans).
- **How it's effective:** one upload triggers extract → (classify ‖ flag) → template diff → render + PDF, with results cached so reruns don't re-call the APIs.

### 9. Evaluation harness — `eval_classification.py`
- **Why:** measure classification accuracy objectively and re-check after prompt/model changes (instead of guessing); also lets us A/B models by swapping `AZURE_OPENAI_DEPLOYMENT`.
- **What changed:** ground-truth labels for the example contracts (filename-derived, plus a few content-derived), routed through `extract_text` (OCR cached); classifies each and reports accuracy + misclassifications.
- **How it's effective:** `python eval_classification.py` prints the table below.

### 10. Housekeeping
- `requirements.txt` — added `fpdf2` (PDF export).
- `.gitignore` — excludes `.ocr_cache/`, `kb_docs/`, `kb_state.json` (contain contract text or environment-specific ids).
- Removed the stale fine-tune `*.jsonl` files (the project uses few-shot prompting, not fine-tuning — chosen because the corpus is too small and imbalanced to fine-tune).
- Removed the legacy starter scripts `main.py`, `test.py`, `test_setup.py` (unused, not part of the pipeline).
- Removed a few-shot/eval **leakage**: a classification exemplar had reused `Contract Example 1`, which is also in the eval set. The exemplars are now all drawn from the UoA **templates** and are **disjoint from the eval example contracts** (no train/test overlap).
- `_visual_check.py` — a no-API Streamlit harness that renders the report with sample data, for eyeballing layout/CSS changes for free.

### 11. Responsible AI & confidentiality
- **Why:** the brief requires confidential handling, transparency in how issues are identified, and strong human oversight.
- **What changed:** `.streamlit/config.toml` disables Streamlit's usage-statistics telemetry; `app.py` shows a **confidentiality + advisory banner** and an **"ℹ️ Responsible AI & data handling"** expander.
- **How it's effective:**
  - **Confidentiality** — text is processed in the University's Foundry/Azure tenant; extraction is local-first (only scanned PDFs go to Azure DI, cached locally); the KB lives in the team's Foundry project; `.ocr_cache/`, `kb_docs/`, `kb_state.json` are gitignored. (Tenant should be confirmed for no-training/no-retention of prompt data.)
  - **Transparency** — each flag cites its matched UoA position + `reference_doc`; classification returns evidence quotes.
  - **Human oversight** — the tool is advisory: it flags and *suggests* for human review; it does not approve, sign, or redline contracts.

---

## Classification evaluation

Run with `python eval_classification.py`. Current result (after the team adjudicated the two services agreements as Consulting):

- **Filename-labelled accuracy: ≈ 20 / 22 = 91%**
- **Content-labelled (team/inferred): ~3–4 / 4**
- 0 skipped (all scanned PDFs OCR'd on the S0 tier).

The few-shot exemplars are drawn from the UoA **templates** and are **disjoint from these eval example contracts** — no train/test leakage.

Every clean category passes: CDA/NDA (4/4), MTA (1, 2, 4), DTA, Subcontract 1, Consultancy + Service Provider + Master Services → Consulting, Student Research (2/2), and the content-labelled Research / Variation cases.

**Ground-truth labels (the eval set — what each example contract is labelled as):**

| Contract type | Example contracts |
|---|---|
| Confidential Disclosure Agreements | CDA example 1–3; NDA example 1; NDA student work experience 1–2 |
| Collaboration Agreements | Collaboration Agreement Example 1–4; Contract Example 5 \* |
| Material Transfer Agreements | MTA Example 1–4 |
| Data Transfer Agreements | Data Transfer Agreement Example |
| Subcontracts | Subcontract Example 1–2 |
| Consulting Contracts | Consultancy Services Agreement; Service Provider Agreement †; Master Services Agreement Example 1 † |
| Research Contracts | Contract Example 1 \* |
| Student Research Agreements | Student Research Agreement Example 1–2 |
| Variation / Amendment | Master Services Agreement Example 1.5 \* |
| Unknown / Escalate | Contract for Goods and Services Example \* |

\* content-derived label (provisional, not from the filename). † team-adjudicated under the 11-type taxonomy.

The persistent misclassifications — none are classifier-logic defects:

| Document | Expected | Predicted | Is it an issue? |
|---|---|---|---|
| MTA Example 3 | Material Transfer | Data Transfer | **No — data quality.** Its extractable text is headed "Non-Disclosure of **Data**" with "data" 24× vs "material" 2×, so it genuinely reads as a data agreement; the DTA call is defensible and the filename label is questionable. |
| Subcontract Example 2 | Subcontracts | Research | **No — data quality.** Redaction removed the subcontract markers ("Funder"/"subcontract"/"prime" appear 0×), so the remaining text reads as a research contract; unrecoverable by any model. |

Both are **data quality** (the source text genuinely supports the model's answer), not logic defects. Note that gpt-5-mini is a reasoning model with **run-to-run variance on genuinely fuzzy boundaries** (Collaboration ↔ Research ↔ Consulting all involve funded research), so a given run may flip one borderline example and the headline number fluctuates by ±1–2.

### Flagging validation

Clause flagging has no per-clause ground truth (filenames give only the contract *type*), so it is validated three ways rather than scored:

- **Faithfulness** — every `detected_text` quote is checked to actually appear in the contract. On a clean template it matched ~100%; on OCR'd contracts the figure is lower only because OCR introduces spacing/character differences, not because quotes are invented.
- **Calibration ("template = green" check)** — flagging a UoA *template* (the preferred position by definition) should yield mostly Green. An early version over-flagged Red, which drove the calibration fix (judge by **outcome not wording**; reserve Red for genuine breaches). A complete template now skews Green/Blue with no spurious Red.
- **Flag ↔ position cross-check** — on a crafted contract with known-correct answers, each Amber/Red/Blue flag was verified against the Contracting Positions PDF: all pointed to the correct position (Governing Law → item 16, Liability → item 7, Publication → item 12, …), and a borderline Confidentiality clause correctly moved Red → Amber after the calibration tweak.

---

## Template comparison — how the `sim` value is computed

In the **Missing Standard Clauses (risk)** section, each row shows a `sim` value. It is a **cosine similarity** from `text-embedding-3-small`:

1. The matching UoA template and the uploaded contract are each split into clauses.
2. Every clause (template and contract) is converted to a 1536-dimension **embedding vector** by `text-embedding-3-small` on Foundry.
3. For each **template** clause, `sim` = the **maximum cosine similarity** between its vector and the vectors of the contract's clauses, where
   `cos(A, B) = (A · B) / (‖A‖ · ‖B‖)` — i.e. the dot product divided by the product of the vector magnitudes (range −1…1; for legal text typically ≈ 0.35–0.95).
4. The status is derived from that best `sim`:
   - `sim < 0.52` → **missing** (no contract clause is close enough → a standard protection may be absent),
   - `sim ≥ 0.62` → **aligned**,
   - in between → **modified**.

Thresholds were calibrated on real data: legal clauses have a high similarity baseline (even unrelated clauses score ≈ 0.45), so a *present* clause scores ≥ 0.62 while a *genuinely absent* one scores ≈ 0.43–0.52. The values are **heuristic and advisory** — see Known Limitations.

---

## Knowledge base (File Search): how it's used, how to query it, why it's separate

**What it is.** A Foundry **File Search vector store** built from the local source documents — the 21 contracting positions, the UoA templates, and the anonymised example contracts. `python knowledge_base.py build` uploads those docs to Foundry, which chunks and embeds them **server-side**; the store's id is saved locally to `kb_state.json`. The index lives on Foundry, not on your machine — so `kb_docs/` is just build scaffolding and can be deleted afterwards.

**How it's used today.** The File Search KB powers **exactly one feature — the "Ask the Knowledge Base" Q&A box.** Nothing in the contract-review pipeline (classification, flagging, template diff) queries it.

**How to use the Q&A.**
- *In the app:* expand **"💬 Ask the Knowledge Base"** near the top, type a question (e.g. *"What is the preferred liability cap?"*, *"How does UoA treat publication embargoes?"*), and click **Ask**. The answer is grounded in the positions and the real example contracts.
- *Programmatically:* `from knowledge_base import query_kb; query_kb("...")`, or CLI `python knowledge_base.py query "your question"`.

**How it works (mechanically).** `query_kb()` calls gpt-5-mini on Foundry with the `file_search` tool pointed at the vector-store id; Foundry searches the store for the most relevant chunks, the model answers using them, and the text is returned. That tool call is the entire "use" of the KB.

**Why it is NOT hooked into the review operation.** We tried attaching `file_search` to the clause-flagging call so grading could be "grounded in precedent." It backfired: with the whole positions matrix retrievable, the model began **reciting the matrix** — grading clauses that were not present in the contract — and intermittently returned **no parseable JSON**, dropping clauses. So we removed it. Flagging instead keeps the positions matrix **in-context** (pasted straight into the prompt), which is reliable and faithful to the actual contract text.

**The distinction worth remembering.** The *knowledge* (positions, templates, examples) is used throughout the pipeline, but via **different mechanisms** — only the Q&A uses the File Search vector store:

| Knowledge | Used by | Mechanism |
|---|---|---|
| 21 contracting positions | Clause flagging | pasted **in-context** into the prompt (not File Search) |
| UoA templates | Template comparison | **embedded directly** with `text-embedding-3-small` (not File Search) |
| positions + templates + example contracts | **"Ask the KB" Q&A** | **Foundry File Search vector store** |

**If the KB should later contribute to a review,** the safe pattern is a *separate, text-only precedent step* — e.g. for each Amber/Red clause, query the KB for "how was a similar clause treated before?" and attach it as a note — kept **out** of the structured-JSON grading call so it can't corrupt the flag output.

---

## Setup (brief)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

`.env` is kept in this repo — it stays listed in `.gitignore` but is **force-added** (`git add -f .env`; see the security note) because the repo is private and team-restricted. So **once it has been committed**, cloning gives a working configuration with no need to recreate it. If your clone doesn't contain it, create `.env` with these variables (the endpoint paths matter):

```env
# Foundry chat model (PROJECT-scoped endpoint, must end with /openai/v1)
AZURE_OPENAI_BASE_URL=https://<resource>.services.ai.azure.com/api/projects/<project>/openai/v1
AZURE_OPENAI_API_KEY=<foundry key>
AZURE_OPENAI_DEPLOYMENT=gpt-5-mini
# Embedding deployment name (embeddings resolve to the ACCOUNT-level endpoint automatically)
AZURE_OPENAI_EMBED_DEPLOYMENT=text-embedding-3-small
# Azure Document Intelligence (S0 tier recommended; F0 caps at 2 pages / 4 MB)
AZURE_FORM_RECOGNIZER_ENDPOINT=https://<docintel>.cognitiveservices.azure.com/
AZURE_FORM_RECOGNIZER_KEY=<key>
```

> **Security note:** `.env` contains live keys and is shared only because this repo is private and team-restricted. It stays listed in `.gitignore` and is committed **manually when needed** (`git add -f .env`), not tracked automatically. If the repo's visibility or membership ever changes, **rotate these keys**.

Then:

```powershell
python knowledge_base.py build      # one-time: build the Foundry File Search KB
python -m streamlit run app.py      # run the app (http://localhost:8501)
python eval_classification.py       # (optional) classification accuracy
```

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| **HTTP 405** on model calls | `AZURE_OPENAI_BASE_URL` is missing the `/openai/v1` suffix (or points at the bare project endpoint). It must be `…/api/projects/<project>/openai/v1`. |
| **HTTP 404** on embeddings (template diff) | Embeddings are **not** served from the project-scoped path — they live at the **account-level** endpoint (`…services.ai.azure.com/openai/v1`). `template_diff.py` derives this automatically; override with `AZURE_OPENAI_EMBED_BASE_URL` if your setup differs, and confirm the embedding model is deployed. |
| OCR **"input too large"**, or only ~2 pages extracted from a scan | The Document Intelligence resource is on the **free F0** tier (≈2 pages / 4 MB cap). Use **S0**. |
| Classification shows prose / "could not parse the result" | A transient model blip — the built-in 3× retry usually self-recovers; re-upload if it surfaces. |
| `ModuleNotFoundError` | The venv isn't activated, or `pip install -r requirements.txt` hasn't been run. |
| Telemetry message ("Collecting usage statistics") still appears | Ensure `.streamlit/config.toml` is present (it sets `gatherUsageStats = false`). |

---

## Status & known limitations (room for change)

- **Template comparison is advisory (similarity-based).** The earlier over-flagging (e.g. "PARTIES missing", placeholder `SCHEDULE [X]` artifacts) is fixed: structural sections and fill-in placeholders are now filtered, so only substantive clauses are checked and a complete contract returns 0 missing. It can still produce borderline calls on terse contracts (a present-but-brief clause may score just under the threshold), so it remains a review aid, not an authority.
- **Template comparison only covers types with a mapped template** — Research, Consulting, Subcontracts, MTA, DTA, CDA, Collaboration, and Student Research have one; **Clinical Trial, MOU, Variation, and Unknown / Escalate do not**, so those contracts get **no** missing/modified-clause check.
- **Cost & latency at volume are untested** — RGC processes ~3,250 contracts/year; each review is one classification call + several chunked flagging calls + embeddings (+ OCR for scans), ≈10–30s. Fine for a demo, but batch throughput, Foundry rate limits, and per-contract cost at scale have not been measured.
- **Blue is verbose** — boilerplate clauses outside the 21 positions all flag Blue; correct but noisy.
- **New types validated only on crafted examples** — Clinical Trial / MOU / Variation are classified correctly (high confidence) on hand-written examples with clear markers, but there are **no real example contracts of these types in the corpus**, so accuracy on real-world variants is unproven.
- **Label adjudication** — the "Service Provider" and "Master Services Example 1" cases were team-adjudicated to **Consulting** (eval updated). Any further borderline labels under the 11-type taxonomy should likewise be confirmed by the team.
- **Not yet done** — reading inputs from / writing reports to the shared/team **blob storage**; interpreting international (e.g. US federal) legislation against NZ equivalents.
- **Auth note** — embeddings and OCR use API-key auth (works from any environment); AAD-based access to blob / the Agent Service is subject to the tenant's Conditional Access (managed-device) policy.
