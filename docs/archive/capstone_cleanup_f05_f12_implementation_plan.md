# Implementation plan: cleanup findings F05–F12

> Historical record. Paths, APIs, commands, and line numbers below describe the original work. For the current layout and runnable commands, use the [documentation index](../README.md).

Prepared: 18 October 2026. Source: [capstone cleanup review](../reviews/capstone_cleanup_review.md), findings F05–F12. Code inspected at `92a21e4`, including the current uncommitted changes.

This is an implementation plan. Preparing it changes no application code, tests, configuration, datasets, caches, or model artifacts. The review's test results are historical evidence; this planning task did not rerun the suites or make live model requests.

Implementation evidence and remaining gates are recorded in
[the implementation results](../reviews/capstone_cleanup_f05_f12_implementation_results.md).

## Intended outcome and constraints

The retained assessment workflow should reject unsupported structured results, expose deterministic trends with prediction disabled, and give analysts answers supported by actual tool execution. Its storage, covenant resolution, retrieval, and framework-event boundaries should be understandable and independently testable.

Preserve PydanticAI, SQLite, synthetic training and prediction, explicit formula mappings, exact source provenance, information cutoffs, abstention, complete-document extraction, resumable caches, and borrower/time-separated model validation. Automatic post-extraction verification remains disabled; its standalone validators remain available. Active assessment verification does not certify generated prose.

F01–F04 and F13–F19 are outside this plan. F01 is already represented by commit `92a21e4`; retain its formula-family tests. The working tree contains HTML-cleaning and Streamlit work relevant to F03/F04: integrate with that work without overwriting it or claiming those findings are complete. SYN010's missing-input behavior remains authoritative while F02's fixture correction is handled separately. No WATCH rule, additional agents, vector infrastructure, monitoring platform, ORM, or dependency-injection container is needed here. The separate bullish/bearish agents proposal is not a dependency of this cleanup.

The [F13–F19 plan](capstone_cleanup_f13_f19_implementation_plan.md) also schedules offline judge-helper regressions under F16. Implement that shared test module once: F06 defines the answer/tool contracts, while F16 incorporates those tests into the documented check commands. Coordinate overlapping notebook setup, logging-decorated helpers, and documentation edits without expanding either plan's scope.

## Delivery sequence

Each row is a reviewable change. F07 investigation can continue alongside the boundary work; its quality failures remain visible throughout.

| Order | Finding | Deliverable | Dependency / completion gate |
| --- | --- | --- | --- |
| 1 | F05 | Direct negative tests for the active verifier. | Establish before changing assessment orchestration. |
| 2 | F06 | Shared scenario contracts, explicit final-answer judging, and offline judge-helper regressions. | Preserve existing financial-read order and date requirements. Establish before streaming refactoring. |
| 3 | F07 | Portable comparator tests, an explicit snapshot comparison command, and a source-based failure register. | Capture the selected observations before any regeneration. Quality fixes follow their established causes. |
| 4 | F10 | Typed financial reads and persistence-owned row mapping. | Update both assessment and tool consumers together. |
| 5 | F09 | Explicit service composition and narrow extraction/source-reading capabilities. | Build on typed financial reads; update every constructor call site. |
| 6 | F08 | Deterministic trends returned independently of prediction. | Reuse the existing feature builder and the composed result repository. |
| 7 | F12 | Retrieval-owned chunk/index lifecycle and real-index selection tests. | Inject the retrieval collaborator through F09's composition boundary. |
| 8 | F11, covenant resolution | Typed helpers for source selection, applicability, evidence, and resolved terms. | Use F09's source-reading boundary; retain F05 protections. |
| 9 | F11, ML | Separate simulation, labeling, training validation, fitting, and artifact-writing phases. | Keep F08's shared feature contract and all current leakage safeguards. |
| 10 | F11, streaming | Smaller event translation and completion/failure phases. | Preserve F06's contracts and existing streaming/conversation behavior. |

Before implementation, record the current targeted test outcomes and the working-tree changes. Run all checks against temporary storage. Treat differences from the review's baseline as new observations to investigate, rather than assuming the review still describes the exact checkout.

