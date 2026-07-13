"""Throwaway visual check for issue #5 rendering (NO API / NO OCR calls).

Feeds a precomputed sample through the real render functions so the 4-section
layout, escalation routing, citations, and empty-section placeholder can be
eyeballed. Run:  python -m streamlit run _visual_check.py
"""
import json
import streamlit as st
from ui_components import inject_css, render_classification_card, render_flag_cards

st.set_page_config(page_title="Visual check", layout="centered")
inject_css()

positions = json.load(open("contract_positions.json", encoding="utf-8"))

st.markdown("## 📄 Contract Analyser (visual check — sample data)")

st.markdown('<p class="section-header">Contract Type</p>', unsafe_allow_html=True)
render_classification_card({
    "contract_type": "Subcontracts",
    "confidence": "high",
    "reason": "The contract is performed under a Funder/head agreement with flow-down obligations.",
    "evidence": ["engaged under the Funder Agreement", "subject to the Head Contract terms"],
})

st.markdown('<p class="section-header">Clause Review</p>', unsafe_allow_html=True)
flagged = [
    {"clause_reference": "Clause 6", "clause_topic": "Payment Terms",
     "detected_text": "paid on the 20th of the month following invoice",
     "matched_position": "Payment Terms (preferred)", "flag": "green",
     "reason": "Matches the preferred position.", "escalation": "no"},
    {"clause_reference": "Clause 11", "clause_topic": "Confidentiality",
     "detected_text": "confidential for five (5) years after expiry",
     "matched_position": "Confidentiality (preferred)", "flag": "green",
     "reason": "Duration and exclusions align with the preferred position.", "escalation": "no"},
    {"clause_reference": "Clause 18", "clause_topic": "Governing Law and Jurisdiction",
     "detected_text": "governed by the laws of England and Wales",
     "matched_position": "Governing Law (acceptable)", "flag": "amber",
     "reason": "UK is acceptable, not preferred NZ.", "escalation": "no",
     "next_steps": "Contract Manager to review.",
     "suggested_revision": "This Agreement is governed by the laws of New Zealand, and the parties submit to the non-exclusive jurisdiction of the New Zealand courts."},
    {"clause_reference": "Clause 12", "clause_topic": "Liability Limitations and Exclusions",
     "detected_text": "the University's liability shall be unlimited",
     "matched_position": "Liability (outside acceptable)", "flag": "red",
     "reason": "Uncapped liability conflicts with the capped-liability position.", "escalation": "yes",
     "next_steps": "Must be revised before signing.",
     "suggested_revision": "The University's total aggregate liability is limited to the lesser of the contract value or NZD $500,000, and to direct losses caused by the University's negligence or wilful misconduct."},
    {"clause_reference": "Clause 20", "clause_topic": "Force Majeure",
     "detected_text": "not liable for events beyond reasonable control",
     "matched_position": "", "flag": "blue",
     "reason": "Recognised clause, not addressed in the positions matrix.", "escalation": "no"},
]
render_flag_cards(flagged, positions)
