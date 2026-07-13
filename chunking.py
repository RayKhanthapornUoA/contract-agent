"""
Document segmentation and grading-merge helpers (issue #4).

- segment_text: structure-aware segmentation with a fixed-size overlapping
  fallback, so the WHOLE contract is processed (no truncation).
- merge_gradings: flatten per-chunk grading arrays, de-duplicating by
  clause_topic and keeping the MOST SEVERE flag per topic.
"""
import re

# Numbered clause headings, e.g. "1 ", "1. ", "2.3 ", "10) " followed by a capital.
_HEADING = re.compile(r"(?m)^\s*\d+(?:\.\d+)*[.)]?\s+[A-Z]")

# Flag severity for merge precedence (higher = more severe).
_SEVERITY = {"red": 3, "amber": 2, "blue": 1, "green": 0}


def _fixed_chunks(text, max_chars, overlap):
    chunks = []
    step = max(1, max_chars - overlap)
    i = 0
    while i < len(text):
        chunks.append(text[i:i + max_chars])
        i += step
    return chunks


def _group_sections(sections, max_chars):
    """Greedily pack sections into chunks <= max_chars; split any oversized one."""
    chunks = []
    cur = ""
    for s in sections:
        if cur and len(cur) + len(s) > max_chars:
            chunks.append(cur)
            cur = ""
        cur += s
        while len(cur) > max_chars:
            chunks.append(cur[:max_chars])
            cur = cur[max_chars:]
    if cur.strip():
        chunks.append(cur)
    return chunks


def segment_text(text, max_chars=12000, overlap=1000):
    """Split a contract into chunks for per-chunk analysis.

    Prefers clause/section boundaries; falls back to fixed-size overlapping
    windows when no clear structure is detected. Never truncates.
    """
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    positions = [m.start() for m in _HEADING.finditer(text)]
    if len(positions) >= 3:
        bounds = positions + [len(text)]
        sections = [text[bounds[i]:bounds[i + 1]] for i in range(len(bounds) - 1)]
        if positions[0] > 0:
            sections.insert(0, text[:positions[0]])  # preamble before first heading
        return _group_sections(sections, max_chars)

    return _fixed_chunks(text, max_chars, overlap)


def merge_gradings(arrays):
    """Merge per-chunk grading lists into one, most-severe-per-topic.

    Ties on severity prefer an entry with escalation == "yes". Items with no
    clause_topic are kept individually (not de-duplicated).
    """
    best = {}
    untopiced = []
    for arr in arrays:
        if not arr:
            continue
        for g in arr:
            topic = (g.get("clause_topic") or "").strip().lower()
            if not topic:
                untopiced.append(g)
                continue
            new_sev = _SEVERITY.get((g.get("flag") or "").lower(), -1)
            if topic not in best:
                best[topic] = g
                continue
            cur = best[topic]
            cur_sev = _SEVERITY.get((cur.get("flag") or "").lower(), -1)
            if new_sev > cur_sev:
                best[topic] = g
            elif new_sev == cur_sev and \
                    (g.get("escalation", "").lower() == "yes" and
                     cur.get("escalation", "").lower() != "yes"):
                best[topic] = g
    return list(best.values()) + untopiced
