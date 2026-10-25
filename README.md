# AI Credit Monitoring POC

Evidence-backed covenant monitoring for an analyst: SEC document extraction and lexical
retrieval, deterministic financial calculations and trends, structured verification,
optional synthetic-trained risk prediction, and PydanticAI follow-ups.

[Architecture](docs/architecture.md) describes the current implementation;
[POC definition](docs/poc_definition.md) defines business scope. The analyst retains
responsibility for decisions. Missing information remains explicitly missing.

## Run the working analyst UI

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/). From the repository root:

```bash
uv sync --group dev --locked
uv run --locked streamlit run src/credit_monitoring/web/app.py
```

Choose a borrower, reporting period, and information cutoff, then **Run assessment**.
The working page uses bundled synthetic financials and covenant terms through real
services. It displays exact statuses, headroom, provenance, deterministic trends, and
verification. No credentials are needed for deterministic assessments. The separate
**Benchmark portfolio (mock)** page contains fixed examples.

Streamlit initializes storage under ignored `data/processed/streamlit/`; restart the
app to reload edited CSVs. Conversation memory belongs to each browser session and
clears on a new assessment or **Clear conversation**. SEC borrower/document bindings
remain a separate service/notebook workflow.

Prediction defaults to **Off**. **Stub** returns no probability. **Logistic Regression**
requires `uv sync --extra ml --group dev --locked` and a compatible local artifact.
Its training and evaluation data are synthetic. Model failures preserve deterministic
results. See [training, loading, and data limits](docs/ml_early_warning.md).

For analyst follow-ups, set `OPENAI_API_KEY` in the environment or root `.env`.
The UI accepts `LLM_MODEL`; its default is `openai-responses:gpt-4o-mini`.
Notebooks select their model explicitly. [.env.example](.env.example) distinguishes
active entry-point settings from reserved names; configuration is not loaded globally.

[Logfire setup and validation](docs/logfire_setup.md) covers optional EU telemetry,
content capture, conversation traces, and the separate offline/live SDK smoke script.

## Load inputs and assess from the CLI

```bash
uv run --locked python -m credit_monitoring.ingestion.loaders.financials \
  --csv data/synthetic_quarterly_financials.csv --db data/processed/financials.sqlite3
uv run --locked python scripts/run_assessment.py \
  --borrower-id SYN002 --period-end 2025-09-30 --information-cutoff 2025-09-30
```

Add `--ml` for the stub or explicitly select a trained model as described in the
[assessment guide](docs/ml_early_warning.md). `--log-level INFO` shows selected terms,
financial inputs, contractual adjustments, final results, and operation timings on
stderr while stdout remains JSON. Financial notes and gold labels stay out of runtime
agent inputs. Missing data, conflicting sources, and unknown availability dates remain
visible limitations; reporting dates do not establish source publication times.

For SEC documents, set an identifying `SEC_USER_AGENT` and populate the shared cache:

```bash
uv run --locked python data/download_sec_documents.py --document-id DOC_FMC_AMD3_2025
```

Omit `--document-id` to download the catalog. See [cache paths and CLI options](data/README.md#sec-source-download)
and [document services, tool reuse, streaming, and conversations](docs/document_processing.md).
Automatic post-extraction verification remains disabled with its validators retained;
structured assessment verification is active. Neither certifies arbitrary generated prose.

## Notebooks

Use the project's `.venv` kernel and run cells in order:

- [01-setup](notebooks/01-setup.ipynb): PydanticAI model setup.
- [02-rag](notebooks/02-rag.ipynb): lexical retrieval, narrative RAG, document processing.
- [03-agents](notebooks/03-agents.ipynb): independent document/borrower demonstrations,
  executed-tool provenance, and follow-ups. The risk model defaults to a stub;
  `USE_TRAINED_MODEL = True` opts into prerequisite-checked Logistic Regression.

Live model cells require `OPENAI_API_KEY`; downloading uncached filings requires
`SEC_USER_AGENT`. Borrower IDs in synthetic examples have no inferred relationship to
real SEC issuers.

## Checks

```bash
make test          # Portable offline tests plus homework helper regressions; live cases skip.
make lint          # src, tests, scripts, homework-tests, and the SEC download utility.
make test-homework # Offline helper checks and skipped opt-in live scenarios.
make test-ml       # Enables the ml extra for actual training/loading integration tests.
```

The optional Evidently package uses its own Python 3.13 environment:

```bash
uv sync --project tools/llm_judges --group dev --locked
make test-judges
make lint-judges
make check         # All checks above, in separate Python environments.
```

Public-cache quality measurement is an explicit read-only command, separate from the
portable suite. Its known extraction mismatches remain documented, without expected-failure
markers. See [evaluation commands and limitations](docs/evaluation.md),
[homework live scenarios](homework-tests/README.md), and [optional Evidently judges](docs/llm_judges.md).
A passing mocked or portable check does not establish live model quality.

## Repository guide

- `src/credit_monitoring/`: implemented domain, adapters, application services, agents, and UI.
- `tests/` and `homework-tests/`: controlled regressions, fixtures, and opt-in live scenarios.
- `data/`: source catalog, benchmarks, synthetic inputs/training output, and retained models.
- `scripts/`: assessment, training, evaluation, and public snapshot comparison commands.
- `docs/`: usage, current architecture, dated historical plans, and future proposals.

See the [roadmap](docs/architecture.md#roadmap) for remaining UI bindings, later monitoring,
and proposed agent work.

## Credit perspective reviews

The [credit review service](docs/credit_review.md) runs bullish and bearish agents over
one borrower's completed calculations, trends, and optional ML output, then passes both
full analyses and rationales to a neutral Recommendation agent. Typed results preserve
supporting arguments and evidence for the analyst. The workflow is available through
Python services; web UI integration and live news retrieval remain future work.
See the [recorded architecture decisions](docs/decisions/001-credit-review-agents.md).
