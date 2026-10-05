# Architecture

The package separates analyst interaction, orchestration, retrieval, structured financial data, deterministic calculation, assessment synthesis, and verification. The current analyst app is a mock-only demonstration that reads pre-labeled synthetic benchmark cases; it does not connect to a model, live retrieval, calculation workflow, or verifier.

The application-service layer now includes complete-document extraction with SQLite
caching and a monitoring agent using the OpenAI Agents SDK with document tools.
These are demonstrated in the RAG notebook and remain independent of the mocked
web app. Automatic post-extraction
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

## Boundaries

- Calculations are deterministic and independent of LLMs.
- LLM outputs must be grounded in evidence with provenance.
- Missing information stays explicitly missing.
- Domain, ingestion, retrieval, calculation, application, persistence, and UI layers remain independently testable.
- One orchestrator coordinates approved services; the analyst retains responsibility for interpretation and decisions.
