# Brady/Giglio Benchmark Specification

Date: March 15, 2026
Version: 1.1
Author: ECA Engineering

## Honest Framing

These benchmarks measure ECA's ability to identify **Giglio / impeachment-relevant police misconduct records** and **Brady-adjacent material** in internal affairs datasets.

They are **not** finished Brady benchmarks in the legal sense.

What they support:
- ECA can rank and flag police misconduct records that are often relevant to officer impeachment.
- ECA can recover structured and semi-structured misconduct records at different strictness tiers.

What they do not support:
- "ECA finds all Brady material"
- "ECA ensures Brady compliance"
- "This corpus is legal ground truth for Brady disclosure"

Safe claim:
- "ECA identifies Giglio-relevant misconduct records in police oversight datasets with measurable recall."

Unsafe claim:
- "ECA determines Brady materiality automatically."

## Current Benchmark Assets

In this repository:
- [build_ppd_benchmark.py](build_ppd_benchmark.py) — PPD v1 builder script
- [build_cpd_benchmark.py](build_cpd_benchmark.py) — CPD v2 builder script
- [ppd_v1/benchmark_summary.json](ppd_v1/benchmark_summary.json) — PPD build stats + label rules
- [ppd_v1/ground_truth_labels.csv](ppd_v1/ground_truth_labels.csv) — PPD tier labels per complaint
- [cpd_v2/benchmark_summary.json](cpd_v2/benchmark_summary.json) — CPD build stats + label rules
- [cpd_v2/ground_truth_labels.csv](cpd_v2/ground_truth_labels.csv) — CPD tier labels per complaint

This document describes the benchmark **as currently implemented**, not a hypothetical future design.

The generated document corpora (3,618 PPD + 10,000 CPD `.txt` files) are gitignored — run the builder scripts against the source CSVs to regenerate them.

## Benchmark v1: Philadelphia Police Department

### Purpose

Primary text benchmark for police-misconduct discovery. This is the strongest current benchmark because the source data contains short natural-language complaint summaries.

### Source Files

- `ppd_complaints.csv` — 3,622 complaint records with narrative summaries
- `ppd_complaint_disciplines.csv` — 11,196 officer discipline records

