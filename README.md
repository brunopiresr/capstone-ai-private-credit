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

Status: Analyst-facing Streamlit demo, CSV-to-SQLite financial loading, complete SEC document extraction with SQLite reuse, and a `CreditAssessmentAgent` with document tools plus optional borrower-scoped financial, calculation and ML prediction tools. The Streamlit cockpit still uses synthetic cases and fixed assistant responses; document processing and the agent are available through application services and the notebooks. Automatic post-extraction verification is temporarily disabled, with its implementation retained. Structured assessment verification remains active.

See [document processing and agent usage](docs/document_processing.md) for the service
interfaces, cache behavior, tool loop, and verification migration notes.

The credit assessment agent uses the OpenAI Agents SDK while retaining the document
service and evidence trace. Use `agent.ask()` in synchronous application code or
`await agent.ask_async()` in notebooks and asynchronous applications.
Its reusable `DocumentTools` and `AssessmentTools` classes expose typed methods with
descriptive docstrings; their `.tools` properties wrap bound methods with SDK
`function_tool()`. Services and scope stay on tool instances, while `AgentRunState`
contains only per-question execution state. See [tool reuse](docs/document_processing.md#reuse-the-tool-classes).

## Setup

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --group dev
uv run pytest
uv run ruff check .
uv run streamlit run src/credit_monitoring/web/app.py
```

The scaffold import test and demo app do not need credentials or external services. Configuration names are listed in `.env.example` for future use.

Run the notebooks with the project's `.venv` kernel:

- [01-setup.ipynb](notebooks/01-setup.ipynb) checks the OpenAI client setup.
- [02-rag.ipynb](notebooks/02-rag.ipynb) covers retrieval, narrative RAG, and direct document processing.
- [03-agents.ipynb](notebooks/03-agents.ipynb) independently configures and runs the document research and borrower assessment agents, with tool lists, citations, and execution traces. Run its cells in order; it does not require running the RAG notebook first.

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

## Quarterly assessment and optional ML

The assessment service now resolves existing covenant inputs, calculates leverage and coverage,
and stores calculation history in a separate analytics database. Optional feature engineering
and a replaceable model service run after those results are persisted. The built-in stub returns
unknown risk and null probabilities; it does not forecast events. The analyst UI remains a mock.
An optional Logistic Regression model can be trained on independently generated synthetic histories
and loaded through the same model service.

After loading financials, run:

```bash
uv run python scripts/run_assessment.py \
  --borrower-id SYN002 \
  --period-end 2025-09-30 \
  --information-cutoff 2025-09-30 \
  --ml
```

Omit `--ml` for deterministic assessments only. See [service usage and storage](docs/ml_early_warning.md)
for Python interfaces, existing extraction inputs, and data limits. Model-training dependencies are
available through the optional `ml` extra. Financial loading and document-processing APIs retain
their existing behavior.

To generate the dataset and train the baseline:

```bash
uv sync --extra ml --locked
uv run --extra ml python scripts/generate_training_dataset.py
uv run --extra ml python scripts/train_risk_model.py
```

The default dataset contains 600 simulated borrowers and 4,800 quarterly observations. Artifacts
are saved under `data/models/logistic_regression/v1/`. Select them explicitly with `--ml`,
`--model-type logistic_regression`, and `--model-artifact` when assessing a borrower. Follow the
[complete trained-model workflow](docs/ml_early_warning.md#use-the-trained-model-in-assessments)
for the required input paths. Evaluation measures performance on the simulation.

## Repository map

Offline [Evidently LLM judges](docs/llm_judges.md) evaluate captured extraction,
retrieval and answer outputs. Run `python scripts/run_evaluation.py --help` for the
snapshot runner. The judges use an isolated Python 3.13 environment and do not
change the monitoring workflow.

- `src/credit_monitoring/` — package boundaries for the planned application layers
- `tests/` — unit, integration, evaluation, and fixture locations
- `data/` — existing capstone materials plus raw, processed, and benchmark locations
- `docs/` — architecture, scope, sources, evaluation, and decision notes
- `notebooks/` — existing exploratory setup and retrieval notebooks
- `scripts/` — future command entry points

## Next implementation step

Connect the credit assessment agent and its document, calculation and prediction tools to the analyst UI.
