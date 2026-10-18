# Implementation plan: cleanup findings F13–F19

Date: 18 October 2026. Status: implemented in the working tree.

Implementation used committed F05–F12 work at `b0e020a` as its baseline. The observations
and proposed commands below preserve the original planning context; current validation
and deviations are recorded in the completion evidence at the end.

Source: [Capstone cleanup and polish review](capstone_cleanup_review.md), findings F13–F19.
The review describes revision `3961c81`; this plan also checks the current working tree
at HEAD `92a21e4`, including work in progress. Recheck affected files before each change
because application code and documentation are being edited independently.

The intended outcome is a reproducible entry path, useful offline checks, simpler
logging, and documentation that accurately describes the retained POC. Keep PydanticAI,
lexical retrieval, deterministic calculations, synthetic ML training and prediction,
the small homework judge, and the separate optional Evidently package. Automatic
extraction verification stays disabled; structured assessment verification stays active.

## Current evidence and scope

| Finding | Current observation | Planned outcome |
| --- | --- | --- |
| F13 | The data utility performs downloads at import time and writes `<id>.htm`; the converter reads `html/<id>.html`. All 29 current catalog URLs are HTML; none ends in PDF. | One explicit download command using the same helper and cache as document processing. |
| F14 | Cell `9cf32123` in `03-agents.ipynb` actively selects Logistic Regression while its teaching text and stub-probability exercise assume a stub. Numerical dependencies remain optional. | A working stub default and an explicit, checked trained-model exercise. |
| F15 | Tests assert a signature string, whole prompt assembly/word count, display lines, and private conversation fields. Other tests already inspect executed tools and subsequent model requests. | Preserve the underlying guarantees through observable behavior and a small set of deliberate technical contracts. |
| F16 | Default pytest discovery omits homework; root Ruff omits homework and the data downloader. Judge-helper safeguards have no retained offline regression module. | Named checks with explicit scope, committed helper regressions, and separate Python environments. |
| F17 | `logged_operation()` binds signatures and projects inputs before checking INFO logging. It is used beyond formulas, including covenant resolution and feature construction. | Explicit diagnostic events and timing without generic signature-binding decorators. |
| F18 | Documentation is partly being updated for the working Streamlit assessment. The architecture diagram still says vector search, an older plan prohibits agent frameworks, and the judge capture example passes `service.client`. | One current architecture reference and runnable examples, with older instructions clearly dated. |
| F19 | AST inspection still finds the review's 14 docstring-only modules/scripts. Five package areas are scaffold-only. A newer agent plan refers to `public_context`. | Remove proven-unused files while retaining working packages, artifacts, and clearly identified future plans. |

F01–F12 implementation is outside this plan. In particular, F07 owns public benchmark
quality and any redesign of portable versus cache-dependent comparisons. F04's working
Streamlit changes are already visible in the working tree; F18 must describe their final
behavior instead of repeating the review's older statement that the entire UI is a mock.
Do not introduce WATCH rules, new agents, vector retrieval, Logfire, or artifact deletion.

## Delivery order

Use small, independently reviewable changes. The order below establishes checks before
refactors and leaves the final documentation pass until commands and files settle.

| Step | Findings | Deliverable and dependency |
| --- | --- | --- |
| 1 | F16 | Explicit check commands, expanded discovery/lint scope, and offline judge-helper tests. Include the downloader's existing import-order fixes so the expanded lint scope is usable. |
| 2 | F13 | Shared HTML-cache loader and guarded download CLI, followed by its cache-reuse regression. |
| 3 | F14 | Stub notebook default and explicit trained-model prerequisites; use the checks established in step 1. |
| 4 | F15 | Replace brittle assertions and relocate independent formula expectations before changing logging. |
| 5 | F17 | Simplify logging after step 4 preserves its useful guarantees. Coordinate with any F09–F12 edits to the same services. |
| 6 | F19 | Remove verified scaffolding after a fresh consumer search, including the new web files and future agent plan. |
| 7 | F18 | Finish README, architecture, usage examples, historical labels, and roadmap against the resulting implementation. |