## F05 — Prove that active verification rejects altered assessments

**Primary files:** `src/credit_monitoring/verification/verifier.py`; new `tests/unit/verification/test_assessment_verifier.py`; existing calculation and assessment workflow tests.

Build a small, independently specified valid assessment with known availability dates and source evidence. For example, debt 100, eligible cash 20, and adjusted EBITDA 20 imply net leverage 4.0x; a maximum of 5.0x implies headroom 1.0x and compliance. Specify the expected result explicitly rather than generating the entire test oracle with `calculate_covenant()`.

Deep-copy that baseline and alter one fact per parameterized case. Use separately valid reported-result and stub-prediction controls for their respective cases. Call `verify_assessment()` directly and assert `is_valid == False`, the expected error code, and the affected field where useful. Avoid assertions on entire message strings or issue ordering.

| Invalid fact | Expected issue code |
| --- | --- |
| Result borrower, run identifier, reporting period, or cutoff lies outside the enclosing assessment. | `result_scope_mismatch` |
| Financial availability is later than the assessment cutoff. | `future_financial_inputs` |
| Covenant availability is later than the assessment cutoff. | `future_covenant_terms` |
| Resolved result has no provenance. | `missing_provenance` |
| A source-reported actual has no supporting reported-value evidence. | `missing_reported_evidence` |
| Unresolved terms claim an established compliance result. | `unresolved_compliance` |
| Stored actual, headroom, threshold, operator, or compliance status differs from its inputs. | `calculation_mismatch` |
| Prediction has no snapshot or identifies another snapshot/borrower/period. | `prediction_identity_mismatch` |
| Stub supplies a probability, anomaly score, or a risk level other than `unknown`. | `stub_forecast` |

Keep a valid control and a warning-only case: unknown availability should produce `information_availability_unknown` without invalidating otherwise valid calculations. Exercise a historical result as well as a current result. Retain independent minimum-covenant and equality examples in `test_assessment_calculations.py`.

**Acceptance:** every protection above is exercised by a schema-valid altered assessment and fails for its intended reason. Existing valid service assessments still verify. Production changes are limited to defects these tests expose; do not enable extraction verification or broaden this into a verifier redesign.

## F06 — Evaluate what the analyst actually receives

**Primary files:** `homework-tests/test_main_scenarios.py`, `test_llm_scenarios.py`, `criteria_helpers.py`, and `README.md`; new shared `scenarios.py` and offline `test_criteria_helpers.py` in that directory.

1. Share the three prompts, exact structured assertions, and final-answer criteria so the ordinary and judged suites cannot drift. Keep the ordinary suite explicitly named and documented as tool-contract coverage. A nonempty answer or a scripted final reply does not establish response quality.
2. Apply exact tool/result checks in the judged suite before calling the existing `assert_criteria()`. Continue using the small PydanticAI judge for meaning and explanation; do not replace it with brittle phrase matching or another evaluation framework.
3. Retain the following acceptance contracts:

| Scenario | Deterministic checks | Final-answer judge checks |
| --- | --- | --- |
| SYN010 missing FCCR inputs | `get_financials` precedes `assess_covenants`; both dates are exactly `2025-09-30`; no prediction call; active test, minimum 1.15x, null actual/headroom, `incomplete`. | Explain activation from 20% availability versus the 25% trigger and explain missing inputs. Claim neither compliance nor breach; invent no FCCR or headroom. |
| SYN002 missing dates | Complete run with an empty tool trace. | Explicitly request both reporting date and information cutoff. Infer no dates from “latest” and give no compliance conclusion. |
| SYN002 stub forecast | `get_financials` precedes `predict_risk`; exact requested dates; stub, null probability, unknown risk; current actual `135 / 26`, maximum 5.5x, and corresponding headroom. | Explain that the forecast is unavailable and distinguish this from current compliance. Never turn null into 0% risk or confidence into breach probability. |

