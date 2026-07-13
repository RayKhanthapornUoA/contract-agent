import streamlit as st
import json
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

from extractor import extract_text, extract_text_with_azure, analyze_with_foundry_model
from classifier import classify_contract_type
from flagger import flag_contract_clauses, extract_json_array
from ui_components import (
    inject_css,
    render_classification_card,
    render_flag_cards,
    render_template_comparison,
)
from report_export import build_pdf_report
from template_diff import compare as compare_to_template

load_dotenv()

# -- Page config ---------------------------------------------------------------
st.set_page_config(
    page_title="Contract Analyser",
    page_icon="📄",
    layout="centered",
    initial_sidebar_state="collapsed",
)
inject_css()

# -- Header --------------------------------------------------------------------
st.markdown("## 📄 Contract Analyser")
st.markdown(
    "<p style='color:#666;margin-top:-0.5rem;margin-bottom:0.6rem'>"
    "Upload a contract to receive an instant AI-powered review."
    "</p>",
    unsafe_allow_html=True,
)

# -- Confidentiality / Responsible-AI notice -----------------------------------
st.markdown(
    "<div style='background:#fff8e6;border:1px solid #f0e0a8;border-radius:8px;"
    "padding:0.6rem 0.9rem;font-size:0.84rem;color:#5a4b1a;margin-bottom:1rem'>"
    "🔒 <b>Confidential &amp; advisory.</b> Contract text is processed within the "
    "University's Microsoft Foundry tenant to support review only. This is an "
    "AI <i>adviser</i> — every classification, flag, and suggested revision requires "
    "human review by the RGC team and is not legal advice."
    "</div>",
    unsafe_allow_html=True,
)
with st.expander("ℹ️ Responsible AI & data handling", expanded=False):
    st.markdown(
        "- **Confidentiality:** documents are processed within the University's Azure "
        "Foundry / Azure tenant. Text extraction is done locally where possible; only "
        "scanned PDFs are sent to Azure Document Intelligence, and OCR results are cached "
        "locally. The knowledge base lives in the team's Foundry project. *(Confirm your "
        "tenant is configured for no-training / no-retention of prompt data.)*\n"
        "- **Transparency:** every clause flag cites the matched UoA position and its "
        "reference document; the contract-type result includes short evidence quotes from "
        "the contract.\n"
        "- **Human oversight:** the agent flags and suggests for **human consideration**. "
        "It does not approve, sign, or redline contracts; the RGC reviewer makes all decisions."
    )

# -- Contract positions (loaded once) ------------------------------------------
with open("contract_positions.json", "r") as _f:
    positions_json = json.load(_f)

# -- Ask the Knowledge Base (Foundry File Search over positions + examples) ----
with st.expander("💬 Ask the Knowledge Base (UoA positions + example contracts)", expanded=False):
    st.markdown(
        "<p style='color:#777;font-size:0.85rem;margin-top:-0.3rem'>"
        "Grounded in the UoA contracting positions and anonymised example contracts, "
        "via Foundry File Search."
        "</p>",
        unsafe_allow_html=True,
    )
    kb_question = st.text_input(
        "Question",
        placeholder="e.g. How does UoA treat publication embargoes? What is the preferred liability cap?",
        label_visibility="collapsed",
    )
    if st.button("Ask") and kb_question.strip():
        with st.spinner("Searching the knowledge base..."):
            try:
                from knowledge_base import query_kb
                st.markdown(query_kb(kb_question))
            except Exception as exc:
                st.error(f"Knowledge base unavailable: {exc}")

# -- File uploader -------------------------------------------------------------
uploaded_file = st.file_uploader(
    "Upload a contract",
    type=["pdf", "docx", "txt"],
    help="Supported formats: PDF, DOCX, TXT",
    label_visibility="collapsed",
)

if not uploaded_file:
    st.markdown(
        "<p style='color:#999;font-size:0.9rem;text-align:center;margin-top:0.5rem'>"
        "Drag and drop or click Browse files above to get started."
        "</p>",
        unsafe_allow_html=True,
    )

