# Quarterly assessment and ML service

The assessment service resolves existing terms for each reporting period, calculates covenant
metrics, and stores verified results before building deterministic trends, with optional prediction. The
`CreditAssessmentAgent` can invoke it through calculation and prediction tools;
the Streamlit borrower page invokes the same workflow directly and uses the agent for follow-ups.
See [agent configuration](document_processing.md#calculation-and-prediction-tools).
Built-in models include the integration stub and a
Logistic Regression adapter for locally trained synthetic artifacts. ML remains disabled by default.
The stub returns unknown risk and null probabilities.

## Working Streamlit review

Run `make run`. The app copies the Git-versioned financial database into a fresh workspace,
then applies backed-up additive updates to existing `data/runtime/streamlit/financials.sqlite3`
without replacing existing financial rows. It stores
assessment results in that directory's separate analytics database. These app files are ignored
by Git. No financial import or model training is needed after cloning. After editing the
bundled financial CSV, run `uv run --locked python scripts/prepare_demo_database.py`,
commit the CSV and database together, and restart the app.

Select a borrower, reporting date, and information cutoff, then **Run assessment**. The selected
dates and returned run ID remain attached to the visible results; changing controls does not
recalculate until another run is requested. Covenant statuses are shown individually, with no
aggregate WATCH rule. Period history comes from stored service results, including missing values
and calculation bases. Input notes and gold labels are excluded from this page and its assistant.

Prediction modes are **Off** (default), **Stub**, and **Logistic Regression**. The trained option
uses `data/models/logistic_regression/v1/`; `make install` and `make run` include the
`ml` dependencies. Missing
dependencies or an incompatible artifact produce an explicit forecast failure while preserving
deterministic results. Forecasts are shown separately from observed compliance, with their model,
horizon, and synthetic-training limitations.

`OPENAI_API_KEY` enables follow-ups using the existing PydanticAI agent's borrower-scoped tools;
`LLM_MODEL` optionally selects a provider-qualified model. Both may be supplied through `.env`.
Without credentials, the financial and covenant workflow remains usable. A separate **Benchmark
portfolio (mock)** page retains fixed benchmark examples and can prefill a working review.

## Run with existing synthetic inputs

The CLI defaults to the bundled financial database, so run directly:

```bash
uv run python scripts/run_assessment.py \
  --borrower-id SYN002 \
  --period-end 2025-09-30 \
  --information-cutoff 2025-09-30 \
  --ml
```

Omit `--ml` to disable predictions. Use `--financial-db`, `--analytics-db`, and `--terms` to select
explicit input/storage locations. Analytics storage must be separate from the financial database.

## Call the service

```python
from datetime import date
from pathlib import Path

from credit_monitoring.application.bootstrap import create_assessment_service
from credit_monitoring.config.settings import AssessmentSettings
from credit_monitoring.covenants.structured import SyntheticCovenantReader
from credit_monitoring.financials.repositories import FinancialRepository

service = create_assessment_service(
    financial_repository=FinancialRepository(Path("data/app/synthetic/financials.sqlite3")),
    covenant_reader=SyntheticCovenantReader(Path("data/app/synthetic/synthetic_covenant_terms.csv")),
    settings=AssessmentSettings(analytics_database=Path("data/runtime/analytics.sqlite3")),
)
assessment = service.assess(
    "SYN002", date(2025, 9, 30), date(2025, 9, 30), ml_enabled=True,
)
```

Every invocation gets a new run ID and snapshots the available historical calculation inputs.
`assessment.results` contains current results; `history` contains earlier results from that run.
`trends` contains deterministic covenant changes and financial QoQ/YoY growth, including
when ML is off. It includes current feature values for context; missing or incompatible
comparison periods remain null. Streamlit displays these changes separately from forecasts.
`feature_snapshot`, `prediction`, and `ml_status` describe optional model execution.
With ML off, no model, feature snapshot, or prediction record is created. A trend-building
failure preserves verified compliance results and records the limitation.

`create_assessment_service()` initializes analytics storage and composes the repositories.
Direct `AssessmentService` construction accepts repositories and an optional model,
and performs no storage initialization. Features use the bounded in-memory calculation
run; they do not reread newly written calculations through SQLite. Typed
`FinancialRepository.get_period()` and `get_period_history()` reads own database-row mapping;
the raw quarter/history APIs remain available for loading and inspection.
`verification` identifies structured errors and unknown source availability.

## Inspect calculation inputs and results

Enable step-by-step output in a notebook or application before calling the service:

```python
from credit_monitoring.observability.logging import configure_logging

configure_logging()  # INFO: covenant selection, inputs, adjustments, and results
# Call service.assess(...) or the agent as usual.
# configure_logging("WARNING") hides routine calculation details.
```

The agent notebook already calls `configure_logging()`. Explicit events show addback,
cash and synergy caps, missing metrics, debt conflicts, selected/rejected covenant terms,
and final status, basis, headroom and issues. Tiny formula helpers no longer produce
automatic start/end records. Formulas and threshold comparisons remain deterministic.

For example, a capped EBITDA adjustment includes these diagnostic fields:

```text
apply_addback_cap complete {"inputs": {"reported_ebitda": 50, "eligible_addbacks": 20, "cap_fraction": 0.2}, "outputs": {"eligible_addbacks": 10}}
```

Structured records carry run, borrower, reporting-period, and covenant identifiers when
available. Context is restored after failures and isolated across asyncio tasks and
`asyncio.to_thread` work. Manually created threads need explicit context propagation.
Domain projections are guarded by the INFO level check; disabled diagnostics do not
serialize financial or covenant objects. The `log_step()` context manager reports
progress before blocking work, elapsed time, and sanitized error types.

The CLI's `--log-level INFO` sends diagnostics to stderr while stdout remains JSON.
`--log-level WARNING` suppresses routine details. Full documents, prompts, evidence
bodies, financial notes and benchmark labels are excluded. Console setup is idempotent
and preserves external logging handlers.

Optional Logfire integration is available through the shared observability modules;
see the [setup guide](logfire_setup.md) and the [monitoring exercise](../../homework/monitoring/README.md).

## Consume stored document covenants

Use the existing `DocumentProcessingService` instance and explicit identities:

```python
from credit_monitoring.covenants.structured import ExtractionBinding, ExtractionCovenantReader

reader = ExtractionCovenantReader(document_service, [
    ExtractionBinding(
        borrower_id="your-financial-borrower-id",
        agreement_id="your-agreement-id",
        covenant_id="your-agreement-id:leverage",
        covenant_name="Exact extracted covenant name",
        document_id="Exact catalog document ID",
    ),
])
```

The reader only consumes complete current stored extractions. It does not process documents or
infer entity/formula links. Configure `CalculationRules` on the binding only when the formula and
measurement basis have been explicitly established. Otherwise, a matching source-reported actual
can be assessed as `reported`; missing or ambiguous terms produce an abstention. Conditional legal
clauses and overlapping versions requiring interpretation remain unresolved.

Risk features use the resolved covenant's explicitly configured calculation formula as their
`covenant_type`, such as `net_leverage` or `total_leverage`. Extracted terms, resolved covenants,
and calculation records retain the source classification, such as `leverage`. Without a configured
formula, features retain that classification; the trained-model converter rejects generic
`leverage` rather than inferring a family from its name. A supported comparison using a
source-reported actual remains valid when model conversion fails. Model failure metadata is
persisted without a forecast probability. This mapping preserves the existing feature columns
and model artifact compatibility; it does not require retraining or a database migration.

## Storage and model replacement

`covenant_results`, `risk_feature_snapshots`, and `risk_predictions` are appended in the analytics
database. Applied terms are copied into each result rather than stored in a separate resolved-term
table. Exact financial inputs and feature vectors survive later source reloads. The executable DDL
is [analytics_schema.sql](../../src/credit_monitoring/persistence/analytics_schema.sql).

`create_risk_model(config)` selects the built-in stub or Logistic Regression adapter.
Tests or callers can pass `risk_model=` to `create_assessment_service(...)` directly.
Models consume `BorrowerRiskFeatures` and return `RiskPrediction`. The workflow checks probabilities, borrower-period identity, the next-quarter
horizon, and snapshot linkage. Model or prediction-storage failures preserve deterministic results.

`format_assessment_summary(assessment)` creates the deterministic summary.
`assessment_context(assessment)` retains a detached structured context for callers.
Verification checks structured results; it does not certify generated prose.

## Data limits

Financial notes and gold labels are excluded from runtime inputs. Missing quarters remain missing,
and basis changes suppress incompatible ratio trends. Liquidity is not inferred from cash or
revolver availability. `SYN010` returns an incomplete active FCCR calculation because its raw inputs
are missing. Source availability and monetary scale remain unknown unless explicitly supplied;
the workflow does not claim reliable point-in-time forecasts from reporting dates alone.

The [historical implementation plan](<../archive/ML Early-Warning Integration — Code Agent Implementation Plan.md>)
contains domain models, the complete DDL, constraints, and acceptance criteria.

## Generate and train the synthetic baseline

Install the optional, locked ML dependencies:

```bash
uv sync --extra ml --group dev --locked
```

The `ml` extra pins scikit-learn 1.8.0, NumPy 2.4.4, SciPy 1.17.1 and joblib 1.5.3.
The generator itself does not require scikit-learn. Training uses the CPU and makes no LLM calls.

```bash
uv run --extra ml python scripts/generate_training_dataset.py
uv run --extra ml python scripts/train_risk_model.py
```

Generation defaults to seed 42 and 50 borrowers for each of the 12 PoC scenarios, producing 600
borrowers and 4,800 observations from 2025 Q1 through 2026 Q4. Use `--seed`,
`--borrowers-per-scenario` (at least five), `--source-directory` and `--output-directory` to select
other generation settings. Existing source fixtures remain unchanged. Generated numeric defaults
and completed FCCR inputs belong only to the simulated borrowers; they do not repair the original
SYN010 case. Contractual caps, amendment dates, the covenant holiday and springing condition remain.

The runtime expansion to SYN013–SYN037 does not expand this training population.
Generation explicitly retains the original twelve templates; the bundled training dataset,
model pipeline and `logistic-v1` feature schema remain unchanged. New runtime calculations
use the same formula families, with versioned economic definitions and explicit gaps.

The output directory `data/training/synthetic/` contains:

| File | Contents |
| --- | --- |
| `borrowers.csv` | Template provenance and assigned borrower partition |
| `quarterly_financials.csv` | Simulated financial inputs, compatible with the existing loader |
| `covenant_terms.csv` | Borrower-specific copies of the existing contractual rules |
| `features.jsonl` | Typed feature vectors available at each reporting period |
| `training.csv` | Fixed feature columns, identity metadata, nullable target and evaluation split |
| `outcomes.jsonl` | Next-quarter labels, exclusion reasons and calculation references |
| `calculations.jsonl` | Reproducible calculations and their applied terms and inputs |
| `manifest.json` | Seed, schemas, assumptions, counts, missingness and file checksums |

A positive label means an established next-quarter breach. A negative label requires at least one
active test and no unresolved relevant outcomes. Wholly inactive, missing and unresolved outcomes
remain unknown. The last quarter is unlabeled. Rows without usable current numeric covenant inputs
remain in the audit files but are excluded from evaluation, matching runtime abstention behavior.

At the default size each scenario assigns 35 borrowers to training, 7 to validation and 8 to test.
Training features end in 2025 Q3 so their outcomes end by 2025 Q4. Validation features are from 2026
Q1-Q2 and test features from 2026 Q3. These sets contain different borrowers. Other periods have
split `unused`; unknown labels never enter fitting or held-out evaluation.

The same `model_feature_row()` converter supplies training and runtime columns. It aggregates
multiple covenants by supported formula family and includes fixed missingness indicators. Identity,
scenario, notes, outcome records and generation parameters are excluded from model columns.
The converter schema is `logistic-v1`, distinct from the typed feature contract `v1`.

Training fits median imputation, missingness indicators, retained empty columns, scaling and a
Logistic Regression classifier on the training partition only. It requires both target classes.
The evaluation manifest records precision, recall, average precision (PR-AUC), ROC-AUC, log loss,
Brier score and a constant-prevalence baseline. The evaluation classification threshold is 0.5;
it does not define application risk levels. Undefined AUC metrics are null. Empty partitions have
an explicit reason. Training/validation/test results describe this simulation, not real credit risk.

Use training options `--dataset-directory`, `--artifact-directory`, `--version` and `--seed` to save
another version. The default `data/models/logistic_regression/v1/` holds `pipeline.joblib` and
`manifest.json`. The manifest identifies synthetic training, feature order, target/horizon,
dependency/Python versions, dataset fingerprint, evaluation and pipeline SHA-256 hash. Load only
trusted local artifacts produced by this training workflow. The existing reviewed dataset and compatible baseline artifact are retained in Git;
local runtime output and downloaded caches are ignored. No model is automatically activated after training.

## Use the trained model in assessments

The agents notebook defaults to `USE_TRAINED_MODEL = False` and a stub. Installing the
extra does not change that selection. To opt in, install the dependencies below, select
the project `.venv` kernel, set the switch to `True`, and rerun configuration. It validates
the local model through `create_risk_model(config)` before creating the service and reports
missing dependencies/files or incompatible versions/checksums immediately. It never
silently substitutes the stub. A compatible tracked artifact under
`data/models/logistic_regression/v1/` can be loaded directly; generating a new dataset
and retraining are optional exercises. Restore the switch for the stub-probability test.


The following workflow uses separate demonstration databases:

```bash
uv run --extra ml python -m credit_monitoring.ingestion.loaders.financials \
  --csv data/training/synthetic/quarterly_financials.csv \
  --db data/runtime/synthetic_training_financials.sqlite3

uv run --extra ml python scripts/run_assessment.py \
  --borrower-id SIM_SYN001_0001 \
  --period-end 2026-09-30 \
  --information-cutoff 2026-09-30 \
  --financial-db data/runtime/synthetic_training_financials.sqlite3 \
  --analytics-db data/runtime/synthetic_training_analytics.sqlite3 \
  --terms data/training/synthetic/covenant_terms.csv \
  --ml --model-type logistic_regression --model-version v1 \
  --model-artifact data/models/logistic_regression/v1
```

For Python callers, pass `RiskModelConfig(type="logistic_regression", version="v1",
artifact_path=Path("data/models/logistic_regression/v1"))` through `AssessmentSettings.risk_model`.
The artifact is loaded when its adapter is constructed; configured built-in models are
constructed for requested predictions unless a caller injects a model instance. A missing, incompatible or corrupt artifact yields
the existing explicit ML failure metadata while preserving deterministic calculations.

The adapter returns next-quarter breach probability and the model version/hash. Without usable
current numeric inputs it returns `unavailable`. Risk level remains `unknown`, drivers remain empty,
and deterioration probability and anomaly score remain null. The default narrative identifies
synthetic training. Predictions are appended to the same `risk_predictions` table and linked to
the persisted exact feature snapshot. The default analytics location remains
`data/runtime/analytics.sqlite3`; the example overrides it for demonstration isolation.

Additional model families can later implement the same prediction boundary.
Boosting can reuse the labels and converter; anomaly detection needs a separate target contract.
The working Streamlit review uses this model boundary. SEC document bindings in the UI and
additional model families remain separate work.
