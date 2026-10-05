# Quarterly assessment and ML service

The assessment service resolves existing terms for each reporting period, calculates covenant
metrics, and stores the results before building optional risk features. It works independently of
the document agent and mocked Streamlit app. Built-in models include the integration stub and a
Logistic Regression adapter for locally trained synthetic artifacts. ML remains disabled by default.
The stub returns unknown risk and null probabilities.

## Run with existing synthetic inputs

Load the financial CSV with the existing loader, then run:

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

from credit_monitoring.application.assessment_service import AssessmentService
from credit_monitoring.config.settings import AssessmentSettings
from credit_monitoring.covenants.structured import SyntheticCovenantReader
from credit_monitoring.financials.repositories import FinancialRepository

service = AssessmentService(
    financial_repository=FinancialRepository(Path("data/processed/financials.sqlite3")),
    covenant_reader=SyntheticCovenantReader(Path("data/synthetic_covenant_terms.csv")),
    settings=AssessmentSettings(analytics_database=Path("data/processed/analytics.sqlite3")),
)
assessment = service.assess(
    "SYN002", date(2025, 9, 30), date(2025, 9, 30), ml_enabled=True,
)
```

Every invocation gets a new run ID and snapshots the available historical calculation inputs.
`assessment.results` contains current results; `history` contains earlier results from that run.
`feature_snapshot`, `prediction`, and `ml_status` describe optional model execution.
`verification` identifies structured errors and unknown source availability.

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

## Storage and model replacement

`covenant_results`, `risk_feature_snapshots`, and `risk_predictions` are appended in the analytics
database. Applied terms are copied into each result rather than stored in a separate resolved-term
table. Exact financial inputs and feature vectors survive later source reloads. The executable DDL
is [analytics_schema.sql](../src/credit_monitoring/persistence/analytics_schema.sql).

Register a constructor with `RiskModelFactory.register()`, select it through `RiskModelConfig`,
and pass the factory to `AssessmentService`. Models consume `BorrowerRiskFeatures` and return
`RiskPrediction`. The workflow checks probabilities, borrower-period identity, the next-quarter
horizon, and snapshot linkage. Model or prediction-storage failures preserve deterministic results.

An optional `AssessmentNarrator.summarize(context)` receives a detached structured context.
Narrative output cannot change stored calculations. Verification checks structured results; it does
not prove the semantic correctness of arbitrary injected prose.

## Data limits

Financial notes and gold labels are excluded from runtime inputs. Missing quarters remain missing,
and basis changes suppress incompatible ratio trends. Liquidity is not inferred from cash or
revolver availability. `SYN010` returns an incomplete active FCCR calculation because its raw inputs
are missing. Source availability and monetary scale remain unknown unless explicitly supplied;
the workflow does not claim reliable point-in-time forecasts from reporting dates alone.

The [implementation plan](ML%20Early-Warning%20Integration%20%E2%80%94%20Code%20Agent%20Implementation%20Plan.md)
contains domain models, the complete DDL, constraints, and acceptance criteria.

## Generate and train the synthetic baseline

Install the optional, locked ML dependencies:

```bash
uv sync --extra ml --locked
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

The output directory `data/synthetic_training/` contains:

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
trusted local artifacts produced by this training workflow. Generated datasets and artifacts are
ignored by Git. No model is automatically activated after training.

## Use the trained model in assessments

The following workflow uses separate demonstration databases:

```bash
uv run --extra ml python -m credit_monitoring.ingestion.loaders.financials \
  --csv data/synthetic_training/quarterly_financials.csv \
  --db data/processed/synthetic_training_financials.sqlite3

uv run --extra ml python scripts/run_assessment.py \
  --borrower-id SIM_SYN001_0001 \
  --period-end 2026-09-30 \
  --information-cutoff 2026-09-30 \
  --financial-db data/processed/synthetic_training_financials.sqlite3 \
  --analytics-db data/processed/synthetic_training_analytics.sqlite3 \
  --terms data/synthetic_training/covenant_terms.csv \
  --ml --model-type logistic_regression --model-version v1 \
  --model-artifact data/models/logistic_regression/v1
```

For Python callers, pass `RiskModelConfig(type="logistic_regression", version="v1",
artifact_path=Path("data/models/logistic_regression/v1"))` through `AssessmentSettings.risk_model`.
The artifact is loaded once per adapter instance. A missing, incompatible or corrupt artifact yields
the existing explicit ML failure metadata while preserving deterministic calculations.

The adapter returns next-quarter breach probability and the model version/hash. Without usable
current numeric inputs it returns `unavailable`. Risk level remains `unknown`, drivers remain empty,
and deterioration probability and anomaly score remain null. The default narrative identifies
synthetic training. Predictions are appended to the same `risk_predictions` table and linked to
the persisted exact feature snapshot. The default analytics location remains
`data/processed/analytics.sqlite3`; the example overrides it for demonstration isolation.

XGBoost, LightGBM and Isolation Forest can be registered later using the same model boundary.
Boosting can reuse the labels and converter; anomaly detection needs a separate target contract.
There is no ML agent, new SEC ingestion or UI wiring in this delivery.
