# ML Early-Warning Integration — Implementation Plan

## Objective

Add an ML early-warning step to the existing covenant-monitoring flow without replacing the deterministic covenant calculation logic.

The ML component consumes:

- normalized financial data
- calculated covenant results
- historical borrower metrics
- historical covenant trends

and produces predictive signals such as:

- deterioration probability
- covenant breach probability
- anomaly score
- important feature drivers

The first implementation should establish the architecture and interfaces. It does not need to train a production-quality model.

---

# 1. Target Flow

Implement the following flow:

```text
Documents
    ↓
Document Retrieval / RAG
    ↓
LLM Covenant Extraction
    ↓
Structured Covenant Records
    ↓
Covenant Resolution
    ↓
Active Covenant Definition
    ↓
Financial Data
    ↓
Calculation Tools
    ↓
Covenant Results
    ↓
Feature Engineering
    ↓
ML Early-Warning Model
    ↓
Risk Signals
    ↓
Risk / Trend Analysis
    ↓
Verification
    ↓
Analyst Output
```

The ML model must not replace:

- covenant extraction
- covenant resolution
- financial calculations
- covenant calculations

It operates after these steps.

---

# 2. Architectural Principle

Separate the system into three information layers.

## Layer 1 — Source Evidence

Original documents and document chunks.

Examples:

- SEC filings
- credit agreements
- amendments
- covenant disclosures

Used for:

- extraction
- provenance
- analyst evidence
- verification
- answering source-specific questions

Storage may include:

```text
documents
document_chunks
embeddings
```

---

## Layer 2 — Structured Credit State

Canonical data extracted and resolved from source documents.

Examples:

```text
Borrower
CovenantDefinition
ThresholdSchedule
CovenantEvidence
ResolvedCovenant
FinancialPeriod
CovenantResult
```

This layer is the primary source for application logic.

Do not retrieve active covenant definitions using semantic RAG once they have been parsed and resolved.

Use deterministic structured queries.

Example:

```python
active_covenant = covenant_repository.get_active_covenant(
    borrower_id=borrower_id,
    covenant_type="net_leverage",
    period_end=period_end,
)
```

---

## Layer 3 — Derived Analytics

Calculated and predictive information.

Examples:

```text
CovenantResult
BorrowerFeatureSnapshot
MLRiskPrediction
RiskAssessment
```

This layer is generated from structured credit state and financial data.

---

# 3. ML Component

Do not implement the ML model as an autonomous LLM agent.

Implement it as an ML service/tool callable by the monitoring workflow.

Recommended abstraction:

```python
class RiskModel(Protocol):
    def predict(
        self,
        features: BorrowerRiskFeatures,
    ) -> RiskPrediction:
        ...
```

Possible future implementations:

```text
LogisticRegressionRiskModel
XGBoostRiskModel
IsolationForestRiskModel
```

The rest of the application should not depend on a specific ML library.

---

# 4. New Domain Models

Add the following models.

## BorrowerRiskFeatures

Represents the model input for one borrower and one reporting period.

Suggested fields:

```python
class BorrowerRiskFeatures(BaseModel):
    borrower_id: str
    period_end: date

    net_leverage: float | None = None
    covenant_threshold: float | None = None
    covenant_headroom: float | None = None

    leverage_change_qoq: float | None = None
    headroom_change_qoq: float | None = None

    ebitda_growth_qoq: float | None = None
    ebitda_growth_yoy: float | None = None

    debt_growth_qoq: float | None = None
    debt_growth_yoy: float | None = None

    liquidity: float | None = None
    liquidity_change_qoq: float | None = None

    interest_coverage: float | None = None

    previous_breach: bool = False
    previous_waiver: bool = False
```

Do not tightly couple this schema to XGBoost, sklearn, or another ML framework.

---

## RiskPrediction

```python
class RiskPrediction(BaseModel):
    borrower_id: str
    period_end: date

    model_name: str
    model_version: str

    breach_probability: float | None = None
    deterioration_probability: float | None = None
    anomaly_score: float | None = None

    risk_level: Literal[
        "low",
        "medium",
        "high",
        "unknown",
    ]

    top_drivers: list[str] = []

    generated_at: datetime
```

