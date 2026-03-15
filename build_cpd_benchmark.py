#!/usr/bin/env python3
"""
Chicago CPD Brady/Giglio Benchmark Builder (v2)

Uses complaints-accused.csv to build a structured classification benchmark.
Since Chicago data lacks narrative text, this generates synthetic complaint
documents from the structured fields — category, finding, outcome, officer ID.

This tests whether ECA's triage pipeline can correctly rank/flag
records by Giglio-relevance when the content is structured IA data.

HONEST FRAMING:
  - These are synthetic documents generated from real structured data.
  - Finding codes: SU=Sustained, NS=Not Sustained, UN=Unfounded,
    NAF=No Affidavit, EX=Exonerated, AC=Administratively Closed
  - Proxy labels use the same tiered approach as PPD v1.
  - Chicago has no narrative summaries — this is a classification test,
    not a text retrieval test.
"""

import csv
import json
import os
import hashlib
from collections import defaultdict, Counter
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CPD_ACCUSED = "/Users/hgh/Sample_Ediscovery/unified_extracted/unified_data/complaints/complaints-accused.csv"
CPD_COMPLAINTS = "/Users/hgh/Sample_Ediscovery/unified_extracted/unified_data/complaints/complaints-complaints.csv"
OUTPUT_DIR = "/Users/hgh/Sample_Ediscovery/benchmarks/cpd_v2"

FINDING_MAP = {
    "SU": "Sustained",
    "NS": "Not Sustained",
    "UN": "Unfounded",
    "NAF": "No Affidavit",
    "EX": "Exonerated",
    "AC": "Administratively Closed",
    "DIS": "Discharged",
    "NC": "No Cooperation",
}

# Strong Giglio categories (officer credibility / criminal conduct)
STRONG_GIGLIO_KEYWORDS = {
    "false arrest", "illegal arrest", "false report",
    "perjury", "falsif", "criminal",
}

# Brady-adjacent categories (excessive force / civil rights)
BRADY_ADJACENT_KEYWORDS = {
    "excessive force", "civil rights", "unnecessary physical",
    "coercion", "racial", "discrimination",
}

# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_complaint_dates():
    """Load complaint dates from complaints-complaints.csv for context."""
    dates = {}
    with open(CPD_COMPLAINTS) as f:
        for row in csv.DictReader(f):
            cr_id = row.get("cr_id", "").strip()
            if cr_id:
                dates[cr_id] = {
                    "complaint_date": row.get("complaint_date", ""),
                    "incident_date": row.get("incident_date", ""),
                    "closed_date": row.get("closed_date", ""),
                    "current_status": row.get("current_status", ""),
                }
    return dates


def load_accused():
    """Load accused records, group by cr_id."""
    groups = defaultdict(list)
    with open(CPD_ACCUSED) as f:
        for row in csv.DictReader(f):
            cr_id = row.get("cr_id", "").strip()
            if cr_id:
                groups[cr_id].append(row)
    return groups

# ---------------------------------------------------------------------------
# Classify
# ---------------------------------------------------------------------------

def classify_cpd_complaint(cr_id, accused_rows, date_info):
    """Classify a CPD complaint by Giglio/Brady proxy tier."""
    reasons = []
    has_sustained = False
    has_strong_giglio = False
    has_brady_adjacent = False

    for row in accused_rows:
        category = (row.get("complaint_category") or "").lower()
        finding = (row.get("final_finding") or "").strip()
        is_sustained = finding == "SU"
        is_disciplined = row.get("disciplined", "").strip().lower() == "true"

        if is_sustained:
            has_sustained = True

        for kw in STRONG_GIGLIO_KEYWORDS:
            if kw in category:
                has_strong_giglio = True
                finding_label = FINDING_MAP.get(finding, finding)
                reasons.append(f"{row.get('complaint_category','')} ({finding_label})")
                break

        if not has_strong_giglio:
            for kw in BRADY_ADJACENT_KEYWORDS:
                if kw in category:
                    has_brady_adjacent = True
                    finding_label = FINDING_MAP.get(finding, finding)
                    reasons.append(f"{row.get('complaint_category','')} ({finding_label})")
                    break

    if has_strong_giglio and has_sustained:
        return 1, "strong_giglio", reasons
    elif has_strong_giglio:
        return 2, "giglio_relevant", reasons
    elif has_brady_adjacent and has_sustained:
        return 3, "brady_adjacent", reasons
    elif has_brady_adjacent:
        return 4, "brady_weak", reasons
    else:
        return 0, "negative", []

# ---------------------------------------------------------------------------
# Generate synthetic document
# ---------------------------------------------------------------------------

