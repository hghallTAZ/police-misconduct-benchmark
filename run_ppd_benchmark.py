#!/usr/bin/env python3
"""
PPD Brady/Giglio Benchmark Runner

Runs search queries against an ECA matter and measures recall
against ground truth labels at each tier.

Usage:
    python run_ppd_benchmark.py --api-url https://api.ecasses.com --matter-id f14a3c10-...

Requires: requests, ECA_TOKEN env var or --token flag
"""

import argparse
import csv
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple

import requests

# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------

@dataclass
class GroundTruth:
    filename: str
    classification: str
    tier: int
    label: str
    reasons: str
    has_sustained: bool


def load_ground_truth(csv_path: str) -> Dict[str, GroundTruth]:
    """Load ground truth labels keyed by filename. Handles both PPD and CPD formats."""
    gt = {}
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            gt[row["filename"]] = GroundTruth(
                filename=row["filename"],
                classification=row.get("classification", row.get("label", "")),
                tier=int(row["tier"]),
                label=row.get("label", ""),
                reasons=row.get("reasons", ""),
                has_sustained=row.get("has_sustained", "False") == "True",
            )
    return gt


# ---------------------------------------------------------------------------
# Search queries — designed to surface Brady/Giglio material
# ---------------------------------------------------------------------------

BRADY_QUERIES = [
    # Tier 1: Falsification / Criminal
    {
        "name": "falsification_sustained",
        "query": "falsification sustained finding",
        "description": "Officers with sustained falsification allegations",
    },
    {
        "name": "criminal_allegation",
        "query": "criminal allegation officer",
        "description": "Criminal allegations against officers",
    },
    {
        "name": "dishonesty",
        "query": "dishonesty false statement lying",
        "description": "Dishonesty patterns in officer conduct",
    },
    # Tier 2: Giglio-relevant (falsification/criminal any finding)
    {
        "name": "falsification_any",
        "query": "falsification allegation investigated",
        "description": "Any falsification allegation regardless of finding",
    },
    {
        "name": "criminal_conduct",
        "query": "criminal conduct charge allegation",
        "description": "Criminal conduct references",
    },
    # Tier 3: Brady-adjacent (physical abuse / civil rights + sustained)
    {
        "name": "physical_abuse_sustained",
        "query": "physical abuse sustained finding disciplinary",
        "description": "Physical abuse with sustained findings",
    },
    {
        "name": "civil_rights_sustained",
        "query": "civil rights complaint sustained finding",
        "description": "Civil rights complaints with sustained findings",
    },
    {
        "name": "excessive_force",
        "query": "excessive force physical abuse assault",
        "description": "Excessive force and physical abuse",
    },
    # Broad sweeps
    {
        "name": "sustained_discipline",
        "query": "sustained finding suspension termination reprimand",
        "description": "Any sustained finding with real discipline",
    },
    {
        "name": "impeachment_material",
        "query": "credibility impeachment misconduct Brady Giglio",
        "description": "Direct impeachment/Brady/Giglio terminology",
    },
    # CPD-specific terminology
    {
        "name": "illegal_arrest",
        "query": "illegal arrest false arrest",
        "description": "CPD illegal/false arrest allegations",
    },
    {
        "name": "perjury_false_report",
        "query": "perjury false report false statement official misconduct",
        "description": "CPD perjury and false reporting",
    },
]


# ---------------------------------------------------------------------------
# ECA Search API
# ---------------------------------------------------------------------------

