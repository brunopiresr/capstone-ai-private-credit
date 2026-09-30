# Architecture

The package separates analyst interaction, orchestration, retrieval, structured financial data, deterministic calculation, assessment synthesis, and verification. The current analyst app is a mock-only demonstration that reads pre-labeled synthetic benchmark cases; it does not connect to a model, live retrieval, calculation workflow, or verifier.

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
