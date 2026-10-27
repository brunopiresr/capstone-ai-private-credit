# POC complexity review and cleanup

Reviewed 27 October 2026 for peer navigation and setup. This review distinguishes
completed simplifications from larger proposals. The application, data, and
homework were reviewed by separate specialists; findings were checked against
actual imports, callers, persistence, and test coverage. Evidence below points to
the post-cleanup source unless explicitly described as the previous design.

## Completed changes

| Finding | Why it increased complexity | Change and current evidence |
| --- | --- | --- |
| App, exercises, experiments, and old plans competed at the root | Reviewers had to infer which entrypoint and instructions were current | Coursework is grouped under `homework/`; [documentation navigation](../README.md) separates context, guides, homework, reviews, and archive. Root onboarding uses `make install`, `make run`, and separate app/homework checks. |
| Runtime inputs, gold answers, generated state, and training outputs shared `data/` | File ownership and prerequisites were unclear; mixed expected answers make accidental leakage easier | [Data navigation](../../data/README.md) defines each location. [paths.py:9](../../src/credit_monitoring/paths.py#L9) supplies simple checkout constants with no import-time I/O. Existing overrides remain. |
| A mutable model registry supported future extension that only tests used | Understanding selection required a stateful registry and registration rules for two built-in models | [factory.py:10](../../src/credit_monitoring/ml/factory.py#L10) now uses explicit model selection. [bootstrap.py:60](../../src/credit_monitoring/application/bootstrap.py#L60) accepts an injected `risk_model` for controlled tests/custom callers. Unknown types still fail explicitly. |
| Features reread newly written results through a repository-bound service | The caller had the exact run in memory, but feature construction required storage setup, filtering, and another read | [risk_feature_builder.py:29](../../src/credit_monitoring/features/risk_feature_builder.py#L29) now accepts results explicitly. [assessment_service.py:150](../../src/credit_monitoring/application/assessment_service.py#L150) uses the current run; borrower/run/date boundaries and missing-quarter rules remain. |
| Synthetic training replayed generated results through temporary SQLite | The generator already held every calculation in memory, so persistence added setup and row-mapping work to a reproducible offline task | The generator now passes the same bounded run to `build_risk_features()`. Exact comparison retained the same 480 controlled feature vectors, training rows, outcomes, and calculations. |
| A narrator protocol and service wrapped a deterministic summary | There was no app caller requiring arbitrary narrator implementations | [risk_analysis_service.py:31](../../src/credit_monitoring/application/risk_analysis_service.py#L31) now exposes a plain formatter. `assessment_context()` remains available as detached structured context. |
| Analytics repositories repeated schema initialization during use | Ordinary reads/writes carried setup side effects and repeated work | [bootstrap.py:71](../../src/credit_monitoring/application/bootstrap.py#L71) initializes the analytics schema at composition. Repository constructors retain a database path; domain operations use the existing tables. Direct repository callers initialize explicitly. |
| Optional learning dependencies complicated app setup | Notebook and judge tooling could look like prerequisites for the app | The base environment runs the app and its checks. Notebook tooling is an optional dependency group; Evidently keeps its separate compatible Python 3.13 environment under `homework/llm-judges`. |
| Four tracked working databases looked like authored inputs | A fresh setup appeared to require retained state; extraction observations risked being discarded as cache | The historical extraction database is preserved as a read-only evaluation snapshot. Financial/analytics working databases are preserved locally under ignored runtime output. Training/model bytes and source observations are retained. |
| Empty benchmark files looked like another implemented benchmark | Six zero-byte placeholders were referenced by an old spec but had no executable consumers | Removed placeholders; original design remains in the archive. No actual benchmark records were removed. |

The service constructor no longer accepts a model factory, feature-builder object,
or narrator. Callers use `create_assessment_service(..., risk_model=...)` where a
test double is needed. `create_risk_model(config)` and
`build_risk_features(results, borrower_id, period_end, information_cutoff,
assessment_run_id=...)` replace the old extension objects. These are internal Python
API changes; no HTTP service or public endpoint was introduced.

## Ranked remaining opportunities

| Priority | Area and evidence | Assessment and disposition |
| --- | --- | --- |
| 1 | Remote cost queries at [costs.py:93](../../src/credit_monitoring/observability/costs.py#L93), duplicated sync/async pagination at lines 130/152, and timed reconciliation at [cost_footer.py:12](../../src/credit_monitoring/web/cost_footer.py#L12) | A remote query system, retry schedule, UI refresh state, and pricing reconciliation are substantial for a POC. Useful to the monitoring lesson, so preserved. Consider explicit refresh and a shared query core after the UI is stable. |
| 2 | Structured stream at [streaming.py:145](../../src/credit_monitoring/agents/streaming.py#L145), plain-text credit coordinator at [monitoring_backend.py:298](../../homework/monitoring/monitoring_backend.py#L298) | Both translate provider events and manage turn/history lifecycle. The output contracts differ, so indiscriminate merging would risk retries and cancellation. Deferred; consolidate lifecycle mechanics only. |
| 3 | Gold-backed mock assembly at [demo_assessment_service.py:52](../../src/credit_monitoring/application/demo_assessment_service.py#L52) and working input flow at [workspace.py:24](../../src/credit_monitoring/web/workspace.py#L24) | Two presentations of the same borrower concepts increase maintenance and explanation cost. Existing UI is outside this cleanup's design scope; only data paths changed. Keep the mock clearly labeled and its evaluation input separate. |
| 4 | Review orchestration at [credit_review_service.py:119](../../src/credit_monitoring/application/credit_review_service.py#L119), two parallel roles at line 226, future news interface at [retrieval.py:9](../../src/credit_monitoring/public_context/retrieval.py#L9) | The multi-agent workflow is implemented POC functionality. Its base classes, execution metadata, events, and unused live-news extension warrant a later reduction pass; removing the workflow would change features. |
| 5 | Prediction fields at [risk_prediction.py:46](../../src/credit_monitoring/domain/risk_prediction.py#L46) and their SQL/repository/verification consumers | Deterioration, anomaly, risk-level, and driver fields have no built-in producer. They are speculative complexity, but persisted contracts and old observations make removal a coordinated migration decision. Preserved for now. |
| 6 | One-file ingestion namespaces at [sec_html.py:31](../../src/credit_monitoring/ingestion/cleaners/sec_html.py#L31), [sec_markdown.py:16](../../src/credit_monitoring/ingestion/converters/sec_markdown.py#L16), and [sec.py:27](../../src/credit_monitoring/ingestion/loaders/sec.py#L27) | Flattening the namespaces would shorten the code tour. The implementation itself is small and useful; moving all imports is lower value than the completed behavioral simplifications. Deferred. |
| 7 | [criteria_helpers.py:59](../../homework/agent-tests/criteria_helpers.py#L59), [evaluator.py:55](../../homework/llm-judges/src/credit_monitoring_judges/evaluator.py#L55), and dated [workbench.py:1](../../homework/evaluation/2026-10-26/workbench.py#L1) | Three approaches overlap in capture, judging, labels, and reports. They serve distinct lessons and environments. Grouped visibly under homework; consolidation awaits a decision on the canonical exercise. Deterministic SEC gold comparison remains an app quality check. |

The [deferred plan](../project/deferred-simplification-plan.md) gives implementation
steps, dependency ordering, compatibility decisions, and acceptance criteria for all seven.

## Complexity that protects POC behavior

Keep deterministic ratios, threshold direction, contractual adjustments, explicit
missing/conflicting states, information cutoffs, and source provenance. These explain
why a result can be trusted or why it abstains. Keep shared training/inference feature
order, borrower/time separation, and artifact compatibility checks. Reducing the current
204-column model projection is an ML experiment change requiring retraining, not a
mechanical cleanup.

Full-document extraction differs deliberately from selected notebook excerpts. Retain
complete-document coverage, successful-section reuse, exact quote offsets, and source/config
cache identity. Automatic extraction verification remains disabled; standalone validators
and tests are retained. Active assessment verification still replays calculations and
checks scope and prediction identity. Neither validates arbitrary prose semantically.

## Validation and limits

The restructuring preserves existing training/model/evaluation assets byte for byte:
64 tracked assets matched their original hashes, and 93 prepared evaluation source and
conversion-marker files matched the recorded manifest. A fresh temporary CLI workflow
ran without credentials or SEC cache and returned verified deterministic results and
trends with ML disabled. Replaying the frozen SEC snapshot produced the same report
without modifying its database: **37 existing failures and 5 supported-facts matches**.
These are historical extraction limitations, not a newly passing benchmark.

Final checks in the existing environments: **630 app tests passed**, **74 homework
tests passed with 6 opt-in live skips**, and **18 isolated judges tests passed**.
Root and judges lint passed. A fresh isolated environment installed the locked app
and dev dependencies, included `nbformat` without the Jupyter/Notebook/JupyterLab
distributions, and completed a verified deterministic assessment. The existing project
environment was preserved. No live model run, telemetry cloud verification, or UI
redesign is claimed by this cleanup.