def build_cpd_document(cr_id, accused_rows, date_info):
    """Build a synthetic IA document from structured CPD data."""
    info = date_info or {}
    lines = [
        "CHICAGO POLICE DEPARTMENT — CIVILIAN OFFICE OF POLICE ACCOUNTABILITY",
        f"COMPLAINT RECORD: CR-{cr_id}",
        f"Complaint Date: {info.get('complaint_date', 'Unknown')}",
        f"Incident Date: {info.get('incident_date', 'Unknown')}",
        f"Closed Date: {info.get('closed_date', 'Unknown')}",
        f"Status: {info.get('current_status', 'Unknown')}",
        "",
        "ACCUSED OFFICERS AND FINDINGS:",
    ]

    for i, row in enumerate(accused_rows, 1):
        uid = row.get("UID", "Unknown")
        category = row.get("complaint_category", "Unknown")
        finding = row.get("final_finding", "")
        finding_label = FINDING_MAP.get(finding, finding or "Pending")
        outcome = row.get("final_outcome_desc", "") or row.get("final_outcome", "")
        disciplined = row.get("disciplined", "")
        recc = row.get("recc_finding", "")
        recc_label = FINDING_MAP.get(recc, recc or "N/A")

        lines.append("")
        lines.append(f"  Officer {i}: UID {uid}")
        lines.append(f"    Complaint Category: {category}")
        lines.append(f"    Recommended Finding: {recc_label}")
        lines.append(f"    Final Finding: {finding_label}")
        lines.append(f"    Final Outcome: {outcome}")
        lines.append(f"    Disciplined: {disciplined}")

    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Loading Chicago CPD data...")
    dates = load_complaint_dates()
    accused_groups = load_accused()

    docs_dir = os.path.join(OUTPUT_DIR, "documents")
    os.makedirs(docs_dir, exist_ok=True)

    labels = []
    tier_counts = Counter()
    total = 0

    # Sample: take complaints that have at least one accused record
    # Cap at 10K for a manageable benchmark (full set is 234K complaints)
    MAX_DOCS = 10000
    cr_ids = sorted(accused_groups.keys())[:MAX_DOCS]

    print(f"Processing {len(cr_ids)} complaints (capped at {MAX_DOCS})...")

    for cr_id in cr_ids:
        accused_rows = accused_groups[cr_id]
        date_info = dates.get(cr_id, {})

        tier, label, reasons = classify_cpd_complaint(cr_id, accused_rows, date_info)
        tier_counts[label] += 1
        total += 1

        doc_text = build_cpd_document(cr_id, accused_rows, date_info)

        filename = f"CPD_CR-{cr_id}.txt"
        filepath = os.path.join(docs_dir, filename)
        with open(filepath, "w") as f:
            f.write(doc_text)

        doc_hash = hashlib.sha256(doc_text.encode()).hexdigest()

        labels.append({
            "cr_id": cr_id,
            "filename": filename,
            "sha256": doc_hash,
            "officer_count": len(accused_rows),
            "tier": tier,
            "label": label,
            "reasons": "; ".join(reasons[:3]) if reasons else "",
            "has_sustained": any(r.get("final_finding") == "SU" for r in accused_rows),
            "complaint_date": date_info.get("complaint_date", ""),
        })

    # Write labels
    labels_path = os.path.join(OUTPUT_DIR, "ground_truth_labels.csv")
    with open(labels_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "cr_id", "filename", "sha256", "officer_count",
            "tier", "label", "reasons", "has_sustained", "complaint_date",
        ])
        writer.writeheader()
        writer.writerows(labels)

    positive_count = sum(1 for l in labels if l["tier"] > 0)
    summary = {
        "benchmark": "CPD Brady/Giglio Benchmark v2",
        "built_at": datetime.utcnow().isoformat(),
        "source": "Chicago Police Department via COPA (Civilian Office of Police Accountability)",
        "framing": "Structured classification benchmark — synthetic documents from real IA data",
        "limitation": "No narrative text in source data. Documents are generated from structured fields. Tests AI classification, not text retrieval.",
        "total_documents": total,
        "positive_documents": positive_count,
        "positive_rate": round(positive_count / total * 100, 1) if total else 0,
        "tier_distribution": dict(tier_counts),
        "label_rules": {
            "tier_1_strong_giglio": "False arrest/report/perjury/falsification WITH sustained finding",
            "tier_2_giglio_relevant": "False arrest/report/perjury/falsification (any finding)",
            "tier_3_brady_adjacent": "Excessive force/civil rights WITH sustained finding",
            "tier_4_brady_weak": "Excessive force/civil rights (any finding)",
            "tier_0_negative": "Everything else",
        },
        "finding_codes": FINDING_MAP,
    }

    summary_path = os.path.join(OUTPUT_DIR, "benchmark_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*60}")
    print(f"CPD BRADY/GIGLIO BENCHMARK v2 — BUILD COMPLETE")
    print(f"{'='*60}")
    print(f"Total documents:          {total}")
    print(f"Positive (any tier):      {positive_count} ({summary['positive_rate']}%)")
    print()
    for label, count in tier_counts.most_common():
        print(f"  {label:25s} {count:>6}")
    print()
    print(f"Output:")
    print(f"  Documents:  {docs_dir}/ ({total} .txt files)")
    print(f"  Labels:     {labels_path}")
    print(f"  Summary:    {summary_path}")


if __name__ == "__main__":
    main()
