# Dataset expansion and parallel document processing

Status: Implemented, October 31, 2026.

## Included data

The normalized delivery adds SYN013–SYN037: 25 fictional borrowers, 150 financial
records, 30 covenant identities and 180 independent expected results. SYN018–SYN022
have two covenants. The six periods run from March 2025 through June 2026. Combined
totals are **37 borrowers, 172 financial records and 198 synthetic expected results**.

Forty SEC references add ten issuers, each with one annual and three quarterly filings,
bringing the catalog to **69 sources**. Filing dates and fiscal period ends are distinct.
Accession numbers, filing-index URLs, selection exceptions and delivery verification
metadata remain in the catalog. These are supplied references, not freshly verified
sources. Catalog seeding does not link authentic issuers to fictional borrowers.
Downloads, live extraction and new public-company gold cases are separate explicit work.

## Import and economic definitions

Run `uv run --locked python scripts/import_credit_monitoring_bundle.py` to validate the
local delivery ZIP without changing authored inputs. Add `--apply` to publish staged,
validated normalized CSVs, gold cases, provenance and the ready-to-use financial database.
A repeated identical import is a no-op; conflicting authored keys fail before publication.
The ZIP and supplied README remain ignored. A fresh checkout uses the committed normalized
assets and database without the ZIP, imports, model credentials or training.

Gold cases remain in `data/evaluation/synthetic_bundle_gold_cases.csv`; runtime calculations
never read them. The mock benchmark explicitly combines them with the 18 legacy examples,
shows one row per borrower/covenant, and retains covenant-specific histories. Missing early
warning labels remain unknown. Financial notes and scenario descriptions are excluded from
assessment/model inputs.

New terms select `bundle_v1`; old terms and saved records default to `legacy_v1`.
The bundle contract includes acquired EBITDA and synergies, applies adjustment caps against
nonnegative base EBITDA, floors net debt at zero, and uses the supplied TTM interest expense
and direct fixed-charge numerator/charges. Financial inputs retain USD/millions metadata;
ratios use `x`. Missing values stay null and explicit zeros remain zero.

Springing tests activate strictly below 25%; missing availability is unresolved and inactive
tests do not request calculation inputs. Waived tests retain hypothetical status, actual and
headroom under `financial_inputs.underlying_calculation`, while reported headroom stays null.
SYN037 retains a conflict flag and absent canonical debt, without fabricated competing values.
Comparison precedes display rounding. Calculation replay checks the waived underlying result.
Contract versioning prevents comparisons across different economic definitions.

## Workspace upgrades and ML

Both app entry points share backed-up, additive financial initialization. Existing rows,
analyst edits and saved workflows remain intact. Schema changes, missing-record insertion
and the import receipt commit transactionally. Backups live under the workspace's `backups/`;
repeated startup with the same dataset version does not recopy or back up again. Failed
migrations can be retried. The explicit database rebuild remains available.

The bundled training dataset, model artifact and feature schema are retained. Training
continues to use the original SYN001–SYN012 templates; runtime expansion does not silently
change the reviewed training population. No retraining is part of this integration.

## Parallel document processing

`process_all_documents(ticker=None, *, force=False, max_workers=4)` and
`process_documents(document_ids, *, force=False, max_workers=4, progress=None)` share a
bounded thread-pool runner. The app's Process actions call the selected-document API;
**Documents processed at once** controls concurrency. Setting one runs sequentially.

Each document task owns its model/provider client, event loop and converter; its sections
remain sequential. Injected resources require factories for parallel processing, with
matching model identity. Complete cache hits do not construct clients. Workers inherit a
separate copied execution context, preserving session/tracing attribution. Progress events
are drained on the caller, aggregate progress is monotonic, and outcomes preserve input order.
Individual failures retain their outcomes and do not prevent other files from finishing.

Catalog validation occurs before workers start. Short SQLite writes and same-document cache
writers are locked. SEC requests retain a process-wide request/delay lock. Atomic cache writes
avoid partial published files. Workflow notifications run on the coordinator; the extraction
archive is published after workers finish, under the existing maintenance-operation lock.

## Validation

The independent suite covers all 180 new outcomes, multi-covenant selection, null/zero inputs,
waivers, trigger boundaries, debt conflicts, legacy compatibility, source cutoff isolation,
additive upgrades and migration recovery. Portable importer tests reconstruct a delivery from
versioned inputs, so CI does not depend on the ignored ZIP.

Concurrency tests use barriers/events for overlap, bounds, result order, worker-resource
cleanup, context propagation, caller-thread progress, cache reuse, and same-document locking.
The Streamlit checks exercise multi-file Process and the expanded borrower/benchmark views.

Run `make lint`, `make test-all` and `make test-ml`. The offline throughput command is:

```bash
uv run --locked python scripts/benchmark_document_processing.py \
  --output data/runtime/document-processing-benchmark.json
```

An eight-document run with 150 ms simulated model I/O per document measured 1.508 s with
one worker, 0.730 s with two and 0.434 s with four: **3.47×** faster with four workers and
exactly eight model calls in every run. This measures orchestration with real local storage
and mocked model I/O, not live-provider throughput or extraction accuracy. Timing is reported
rather than asserted in CI.