Update directly affected usage instructions in each step; step 7 reconciles the whole
documentation set. No business decision from the review blocks this cleanup scope.

## F13 — Unify SEC downloading and HTML cache reuse

**Files:** `data/download_sec_documents.py`,
`src/credit_monitoring/ingestion/loaders/sec.py`,
`src/credit_monitoring/ingestion/converters/sec_markdown.py`,
`tests/unit/ingestion/test_sec_pipeline.py`, and `data/README.md`.

1. Keep `data/download_sec_documents.py` as the documented CLI, preserving the existing
   discoverable entry point. Move all argument parsing, environment access, directory
   creation, catalog loading, and execution behind `main()` and an explicit main guard.
   Importing the module and invoking `--help` must require neither credentials nor I/O.
2. Add a small shared HTML-cache helper in `ingestion/loaders/sec.py`. Both the CLI and
   `load_markdown()` call it. It owns `<html_dir>/<document_id>.html`, reuses valid existing
   HTML, and calls `download_sec_filing()` and the existing throttle for actual requests.
   Keep `requests` as the sole maintained download implementation; remove the utility's
   `urllib` path. Validate document IDs before constructing paths.
3. Default the CLI to the repository's `data/public_sec_documents.csv` and
   `data/sec_documents/html/`, with explicit `--source-file`, `--html-dir`, and optional
   document selection. Resolve default paths from the script location so the working
   directory does not change the cache. Read `SEC_USER_AGENT` at execution time and
   require it when a download is needed, allowing an already cached run without it.
4. Write a downloaded file only after a successful response, using a temporary file
   and replacement so an interrupted write cannot become a cache hit. Report individual
   failures and return a nonzero exit code when any requested document fails. Do not
   turn failed or empty downloads into successful cache entries.
5. Keep the CLI HTML-only. Reject an explicitly selected PDF with a clear unsupported
   message; do not decode it as HTML. No current catalog entry requires a PDF workflow.
   Document that the old flat `.htm`/`.pdf` directory is not the active cache. Leave old
   files intact and populate the canonical cache through the command; no automatic
   renaming or deletion is needed for this cleanup.
6. Preserve the current conversion version and Markdown marker checks. The working tree
   already uses `beautifulsoup-clean-v2`; changing download ownership alone must not
   revert or gratuitously invalidate conversion/extraction identities.

**Acceptance:** a mocked CLI download creates `html/<id>.html`; a subsequent real
`load_markdown()` call with an injected converter consumes it with no HTTP request.
Also cover import/`--help` without side effects, a cached rerun, missing identity on a
cache miss, and a failed download leaving no reusable file. Retain the existing stale
Markdown reconversion and financial-content preservation tests. No live SEC download
is required for these checks.

## F14 — Make notebook model selection explicit

**Files:** `notebooks/03-agents.ipynb`,
`tests/unit/covenants/test_agent_notebook.py`, and `docs/ml_early_warning.md`.

1. Set the active configuration to `RiskModelConfig(type="stub")`. Preserve deterministic
   calculation, the stub's null probability, and the stub exercise's expected behavior.
2. Put the trained-model choice behind an explicit opt-in setting in the configuration
   cell, defaulting to false. Explain that installing the `ml` extra does not select
   the model automatically. Keep the trained exercise and its synthetic-data caveat.
3. Before creating the assessment service in the trained branch, use the existing
   `RiskModelFactory` to validate the selected local artifact. Surface actionable
   dependency/path/version/checksum errors there rather than waiting for the service
   to catch a prediction failure. Preserve the adapter's existing compatibility checks;
   never silently substitute a stub when the analyst selected Logistic Regression.
4. Document `uv sync --extra ml --group dev --locked`, selection of the project kernel,
   and the generation/training commands in `docs/ml_early_warning.md`. Explain that the
   tracked `manifest.json` and `pipeline.joblib` may be loaded when compatible; generating
   and retraining are separate exercises, not required to run the stub example.