Source: [Philadelphia Police Advisory Commission Open Data](https://www.opendataphilly.org/)

### Unit of Evaluation

One document per `complaint_id`.

The builder joins:
- `ppd_complaints.csv` on `complaint_id`
- `ppd_complaint_disciplines.csv` on `complaint_id`

The generated document contains:
- complaint metadata
- complaint summary text
- one or more officer allegation / finding blocks

### Inclusion Rule

The current builder only emits documents where `summary` length is at least 20 characters.

### Current Build Output

From [ppd_v1/benchmark_summary.json](ppd_v1/benchmark_summary.json):
- Total documents: 3,618
- Positive documents: 436
- Positive rate: 12.1%

Tier distribution:
- Tier 0 `negative`: 3,182
- Tier 1 `strong_giglio`: 60
- Tier 2 `giglio_relevant`: 113
- Tier 3 `brady_adjacent`: 263

### Label Rules

Implemented in [build_ppd_benchmark.py](build_ppd_benchmark.py).

Tier 1 `strong_giglio`
- allegation contains `Falsification`, `Criminal allegation`, or `Criminal`
- and investigative finding is `Sustained Finding`

Tier 2 `giglio_relevant`
- allegation contains `Falsification`, `Criminal allegation`, or `Criminal`, regardless of finding
- or top-level complaint classification is `CRIMINAL ALLEGATION` or `FALSIFICATION`

Tier 3 `brady_adjacent`
- complaint classification is `PHYSICAL ABUSE` or `CIVIL RIGHTS COMPLAINT`
- and the complaint has at least one sustained finding

Tier 0 `negative`
- everything else

### What v1 Actually Tests

- complaint-text retrieval
- complaint-level classification
- ability to recover high-signal officer misconduct from short narrative text plus structured findings

### What v1 Does Not Test

- long-form discovery review
- OCR-heavy police records
- bodycam transcript review
- witness-specific Brady materiality

### Recommended Metrics

Primary:
- Recall at tier `>= 1`

Secondary:
- Recall at tier `>= 2`
- Precision at tier `>= 2`

Operational metric:
- Median rank of tier-1 documents in search / triage outputs

## Benchmark v2: Chicago Police Department

### Purpose

Structured classification benchmark using Chicago police oversight data. This is useful for impeachment-pattern detection, but it is materially weaker than PPD for pure text retrieval because the source tables are mostly structured.

### Canonical Source Files Used by the Builder

- `complaints-accused.csv` — 263,765 accused officer records
- `complaints-complaints.csv` — 234,978 complaint records (metadata)

Source: [Chicago COPA / Invisible Institute Citizens Police Data Project](https://beta.cpdp.co/)

The builder scripts reference local paths to these CSVs. Update the path constants in the scripts if your local layout differs.

### Unit of Evaluation

One synthetic document per `cr_id` complaint record.

The builder:
- groups `complaints-accused.csv` by `cr_id`
- looks up dates / status in `complaints-complaints.csv`
- writes a synthetic internal-affairs-style text document for each complaint

### Sampling Rule

The current implementation caps the benchmark at the first 10,000 sorted `cr_id` values. This is a tractability choice, not a methodological requirement.

### Current Build Output

From [cpd_v2/benchmark_summary.json](cpd_v2/benchmark_summary.json):
- Total documents: 10,000
- Positive documents: 2,210
- Positive rate: 22.1%

Tier distribution:
- Tier 0 `negative`: 7,790
- Tier 1 `strong_giglio`: 8
- Tier 2 `giglio_relevant`: 502
- Tier 3 `brady_adjacent`: 59
- Tier 4 `brady_weak`: 1,641

### Label Rules

Implemented in [build_cpd_benchmark.py](build_cpd_benchmark.py).

Strong Giglio keywords:
- `false arrest`
- `illegal arrest`
- `false report`
- `perjury`
- `falsif`
- `criminal`

Brady-adjacent keywords:
- `excessive force`
- `civil rights`
- `unnecessary physical`
- `coercion`
- `racial`
- `discrimination`

Tier 1 `strong_giglio`
- strong Giglio keyword present
- and `final_finding == SU`

Tier 2 `giglio_relevant`
- strong Giglio keyword present
- regardless of final finding

Tier 3 `brady_adjacent`
- Brady-adjacent keyword present
- and `final_finding == SU`

Tier 4 `brady_weak`
- Brady-adjacent keyword present
- regardless of final finding

Tier 0 `negative`
- everything else

Finding-code map used by the builder:
- `SU`: Sustained
- `NS`: Not Sustained
- `UN`: Unfounded
- `NAF`: No Affidavit
- `EX`: Exonerated
- `AC`: Administratively Closed
- `DIS`: Discharged
- `NC`: No Cooperation

### What v2 Actually Tests

- classification over structured misconduct content
- ranking complaints by impeachment relevance
- synthetic-document ingestion based on real fields

### What v2 Does Not Test

- natural-language retrieval over real complaint narratives
- large heterogeneous discovery sets
- direct linkage from use-of-force reports to complaint documents

## TRR Supplement

Useful but not yet integrated into the benchmark:
- `trr_main.csv` — 98,865 tactical response reports
- `trr_actions_responses.csv` — 1,432,481 force action records
- `trr_subjects.csv` — 168,584 subject records

Observed row counts:
- `trr_main.csv`: 98,865
- `trr_subjects.csv`: 168,584
- `trr_actions_responses.csv`: 1,432,481

Current limitation:
- the extracted `trr_main.csv` header does not expose a reliable complaint join field for direct complaint-benchmark integration

Recommended use:
- separate force-pattern benchmark
- secondary enrichment signal for officer-risk profiling

## Practical Recommendation

If only one benchmark is used for product claims, use **PPD v1**.

Reason:
- it contains real narrative text
- it has explicit officer findings
- it is the closest thing in this dataset pack to an ingest-and-retrieve discovery benchmark

Use **CPD v2** as a supplement for:
- larger-scale misconduct classification
- synthetic document generation
- structured impeachment-pattern detection

## Scoring Guidance

For any benchmark run, record at minimum:
- corpus version
- benchmark version
- model / pipeline version
- ingest settings
- query set used
- top-k window evaluated
- recall by tier
- precision by tier

Minimum reporting table:

| Benchmark | Docs | Positive Tier | Recall@k | Precision@k | Notes |
|-----------|------|---------------|----------|-------------|-------|
| PPD v1 | 3,618 | Tier >= 1 | | | |
| PPD v1 | 3,618 | Tier >= 2 | | | |
| CPD v2 | 10,000 | Tier >= 1 | | | |
| CPD v2 | 10,000 | Tier >= 2 | | | |

## Claim Language

Recommended:
- "Measured on police oversight datasets containing misconduct allegations, findings, and discipline outcomes."
- "Measured on a Giglio-relevant misconduct benchmark."
- "Measured on Philadelphia complaint narratives and Chicago structured misconduct records."

Avoid:
- "Brady-complete"
- "Guaranteed Brady compliance"
- "Finds all exculpatory evidence automatically"

## Known Gaps

This benchmark suite still lacks:
- bodycam transcripts
- jail call transcripts
- police report narratives at discovery scale
- prosecutor disclosure logs
- witness-specific linkage to a live criminal case

That means this benchmark is credible for **Giglio / impeachment signal detection**, but still incomplete for full criminal-discovery benchmarking.
