import streamlit as st

_FLAG_STYLES = {
    "green": {"border": "#28a745", "bg": "#f6fff8", "label": "Green"},
    "amber": {"border": "#e6a817", "bg": "#fffdf0", "label": "Amber"},
    "red":   {"border": "#dc3545", "bg": "#fff8f8", "label": "Red"},
    "blue":  {"border": "#0d8fbb", "bg": "#f0faff", "label": "Blue"},
}

_CONFIDENCE_COLORS = {
    "high":   "#28a745",
    "medium": "#e6a817",
    "low":    "#dc3545",
}


def inject_css() -> None:
    st.markdown(
        """
        <style>
        /* ── Page ─────────────────────────────────────── */
        .block-container { padding-top: 2rem; max-width: 960px; }

        /* ── Upload zone label ───────────────────────── */
        .upload-label {
            font-size: 1.05rem;
            color: #444;
            margin-bottom: 0.4rem;
        }

        /* ── Section headers ─────────────────────────── */
        .section-header {
            font-size: 1.15rem;
            font-weight: 700;
            color: #1a1a2e;
            margin: 1.6rem 0 0.8rem 0;
            padding-bottom: 0.4rem;
            border-bottom: 2px solid #e8e8f0;
        }

        /* ── Classification card ─────────────────────── */
        .cls-card {
            background: #ffffff;
            border: 1px solid #e2e2ec;
            border-radius: 12px;
            padding: 1.4rem 1.6rem;
            box-shadow: 0 2px 10px rgba(0,0,0,0.06);
            margin-bottom: 0.5rem;
        }
        .cls-type {
            font-size: 1.55rem;
            font-weight: 700;
            color: #1a1a2e;
            margin-bottom: 0.7rem;
        }
        .cls-badge {
            display: inline-block;
            padding: 3px 14px;
            border-radius: 20px;
            color: #fff;
            font-size: 0.82rem;
            font-weight: 600;
            letter-spacing: 0.03em;
            margin-bottom: 0.85rem;
        }
        .cls-reason {
            color: #444;
            font-size: 0.95rem;
            line-height: 1.65;
        }

        /* ── Flag cards ──────────────────────────────── */
        .flag-card {
            border-left: 5px solid;
            border-radius: 8px;
            padding: 1rem 1.25rem;
            margin-bottom: 0.75rem;
            box-shadow: 0 1px 5px rgba(0,0,0,0.05);
        }
        .flag-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.55rem;
        }
        .flag-topic {
            font-weight: 700;
            font-size: 0.98rem;
            color: #1a1a2e;
        }
        .flag-badge {
            display: inline-block;
            padding: 2px 11px;
            border-radius: 14px;
            color: #fff;
            font-size: 0.78rem;
            font-weight: 600;
        }
        .flag-quote {
            font-style: italic;
            color: #555;
            font-size: 0.88rem;
            border-left: 3px solid #ccc;
            padding-left: 0.6rem;
            margin-bottom: 0.45rem;
        }
        .flag-reason {
            color: #333;
            font-size: 0.91rem;
            margin-bottom: 0.3rem;
        }
        .flag-meta {
            color: #666;
            font-size: 0.85rem;
            margin-bottom: 0.25rem;
        }
        .flag-hint {
            color: #777;
            font-size: 0.83rem;
            font-style: italic;
        }
        .escalation-pill {
            display: inline-block;
            background: #dc3545;
            color: #fff;
            padding: 2px 11px;
            border-radius: 4px;
            font-size: 0.8rem;
            font-weight: 600;
            margin-top: 0.5rem;
        }
        .suggested-revision {
            background: #f4f6fb;
            border: 1px solid #d7deea;
            border-radius: 6px;
            padding: 0.6rem 0.8rem;
            margin: 0.45rem 0;
            font-size: 0.88rem;
            color: #333;
        }
        .suggested-revision b {
            display: block;
            font-size: 0.72rem;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            color: #5a6b8c;
            margin-bottom: 0.25rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_classification_card(data: dict) -> None:
    contract_type = data.get("contract_type", "Unknown")
    confidence = data.get("confidence", "").lower()
    reason = data.get("reason", "")
    evidence = data.get("evidence", [])

    conf_color = _CONFIDENCE_COLORS.get(confidence, "#6c757d")
    conf_label = confidence.capitalize() + " Confidence" if confidence else "Confidence Unknown"

    st.markdown(
        f"""
        <div class="cls-card">
            <div class="cls-type">{contract_type}</div>
            <span class="cls-badge" style="background:{conf_color}">{conf_label}</span>
            <p class="cls-reason">{reason}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if evidence:
        with st.expander("View supporting evidence"):
            for quote in evidence:
                st.info(f'"{quote}"')


# Brief-mandated sections, rendered in this order.
_SECTIONS = [
    ("green", "Green Flags – Align with UoA Position", "#28a745"),
    ("amber", "Amber Flags – Requires Contract Manager Review", "#e6a817"),
    ("red", "Red Flags – Conflicts with UoA Position", "#dc3545"),
    ("blue", "Blue Flags – Not Covered in UoA Position", "#0d8fbb"),
]


def _position_lookups(positions_json: list):
    """clause_topic (lowered) -> explanation_hint / escalation_route / reference_doc."""
    hints, routes, refs = {}, {}, {}
    for pos in positions_json:
        key = pos.get("clause_topic", "").strip().lower()
        hints[key] = pos.get("explanation_hint", "")
        routes[key] = pos.get("escalation_route", "")
        refs[key] = pos.get("reference_doc", "")
    return hints, routes, refs


def _render_flag_card(clause: dict, hints, routes, refs) -> None:
    flag = clause.get("flag", "blue").lower()
    style = _FLAG_STYLES.get(flag, _FLAG_STYLES["blue"])

    clause_topic = clause.get("clause_topic", "")
    clause_ref = clause.get("clause_reference", "")
    key = clause_topic.strip().lower()
    hint = hints.get(key, "")
    route = routes.get(key, "")
    ref_doc = refs.get(key, "")
    matched = clause.get("matched_position", "")
    detected = clause.get("detected_text", "")
    reason = clause.get("reason", "")
    next_steps = clause.get("next_steps", "")
    suggested = clause.get("suggested_revision", "")
    escalation = clause.get("escalation", "no").lower() == "yes"

    title = clause_topic or "<i>Unspecified</i>"
    if clause_ref:
        title = f"{clause_ref} &mdash; {title}"

    # Assemble with no indentation and no empty lines: indented or blank lines
    # would make Streamlit's markdown treat the HTML as a code block.
    parts = [
        f'<div class="flag-card" style="border-left-color:{style["border"]};background:{style["bg"]}">',
        f'<div class="flag-header"><span class="flag-topic">{title}</span>'
        f'<span class="flag-badge" style="background:{style["border"]}">{style["label"]}</span></div>',
        f'<p class="flag-quote">"{detected}"</p>',
        f'<p class="flag-reason"><b>Rationale:</b> {reason}</p>',
    ]
    if matched:
        parts.append(f'<p class="flag-meta"><b>Matched Position:</b> {matched}</p>')
    if next_steps:
        parts.append(f'<p class="flag-meta"><b>Next steps:</b> {next_steps}</p>')
    if route and flag in ("amber", "red"):
        parts.append(f'<p class="flag-meta"><b>Escalate to:</b> {route}</p>')
    if suggested and flag in ("amber", "red"):
        parts.append(
            f'<div class="suggested-revision"><b>Suggested revision</b><br>"{suggested}"</div>'
        )
    if hint:
        parts.append(f'<p class="flag-hint"><b>Position Guide:</b> {hint}</p>')
    if ref_doc:
        parts.append(f'<p class="flag-hint"><b>Source:</b> {ref_doc}</p>')
    if escalation:
        parts.append('<span class="escalation-pill">⚠ Escalation Required</span>')
    parts.append('</div>')
    st.markdown("".join(parts), unsafe_allow_html=True)


def render_flag_cards(flagged_data: list, positions_json: list) -> None:
    hints, routes, refs = _position_lookups(positions_json)

    # Summary counts
    counts = {"green": 0, "amber": 0, "red": 0, "blue": 0}
    for clause in flagged_data:
        key = clause.get("flag", "blue").lower()
        counts[key] = counts.get(key, 0) + 1

    cols = st.columns(4)
    for col, (flag, _heading, color) in zip(cols, _SECTIONS):
        label = flag.capitalize()
        col.markdown(
            f"""
            <div style="background:{color};border-radius:8px;padding:0.7rem 1rem;text-align:center;color:#fff">
                <div style="font-size:1.5rem;font-weight:700">{counts[flag]}</div>
                <div style="font-size:0.85rem;font-weight:600">{label}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # Four labelled sections, in the brief's order.
    for flag, heading, color in _SECTIONS:
        st.markdown(
            f'<p class="section-header" style="color:{color};border-bottom-color:{color}">{heading}</p>',
            unsafe_allow_html=True,
        )
        section_clauses = [c for c in flagged_data if c.get("flag", "blue").lower() == flag]
        if not section_clauses:
            st.markdown(
                f'<p style="color:#999;font-size:0.9rem;margin:-0.3rem 0 0.8rem 0">'
                f'No {flag} flags identified.</p>',
                unsafe_allow_html=True,
            )
            continue
        for clause in section_clauses:
            _render_flag_card(clause, hints, routes, refs)


def render_template_comparison(diff) -> None:
    """Render the template-diff result: missing / modified standard clauses."""
    if diff is None:
        st.markdown(
            '<p style="color:#999;font-size:0.9rem">No standard UoA template maps to '
            'this contract type, so a template comparison was not performed.</p>',
            unsafe_allow_html=True,
        )
        return

    clauses = diff.get("clauses", [])
    missing = [c for c in clauses if c["status"] == "missing"]
    modified = [c for c in clauses if c["status"] == "modified"]
    aligned = [c for c in clauses if c["status"] == "aligned"]
    st.markdown(
        f"<p style='color:#777;font-size:0.88rem'>Compared against "
        f"<b>{diff.get('template','')}</b> &mdash; {len(missing)} missing, "
        f"{len(modified)} modified, {len(aligned)} aligned of {len(clauses)} standard clauses.</p>",
        unsafe_allow_html=True,
    )

    def _block(title, items, color, empty_msg, show_snippet):
        st.markdown(
            f'<p class="section-header" style="color:{color};border-bottom-color:{color}">{title}</p>',
            unsafe_allow_html=True,
        )
        if not items:
            st.markdown(f'<p style="color:#999;font-size:0.9rem;margin:-0.3rem 0 0.8rem 0">{empty_msg}</p>',
                        unsafe_allow_html=True)
            return
        for c in items:
            snippet = (f'<p class="flag-quote">"{c.get("contract_snippet","")}"</p>'
                       if show_snippet and c.get("contract_snippet") else "")
            st.markdown(
                f'<div class="flag-card" style="border-left-color:{color};background:#fff">'
                f'<div class="flag-header"><span class="flag-topic">{c["template_clause"]}</span>'
                f'<span class="flag-badge" style="background:{color}">sim {c["similarity"]}</span></div>'
                f'{snippet}</div>',
                unsafe_allow_html=True,
            )

    _block("Missing Standard Clauses (risk)", missing, "#dc3545",
           "None &mdash; all standard clauses appear to be present.", show_snippet=False)
    _block("Modified / Differs From Standard", modified, "#e6a817",
           "None flagged as materially modified.", show_snippet=True)