4. Retain offline helper regressions for incomplete/error runs being rejected before judging, failed criteria, missing/reordered/mismatched feedback, and inclusion of the actual final answer plus ordered tool arguments/results in the judge input. These tests mock the judge and prove helper behavior only.
5. Capture generating-model identity, judge identity, final answer, executed trace, criteria, and feedback for live runs. Document the command and current outcome. If live behavior still fails, diagnose the existing prompt/tool orchestration and make the smallest supported correction; keep financial-read order and both date requirements intact.

**Acceptance:** offline helper checks pass, and the same three live scenarios satisfy both exact assertions and final-answer criteria. Live cases remain opt-in. If credentials or a live run are unavailable, mark live acceptance as pending; offline tests alone do not close this finding. No live requests are part of preparing this plan.

## F07 — Separate portable comparison logic from cached quality measurement

**Primary files:** `tests/evaluation/extraction/test_public_sec_gold_cases.py`, its README, `src/credit_monitoring/evaluation/`; new small `scripts/compare_public_sec_gold.py`; compact fixtures under `tests/fixtures/`.

### Reproducibility and reporting

1. Move reusable comparison/report logic into `evaluation/sec_gold.py`. Keep its controlled tests in the ordinary offline suite. Preserve strict unit/number projection, exact threshold comparison, period matching, source restrictions, conflicting-version detection, and the documented rounding tolerance. Gold values are expectations only.
2. Move the database-backed parametrized comparison into an explicit read-only runner. The portable suite should no longer depend on `data/processed/covenants.sqlite3`; this change must make the external comparison easier to run and inspect. Do not replace measured failures with skips or `xfail`.
3. Require an explicit database path for the runner. Fail clearly if it is absent or invalid, and never create it. Preserve selection of the newest document state, including a newest failed state; do not silently fall back to an older success. Report the selection rule.
4. Export a versioned observation snapshot and manifest before regenerating anything. Include repository revision, gold/catalog hashes, selected document IDs and cache keys, configuration/schema/prompt/conversion/segmentation versions, stored statuses, and extraction payload hashes. Include source URLs and source hashes when bytes are available; otherwise record missing source bytes explicitly. A frozen observation export avoids relying on later mutations of the working database.
5. Produce per-case JSON plus a short readable report separating matched facts, mismatches, missing supported facts, missing sources, unsupported targets, partial comparisons, and unevaluable cases. Report denominators and case/field counts. A partial match is never described as full extraction accuracy, and unsupported assessment concepts never count as successful extraction.
6. Exit nonzero on supported mismatches, missing required facts, or no evaluable cases. Preserve documented partial-source comparison semantics in the ordinary report; add `--require-complete-sources` for the strict supported-fact acceptance command. Unsupported targets remain explicitly outside that command's success claim.

Planned command, added by this change:

```bash
.venv/bin/python scripts/compare_public_sec_gold.py \
  --database /absolute/path/to/reviewed-covenants.sqlite3 \
  --output /tmp/public-sec-comparison \
  --require-complete-sources
```

### Investigating quality failures

Create `docs/public_sec_benchmark_triage.md` with one entry per failing supported case/field: expected and observed facts, selected cache keys, exact source quotation and location when available, cause, corrective change, regression, and remaining blocker. Start with the review's FMC examples: mixed 4.77/5.25 thresholds and operators, and the 3.84 reported actual appearing as a 3.0 covenant threshold. These are investigation leads, not established root causes.

Inspect actual source evidence before classifying a problem as extraction error, source/version selection error, comparator error, or an expectation needing correction. Changes to gold require independently documented source justification. Re-extraction, if needed, writes to a separate working cache with its model/configuration recorded. Never edit cached observations or fill missing facts from expected answers.

Add a compact source/observation regression for each distinct corrected cause. Preserve a captured failing observation where useful so the comparator still proves it detects the original error. Keep observations independently produced and disclose whether they are captured model outputs or hand-authored controlled examples.

**Acceptance:** the portable comparator suite runs without a public cache; a named snapshot produces the same report on rerun; supported failures remain visible with source-based dispositions. Track reporting and quality repair separately. F07 is not fully complete while supported quality failures or unreviewed source gaps remain. The review's **37 failures** are its historical measurement, not a fresh result from this planning task.