Model probabilities must be values between `0` and `1`.

---

# 5. Feature Engineering Service

Create a dedicated feature-engineering component.

Suggested interface:

```python
class RiskFeatureBuilder:

    def build(
        self,
        borrower_id: str,
        period_end: date,
    ) -> BorrowerRiskFeatures:
        ...
```

The builder should combine:

```text
FinancialPeriod
+
CovenantResult
+
previous FinancialPeriod records
+
previous CovenantResult records
```

It should not query raw SEC documents.

---

# 6. Feature Calculation

Example:

```text
Current quarter:

Net leverage       = 4.9x
Threshold          = 5.5x
Headroom           = 0.6x

Previous quarter:

Net leverage       = 4.6x
Headroom           = 1.0x
```

Derived features:

```text
leverage_change_qoq = +0.3x
headroom_change_qoq = -0.4x
```

If financial history is missing, fields should remain `None`.

Do not fabricate historical values.

---

# 7. Data Persistence

Persist the following historical datasets.

## Financial history

```text
borrower_id
period_end
revenue
ebitda
debt
cash
liquidity
interest_expense
```

---

## Covenant results

```text
borrower_id
covenant_id
period_end

actual_ratio
threshold
headroom
compliance_status
```

---

## Risk feature snapshots

Persist the exact input used for each model prediction.

```text
borrower_id
period_end
feature_schema_version
features
created_at
```

This is important for:

- reproducibility
- model evaluation
- debugging
- future model training

---

## ML predictions

```text
borrower_id
period_end

model_name
model_version

breach_probability
deterioration_probability
anomaly_score
risk_level

created_at
```

---

## Outcomes

Design storage for future labels even if the POC does not yet populate all of them.

```text
borrower_id
period_end

breach_next_quarter
breach_next_two_quarters

downgrade
default
restructuring
watchlist_event
```

These will eventually become the target variables for supervised ML.

---

# 8. Initial Model Strategy

Implement the architecture so multiple models can be used.

For the POC, support a deterministic stub first.

Example:

```python
class StubRiskModel:

    def predict(
        self,
        features: BorrowerRiskFeatures,
    ) -> RiskPrediction:
        ...
```

The stub allows the full application flow to be tested independently of ML training.

After the integration works, implement one real model.

Recommended order:

```text
1. Logistic Regression baseline
2. XGBoost or LightGBM
3. Isolation Forest if labeled data is insufficient
```

Do not add neural networks.

---

# 9. Model Registry

Introduce a simple model configuration.

Example:

```yaml
risk_model:
  type: logistic_regression
  version: "v1"
  artifact_path: "models/risk_model_v1.pkl"
```

The monitoring workflow should obtain the model through a factory:

```python
risk_model = risk_model_factory.create(config.risk_model)
```

Avoid importing model implementation classes directly into the monitoring workflow.

---

# 10. Monitoring Workflow Integration

Extend the existing quarterly monitoring workflow.

Current logical flow:

```python
covenant = resolve_covenant(...)
financials = load_financials(...)

result = calculate_covenant(
    covenant=covenant,
    financials=financials,
)
```

Extend it to:

```python
covenant = resolve_covenant(...)

financials = load_financials(...)

covenant_result = calculate_covenant(
    covenant=covenant,
    financials=financials,
)

features = risk_feature_builder.build(
    borrower_id=borrower_id,
    period_end=period_end,
)

risk_prediction = risk_model.predict(features)

assessment = risk_analysis_service.analyze(
    covenant_result=covenant_result,
    risk_prediction=risk_prediction,
)
```

The risk model must only run after the current covenant result has been calculated.

---

# 11. Risk Analysis Agent Input

Extend the Risk / Trend Agent input schema to include:

```text
current financial metrics

current covenant result

historical covenant results

ML prediction

source evidence references
```

Example context:

