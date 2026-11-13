# Data layout and provenance

Runtime inputs, evaluation answers, training data, and local outputs are separate.
The assessment does not read gold answers. The [POC overview](../docs/poc-overview.md)
explains why synthetic borrowers and public issuers are distinct.

| Location | Contents | In Git? |
| --- | --- | --- |
| `app/synthetic/` | 37 fictional borrowers, 172 financial records, prepared terms, and ready-to-use SQLite | Yes |
| `app/sec/public_sec_documents.csv` | 69 public filing references with identities and dates | Yes |
| `evaluation/` | Expected answers, synthetic scenarios, judge demos, and historical extraction snapshot | Yes |
| `training/synthetic/` | Simulated histories, features, outcomes, splits, and manifest | Yes |
| `models/logistic_regression/v1/` | Synthetic-trained pipeline and compatibility/evaluation manifest | Yes |
| `cache/sec/` | Downloaded HTML, cleaned HTML, Markdown, and conversion markers | No |
| `runtime/` | Working databases, saved assessments/reports, backups, and local evaluation output | No |

Test fixtures live in `tests/fixtures/`; the dated evaluation corpus lives in
`homework/evaluation/`. Source catalog membership does not establish that a filing
has been downloaded, processed, or checked for the required exhibit.

## Run with bundled inputs

Web V2 needs no import or training after cloning. It creates working copies under
`data/runtime/portfolio/`. Existing workspaces receive backed-up additive updates
that preserve saved work. The CLI reads bundled inputs and writes local analytics:

```bash
uv run --locked python scripts/run_assessment.py \
  --borrower-id SYN002 --period-end 2025-09-30 --information-cutoff 2025-09-30
```

For forecasts and calculation definitions, see [covenant assessment](../docs/guides/covenant-assessment.md).
Maintainers who edit the financial CSV must run
`uv run --locked python scripts/prepare_demo_database.py`, commit the CSV/database
together, and restart the app. `--financial-db` chooses a separate CLI database.

The bundle has **198 synthetic expected results**: 18 original and 180 added.
Import provenance is in
[dataset_bundle_manifest.json](app/synthetic/dataset_bundle_manifest.json).
The original delivery ZIP is unnecessary for reproduction. The
[integration record](../v2-plan/archive/implementation/dataset-integration.md)
preserves import and compatibility details. The trained model uses the original
12 scenario templates rather than the expanded runtime population.

## SEC source download

```bash
export SEC_USER_AGENT="Your Name your.email@example.com"
uv run --locked python scripts/download_sec_documents.py --document-id DOC_FMC_AMD3_2025
```

Omit `--document-id` for the catalog, or repeat it for selected documents. Downloads
and processing share `cache/sec/html/<document_id>.html`; conversion writes to
`cache/sec/markdown/`. Nonempty cached HTML is reused. Cache misses need the
identifying User-Agent; requests are throttled and failures return nonzero.
Only HTML is supported. `--source-file` and `--html-dir` override locations.

Explicit source links do not automatically transfer extracted terms or financial
values into a synthetic borrower assessment. Legal precedence and formula
interpretation require review. [Document processing](../docs/guides/document-processing.md)
explains binding and reuse.

## Evaluation and preservation

The public benchmark has 42 cases across ten borrowers. Its evidence grades are:

| Grade | What the supplied evidence supports |
| --- | --- |
| A | Enough inputs to recompute a metric |
| B | A disclosed threshold/actual, status, breach, or waiver |
| C | Mainly threshold, amendment, or waiver facts |
| EW | A temporal early-warning comparison |

Filings often lack contractual EBITDA inputs needed for independent calculation.
Later filings are outcome labels only in early-warning tests. Gold answers, notes,
and scenario descriptions are excluded from runtime evidence. Unknown availability
dates stay unknown; ingestion timestamps are not publication dates.

The [historical SEC snapshot](evaluation/snapshots/sec/covenants.sqlite3) is read-only
evaluation evidence, never a runtime default. [Evaluation commands](../docs/evaluation/README.md)
and [recorded failures](../docs/evaluation/results.md) explain its contract and limits.
