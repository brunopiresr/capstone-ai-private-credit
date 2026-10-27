# F05–F12 implementation results

> Historical record. Paths, APIs, commands, and line numbers below describe the original work. For the current layout and runnable commands, use the [documentation index](../README.md).

Implemented on 18 October 2026 against `b1dd404`, following
[the implementation plan](../archive/capstone_cleanup_f05_f12_implementation_plan.md).
F05, F06 and F08–F12 meet their implementation gates. F07 reporting/replay is
implemented; **its extraction-quality gate remains open, with catalog/benchmark work deferred by the user**.

| Finding | Delivered | Acceptance evidence |
| --- | --- | --- |
| F05 | Direct verifier controls and schema-valid tampered assessments in `tests/unit/verification/test_assessment_verifier.py`. | 28 tests cover scope, future inputs, provenance, reported evidence, unresolved results, recalculation, history, prediction identity and dishonest stub output. No verifier weakening. |
| F06 | Shared scenario contracts/criteria, offline judge-helper regressions, saved answer/trace/feedback, explicit missing-date gate and required financial-read sequences. | Final live run: all 6 scenarios pass, including all 3 final-answer judge checks. Eight helper tests also pass. One later omission of activation figures was diagnosed and corrected before final validation. |
| F07 | Reusable comparator, explicit read-only snapshot CLI, manifests and hashes, replay, coverage statuses, captured FMC regressions and source-based failure register. | Original selected observations replay identically: 37 failing / 42 evaluable cases. Fresh isolated FMC extraction still fails 4 / 4 cases. Supported failures are retained; quality remains open. |
| F08 | `RiskAssessment.trends` built once after verified results are saved, independent of ML; reused for prediction and narrator/tool context, shown in Streamlit. | Known QoQ deltas, identical ML-on/off trends, no model/snapshot/prediction when off, preserved compliance on trend/model failure, and UI values tested. Invalid calculations cannot reach storage, trends or ML. |
| F09 | Explicit `application/bootstrap.py` factories, injected service collaborators, narrow stored-facts/source-text protocol, migrated CLI/UI/notebooks/tests. | Services construct without filesystem side effects; source resolution works with supplied facts/text; source/analytics database separation remains enforced. |
| F10 | Repository-owned financial row mapper and typed period/history reads; domain-owned metric allowlist. | Metadata/null/date bounds and exclusion of notes/gold fields tested. Existing raw repository reads retained; SQL/schema unchanged. |
| F11 | Typed phases for covenant resolution, simulation, labeling, training, artifact writing, and streaming event/history handling. | Existing ambiguity, provenance, leakage, optional-dependency and stream/cancellation checks pass. Small seeded generation reproduced all seven output hashes exactly. |
| F12 | Retrieval-owned complete-Markdown chunk/index lifecycle, invalidation and ticker filtering; notebook excerpt experiment explicitly labeled. | Real competing-corpus tests cover relevant/decoy/wrong-issuer ranking, late passages, exact offsets, metadata/content/membership changes and retained result caps. |

## Validation

```bash
.venv/bin/python -u -m pytest -q -p no:cacheprovider \
  -o faulthandler_timeout=30 --tb=short tests homework-tests
# 521 passed, 6 skipped in 40.95s (only opt-in live scenarios skipped)

.venv/bin/python -u -m pytest -q homework-tests --run-live
# 14 passed in 37.40s: 8 offline helpers and 6 live scenarios

.venv/bin/ruff check --no-cache .
.venv/bin/ruff check --no-cache --config 'include = ["*.py"]' homework-tests
# Both clean

git diff --check
# Clean
```

The full suite includes installed ML training/integration checks and Streamlit tests.
Asynchronous tests and live requests ran outside the sandbox after sandboxed runs
stalled. Live generation used `openai-responses:gpt-4o-mini` and judging used
`openai:gpt-4o-mini`; captures remain in
ignored `data/processed/judges-homework-*` directories. Live success is evidence for
these scenarios, not a general model-reliability guarantee.

The integrated suite was rerun after the v2.3 input/prompt changes. A focused run
of snapshot, prompt and extraction contracts also passed all 22 tests.

## F07 deferred acceptance gate

See [the source/field failure register](public_sec_benchmark_triage.md), containing
all 37 failing cases and 154 mismatched or missing fields, selected cache keys,
source quotations/locations, corrective instructions, regressions and blockers.
The five remaining baseline cases match supported facts only; 117 populated
assessment targets remain explicitly unsupported.

The v2.2 extraction prompt addresses source-confirmed confusion between actuals
and limits, adjacent-covenant operators, categories and quotations. A real refresh
of three FMC filings (11 complete sections) still produced four failing gold
comparisons. Prompt changes alone did not close the quality gate. Historical
amendment precedence, source/exhibit coverage, exact measure naming and dated
waiver associations also require further work. No gold was changed, no cached
observation was repaired, and no matching amendment was selected merely to pass
an expectation. Automatic extraction verification remains disabled as required.

Follow-up v2.3 removes descriptive catalog notes from single and batch extraction
inputs, preserves source names and addresses contradictory table headers. Both
model-input paths have regressions proving source text and provenance survive.
A further complete-document GPT-4.1 experiment yielded 32 matching and 12 missing
FMC fields, with no mismatches; all four cases still fail because expanded metric
names and agreement-wide disclosures do not satisfy the existing strict projection.
The default model remains unchanged. Source-backed catalog and benchmark changes
were explicitly deferred by the user; the linked triage records the verified
Polaris and American Vanguard exhibit sources for that later work.

Local artifacts and reproducible commands:

```bash
# Baseline report: intentionally exits 1 while supported failures remain.
.venv/bin/python scripts/compare_public_sec_gold.py \
  --snapshot data/processed/sec-evaluations/f05-f12-baseline/observations.json \
  --output /tmp/public-sec-replay --require-complete-sources

# Isolated fresh FMC result: also intentionally exits 1.
.venv/bin/python scripts/compare_public_sec_gold.py \
  --snapshot data/processed/sec-evaluations/f05-f12-fmc-refresh/observations.json \
  --gold data/processed/sec-evaluations/f05-f12-fmc-refresh/gold.csv \
  --catalog data/processed/sec-evaluations/f05-f12-fmc-refresh/catalog.csv \
  --output /tmp/public-sec-fmc-replay --require-complete-sources
```

Full generated reports/snapshots are ignored; compact captured FMC observations
and exact source excerpts are included in `tests/fixtures/public_sec_snapshot/`.
The original working database, source datasets, catalog, gold files and fitted
model artifacts are unchanged. F01–F04, F13–F19 and the separate multi-agent proposal
were not expanded into this work.