5. Preserve cell IDs and unrelated notebook content. Clear stale output only from cells
   whose configuration or displayed prediction behavior changes.

**Acceptance:** execute the actual configuration cell with temporary storage and
controlled collaborators. The default constructs a stub without loading numerical
packages or an artifact; the opt-in branch reports missing prerequisites before use.
Exercise successful trained loading through the existing real ML integration suite
with the `ml` extra. Do not use a source-string assertion as the sole notebook check,
or run credentialed agent cells to prove a configuration change.

## F15 — Replace brittle checks without weakening guarantees

**Files:** `tests/unit/covenants/test_agent_context.py`,
`test_credit_assessment_agent.py`, `test_agent_streaming.py` in the same directory,
`tests/unit/observability/test_calculation_logging.py`, and
`tests/unit/calculations/test_assessment_calculations.py`.

| Existing coupling | Replacement evidence |
| --- | --- |
| Exact `inspect.signature(divide)` string | Known ratio and error outcomes, including positional/keyword calls only where that public calling convention matters. |
| Equality to the prompt builder, section concatenation, and arbitrary word cap | Registered tool availability, required scope, unsupported-scope rejection, and the actual scoped request sent to the injected model. Keep intentional extraction prompt-version snapshots. |
| `_history`, `_sources`, `_in_progress` assertions | Closed conversations reject questions without model calls; a fresh conversation receives no prior evidence; after failure/cancellation a follow-up succeeds and its captured request excludes uncommitted tool results and provisional answers. |
| Full console lines and internal `LogRecord` layout | Required operation/status, useful identifiers, redaction, error type, timing presence, and meaningful displayed source/tool information. |

Move independent expectations for caps, net/total leverage, coverage, pro-forma EBITDA,
headroom, applicability, abstention, and missing-value trends into calculation tests
before reducing logging events. Reuse fixtures and remove duplicate numerical checks
where existing business tests already cover the same case.

Retain provider adaptation, serialization, prompt-version, transaction, cancellation
cleanup, and caller-mutation isolation tests where they protect a real boundary.
Do not add public history getters or a new conversation reset API just for testing.
Failure recovery can retain an error explanation in model history; the guarantee is
that partial tool output is not committed as successful evidence. Preserve that nuance.

**Acceptance:** the resulting tests still fail if scope leaks, a closed conversation
calls a model, a cancelled turn contributes evidence, a failure leaves the conversation
unusable, or final provenance differs from executed tools. Scripted replies establish
these mechanics only; final-answer quality and live judge behavior remain F06 work.

## F16 — Make offline coverage explicit and retain helper regressions

**Files:** `Makefile`, `pyproject.toml`, `homework-tests/README.md`, a new
`homework-tests/test_criteria_helpers.py`, and the command sections of the main README
and `docs/llm_judges.md`. Keep `tools/llm_judges/pyproject.toml` independent.

1. Extend root pytest `testpaths` to `tests` and `homework-tests`. Make `make test`
   invoke an explicit `test-offline` target. Keep existing live flags opt-in and do not
   add the Evidently directory to root discovery.
2. Add the helper regression module beside `criteria_helpers.py`, with no `credit_agent`
   fixture dependency. Inject a fake judge by patching `create_judge_agent`; explicitly
   disallow real model requests for these tests even when homework runs on its own.
3. Cover a valid complete run and ordered answer/tool evidence, an incomplete or errored
   run rejected before judging, a failed criterion, and empty/missing, duplicate,
   reordered, or mismatched criterion feedback. Preserve the existing rejection of
   empty/blank criteria. Parameterize related invalid cases instead of duplicating setup.
4. Expand root Ruff's explicit include policy to `homework-tests/**/*.py` and
   `data/download_sec_documents.py`. Keep `tools/llm_judges` under its own Python 3.13
   Ruff configuration. Resolve findings exposed by the expanded scope without a broad
   repository reformat. Notebook cell execution/validation remains a separate check.