def search_eca(
    api_url: str,
    token: str,
    matter_id: str,
    query: str,
    mode: str = "hybrid",
    limit: int = 500,
) -> List[dict]:
    """Run a search query against ECA and return results."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    resp = requests.post(
        f"{api_url}/api/search/advanced",
        headers=headers,
        json={
            "matter_id": matter_id,
            "query": query,
            "mode": mode,
            "limit": limit,
        },
        timeout=60,
    )

    if resp.status_code == 200:
        data = resp.json()
        # The endpoint returns "hits", not "results"
        return data.get("hits", data.get("results", data.get("documents", [])))

    # Rate limit backoff
    if resp.status_code == 429:
        retry_after = int(resp.json().get("retry_after", 60))
        print(f"  RATE LIMITED — waiting {retry_after}s...")
        time.sleep(retry_after + 2)
        resp2 = requests.post(
            f"{api_url}/api/search/advanced",
            headers=headers,
            json={"matter_id": matter_id, "query": query, "mode": mode, "limit": limit},
            timeout=60,
        )
        if resp2.status_code == 200:
            data = resp2.json()
            return data.get("hits", data.get("results", data.get("documents", [])))
        print(f"  WARN: retry also failed: {resp2.status_code}")
        return []

    print(f"  WARN: search returned {resp.status_code}: {resp.text[:200]}")
    return []


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@dataclass
class QueryResult:
    name: str
    query: str
    hits: int
    filenames_found: Set[str] = field(default_factory=set)
    latency_ms: float = 0.0


@dataclass
class BenchmarkResult:
    matter_id: str
    total_docs: int
    positive_docs: int
    queries_run: int
    # Recall by tier
    tier1_recall: float = 0.0  # Strong Giglio (must find)
    tier2_recall: float = 0.0  # Giglio-relevant
    tier3_recall: float = 0.0  # Brady-adjacent
    any_positive_recall: float = 0.0  # Any tier >= 1
    # Precision
    precision: float = 0.0
    # Details
    tier1_found: int = 0
    tier1_total: int = 0
    tier2_found: int = 0
    tier2_total: int = 0
    tier3_found: int = 0
    tier3_total: int = 0
    total_unique_hits: int = 0
    false_positives: int = 0
    query_results: List[QueryResult] = field(default_factory=list)
    total_search_cost_usd: float = 0.0
    total_latency_ms: float = 0.0


def compute_metrics(
    gt: Dict[str, GroundTruth],
    all_found: Set[str],
    query_results: List[QueryResult],
) -> BenchmarkResult:
    """Compute recall/precision at each tier."""

    tier1 = {fn for fn, g in gt.items() if g.tier == 1}
    tier2 = {fn for fn, g in gt.items() if g.tier == 2}
    tier3 = {fn for fn, g in gt.items() if g.tier == 3}
    any_positive = tier1 | tier2 | tier3

    tier1_found = tier1 & all_found
    tier2_found = tier2 & all_found
    tier3_found = tier3 & all_found
    any_found = any_positive & all_found

    false_positives = all_found - any_positive

    result = BenchmarkResult(
        matter_id="",
        total_docs=len(gt),
        positive_docs=len(any_positive),
        queries_run=len(query_results),
        tier1_recall=len(tier1_found) / len(tier1) if tier1 else 0,
        tier2_recall=len(tier2_found) / len(tier2) if tier2 else 0,
        tier3_recall=len(tier3_found) / len(tier3) if tier3 else 0,
        any_positive_recall=len(any_found) / len(any_positive) if any_positive else 0,
        precision=len(any_found) / len(all_found) if all_found else 0,
        tier1_found=len(tier1_found),
        tier1_total=len(tier1),
        tier2_found=len(tier2_found),
        tier2_total=len(tier2),
        tier3_found=len(tier3_found),
        tier3_total=len(tier3),
        total_unique_hits=len(all_found),
        false_positives=len(false_positives),
        query_results=query_results,
        total_latency_ms=sum(qr.latency_ms for qr in query_results),
    )
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="PPD Brady/Giglio Benchmark Runner")
    parser.add_argument("--api-url", default="https://api.ecasses.com")
    parser.add_argument("--matter-id", required=True)
    parser.add_argument("--token", default=os.environ.get("ECA_TOKEN", ""))
    parser.add_argument("--gt-csv", default=str(Path(__file__).parent / "ppd_v1" / "ground_truth_labels.csv"))
    parser.add_argument("--mode", default="hybrid", choices=["keyword", "semantic", "hybrid"])
    parser.add_argument("--limit", type=int, default=500, help="Max results per query")
    parser.add_argument("--output", default=None, help="Output JSON path")
    args = parser.parse_args()

    # Get token
    token = args.token
    if not token:
        # Try reading from CLI auth storage
        token_file = Path.home() / ".eca" / "credentials.json"
        if token_file.exists():
            creds = json.loads(token_file.read_text())
            token = creds.get("production", {}).get("token", "")
        if not token:
            # Login
            print("Logging in with demo credentials...")
            resp = requests.post(
                f"{args.api_url}/api/auth/login",
                json={"email": "attorney@lawfirm.com", "password": "Eca$Demo2026!"},
            )
            if resp.status_code == 200:
                token = resp.json().get("access_token", "")
            if not token:
                print("ERROR: No token. Set ECA_TOKEN or use --token.")
                sys.exit(1)

    # Load ground truth
    print(f"Loading ground truth from {args.gt_csv}")
    gt = load_ground_truth(args.gt_csv)
    print(f"  {len(gt)} documents, {sum(1 for g in gt.values() if g.tier >= 1)} positive")
    print(f"  Tier 1 (Strong Giglio): {sum(1 for g in gt.values() if g.tier == 1)}")
    print(f"  Tier 2 (Giglio-relevant): {sum(1 for g in gt.values() if g.tier == 2)}")
    print(f"  Tier 3 (Brady-adjacent): {sum(1 for g in gt.values() if g.tier == 3)}")

    # Run queries
    all_found: Set[str] = set()
    query_results: List[QueryResult] = []

    print(f"\nRunning {len(BRADY_QUERIES)} search queries (mode={args.mode}, limit={args.limit})...")
    for i, q in enumerate(BRADY_QUERIES, 1):
        t0 = time.time()
        results = search_eca(args.api_url, token, args.matter_id, q["query"], args.mode, args.limit)
        latency = (time.time() - t0) * 1000

        filenames = set()
        for r in results:
            fn = r.get("filename", r.get("document", {}).get("filename", ""))
            if fn:
                filenames.add(fn)

        all_found |= filenames
        qr = QueryResult(
            name=q["name"],
            query=q["query"],
            hits=len(results),
            filenames_found=filenames,
            latency_ms=latency,
        )
        query_results.append(qr)

        # Count how many of these hits are actually positive
        true_pos = sum(1 for fn in filenames if fn in gt and gt[fn].tier >= 1)
        print(f"  [{i}/{len(BRADY_QUERIES)}] {q['name']:30s} → {len(results):4d} hits, {true_pos:3d} true pos, {latency:.0f}ms")

    # Compute metrics
    metrics = compute_metrics(gt, all_found, query_results)
    metrics.matter_id = args.matter_id

    # Print results
    print(f"\n{'='*60}")
    print(f"PPD BRADY/GIGLIO BENCHMARK RESULTS")
    print(f"{'='*60}")
    print(f"Matter: {args.matter_id}")
    print(f"Mode: {args.mode}")
    print(f"Queries: {metrics.queries_run}")
    print(f"Total unique docs surfaced: {metrics.total_unique_hits}")
    print(f"")
    print(f"RECALL (higher = better, must not miss Brady material):")
    print(f"  Tier 1 (Strong Giglio):   {metrics.tier1_found}/{metrics.tier1_total} = {metrics.tier1_recall:.1%}")
    print(f"  Tier 2 (Giglio-relevant): {metrics.tier2_found}/{metrics.tier2_total} = {metrics.tier2_recall:.1%}")
    print(f"  Tier 3 (Brady-adjacent):  {metrics.tier3_found}/{metrics.tier3_total} = {metrics.tier3_recall:.1%}")
    print(f"  Any positive (tier>=1):   {metrics.tier1_found+metrics.tier2_found+metrics.tier3_found}/{metrics.positive_docs} = {metrics.any_positive_recall:.1%}")
    print(f"")
    print(f"PRECISION:")
    print(f"  Positive in surfaced set: {metrics.precision:.1%}")
    print(f"  False positives: {metrics.false_positives}")
    print(f"")
    print(f"COST & LATENCY:")
    print(f"  Total search latency: {metrics.total_latency_ms:.0f}ms")
    print(f"  Avg per query: {metrics.total_latency_ms / max(1, metrics.queries_run):.0f}ms")
    print(f"{'='*60}")

    # Save JSON output
    output_path = args.output or str(Path(__file__).parent / "ppd_v1" / "benchmark_results.json")
    output = {
        "benchmark": "PPD Brady/Giglio v1",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "matter_id": args.matter_id,
        "search_mode": args.mode,
        "limit_per_query": args.limit,
        "queries_run": metrics.queries_run,
        "total_docs": metrics.total_docs,
        "positive_docs": metrics.positive_docs,
        "recall": {
            "tier1_strong_giglio": {"found": metrics.tier1_found, "total": metrics.tier1_total, "rate": round(metrics.tier1_recall, 4)},
            "tier2_giglio_relevant": {"found": metrics.tier2_found, "total": metrics.tier2_total, "rate": round(metrics.tier2_recall, 4)},
            "tier3_brady_adjacent": {"found": metrics.tier3_found, "total": metrics.tier3_total, "rate": round(metrics.tier3_recall, 4)},
            "any_positive": {"found": metrics.tier1_found+metrics.tier2_found+metrics.tier3_found, "total": metrics.positive_docs, "rate": round(metrics.any_positive_recall, 4)},
        },
        "precision": round(metrics.precision, 4),
        "false_positives": metrics.false_positives,
        "total_unique_hits": metrics.total_unique_hits,
        "total_latency_ms": round(metrics.total_latency_ms, 1),
        "per_query": [
            {
                "name": qr.name,
                "query": qr.query,
                "hits": qr.hits,
                "unique_filenames": len(qr.filenames_found),
                "latency_ms": round(qr.latency_ms, 1),
            }
            for qr in query_results
        ],
    }
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
