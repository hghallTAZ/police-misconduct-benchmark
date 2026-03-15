# Brady/Giglio Benchmark Suite

Tiered ground-truth labels and reproducible builder scripts for measuring AI recall on **Giglio/impeachment-relevant police misconduct records** in law enforcement internal affairs data.

Built for benchmarking [ECA Triage Accelerator](https://github.com/hghallTAZ/early_intake_legal), but usable by any e-discovery or legal-AI system that needs to measure misconduct-detection accuracy.

## What's Here

| File | Description |
|------|-------------|
| `BENCHMARK_SPEC.md` | Full specification: label rules, tier definitions, metrics, honest framing, known gaps |
| `build_ppd_benchmark.py` | Builder script for Philadelphia PD benchmark (v1) |
| `build_cpd_benchmark.py` | Builder script for Chicago PD benchmark (v2) |
| `ppd_v1/ground_truth_labels.csv` | 3,618 labeled PPD complaints with tier assignments |
| `ppd_v1/benchmark_summary.json` | PPD build stats and label rule documentation |
| `cpd_v2/ground_truth_labels.csv` | 10,000 labeled CPD complaints with tier assignments |
| `cpd_v2/benchmark_summary.json` | CPD build stats and label rule documentation |

## Quick Start

The ground truth labels are committed and ready to use. To regenerate the full document corpora:

1. Download source CSVs (see data sources below)
2. Update the path constants at the top of each builder script
3. Run: `python3 build_ppd_benchmark.py` and `python3 build_cpd_benchmark.py`

## Data Sources

| Dataset | Records | Source |
|---------|---------|--------|
| Philadelphia PD complaints | 3,622 complaints + 11,196 discipline records | [OpenDataPhilly](https://www.opendataphilly.org/) |
| Chicago PD complaints | 234,978 complaints + 263,765 accused records | [COPA / Invisible Institute CPDP](https://beta.cpdp.co/) |

## Tier Definitions

| Tier | Label | Meaning |
|------|-------|---------|
| 1 | `strong_giglio` | Sustained falsification or criminal finding — direct impeachment material |
| 2 | `giglio_relevant` | Falsification or criminal allegation exists (any finding) |
| 3 | `brady_adjacent` | Sustained excessive force or civil rights violation |
| 4 | `brady_weak` | Force/rights allegation without sustained finding (CPD only) |
| 0 | `negative` | Not directly Giglio/Brady-relevant |

## Honest Framing

These are **proxy labels**, not legal Brady determinations. "Sustained finding" does not automatically equal "legally disclosable." Brady materiality depends on case-specific context that no benchmark can capture.

See `BENCHMARK_SPEC.md` for the full limitations section and recommended claim language.

## License

The benchmark scripts and labels in this repository are released under MIT.

The underlying police misconduct data is public records from Philadelphia and Chicago oversight agencies. Refer to the original data sources for their terms of use.