## F10 — Map persistence rows once, outside the domain

**Primary files:** `domain/assessment.py`, `domain/financials.py`, `financials/mappings.py`, `financials/repositories.py`, `application/assessment_service.py`, `agents/tools/assessment.py`; financial repository and feature tests.

1. Put the single row-to-`FinancialPeriod` mapper beside `FinancialRepository`. Add typed reads such as `get_period()` and `get_period_history()`. Let assessment orchestration and assessment tools consume those objects directly.
2. Remove `FinancialPeriod.from_repository_row()` after migrating its production and test callers. Preserve explicit source file/row, load timestamp, availability date, currency, scale, null values, ordering, and the reporting-date bound.
3. Move the shared allowed metric names into the domain's financial contracts; let the CSV mapping module import that list and retain storage/unit mapping details. `domain/assessment.py` should no longer import `financials.mappings`, and there should be one authoritative allowlist.
4. Keep raw `get_quarter()`, `get_history()`, and fact-query APIs where existing loading/notebook consumers need repository rows; document these as low-level reads. Do not force unrelated CSV demonstrations to change representation. All business consumers of `FinancialPeriod` use the typed boundary.

**Acceptance:** tools and service calculations receive equivalent typed values; benchmark notes and gold fields cannot enter metrics; `loaded_at` never becomes `available_at`; missing periods stay missing; existing SQL parameterization and atomic imports remain intact. Add a focused mapper/typed-read regression and retain current repository tests.

## F09 — Compose storage and collaborators outside workflows

**Primary files:** both application services, `covenants/structured.py`, a small `application/bootstrap.py` composition module, CLI scripts, `web/workspace.py`, notebook setup cells, and their fixtures.

1. Make `AssessmentService` accept the result, snapshot, and prediction repositories, feature builder, model factory, and risk-analysis collaborator that it currently constructs. Keep settings as settings. The constructor should not choose storage paths or initialize SQLite tables.
2. Make `DocumentProcessingService` accept its `CovenantRepository`. Keep existing model, converter, catalog, sectioning, and cache semantics. F12 subsequently supplies a retrieval collaborator through the same explicit construction path.
3. Add small explicit construction functions used by entry points. They resolve paths, enforce separate source/analytics storage, initialize concrete repositories, and wire shared collaborators. Preserve that database separation guard with a regression. Do not add a registry, container, or optional constructor fallbacks that recreate hidden assembly.
4. Replace `ExtractionCovenantReader`'s `DocumentProcessingService` parameter with narrowly typed capabilities to get a `DocumentExtraction` and read its source Markdown. A small protocol or two typed callables is sufficient. Supply catalog-validated source reading through a public adapter/method. Remove the import from `covenants/structured.py` to `application` and remove its access to `.markdown_dir`.
5. Migrate `scripts/run_assessment.py`, the current Streamlit workspace, both notebook setup paths, homework setup, model-training integration tests, and shared test fixtures together. Keep entry-point-specific choices explicit; tests can supply local collaborators directly.

**Acceptance:** services can be constructed with supplied collaborators without creating a database as a constructor side effect. Resolution can run against supplied stored facts/text without importing an application service or knowing a filesystem layout. Existing stale/failed/missing extraction handling, quote checks, availability filtering, append-only results, atomic writes, and resumability still pass. No new model/network calls occur during construction or source inspection.

## F08 — Return deterministic trends when ML is off

**Primary files:** `domain/assessment.py`, `application/assessment_service.py`, `features/risk_feature_builder.py`, `application/risk_analysis_service.py`, assessment tools, and the current Streamlit assessment renderer.

Use an additive `RiskAssessment.trends: BorrowerRiskFeatures | None` field. The existing `BorrowerRiskFeatures` is explicitly model-independent and already holds the required covenant changes and financial growth. Reuse it rather than introducing a second set of formulas or a forecasting service. Document that the field also carries the current values needed to interpret those changes.

