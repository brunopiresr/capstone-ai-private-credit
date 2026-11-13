# Covenant assessment and synthetic ML

The analyst must establish both the arithmetic and the meaning of its inputs.
The assessment service resolves period-specific terms, calculates supported ratios,
verifies structured results, and builds comparable trends. The
[worked example](../worked-example.md) shows the arithmetic for SYN002.

## Interpret the result

| Item | Interpretation |
| --- | --- |
| Calculation basis | Distinguish independently calculated values from source-reported ratios. |
| Earnings period | Use the period/basis defined by the agreement. Do not mix quarterly, annualized, and trailing-twelve-month values. |
| Adjustments | Apply the contract's eligible addbacks and caps; a management proposal is not automatically eligible. |
| Cash netting | Apply the contract's cash cap before dividing net debt by the earnings measure. |
| Headroom | For a maximum ratio: limit minus actual. For a minimum: actual minus limit. Compare before rounding. |
| Amendment | A relaxed limit can improve headroom without improving earnings or repayment strength. |
| Waiver | Relief is limited to its specified period. It does not mean the underlying failed test passed. |
| Springing test | A test outside its activation condition is not tested, rather than compliant by assumption. |
| Missing/conflicting inputs | Preserve the unresolved result; do not invent a value to obtain compliance. |

The expanded synthetic bundle uses `bundle_v1`; older terms and saved records
default to `legacy_v1`. Different calculation contracts are not interchangeable.
The bundle includes acquired EBITDA and synergies, adjustment caps against
nonnegative base EBITDA, a zero floor on net debt, supplied TTM interest expense,
and direct fixed-charge numerator/charges. Its terms carry currency/scale metadata;
legacy rows may not. Missing values remain null and explicit zero stays zero.

Bundle springing tests activate **strictly below 25%** availability. Missing
availability is unresolved. Waived tests keep hypothetical calculations under
`financial_inputs.underlying_calculation`, while reported headroom stays null.
The [calculation modules](../../src/credit_monitoring/calculations/) implement the
rules; [dataset integration history](../../v2-plan/archive/implementation/dataset-integration.md)
records provenance and compatibility details.

## Run with bundled inputs

Web V2's **Run Full Assessment** uses Logistic Regression. Its current interface
does not expose Off/Stub switches. For a deterministic-only CLI assessment:

```bash
uv run --locked python scripts/run_assessment.py \
  --borrower-id SYN002 --period-end 2025-09-30 --information-cutoff 2025-09-30
```

For a bundled forecast:

```bash
uv run --locked --extra ml python scripts/run_assessment.py \
  --borrower-id SYN002 --period-end 2025-09-30 --information-cutoff 2025-09-30 \
  --ml --model-type logistic_regression --model-artifact data/models/logistic_regression/v1
```

`--ml` alone selects the stub, which returns unknown risk and null probability.
No import or training is needed. `--financial-db`, `--analytics-db`, and `--terms`
select alternate locations. Keep financial inputs and analytics storage separate.

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
assessment = service.assess("SYN002", date(2025, 9, 30), date(2025, 9, 30), ml_enabled=False)
```

Each call creates a run with `results`, prior-period `history`, `trends`, and
`verification`. ML adds feature/prediction metadata. Disabled ML creates no
prediction record. Missing or incompatible models preserve calculations and return
explicit unavailability. Missing periods are not substituted; incompatible bases
suppress comparisons. Unknown availability dates limit historical reliability.

INFO logs show applied terms, adjustments, caps, gaps, and outcomes. The CLI's
`--log-level INFO` writes diagnostics to stderr and keeps stdout as JSON.

## Consume stored document covenants

`ExtractionCovenantReader` consumes explicit `ExtractionBinding` records identifying
borrower, agreement, covenant, exact source name, and document ID. It reads complete
current extractions without processing documents or inferring relationships.

Configure `CalculationRules` only after establishing formula and measurement basis.
Otherwise, a supported disclosed actual may be compared as `reported`. Missing or
ambiguous terms require abstention; legal precedence is unresolved. Generic source
classifications such as `leverage` do not establish a model formula family.

## Synthetic ML baseline

The Logistic Regression artifact predicts **next-quarter covenant breach**, not
payment default, loss, or general creditworthiness. Its metrics describe simulated
outcomes. No real-world accuracy or advantage over a simple headroom/trend rule has
been demonstrated.

The included training assets use seed 42, 600 simulated borrowers, and 4,800
observations across 2025–2026, based on the original 12 scenario templates. Runtime
borrowers SYN013–SYN037 do not change those templates. A positive label means an
established next-quarter breach. Negative labels require an active test without
unresolved outcomes. Missing, wholly inactive, and final-quarter targets stay unlabeled.

Training, validation, and test use different borrowers and time windows. Training
features end in 2025 Q3, validation uses 2026 Q1–Q2, and test uses 2026 Q3. The shared
`logistic-v1` feature converter excludes identities, scenario notes, and outcome
metadata. Imputation, scaling, and model fitting use training rows only.

Optional regeneration and training overwrite the default training/model outputs:

```bash
uv run --locked --extra ml python scripts/generate_training_dataset.py
uv run --locked --extra ml python scripts/train_risk_model.py
```

Use script options for separate experiment outputs. Data and compatibility/evaluation
manifests live in `data/training/synthetic/` and `data/models/logistic_regression/v1/`.
Artifact loading checks versions, feature schema, and hashes. Load trusted local
artifacts only. Unsupported deterioration probabilities and anomaly scores stay
null; risk level remains unknown. See [evaluation](../evaluation/README.md).