```json
{
  "covenant": {
    "ratio": 4.9,
    "threshold": 5.5,
    "headroom": 0.6,
    "status": "pass"
  },
  "trend": {
    "previous_headroom": 1.0,
    "headroom_change": -0.4
  },
  "ml_prediction": {
    "breach_probability": 0.41,
    "deterioration_probability": 0.72,
    "risk_level": "high"
  }
}
```

The LLM must not reinterpret the ML probability as a fact.

It should describe it explicitly as a model prediction.

---

# 12. Explainability

The ML service should return model drivers when available.

Example:

```text
Top drivers:

1. declining covenant headroom
2. increasing leverage
3. negative EBITDA growth
```

For tree models, SHAP may be introduced later.

Do not make SHAP part of the first implementation unless required.

---

# 13. RAG Changes

Do not remove RAG entirely.

Change its responsibility.

## RAG should be used for:

```text
finding relevant sections in source documents

finding supporting covenant evidence

retrieving definitions and clauses during extraction

answering analyst questions about source documents

verification against original documents
```

---

## RAG should not be used for:

```text
finding the active covenant threshold

finding the current covenant definition

retrieving historical covenant calculations

retrieving current financial values

retrieving ML predictions
```

Those should come from structured repositories.

---

# 14. Structured Repository Interfaces

Create repository abstractions such as:

```python
class CovenantRepository:

    def get_active_covenant(
        self,
        borrower_id: str,
        covenant_type: str,
        period_end: date,
    ) -> ResolvedCovenant:
        ...
```

```python
class FinancialRepository:

    def get_period(
        self,
        borrower_id: str,
        period_end: date,
    ) -> FinancialPeriod:
        ...
```

```python
class CovenantResultRepository:

    def get_history(
        self,
        borrower_id: str,
        covenant_type: str,
    ) -> list[CovenantResult]:
        ...
```

```python
class RiskPredictionRepository:

    def save(
        self,
        prediction: RiskPrediction,
    ) -> None:
        ...
```

---

# 15. Recommended Retrieval Architecture

Use two retrieval paths.

```text
                  Analyst / Monitoring Agent
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
       Structured Query            Document RAG
              │                         │
              ▼                         ▼
    Covenant / Financial       Original evidence
    / Historical state         and legal language
```

Example analyst question:

```text
"What is Acme's current leverage covenant?"
```

Answer primarily from:

```text
ResolvedCovenant
```

Then attach source evidence retrieved from:

```text
Document RAG
```

Example:

```text
Current covenant:
Net leverage <= 5.50x

Effective period:
Q1 2026 onward

Source:
Credit Agreement Amendment No. 2, Section 6.11
```

The structured state answers the question.

RAG provides provenance.

---

# 16. Suggested Project Structure

Add modules similar to:

```text
src/
    domain/
        risk_features.py
        risk_prediction.py

    features/
        risk_feature_builder.py

    ml/
        base.py
        factory.py
        stub_model.py
        logistic_regression.py

    repositories/
        covenant_repository.py
        financial_repository.py
        covenant_result_repository.py
        risk_prediction_repository.py

    workflows/
        quarterly_monitoring.py
```

Do not reorganize unrelated existing modules unless necessary.

---

# 17. Tests

Add unit tests for:

```text
feature calculation

missing historical periods

headroom calculation input

model interface

prediction bounds

model factory

prediction persistence
```

Add workflow test:

```text
document/extracted covenant
        ↓
resolved covenant
        ↓
financial data
        ↓
covenant result
        ↓
feature vector
        ↓
ML prediction
        ↓
risk assessment
```

The workflow test can use the stub ML model.

---

# 18. Acceptance Criteria

The implementation is complete when:

1. Covenant calculation still works independently of ML.

2. Risk features can be constructed from stored structured data.

3. A model implementation can be swapped without changing the monitoring workflow.

4. Risk predictions are stored with model name and version.

5. Historical feature snapshots are preserved.

6. The Risk / Trend Agent receives both deterministic covenant results and ML predictions.

7. Raw-document RAG is not used to obtain data that already exists in the structured domain model.

8. Every structured covenant remains traceable to its original document evidence.

9. The complete quarterly assessment works with a stub ML model.

10. The architecture supports adding Logistic Regression or XGBoost later without redesigning the workflow.