1. After successful structured verification and persistence of the run's results, build deterministic features once whenever current results exist, regardless of `ml_enabled`. Attach them as `trends`; keep the builder bounded by borrower, run, period, and cutoff.
2. Change `_run_ml()` to snapshot and predict from those same features. Keep the model's deep copy, snapshot/source-result references, identity checks, prediction verification, and failure records. With ML off, create no model, feature snapshot, or prediction record.
3. Preserve exact prior-quarter/year requirements, calculation-basis compatibility, calculated-versus-reported distinctions, waiver/breach indicators, and financial source/currency/scale checks. Unsupported model families can still have deterministic trends; model conversion remains a separate guarded step.
4. Expose trends in narrator context and existing tool serialization. Keep the current `risk_features` context key compatible while sourcing it from the deterministic field. Display service-provided changes in the current UI without adding UI-side arithmetic or a WATCH cutoff.
5. If current results are absent or verification fails, return unavailable trends with a clear issue where appropriate. A feature-building failure preserves calculated results and records the limitation. With prediction requested, report its unavailability/failure using existing ML status semantics.

**Acceptance:** SYN002's ML-off assessment returns metric change `135 / 26 - 130 / 28`, EBITDA growth `-2 / 28`, and null year-over-year growth. The same inputs yield identical deterministic values with ML on, and the snapshot contains those values. Missing quarters, basis changes, source/currency/scale changes, incomplete inputs, and model failure preserve the existing null/comparability rules. Invalid structured results never feed prediction or published trends.

## F12 — Give lexical retrieval ownership of evidence selection

**Primary files:** `application/document_processing_service.py`, `retrieval/lexical/sec.py` and a small adjacent local-search module, `notebooks/02-rag.ipynb`, retrieval tests, and document-processing tests.

1. Move complete-Markdown chunk construction, content/metadata fingerprinting, retained index state, and invalidation out of `DocumentProcessingService.search_evidence()` into one retrieval collaborator. Preserve the current 3,500-character windows at 3,000-character steps, measured Markdown offsets, citations, ticker filtering, two-passages-per-filing cap, and ten-result service limit.
2. Keep the application service responsible for selecting/reading eligible local documents and delegating the query. Retrieval owns chunk/index/search mechanics; it performs no downloading, extraction, or model calls. Changes to text, catalog metadata, or corpus membership must invalidate the retained index.
3. Retain the notebook's keyword/neighbor selection path as an explicitly labeled teaching experiment. Document its `selected_excerpt` coordinates and truncation, and distinguish it from complete-Markdown search. Both paths continue to use the existing lexical index API; a selected excerpt must never masquerade as an original-Markdown offset.
4. Add a tiny real-MinSearch corpus with two issuers, a relevant covenant clause, same-issuer irrelevant material, and a strongly matching wrong-issuer clause. Assert relevant evidence is selected ahead of clear same-issuer decoys and wrong-issuer content is excluded under a ticker filter. Check inclusion and ordering relationships without freezing floating-point scores or the complete ranking.
5. Add a service-level regression using local files and the real retrieval collaborator. Include a relevant later passage beyond the first window, source-slice/offset checks, and an edited document that changes the next search result. Retain compact tests for empty corpora and per-filing/result limits.

**Acceptance:** the competing-corpus tests use the actual index; the service delegates retrieval mechanics; provenance survives chunking and source changes are reflected. Complete-document extraction and section recovery still operate over the entire document, independently of search results. No vector/hybrid infrastructure is added.

## F11 — Extract coherent typed phases after boundaries stabilize

Keep this as three independent refactors. Preserve behavior rather than targeting a method-length number. Reuse existing fixtures and add checks only for meaningful gaps exposed by the new boundaries.

