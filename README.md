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

Status: Project scaffold plus an analyst-facing Streamlit cockpit and a CSV-to-SQLite financial loader. The portfolio view filters and prioritizes pre-labeled synthetic borrower cases, then opens a borrower-specific assessment. The assistant uses fixed response templates. The SQLite repository is available independently; the cockpit, live retrieval, financial calculation services, model calls, and verification are not connected to it. Existing notebooks and data assets are retained as capstone research materials.

## Setup

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --group dev
uv run pytest
uv run ruff check .
uv run streamlit run src/credit_monitoring/web/app.py
```

The scaffold import test and demo app do not need credentials or external services. Configuration names are listed in `.env.example` for future use.

## Load quarterly financials

The loader runs entirely in `src` and uses Python's built-in SQLite engine:

```bash
uv run python -m credit_monitoring.ingestion.loaders.financials \
  --csv data/synthetic_quarterly_financials.csv \
  --db data/processed/financials.sqlite3
```

Use the same entry point from a notebook, with paths relative to the repository root:

```python
from pathlib import Path

from credit_monitoring.financials.repositories import FinancialRepository
from credit_monitoring.ingestion.loaders.financials import load_financials

# Works when the notebook kernel starts in the root or in notebooks/.
root = Path.cwd()
if root.name == "notebooks":
    root = root.parent
database_path = root / "data/processed/financials.sqlite3"
result = load_financials(root / "data/synthetic_quarterly_financials.csv", database_path)
repository = FinancialRepository(database_path)
quarter = repository.get_quarter("SYN001", "2025-09-30")
history = repository.get_history("SYN002", as_of="2025-09-30")
facts = repository.get_facts("SYN007", "2025-09-30")
```

The `quarterly_financials` table stores one current snapshot per borrower and period,
including source path, CSV line number, notes, and load time. Reloading a matching
borrower/period replaces that snapshot; it does not retain restatement history.
All rows are validated before writing and upserted in one transaction. CSVs require
`borrower_id`, an ISO `period_end`, and at least one recognized metric column;
omitted metrics and blank values become SQL `NULL`, while zero remains zero.

The `financial_facts` view exposes one row per metric with provenance and
`provided`/`missing` status, including separate financial-package and certificate
debt figures. Monetary values use SQLite `REAL` for this POC; currency and scale
remain unspecified because the source does not declare them. Revolver availability
uses percentage points. The period cutoff filters reporting dates, not source
availability dates. Source notes can contain benchmark answers; exclude them from
agent prompts. Calculated ratios and gold labels are not imported.

For direct SQL or pandas queries:

```python
import sqlite3
import pandas as pd

with sqlite3.connect(database_path) as connection:
    frame = pd.read_sql_query(
        "SELECT * FROM financial_facts WHERE borrower_id = ? AND period_end <= ?",
        connection,
        params=("SYN002", "2025-09-30"),
    )
```

## Repository map

- `src/credit_monitoring/` — package boundaries for the planned application layers
- `tests/` — unit, integration, evaluation, and fixture locations
- `data/` — existing capstone materials plus raw, processed, and benchmark locations
- `docs/` — architecture, scope, sources, evaluation, and decision notes
- `notebooks/` — existing exploratory setup and retrieval notebooks
- `scripts/` — future command entry points

## Next implementation step

Finalize the typed domain schemas and contracts before implementing ingestion or retrieval.
