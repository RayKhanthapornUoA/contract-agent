"""
Classification regression harness (few-shot strategy, NOT fine-tuning).

Ground-truth labels for the redacted example contracts, used to measure the
accuracy of classify_contract_type() whenever the prompt changes.

Label sources:
  - "filename": the example's filename states its type (authoritative).
  - "content" : type was derived from the contract text (provisional; a human
                reviewer should confirm). Excluded from the headline metric to
                avoid circularity, but still reported.

The 17 UoA templates are intentionally NOT scored here -- they are the few-shot
exemplar pool (see fewshot_examples.jsonl), kept separate from the eval set to
avoid leakage.

Scanned/image PDFs (PyPDF2 extracts 0 chars) are skipped and listed; they need
the Azure Document Intelligence OCR path (improvement #6) to be evaluated.

Run:  python eval_classification.py
"""
import os
import json
from collections import Counter
from classifier import classify_contract_type
from extractor import extract_text

EXAMPLES_DIR = os.path.join("Contracts", "Redacted Examples")

# file -> (ground_truth_label, source)
LABELS = {
    "CDA example 1.pdf": ("Confidential Disclosure Agreements", "filename"),
    "CDA example 2.pdf": ("Confidential Disclosure Agreements", "filename"),
    "CDA example 3.pdf": ("Confidential Disclosure Agreements", "filename"),
    "NDA example 1.pdf": ("Confidential Disclosure Agreements", "filename"),
    "NDA student work experience example 1.pdf": ("Confidential Disclosure Agreements", "filename"),
    "NDA student work experience example 2.pdf": ("Confidential Disclosure Agreements", "filename"),
    "Collaboration Agreement Example 1.pdf": ("Collaboration Agreements", "filename"),
    "Collaboration Agreement Example 2.pdf": ("Collaboration Agreements", "filename"),
    "Collaboration Agreement Example 3.pdf": ("Collaboration Agreements", "filename"),
    "Collaboration Agreement Example 4.pdf": ("Collaboration Agreements", "filename"),
    "MTA Example 1.pdf": ("Material Transfer Agreements", "filename"),
    "MTA Example 2.pdf": ("Material Transfer Agreements", "filename"),
    "MTA Example 3.pdf": ("Material Transfer Agreements", "filename"),
    "MTA Example 4.pdf": ("Material Transfer Agreements", "filename"),
    "Data Transfer Agreement Example.pdf": ("Data Transfer Agreements", "filename"),
    "Subcontract Example 1.pdf": ("Subcontracts", "filename"),
    "Subcontract Example 2.pdf": ("Subcontracts", "filename"),
    "Consultancy Services Agreement Example.pdf": ("Consulting Contracts", "filename"),
    # Team-adjudicated under the 11-type taxonomy (services/expertise -> Consulting).
    "Service Provider Agreement Example.pdf": ("Consulting Contracts", "filename"),
    "Master Services Agreement Example 1 (1).pdf": ("Consulting Contracts", "filename"),
    # The ".5" denotes an amendment to "Master Services Agreement Example 1"; content
    # confirms explicit amendment language -> Variation / Amendment (relabelled).
    "Master Services Agreement Example 1.5.pdf": ("Variation / Amendment", "content"),
    "Student Research Agreement Example 1.pdf": ("Student Research Agreements", "filename"),
    "Student Research Agreement Example 2.pdf": ("Student Research Agreements", "filename"),
    # content-derived (provisional; confirm with a reviewer)
    "Contract Example 1.pdf": ("Research Contracts", "content"),
    "Contract Example 5.pdf": ("Collaboration Agreements", "content"),
    "Contract for Goods and Services Example.pdf": ("Unknown / Escalate", "content"),
}


def extract_pdf(path):
    """Local-first extraction with Azure OCR fallback for scanned PDFs (cached)."""
    with open(path, "rb") as fh:
        data = fh.read()
    return extract_text(data, os.path.basename(path))


def main():
    results = []          # (file, expected, predicted, source, ok)
    skipped = []          # scanned PDFs
    confusion = Counter()

    for fname, (expected, source) in sorted(LABELS.items()):
        path = os.path.join(EXAMPLES_DIR, fname)
        if not os.path.exists(path):
            skipped.append((fname, "missing file"))
            continue
        try:
            text = extract_pdf(path)
        except Exception as e:
            skipped.append((fname, f"extraction failed: {type(e).__name__}"))
            continue
        if not text.strip():
            skipped.append((fname, "no text even after OCR"))
            continue
        try:
            data = json.loads(classify_contract_type(text))
            predicted = data.get("contract_type", "?")
        except Exception as e:
            predicted = f"PARSE_FAIL:{type(e).__name__}"
        ok = (predicted == expected)
        results.append((fname, expected, predicted, source, ok))
        confusion[(expected, predicted)] += 1

    # Headline metric: filename-sourced only (avoids circular content labels)
    fn = [r for r in results if r[3] == "filename"]
    fn_ok = sum(1 for r in fn if r[4])
    ct = [r for r in results if r[3] == "content"]
    ct_ok = sum(1 for r in ct if r[4])

    print("=" * 78)
    print("CLASSIFICATION EVAL")
    print("=" * 78)
    for fname, expected, predicted, source, ok in results:
        flag = "PASS" if ok else "FAIL"
        tag = "" if source == "filename" else "  [content-label]"
        print(f"[{flag}] {fname}{tag}")
        if not ok:
            print(f"        expected : {expected}")
            print(f"        predicted: {predicted}")

    print("-" * 78)
    if fn:
        print(f"Headline accuracy (filename-labelled): {fn_ok}/{len(fn)} = {fn_ok/len(fn):.0%}")
    if ct:
        print(f"Content-labelled (provisional)       : {ct_ok}/{len(ct)}")
    print(f"Skipped (scanned/missing)            : {len(skipped)}")
    for fname, why in skipped:
        print(f"    - {fname}  ({why})")

    mis = {k: v for k, v in confusion.items() if k[0] != k[1]}
    if mis:
        print("\nMisclassifications (expected -> predicted):")
        for (exp, pred), n in mis.items():
            print(f"    {exp}  ->  {pred}   (x{n})")


if __name__ == "__main__":
    main()