if uploaded_file:
    # Use a file key to detect when a new file is uploaded and avoid
    # re-running expensive API calls on every Streamlit rerun.
    file_key = f"{uploaded_file.name}_{uploaded_file.size}"

    if st.session_state.get("file_key") != file_key:
        st.session_state.file_key = file_key
        st.session_state.text = None
        st.session_state.classification_raw = None
        st.session_state.flag_raw = None
        st.session_state.template_diff = None
        st.session_state.file_bytes = uploaded_file.read()

        with st.status("Analysing contract...", expanded=True) as status:
            st.write("Extracting text (local first; Azure OCR only for scanned PDFs)...")
            try:
                st.session_state.text = extract_text(
                    st.session_state.file_bytes, uploaded_file.name
                )
            except Exception as exc:
                status.update(label="Extraction failed", state="error")
                st.error(
                    "Could not extract text from this file. Scanned PDFs are OCR'd via "
                    "Azure Document Intelligence, which on the current tier limits file "
                    f"size and page count. Details: {exc}"
                )
                st.stop()
            st.write("Text extracted.")

            st.write("Running classification and clause review in parallel...")
            with ThreadPoolExecutor(max_workers=2) as executor:
                future_classify = executor.submit(
                    classify_contract_type, st.session_state.text
                )
                future_flag = executor.submit(
                    flag_contract_clauses, st.session_state.text, positions_json
                )
                st.session_state.classification_raw = future_classify.result()
                st.session_state.flag_raw = future_flag.result()

            st.write("Comparing against the matching UoA standard template...")
            try:
                _ctype = json.loads(st.session_state.classification_raw).get("contract_type", "")
                st.session_state.template_diff = compare_to_template(
                    st.session_state.text, _ctype
                )
            except Exception:
                st.session_state.template_diff = None

            st.write("Analysis complete.")
            status.update(label="Analysis complete", state="complete", expanded=False)

    text = st.session_state.text
    classification_raw = st.session_state.classification_raw
    flag_raw = st.session_state.flag_raw

    # -- Contract title --------------------------------------------------------
    contract_title = uploaded_file.name.rsplit(".", 1)[0].replace("_", " ").replace("-", " ")
    st.markdown(
        f"<h2 style='margin-top:1.2rem;margin-bottom:0.2rem;color:#1a1a2e'>{contract_title}</h2>"
        f"<p style='color:#999;font-size:0.82rem;margin-bottom:1.2rem'>{uploaded_file.name}</p>",
        unsafe_allow_html=True,
    )

    classification_data = None
    flagged_data = None

    # -- Contract Type ---------------------------------------------------------
    st.markdown('<p class="section-header">Contract Type</p>', unsafe_allow_html=True)
    try:
        classification_data = json.loads(classification_raw)
        render_classification_card(classification_data)
    except Exception:
        st.error("Could not parse the classification result.")
        st.code(classification_raw, language="json")

    # -- Clause Review ---------------------------------------------------------
    st.markdown('<p class="section-header">Clause Review</p>', unsafe_allow_html=True)
    try:
        flagged_json = extract_json_array(flag_raw)
        if not flagged_json:
            raise ValueError("No JSON array found in model output.")
        flagged_data = json.loads(flagged_json)
        if not isinstance(flagged_data, list):
            raise ValueError("Flagged output is not a list.")
        render_flag_cards(flagged_data, positions_json)
    except Exception as exc:
        st.error(f"Could not parse clause review result: {exc}")
        st.code(flag_raw, language="json")

    # -- Template Comparison ---------------------------------------------------
    template_diff = st.session_state.get("template_diff")
    st.markdown('<p class="section-header">Template Comparison</p>', unsafe_allow_html=True)
    render_template_comparison(template_diff)

    # -- Download report -------------------------------------------------------
    if flagged_data is not None:
        try:
            pdf_bytes = build_pdf_report(
                contract_title, classification_data, flagged_data, positions_json,
                template_diff=template_diff,
            )
            st.download_button(
                "⬇ Download review report (PDF)",
                data=pdf_bytes,
                file_name=f"{contract_title} - review report.pdf",
                mime="application/pdf",
            )
        except Exception as exc:
            st.warning(f"Could not generate the PDF report: {exc}")

    # -- Developer Mode --------------------------------------------------------
    with st.expander("Developer Mode", expanded=False):
        st.text_area("Extracted Text", text, height=280)

        if st.button("Re-extract with Azure Document Intelligence"):
            with st.spinner("Extracting..."):
                new_text = extract_text_with_azure(st.session_state.file_bytes)
            st.text_area("Re-extracted Text", new_text, height=280)

        if st.button("Analyze with Foundry Model (raw)"):
            with st.spinner("Analysing..."):
                raw_analysis = analyze_with_foundry_model(text)
            st.write(raw_analysis)

        if st.button("Classify Contract Type (raw JSON)"):
            with st.spinner("Classifying..."):
                raw_cls = classify_contract_type(text)
            st.code(raw_cls, language="json")

        if st.button("Flag Clauses with Colour (raw JSON)"):
            with st.spinner("Flagging..."):
                raw_flags = flag_contract_clauses(text, positions_json)
            st.code(raw_flags, language="json")