5. Add named targets for homework checks, ML-enabled checks, isolated judge tests, and
   judge lint. An aggregate check should run both environments as separate commands;
   never import both suites into one pytest process. Fix the homework scenario link to
   `test-cases/three-main-cases.md` and update the statement that all homework tests skip:
   the six live scenarios skip by default, while the new helper regressions run.

Proposed commands, run from the repository root after the corresponding environment is
installed; these are implementation acceptance commands, not results from this plan:

```bash
# Core environment and all root offline tests, including homework helper tests.
uv sync --group dev --locked
uv run --locked pytest tests homework-tests -q
uv run --locked pytest homework-tests --collect-only -q
uv run --locked pytest homework-tests -q
uv run --locked ruff check .

# Retained training/loading coverage; numerical dependencies are explicitly enabled.
uv sync --extra ml --group dev --locked
uv run --locked --extra ml pytest tests/integration/workflows/test_model_training.py -q

# Optional Evidently environment, independently configured for Python 3.13.
uv sync --project tools/llm_judges --group dev --locked
uv run --project tools/llm_judges --locked pytest \
  -c tools/llm_judges/pyproject.toml tools/llm_judges/tests -q
uv run --project tools/llm_judges --locked ruff check \
  --config tools/llm_judges/pyproject.toml tools/llm_judges/src tools/llm_judges/tests
```

The broad offline test command currently includes cache-dependent public comparisons
and the optional local Markdown regression. The review recorded 37 public-cache failures;
this plan has not rerun them and does not claim that count is current. Report failures,
missing-cache/source skips, and missing-ML skips separately. Keep deterministic comparator
tests in coverage. Do not obtain a green F16 result by skipping the entire extraction
evaluation file or marking its failures expected. If F07 supplies a portable/cache split
first, adopt its explicit commands and report both surfaces; otherwise document the
remaining benchmark failures with their selected `SEC_GOLD_DATABASE` snapshot.

**Acceptance:** helper safeguards run without credentials; ordinary homework scenarios
remain opt-in; every retained executable Python area belongs to a documented lint/test
command or an explicit notebook check. New and changed offline regressions pass, and
unresolved baseline failures remain visible.

## F17 — Simplify logging around useful operations

**Files:** `observability/logging.py`, `observability/assessment.py`,
`calculations/*.py`, `covenants/applicability.py`, `covenants/structured.py`,
`features/risk_feature_builder.py`, and the assessment service under
`src/credit_monitoring/`; corresponding observability and workflow tests.

1. Keep standard Python logging, idempotent `configure_logging()`, and the existing
   `log_step()` timing context manager. Retain small `log_event()` and scoped context
   helpers where they preserve structured diagnostics and concurrent-run isolation.
   Do not add another timing/tracing abstraction.
2. Remove generic `logged_operation()` use from scalar formulas. Keep direct events for
   meaningful adjustments, conflicting inputs, unavailable trends, and final results.
   Tiny division/threshold helpers need numerical tests, not automatic start/end logs.
3. Replace remaining decorators on calculation dispatch, covenant resolution, and feature
   building with explicit events and operation-level timing where useful. Pass typed
   objects to small allowlisted projection functions; remove helpers that depend on
   a dictionary of Python parameter names and all now-unused signature binding.
4. Guard expensive projections with the log-level check before building them. Preserve
   borrowed identifiers across async/thread work and restore context on exceptions.
   Log sanitized error types and explicit diagnostic fields, not raw exceptions,
   financial notes, source bodies, prompts, or credentials.
5. Preserve visible progress before slow download/conversion/extraction work, final
   calculation status, and CLI separation of JSON stdout from diagnostic stderr.
   Update the logging usage description to the smaller set of retained events.

**Acceptance:** F15's independent calculations remain unchanged; INFO diagnostics still
explain caps, selected terms, abstentions, and results; disabled INFO performs no domain
projection; timing and errors remain observable for blocking work; redaction and
cross-run isolation hold. Use focused checks for these behaviors rather than exact event
counts or formatting snapshots. Remove the decorator only after every caller has moved.

## F19 — Remove only verified scaffolding

