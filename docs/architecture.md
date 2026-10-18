# Architecture

The package separates analyst interaction, orchestration, retrieval, structured financial data, deterministic calculation, assessment synthesis, and verification. Streamlit's default borrower assessment uses working services with synthetic financials and covenant terms. It displays exact covenant statuses, provenance, verification, and optional predictions. The separate **Benchmark portfolio (mock)** page displays fixed expected examples.

The application-service layer now includes complete-document extraction with SQLite
caching and a `CreditAssessmentAgent` using the PydanticAI with document,
financial, calculation and prediction tools when the assessment service is configured.
These are demonstrated in `notebooks/03-agents.ipynb`. Streamlit follow-ups use the same agent
with borrower-scoped assessment tools; document tools are registered only when a document service
is supplied. Automatic post-extraction
verification is temporarily disabled; the verifier code remains available. See
[document processing and agent usage](document_processing.md).

```text
                       ┌─────────────────────────┐
                       │    Credit Analyst       │
                       │      Web App            │
                       └────────────┬────────────┘
                                    │ Trigger / inspect / ask
                                    ▼
                       ┌─────────────────────────┐
                       │ Monitoring Orchestrator │
                       │       / Agent           │
                       └──────────┬───┬──────────┘
                                  │   │
                  ┌───────────────┘   └─────────────────┐
                  ▼                                     ▼
       ┌─────────────────────┐                ┌─────────────────────┐
       │ Legal / Public RAG  │                │ Financial Repository │
       │ text + vector search│                │ quarterly facts      │
       └──────────┬──────────┘                └──────────┬──────────┘
                  │                                      ▼
                  │                           ┌─────────────────────┐
                  │                           │ Calculation Tools   │
                  │                           │ ratios / headroom   │
                  │                           └──────────┬──────────┘
                  └──────────────────┬───────────────────┘
                                     ▼
                          ┌─────────────────────┐
                          │ Assessment / Trend  │
                          │ synthesis           │
                          └──────────┬──────────┘
                                     ▼
                          ┌─────────────────────┐
                          │ Verification        │
                          │ evidence + math     │
                          └──────────┬──────────┘
                                     ▼
                          ┌─────────────────────┐
                          │ Analyst Result      │
                          │ + optional chat     │
                          └─────────────────────┘
```

## Implemented assessment pipeline

The separate `AssessmentService` consumes existing financial rows and structured covenant inputs.
It resolves terms for each reporting period, runs deterministic calculations, and appends historical
results before optional feature/model execution. `ExtractionCovenantReader` uses existing stored
extractions through explicit borrower/agreement/covenant bindings; there is no new SEC ingestion
pipeline. Streamlit invokes the assessment service directly when the analyst runs a review,
then retains that result across ordinary reruns. The credit assessment agent can invoke
this pipeline through borrower-scoped calculation and prediction tools; its LLM does
not execute formulas or supply model probabilities itself.

```text
Existing terms → Period-specific resolution ──┐
                                             ↓
Financial periods → Calculations → Stored covenant results
                                             ↓
                              Feature snapshots → Model service
                                             ↓
                              Assessment context → Verification
```

New analytics storage contains calculation results, exact feature snapshots, and linked predictions.
The stub provides unknown risk and no probabilities. A separate offline generator simulates
histories from the PoC cases and derives next-quarter labels through the same calculation services.
A Logistic Regression training pipeline saves its preprocessing, classifier, metadata and
evaluation. The runtime adapter uses the shared feature converter and loads an explicitly selected
artifact. Synthetic outcome labels remain offline files; prediction storage uses the existing
analytics schema. Streamlit initializes its own financial database once per startup and keeps
analytics under the ignored `data/processed/streamlit/` directory. Conversation memory and active
assessments belong to individual browser sessions. Prediction is off by default, and missing chat
credentials do not prevent deterministic assessments. SEC UI bindings and additional models are
later work. See
[assessment and training usage](ml_early_warning.md).

## Boundaries

- Calculations are deterministic and independent of LLMs.
- LLM outputs must be grounded in evidence with provenance.
- Missing information stays explicitly missing.
- Domain, ingestion, retrieval, calculation, application, persistence, and UI layers remain independently testable.
- One orchestrator coordinates approved services; the analyst retains responsibility for interpretation and decisions.
