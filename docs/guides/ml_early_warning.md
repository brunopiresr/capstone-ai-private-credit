# Quarterly assessment and ML

The assessment service resolves period-specific terms, calculates covenant metrics,
verifies results, and builds deterministic trends. Optional ML adds a next-quarter
breach forecast. Calculations remain usable when forecasts fail or are disabled.

## Working Streamlit review

Use `make preview` for the [main workspace](ui_preview.md), where Logistic Regression
starts enabled. The original `make run` app starts with prediction **Off**. Both offer
**Off**, **Stub**, and **Logistic Regression**. The stub returns unknown risk and null
probabilities.

Bundled financials and the trained model need no import or retraining. Choose borrower,
reporting date, and cutoff, then run an assessment. Changing controls does not recalculate.
The main workspace saves under `data/runtime/portfolio/`; the original app uses
`data/runtime/streamlit/`. See [data maintenance](../../data/README.md#run-with-bundled-inputs).

## Run with existing synthetic inputs

```bash
uv run --locked python scripts/run_assessment.py \
  --borrower-id SYN002 --period-end 2025-09-30 --information-cutoff 2025-09-30
```

Add `--ml` for the stub. For a trained forecast:

```bash
uv run --locked --extra ml python scripts/run_assessment.py \
  --borrower-id SYN002 --period-end 2025-09-30 --information-cutoff 2025-09-30 \
  --ml --model-type logistic_regression --model-artifact data/models/logistic_regression/v1
```

Use `--financial-db`, `--analytics-db`, and `--terms` for alternate locations. Keep
financial inputs and analytics in separate databases.

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
    "SYN002", date(2025, 9, 30), date(2025, 9, 30), ml_enabled=False,
)
```

Each call creates a run with current `results`, prior-period `history`, `trends`, and
`verification`. ML adds `feature_snapshot`, `prediction`, and `ml_status`. With ML off,
no prediction record is created. Stored results retain their exact inputs and terms.

Missing periods remain missing. Incompatible calculation bases suppress comparisons;
unknown source availability prevents a reliable point-in-time forecasting claim.
Financial notes and gold labels are excluded from runtime inputs.

## Inspect calculation inputs and results

Call `configure_logging()` from `credit_monitoring.observability.logging` for INFO
output showing terms, caps, adjustments, gaps, and outcomes. The CLI's `--log-level INFO`
sends diagnostics to stderr and keeps stdout as JSON; use WARNING to reduce detail.
Optional telemetry is described in [Logfire setup](logfire_setup.md).

## Consume stored document covenants

Use `ExtractionCovenantReader` with explicit `ExtractionBinding` records identifying
borrower, agreement, covenant, exact source name, and document ID. It reads complete,
current extractions without processing documents or inferring entity links.

Configure `CalculationRules` only when the formula and measurement basis are established.
Otherwise, a matching disclosed actual can be assessed as `reported`. Missing or ambiguous
terms require abstention; legal precedence remains unresolved. Generic source classifications
such as `leverage` do not establish a model formula family. Model conversion can fail
while a supported source-reported comparison remains valid.

## Generate and train the synthetic baseline

Training is optional; the reviewed dataset and compatible artifact are included in Git.
To regenerate and retrain the default assets:

```bash
uv sync --extra ml --group dev --locked
uv run --locked --extra ml python scripts/generate_training_dataset.py
uv run --locked --extra ml python scripts/train_risk_model.py
```

Defaults use seed 42, 50 borrowers per original scenario, 600 simulated borrowers, and
4,800 observations across 2025–2026. The runtime expansion to SYN013–SYN037 does not
change those 12 training templates. Use script `--help` for alternate output locations.

| Output | Location |
| --- | --- |
| Inputs, calculations, features, labels, splits, and checksums | `data/training/synthetic/` |
| Pipeline and compatibility/evaluation manifest | `data/models/logistic_regression/v1/` |

A positive target is an established next-quarter breach. Negative targets require an
active test with no unresolved outcomes. Missing, wholly inactive, and last-quarter
targets remain unlabeled.

Training, validation, and test use different borrowers and time windows. Training features
end in 2025 Q3, validation uses 2026 Q1–Q2, and test uses 2026 Q3. The shared
`logistic-v1` converter excludes identities, scenarios, notes, and outcome metadata.
The pipeline fits imputation, scaling, and Logistic Regression on training rows only.
Metrics in the manifest describe simulated outcomes, not real credit performance.

## Use the trained model in assessments

For Python callers, set `AssessmentSettings.risk_model` to
`RiskModelConfig(type="logistic_regression", version="v1",
artifact_path=Path("data/models/logistic_regression/v1"))`.

The [agents notebook](../../notebooks/03-agents.ipynb) starts with
`USE_TRAINED_MODEL = False`. Install the ML extra, select the project kernel, set it to
`True`, and rerun configuration to use the included artifact. Restore False for the
stub-probability exercise.

The adapter checks versions, feature schema, and checksums. Missing or incompatible
artifacts produce explicit ML failure while preserving calculations. Load only trusted
local artifacts. Usable predictions include model identity and a next-quarter probability;
without numeric inputs they return unavailable. Risk level remains unknown, and
unsupported deterioration probabilities and anomaly scores remain null.
