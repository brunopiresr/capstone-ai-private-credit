# AI Credit Monitoring POC

## Objective

Prove that legal and public evidence retrieval, structured financial data, deterministic calculations, and an agent workflow can support a traceable covenant and early-warning assessment for a credit analyst.

## Architecture

```text
Credit Analyst Web App
          │ trigger / inspect / ask
          ▼
Monitoring Orchestrator
     ┌────┴────┐
     ▼         ▼
Legal and   Financial
Public RAG  Repository
     │         │
     │         ▼
     │   Deterministic
     │   Calculations
     └────┬────┘
          ▼
Assessment and Trend Synthesis
          ▼
Verification
          ▼
Traceable Analyst Result
```

See [docs/architecture.md](docs/architecture.md) for layer boundaries.

## Scope

The capstone POC focuses on covenant monitoring, deterministic financial calculations, headroom and trend analysis, legal and public evidence, verification, and analyst review. It does not make autonomous lending, investment, or escalation decisions. The longer-term platform may add portfolio prioritization, private-data integrations, specialized agents, and production workflows.

## Development philosophy

- Financial calculations and threshold comparisons stay deterministic.
- Material claims must be backed by evidence with source provenance.
- Missing information remains explicitly missing.
- Layers are independently testable.
- One orchestrator coordinates services; the analyst remains responsible for interpretation and decisions.

## Current implementation status

Status: Project scaffold plus an analyst-facing Streamlit cockpit. The portfolio view filters and prioritizes pre-labeled synthetic borrower cases, then opens a borrower-specific assessment. The assistant uses fixed response templates. Live retrieval, financial calculation services, model calls, and verification are not connected. Existing notebooks and data assets are retained as capstone research materials.

## Setup

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --group dev
uv run pytest
uv run ruff check .
uv run streamlit run src/credit_monitoring/web/app.py
```

The scaffold import test and demo app do not need credentials or external services. Configuration names are listed in `.env.example` for future use.

## Repository map

- `src/credit_monitoring/` — package boundaries for the planned application layers
- `tests/` — unit, integration, evaluation, and fixture locations
- `data/` — existing capstone materials plus raw, processed, and benchmark locations
- `docs/` — architecture, scope, sources, evaluation, and decision notes
- `notebooks/` — existing exploratory setup and retrieval notebooks
- `scripts/` — future command entry points

## Next implementation step

Finalize the typed domain schemas and contracts before implementing ingestion or retrieval.
