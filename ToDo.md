# To-Do: UI Overhaul & Code Refactor

## Phase 1 — Code Split
- [x] Create `extractor.py` — all text extraction logic (local + Azure Document Intelligence + raw Foundry model call)
- [x] Create `classifier.py` — `CLASSIFICATION_PROMPT` constant + `classify_contract_type()`
- [x] Create `flagger.py` — `COLOUR_FLAG_PROMPT`, `flag_contract_clauses()`, `extract_json_array()`
- [x] Create `ui_components.py` — `inject_css()`, `render_classification_card()`, `render_flag_cards()`

## Phase 2 — Rewrite `app.py` as thin orchestrator
- [x] `st.set_page_config(layout="centered")` with page title & icon
- [x] Cache extracted text + AI results in `st.session_state` (avoid re-running on button clicks)
- [x] On file upload: auto-extract via Azure Document Intelligence (no manual button)
- [x] Run `classify_contract_type` + `flag_contract_clauses` **in parallel** via `ThreadPoolExecutor`
- [x] Progress shown via `st.status()` widget with step labels
- [x] Render `render_classification_card()` then `render_flag_cards()` — no manual triggers
- [x] Hide all testing buttons inside `st.expander("Developer Mode", expanded=False)`

## Phase 3 — UI Improvements
- [x] Remove extracted text area from main view (users never see raw contract text)
- [x] Contract type card: large type badge + confidence pill + reason + collapsible evidence quotes
- [x] Colour flag cards: left-border stripe design (not full background fill), clean layout
- [x] Escalation badge (red pill) when escalation == "yes"
- [x] Custom CSS injected via `inject_css()` — shadows, badges, typography
- [x] Summary count row (Green / Amber / Red / Blue totals) above clause cards
