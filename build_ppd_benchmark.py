#!/usr/bin/env python3
"""
PPD Brady/Giglio Benchmark Builder (v1)

Joins Philadelphia Police Department complaints + discipline records,
applies proxy positive labels for Brady/Giglio-relevant material, and
exports:
  1. Individual text files (one per complaint) for ECA ingestion
  2. A ground-truth labels CSV for scoring
  3. A benchmark spec document

HONEST FRAMING:
  This is a Giglio/impeachment benchmark with Brady-adjacent signals.
  Proxy labels are NOT legal determinations — they are algorithmic
  heuristics based on allegation type + investigative finding.

Label Rules (proxy positives):
  TIER 1 — Strong Giglio (officer credibility impeachment):
    - allegation contains "Falsification" AND finding = "Sustained Finding"
    - allegation contains "Criminal" AND finding = "Sustained Finding"

  TIER 2 — Giglio-relevant (pattern evidence):
    - allegation contains "Falsification" (any finding)
    - allegation contains "Criminal" (any finding)
    - classification = "CRIMINAL ALLEGATION" or "FALSIFICATION"

  TIER 3 — Brady-adjacent (exculpatory potential):
    - classification = "PHYSICAL ABUSE" AND any sustained finding
    - classification = "CIVIL RIGHTS COMPLAINT" AND any sustained finding

  NEGATIVE — Everything else (departmental violations, lack of service, etc.)

These tiers let you measure recall at different strictness levels.
"""

import csv
import json
import os
import hashlib
from collections import defaultdict
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PPD_COMPLAINTS = "/Users/hgh/Sample_Ediscovery/ppd_complaints.csv"
PPD_DISCIPLINES = "/Users/hgh/Sample_Ediscovery/ppd_complaint_disciplines.csv"
OUTPUT_DIR = "/Users/hgh/Sample_Ediscovery/benchmarks/ppd_v1"

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

def load_disciplines():
    groups = defaultdict(list)
    with open(PPD_DISCIPLINES) as f:
        for row in csv.DictReader(f):
            cid = row.get("complaint_id", "").strip()
            if cid:
                groups[cid].append({
                    "officer_id": row.get("officer_id", ""),
                    "po_race": row.get("po_race", ""),
                    "po_sex": row.get("po_sex", ""),
                    "unit": row.get("po_assigned_unit", ""),
                    "allegation": row.get("allegations_investigated", "").strip(),
                    "finding": row.get("investigative_findings", "").strip(),
                    "discipline": row.get("disciplinary_findings", "").strip(),
                })
    return groups


def load_complaints():
    with open(PPD_COMPLAINTS) as f:
        return list(csv.DictReader(f))

# ---------------------------------------------------------------------------
# Labeling
# ---------------------------------------------------------------------------

STRONG_GIGLIO_ALLEGATIONS = {"falsification", "criminal allegation", "criminal"}
BRADY_ADJACENT_CLASSIFICATIONS = {"PHYSICAL ABUSE", "CIVIL RIGHTS COMPLAINT"}

def classify_complaint(complaint, discipline_rows):
    """Return (tier, label, reasons) for a complaint."""
    classification = complaint.get("general_cap_classification", "").strip().upper()
    summary = complaint.get("summary", "").strip()

    reasons = []
    has_sustained = False
    has_strong_allegation = False
    has_brady_adjacent = False

    for d in discipline_rows:
        allegation = d["allegation"].lower()
        finding = d["finding"]
        is_sustained = finding == "Sustained Finding"

        if is_sustained:
            has_sustained = True

        # Check for strong Giglio allegations
        for keyword in STRONG_GIGLIO_ALLEGATIONS:
            if keyword in allegation:
                has_strong_allegation = True
                if is_sustained:
                    reasons.append(f"Sustained {d['allegation']}")
                else:
                    reasons.append(f"{d['allegation']} ({finding})")

    # Check classification-level Brady adjacency
    if classification in BRADY_ADJACENT_CLASSIFICATIONS and has_sustained:
        has_brady_adjacent = True
        reasons.append(f"{classification} with sustained finding")

    # Also flag by top-level classification alone
    if classification in {"CRIMINAL ALLEGATION", "FALSIFICATION"}:
        has_strong_allegation = True
        if not reasons:
            reasons.append(f"Classification: {classification}")

    # Assign tier
    if has_strong_allegation and has_sustained:
        return 1, "strong_giglio", reasons
    elif has_strong_allegation:
        return 2, "giglio_relevant", reasons
    elif has_brady_adjacent:
        return 3, "brady_adjacent", reasons
    else:
        return 0, "negative", []

# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def build_document_text(complaint, discipline_rows):
    """Build a realistic discovery-document-style text from the record."""
    cid = complaint["complaint_id"]
    date = complaint.get("date_received", "")
    district = complaint.get("district_occurrence", "")
    classification = complaint.get("general_cap_classification", "")
    summary = complaint.get("summary", "")
    incident_date = complaint.get("incident_date_extract", "")

    lines = [
        f"PHILADELPHIA POLICE DEPARTMENT — INTERNAL AFFAIRS",
        f"COMPLAINT RECORD: {cid}",
        f"Date Received: {date}",
        f"Incident Date: {incident_date}",
        f"District: {district}",
        f"Classification: {classification}",
        f"",
        f"COMPLAINT SUMMARY:",
        summary,
        f"",
        f"OFFICERS INVOLVED AND FINDINGS:",
    ]

    for i, d in enumerate(discipline_rows, 1):
        lines.append(f"")
        lines.append(f"  Officer {i}: ID {d['officer_id']}")
        lines.append(f"    Race: {d['po_race']}  Sex: {d['po_sex']}")
        lines.append(f"    Assigned Unit: {d['unit']}")
        lines.append(f"    Allegation Investigated: {d['allegation']}")
        lines.append(f"    Investigative Finding: {d['finding']}")
        lines.append(f"    Disciplinary Finding: {d['discipline']}")

    return "\n".join(lines)