| Area | Proposed phases and typed seams | Behaviors that must remain unchanged |
| --- | --- | --- |
| `covenants/structured.py` | Group bindings; load eligible stored documents; select applicable schedules; resolve testing state; select reported actuals; validate evidence; construct `ResolvedCovenant`. Annotate `_candidate()` and extracted helpers with existing binding, term, schedule, extraction, document, and date types. | Ambiguity/conflicts abstain; amendments and events apply to the right periods; conditional/group-scoped events remain explicit; exact quote/citation/document checks remain; no name-based formula guessing. |
| `ml/synthetic_dataset.py` and `ml/training.py` | Prepare simulation rows; calculate borrower histories; build shared features; label next-quarter outcomes and assign splits; write outputs/manifests. Separately validate training inputs/partitions, fit training-only preprocessing/model, evaluate, and save the artifact. Use small typed records where a helper genuinely returns several related values. | Seeded random draw order and generated data stay reproducible; source fixtures stay unchanged; labels use future results without entering features; unknown outcomes stay excluded; borrower/time boundaries, training-only fitting, hashes, feature order, metadata, and optional imports remain. |
| `agents/streaming.py` | First document the public event/history contract. Then separate provisional model-output handling, tool call/result translation, graph completion, and failure-history construction into a few typed functions. Keep the existing PydanticAI `iter()` execution path. | Actual executed-tool provenance; bounded requests/tool rounds and output retries; copied event payloads; provisional updates before completion; final acceptance only after graph completion; cancellation/closure/callback errors do not commit partial turns; failed runs retain the existing safe failure exchange. |

**Acceptance:** the main methods read as an ordered sequence of phases; extracted helpers have useful parameter and return types. Resolution, generation/training, and streaming/conversation tests pass independently. A small seeded dataset reproduces its prior output hashes when behavior is unchanged; model behavior and manifest compatibility are checked under the pinned dependencies without requiring serialized artifact bytes to match across environments. No tracked training dataset or model is regenerated as a side effect of this refactor. Preserve the retained extraction validator's checks; it is not a complexity-reduction target in this work.

## Validation and completion

Use focused checks for each change, then one combined offline run after integration. Add the planned test files to the relevant existing suites. Commands below use the existing local environment; optional ML dependencies must be installed to execute the retained trained-model checks rather than silently relying on skips.

| Change | Focused validation |
| --- | --- |
| F05 | `.venv/bin/python -u -m pytest -q tests/unit/verification/test_assessment_verifier.py tests/unit/calculations/test_assessment_calculations.py tests/integration/workflows/test_assessment.py` |
| F06 offline | `.venv/bin/python -u -m pytest -q homework-tests/test_criteria_helpers.py` |
| F06 live, explicit | `.venv/bin/python -u -m pytest -v -s homework-tests/test_main_scenarios.py --run-live` and the same command for `test_llm_scenarios.py --run-llm-evals` |
| F07 | Portable comparator tests plus the explicit named-snapshot command above; compare reports and verify input hashes remain unchanged. |
| F10/F09 | Financial repository/persistence tests, assessment workflows, structured-input workflows, and agent tool tests; run notebook setup regressions and the CLI against temporary databases. |
| F08 | Risk-feature and assessment tests with ML off/on/failing; check narrator/tool serialization and current UI rendering of actual trend fields. |
| F12 | Retrieval tests plus document-processing, SEC-pipeline, document-section, and extraction-workflow tests. |
| F11 | Structured-input tests; model-training integration tests; streaming and conversation tests, selected per refactor. |

After F07 separates snapshot measurement from portable tests, run the combined suite:

```bash
.venv/bin/python -u -m pytest -q -p no:cacheprovider \
  -o faulthandler_timeout=30 --tb=short tests homework-tests
.venv/bin/ruff check --no-cache .
.venv/bin/ruff check --no-cache --config 'include = ["*.py"]' homework-tests
```

The homework lint command overrides the current root include filter so it actually selects those files. Reconcile this command with F16 if its configuration change lands first. Public snapshot comparison is a separate required report; a green portable suite cannot stand in for it. No separate Evidently environment is needed for the small PydanticAI judge changes in F06.

For each finding, record the changed files, acceptance evidence, remaining failures, and any external blocker. Finish only when its stated acceptance criteria are met. In particular, keep F06 live behavior and F07 supported-fact quality open when evidence is missing or failing. Confirm the final diff preserves unrelated work and does not modify tracked source datasets, working databases, or fitted artifacts.
