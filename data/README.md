# Data layout

App inputs, evaluation answers, training data, and local output are kept separately.
The working assessment never reads gold labels. The **Benchmark portfolio (mock)** page
uses pre-labeled examples and is separate from live assessments.

| Location | Contents | In Git? |
| --- | --- | --- |
| `app/synthetic/` | Fictional borrowers, financial CSVs, terms, and ready-to-use SQLite database | Yes |
| `app/sec/public_sec_documents.csv` | Catalog of 69 public SEC sources | Yes |
| `evaluation/` | Gold labels, 60 tasks, judge examples, and a preserved extraction snapshot | Yes |
| `training/synthetic/` | Reviewed synthetic histories, features, outcomes, and manifest | Yes |
| `models/logistic_regression/v1/` | Synthetic-trained pipeline and compatibility manifest | Yes |
| `cache/sec/` | Downloaded HTML, cleaned HTML, Markdown, and conversion markers | No |
| `runtime/` | Working databases, saved reports, backups, and evaluation output | No |

Test fixtures live in `tests/fixtures/`; the dated evaluation corpus lives in
`homework/evaluation/`. See [data sources](../docs/project/data_sources.md) for provenance.

## Run with bundled inputs

No import or training is needed after cloning. The app creates a local working copy;
existing workspaces receive backed-up additive updates that preserve saved work.
The CLI reads the bundled database and writes results to local runtime storage:

```bash
uv run --locked python scripts/run_assessment.py \
  --borrower-id SYN002 --period-end 2025-09-30 --information-cutoff 2025-09-30
```

For the bundled forecast, use `uv run --locked --extra ml` and add
`--ml --model-type logistic_regression --model-artifact data/models/logistic_regression/v1`.
See the [ML guide](../docs/guides/ml_early_warning.md).

Maintainers who edit the bundled financial CSV must run
`uv run --locked python scripts/prepare_demo_database.py`, commit the CSV and database
together, and restart the app. Use `--financial-db` for a separate CLI database.

The bundle has 37 borrowers, 172 financial records, and 198 synthetic expected results
(18 original and 180 added). Import provenance is in
`app/synthetic/dataset_bundle_manifest.json`. The original delivery ZIP is unnecessary
for running the project; [integration notes](../docs/project/dataset_expansion_plan.md)
cover maintenance.

## SEC source download

```bash
export SEC_USER_AGENT="Your Name your.email@example.com"
uv run --locked python scripts/download_sec_documents.py --document-id DOC_FMC_AMD3_2025
```

Omit `--document-id` for the whole catalog, or repeat it for several documents.
Downloads and processing share `cache/sec/html/<document_id>.html`; converted files go
to `cache/sec/markdown/`. Nonempty cached HTML is reused. Cache misses need an identifying
User-Agent; downloads are throttled. Failed files remain explicit and return a nonzero exit.
Only HTML is supported. Use `--source-file` and `--html-dir` to override locations.

## Evaluation and preservation

The public benchmark has 42 cases across 10 borrowers. Evidence grades describe what
the source supports:

| Grade | Evidence |
| --- | --- |
| A | Enough inputs to recompute the metric |
| B | Disclosed threshold and actual, status, breach, or waiver |
| C | Mainly threshold, amendment, or waiver facts |
| EW | A temporal early-warning case |

Public filings often lack contractual EBITDA inputs needed for independent calculation.
Future documents are outcome labels only in early-warning tests. Notes and labels stay
out of model inputs; unknown availability dates remain unknown.

Measure the preserved extraction snapshot explicitly:

```bash
uv run --locked python scripts/compare_public_sec_gold.py \
  --database data/evaluation/snapshots/sec/covenants.sqlite3 \
  --output data/runtime/sec-evaluations/review
```

The runner opens SQLite read-only and saves observations, hashes, coverage, and reports.
Strict source coverage also needs the corresponding local Markdown. The snapshot is
historical evaluation evidence and is never a runtime default. See the
[evaluation guide](../docs/homework/evaluation.md) for comparison rules and known gaps.