Before deletion, search tracked and untracked source, notebooks, tests, packaging, and
documentation for every candidate's import path and filename. The initial search found
historical tree references, and the newer agent plan intentionally names `public_context`.
Repeat it immediately before editing; a placeholder may acquire an implementation.

| Candidate | Planned treatment |
| --- | --- |
| `public_context/` | Remove its initializer and docstring-only `events.py`/`retrieval.py` when still unused. Preserve the future news-provider boundary in the roadmap and clarify in `bullish_bearish_agents_implementation_plan.md` that its package will be created when that work is implemented. That plan is future work, not an implemented provider or a superseded requirement. |
| `retrieval/vector/`, `retrieval/hybrid/` | Remove empty package initializers; retain lexical retrieval and its parent initializer. |
| `web/components/`, `web/pages/` | Remove empty initializers and placeholder `assessment.py`, `chat.py`, and `evidence.py` under `web/pages/`. Preserve the real `web/app.py`, `web/assessment.py`, `web/benchmark.py`, `web/style.py`, and `web/workspace.py`. |
| `application/analyst_chat_service.py`, `application/evidence_service.py` | Remove docstring-only modules; retain working conversation, tool, and evidence services. |
| `domain/borrower.py`, `domain/feedback.py`, `retrieval/repositories.py`, `verification/rules.py` | Remove docstring-only modules; retain implemented domain models, retrieval, and both verification implementations. |
| `scripts/build_indexes.py`, `scripts/ingest_documents.py`, `scripts/load_financials.py` | Remove no-op scripts. Point financial-loading instructions to `python -m credit_monitoring.ingestion.loaders.financials`. |
| Four `.gitkeep`-only directories: `tests/evaluation/end_to_end/`, `tests/evaluation/retrieval/`, `tests/integration/persistence/`, `tests/integration/retrieval/` | Remove their `.gitkeep` files when still empty; retain existing tests in their working locations. |
| `docs/decisions/README.md` | Remove the invitation-only index if still empty; put actual current decisions in architecture documentation. |

This accounts for all 14 placeholder Python modules/scripts and the five empty package
areas from the review. Keep initializers in every implemented package. Do not remove
working environments, ignored caches, SQLite databases, training datasets, model artifacts,
fixtures, SQL, prompt snapshots, or other documents as part of F19. Decisions about
generated-artifact tracking require a separate reproducibility/consumer review.

**Acceptance:** remaining active imports and notebook cells resolve, package import and
relevant workflow checks pass, no current instructions invoke removed commands, and the
diff contains only the reviewed placeholder deletions and associated documentation edits.

## F18 — Publish one accurate account of the current system

1. Make `README.md` the short runnable entry point, linking to `docs/architecture.md` as
   the current implementation reference and `docs/poc_definition.md` for business scope.
   Keep detailed service, training, and evaluation instructions in their existing guides.
2. Revise architecture diagrams to show lexical retrieval, direct deterministic service
   calls, optional ML, tool-based PydanticAI follow-ups, and SQLite/filesystem storage.
   Distinguish disabled automatic extraction verification from active structured assessment
   verification; neither establishes correctness of arbitrary generated prose.
3. Reconcile with the final F04 changes: the working synthetic borrower page uses services,
   while the explicitly labeled benchmark page remains a mock. Document remaining SEC
   UI binding and deterministic trend limitations from actual code; do not present F08
   or other planned capabilities as complete. Preserve concurrent documentation edits.
4. Add dated status/supersession notes to older execution plans, particularly
   `06_POC_Code_Agent_Implementation_Spec.md` and `docs/document_extraction_plan.md`.
   State that the old direct-SDK/no-agent-framework direction has been superseded by
   PydanticAI. Preserve historical rationale and useful schema contracts. Mark the
   borrower-comparison and bullish/bearish/recommendation plans as planned work, not
   implemented features or obsolete requirements.
5. Fix the capture example in `docs/llm_judges.md` to call
   `llm(build_prompt(question, records), model=service.model)`. For a notebook, show
   `await llm_async(build_prompt(question, records), model=service.model)` because its
   event loop is already running. Capture the same retrieved records used in the prompt;
   do not replace actual run evidence with a second retrieval.
