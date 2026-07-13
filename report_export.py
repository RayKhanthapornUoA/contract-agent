"""
Build a downloadable PDF review report (issue #5).

The report mirrors the brief: contract type, then the four flag sections in
order (Green / Amber / Red / Blue), each item shown as
    Clause [reference - title]: "snippet"
        Rationale: ...
with escalation routing and source citation where available.

Uses fpdf2 (pure-Python). Text is sanitised to latin-1 because the core PDF
fonts are not unicode.
"""
from fpdf import FPDF
from fpdf.enums import XPos, YPos


def _cell(pdf, h, txt):
    """multi_cell that always returns the cursor to the left margin on a new line."""
    pdf.multi_cell(0, h, txt, new_x=XPos.LMARGIN, new_y=YPos.NEXT)


# (flag key, heading, RGB)
_SECTIONS = [
    ("green", "Green Flags - Align with UoA Position", (40, 167, 69)),
    ("amber", "Amber Flags - Requires Contract Manager Review", (230, 168, 23)),
    ("red", "Red Flags - Conflicts with UoA Position", (220, 53, 69)),
    ("blue", "Blue Flags - Not Covered in UoA Position", (13, 143, 187)),
]

_REPLACEMENTS = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "…": "...", " ": " ",
    "•": "-",
}


def _ascii(s) -> str:
    s = "" if s is None else str(s)
    for k, v in _REPLACEMENTS.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def _lookups(positions_json):
    routes, refs = {}, {}
    for pos in positions_json or []:
        key = pos.get("clause_topic", "").strip().lower()
        routes[key] = pos.get("escalation_route", "")
        refs[key] = pos.get("reference_doc", "")
    return routes, refs


def build_pdf_report(contract_title, classification, flagged_data, positions_json,
                     template_diff=None) -> bytes:
    routes, refs = _lookups(positions_json)
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 16)
    _cell(pdf, 9, _ascii(contract_title or "Contract Review"))
    pdf.ln(1)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(120, 120, 120)
    _cell(pdf, 5, "Contract Review Adviser Agent - AI-assisted review for human consideration.")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)

    # Contract type
    if classification:
        pdf.set_font("Helvetica", "B", 13)
        _cell(pdf, 7, "Contract Type")
        pdf.set_font("Helvetica", "B", 11)
        ctype = classification.get("contract_type", "Unknown")
        conf = classification.get("confidence", "")
        _cell(pdf, 6, _ascii(f"{ctype}  ({conf} confidence)" if conf else ctype))
        pdf.set_font("Helvetica", "", 10)
        if classification.get("reason"):
            _cell(pdf, 5, _ascii(classification["reason"]))
        for q in classification.get("evidence", []) or []:
            pdf.set_font("Helvetica", "I", 9)
            _cell(pdf, 5, _ascii(f'  - "{q}"'))
        pdf.ln(3)

    # Flag sections
    flagged_data = flagged_data or []
    for flag, heading, rgb in _SECTIONS:
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(*rgb)
        _cell(pdf, 7, _ascii(heading))
        pdf.set_text_color(0, 0, 0)

        items = [c for c in flagged_data if c.get("flag", "blue").lower() == flag]
        if not items:
            pdf.set_font("Helvetica", "I", 10)
            pdf.set_text_color(150, 150, 150)
            _cell(pdf, 6, _ascii(f"No {flag} flags identified."))
            pdf.set_text_color(0, 0, 0)
            pdf.ln(2)
            continue

        for c in items:
            key = c.get("clause_topic", "").strip().lower()
            ref = c.get("clause_reference", "")
            topic = c.get("clause_topic", "Unspecified")
            title = f"{ref} - {topic}" if ref else topic
            pdf.set_font("Helvetica", "B", 10)
            _cell(pdf, 6, _ascii(f"Clause {title}"))
            if c.get("detected_text"):
                pdf.set_font("Helvetica", "I", 9)
                _cell(pdf, 5, _ascii(f'"{c["detected_text"]}"'))
            pdf.set_font("Helvetica", "", 10)
            _cell(pdf, 5, _ascii(f"Rationale: {c.get('reason', '')}"))
            if c.get("matched_position"):
                _cell(pdf, 5, _ascii(f"Matched Position: {c['matched_position']}"))
            if c.get("next_steps"):
                _cell(pdf, 5, _ascii(f"Next steps: {c['next_steps']}"))
            if flag in ("amber", "red") and routes.get(key):
                _cell(pdf, 5, _ascii(f"Escalate to: {routes[key]}"))
            if flag in ("amber", "red") and c.get("suggested_revision"):
                pdf.set_font("Helvetica", "B", 9)
                _cell(pdf, 5, "Suggested revision:")
                pdf.set_font("Helvetica", "I", 9)
                _cell(pdf, 5, _ascii(f'"{c["suggested_revision"]}"'))
                pdf.set_font("Helvetica", "", 10)
            if c.get("escalation", "no").lower() == "yes":
                pdf.set_font("Helvetica", "B", 9)
                pdf.set_text_color(220, 53, 69)
                _cell(pdf, 5, _ascii("Escalation Required"))
                pdf.set_text_color(0, 0, 0)
            if refs.get(key):
                pdf.set_font("Helvetica", "I", 8)
                pdf.set_text_color(120, 120, 120)
                _cell(pdf, 5, _ascii(f"Source: {refs[key]}"))
                pdf.set_text_color(0, 0, 0)
            pdf.ln(2)
        pdf.ln(1)

    # Template comparison (missing / modified standard clauses)
    if template_diff:
        clauses = template_diff.get("clauses", [])
        missing = [c for c in clauses if c["status"] == "missing"]
        modified = [c for c in clauses if c["status"] == "modified"]
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(0, 0, 0)
        _cell(pdf, 7, "Template Comparison")
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(120, 120, 120)
        _cell(pdf, 5, _ascii(f"Compared against {template_diff.get('template','')} - "
                             f"{len(missing)} missing, {len(modified)} modified."))
        pdf.set_text_color(0, 0, 0)
        pdf.ln(1)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(220, 53, 69)
        _cell(pdf, 6, "Missing standard clauses (risk)")
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 10)
        if missing:
            for c in missing:
                _cell(pdf, 5, _ascii(f"- {c['template_clause']}"))
        else:
            pdf.set_font("Helvetica", "I", 10)
            _cell(pdf, 5, "None - all standard clauses appear present.")
        pdf.ln(1)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(230, 168, 23)
        _cell(pdf, 6, "Modified / differs from standard")
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 10)
        if modified:
            for c in modified:
                _cell(pdf, 5, _ascii(f"- {c['template_clause']}"))
        else:
            pdf.set_font("Helvetica", "I", 10)
            _cell(pdf, 5, "None flagged as materially modified.")

    return bytes(pdf.output())