def main():
    print("Loading PPD data...")
    disciplines = load_disciplines()
    complaints = load_complaints()

    docs_dir = os.path.join(OUTPUT_DIR, "documents")
    os.makedirs(docs_dir, exist_ok=True)

    labels = []
    tier_counts = defaultdict(int)
    total_with_text = 0

    print(f"Processing {len(complaints)} complaints...")

    for complaint in complaints:
        cid = complaint.get("complaint_id", "").strip()
        if not cid:
            continue

        disc_rows = disciplines.get(cid, [])
        summary = complaint.get("summary", "").strip()

        if len(summary) < 20:
            continue

        total_with_text += 1

        # Classify
        tier, label, reasons = classify_complaint(complaint, disc_rows)
        tier_counts[label] += 1

        # Build document text
        doc_text = build_document_text(complaint, disc_rows)

        # Write document file
        filename = f"PPD_{cid}.txt"
        filepath = os.path.join(docs_dir, filename)
        with open(filepath, "w") as f:
            f.write(doc_text)

        # Compute hash for chain-of-custody
        doc_hash = hashlib.sha256(doc_text.encode()).hexdigest()

        labels.append({
            "complaint_id": cid,
            "filename": filename,
            "sha256": doc_hash,
            "classification": complaint.get("general_cap_classification", ""),
            "tier": tier,
            "label": label,
            "reasons": "; ".join(reasons) if reasons else "",
            "officer_count": len(disc_rows),
            "has_sustained": any(d["finding"] == "Sustained Finding" for d in disc_rows),
            "incident_date": complaint.get("incident_date_extract", ""),
        })

    # Write labels CSV
    labels_path = os.path.join(OUTPUT_DIR, "ground_truth_labels.csv")
    with open(labels_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "complaint_id", "filename", "sha256", "classification",
            "tier", "label", "reasons", "officer_count", "has_sustained",
            "incident_date",
        ])
        writer.writeheader()
        writer.writerows(labels)

    # Write summary
    positive_count = sum(1 for l in labels if l["tier"] > 0)
    summary = {
        "benchmark": "PPD Brady/Giglio Benchmark v1",
        "built_at": datetime.utcnow().isoformat(),
        "source": "Philadelphia Police Department Complaints + Disciplines (2020-present)",
        "framing": "Giglio/impeachment benchmark with Brady-adjacent supplements",
        "limitation": "Proxy labels are NOT legal Brady determinations. They are algorithmic heuristics based on allegation type + investigative finding.",
        "total_documents": total_with_text,
        "positive_documents": positive_count,
        "positive_rate": round(positive_count / total_with_text * 100, 1) if total_with_text else 0,
        "tier_distribution": {
            "tier_0_negative": tier_counts["negative"],
            "tier_1_strong_giglio": tier_counts["strong_giglio"],
            "tier_2_giglio_relevant": tier_counts["giglio_relevant"],
            "tier_3_brady_adjacent": tier_counts["brady_adjacent"],
        },
        "label_rules": {
            "tier_1_strong_giglio": "Falsification or Criminal allegation WITH sustained finding",
            "tier_2_giglio_relevant": "Falsification or Criminal allegation (any finding)",
            "tier_3_brady_adjacent": "Physical Abuse or Civil Rights with sustained finding",
            "tier_0_negative": "Everything else",
        },
        "recommended_metrics": {
            "primary": "Recall at tier >= 1 (must find all strong Giglio material)",
            "secondary": "Recall at tier >= 2 (should find most impeachment-relevant material)",
            "tertiary": "Precision at tier >= 2 (how much noise in the flagged set)",
        },
    }

    summary_path = os.path.join(OUTPUT_DIR, "benchmark_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    # Print results
    print(f"\n{'='*60}")
    print(f"PPD BRADY/GIGLIO BENCHMARK v1 — BUILD COMPLETE")
    print(f"{'='*60}")
    print(f"Total documents:        {total_with_text}")
    print(f"Positive (any tier):    {positive_count} ({summary['positive_rate']}%)")
    print(f"")
    print(f"Tier 1 (Strong Giglio): {tier_counts['strong_giglio']}")
    print(f"Tier 2 (Giglio-rel):    {tier_counts['giglio_relevant']}")
    print(f"Tier 3 (Brady-adj):     {tier_counts['brady_adjacent']}")
    print(f"Tier 0 (Negative):      {tier_counts['negative']}")
    print(f"")
    print(f"Output:")
    print(f"  Documents:    {docs_dir}/ ({total_with_text} .txt files)")
    print(f"  Labels:       {labels_path}")
    print(f"  Summary:      {summary_path}")


if __name__ == "__main__":
    main()
