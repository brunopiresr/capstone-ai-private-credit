# Private Credit Covenant & Early-Warning Benchmark v1.0

Created for the **Private Credit Covenant & Early-Warning Agent** POC.

## Contents

- `public_sec_documents.csv` — 29 authoritative SEC source documents and URLs.
- `public_sec_gold_cases.csv` — 42 public benchmark cases across 10 borrowers.
- `synthetic_borrowers.csv` — 12 controlled borrower scenarios.
- `synthetic_covenant_terms.csv` — covenant rules, amendments, caps, holidays, springing tests and conflict rules.
- `synthetic_quarterly_financials.csv` — quarterly inputs for deterministic calculation tests.
- `synthetic_gold_labels.csv` — 18 gold synthetic evaluations.
- `evaluation_tasks.jsonl` — 60 ready-to-run evaluation tasks covering both public and synthetic cases.
- `download_sec_documents.py` — guarded CLI sharing the service HTML cache.
- `private_credit_benchmark_v1.xlsx` — human-review workbook containing the same benchmark tables.

## Public evidence grades

- **A** — public source gives enough covenant inputs to independently recompute the metric.
- **B** — public source discloses threshold plus actual/status/breach/waiver, but not every bespoke calculation input.
- **C** — public source is primarily useful for threshold, amendment-precedence or waiver testing.
- **EW** — temporal early-warning case with a later covenant-stress event.

## Recommended evaluation layers

1. **Retrieval:** correct covenant/amendment/source clause.
2. **Versioning:** active amendment or waiver on the test date.
3. **Calculation:** exact numeric metric when inputs are available.
4. **Compliance:** compliant / breach / waived / not-tested / abstain.
5. **Headroom:** direction and exact amount where computable.
6. **Early warning:** flag deterioration before a later breach/waiver event.
7. **Verification:** reject unsupported conclusions and material data conflicts.

## Important leakage rule

For temporal early-warning backtests, do not give the agent documents dated after the information cutoff. Later documents may be used only as outcome labels.

For public extraction cases, the filing itself may contain the answer; these cases measure retrieval, amendment interpretation and faithful extraction rather than independent forecasting.

## Scoring suggestion

- Threshold / operator accuracy: exact match.
- Amendment precedence: exact active version.
- Numeric ratios/headroom: tolerance <= 0.01x (or <= 0.1 for USD_m fields unless a stricter source value exists).
- Status classification: exact categorical match.
- Citation correctness: source document ID must be in the gold source set.
- Early warning: precision/recall by borrower-quarter, plus lead time to subsequent event.
- Abstention quality: conflict cases should not be forced into compliant/breach.

## Public benchmark caveat

Public-company filings are a strong benchmark for covenant extraction, amendments, waivers, disclosed ratios and outcome events. They are not a complete replica of private-credit lender packages, and bespoke covenant EBITDA is often not reconstructible from GAAP financial statements alone. The synthetic set therefore supplies controlled private-credit edge conditions.

## SEC source download

Run from the repository root after the core environment is installed:

```bash
export SEC_USER_AGENT="Your Name your.email@example.com"
uv run --locked python data/download_sec_documents.py
```

The CLI and document processing share `data/sec_documents/html/<document_id>.html`.
Defaults are resolved from the script location, independent of the working directory.
Select one or more documents with repeated `--document-id ID`; override the catalog and
HTML directory with `--source-file PATH` and `--html-dir PATH`. `--help` and importing
the utility perform no downloads or directory creation.

Existing nonempty HTML is reused without credentials. Cache misses require an identifying
`SEC_USER_AGENT`; downloads are serial and throttled. Successful files are published
atomically. A failed or empty download leaves no reusable new file, other documents
continue, and any failure produces a nonzero exit code. Current catalog sources are
HTML. PDF URLs/content are unsupported by this HTML pipeline.

Markdown remains in `data/sec_documents/markdown/` with the existing conversion-version
markers. Old flat `.htm`/`.pdf` files directly under `sec_documents/` are not the active
cache. Leave them intact and run the command to populate the canonical HTML directory;
this cleanup performs no automatic renaming or deletion.