6. Document active configuration by consumer: model selection, OpenAI credentials for
   live generation, SEC identity for downloads, and optional ML selection. Mark unused
   `.env.example` placeholders as reserved instead of suggesting they configure working
   behavior. Update `data/README.md`, `docs/data_sources.md`, evaluation instructions,
   and repository maps for F13/F16/F19.
7. Keep one short roadmap in `docs/architecture.md`, linking to retained future plans.
   Include later Logfire work, fuller evaluation, future news/vector retrieval where
   still intended, and remaining UI integration. Do not create empty implementation
   packages merely to match the diagram.

**Acceptance:** local links resolve; every runnable setup/check command names the right
environment and prerequisites; the corrected capture snippet runs with an injected model
and temporary output; changed notebook cells validate. Historical test results retain
their dates and are not presented as current measurements. No new external research,
credentialed evaluation, or live extraction is needed to verify these documentation changes.

## Completion evidence

Each implementation change should record the files changed, focused checks executed,
and any remaining baseline failures. Run the relevant focused suite after each change;
run the broad F16 commands once after integration, repeating only when a failure or
subsequent change justifies it. Use temporary databases and output directories for checks.

Implementation completed all seven findings:

- **F13:** guarded download CLI and shared, atomic HTML cache with offline failure/reuse checks.
- **F14:** stub notebook default, explicit trained-model switch, and factory preflight.
- **F15:** behavioral conversation/display checks and independent calculation expectations.
- **F16:** expanded default discovery/lint, named Make targets, and extended offline judge guards.
- **F17:** removed signature-binding decorators and parameter-name projections; retained scoped
  diagnostics, guarded domain projections, and operation timing.
- **F18:** current architecture/README, corrected capture example, active configuration notes,
  dated historical plans, and one roadmap.
- **F19:** removed the 14 placeholder modules/scripts, five unused package areas, four empty
  test scaffolds, and the empty decisions index. Retained real packages, datasets, databases,
  model artifacts, fixtures, and validators.

F07 had already supplied portable comparison tests and an explicit public-cache snapshot
runner; the implementation adopted that split. F06 had already added eight offline helper
checks; these were preserved and extended to 14 rather than replaced. F08's deterministic
trends and F04's working UI are reflected as implemented in the updated documentation.

Validation on 18 October 2026:

| Check | Result |
| --- | --- |
| Full root offline suite: `.venv/bin/python -u -m pytest tests homework-tests -q -p no:cacheprovider -o faulthandler_timeout=30 --tb=short` | **543 passed, 6 skipped**, 46.92 s. All six skips are opt-in live homework scenarios; real ML training/loading cases ran. |
| Calculation suite after adding five independent dispatch cases: `.venv/bin/python -u -m pytest tests/unit/calculations/test_assessment_calculations.py -q -p no:cacheprovider` | **20 passed**, including the five added cases; no production change followed the full run. |
| Isolated Python 3.13 judge suite with its own configuration | **18 passed**, 10 third-party deprecation warnings. |
| Root Ruff and isolated judge Ruff | Passed. Root scope includes homework and the download utility. |
| Homework discovery | **20 cases**: 14 offline helper cases and six opt-in live scenarios. |
| Actual documented capture snippet and async generation with an injected offline model | Passed with temporary output. |
| Notebook schema validation, local documentation file links, AST placeholder inventory, `git diff --check`, and `make -n check` | Passed. |

The first broad run found two integration assertions tied to removed logging events;
they now check retained diagnostic/provenance behavior and passed in the full rerun.
The sandbox reproduced the documented asyncio thread stall, so affected tests and the
capture smoke check ran outside it. Existing project environments were used without
changing dependency locks. Checks used temporary databases/output.

No live SEC download or credentialed agent/judge call was performed. Public-cache quality
was not remeasured; the existing snapshot runner and failure register remain authoritative
for those unresolved issues. Passing offline checks do not establish live model accuracy.
