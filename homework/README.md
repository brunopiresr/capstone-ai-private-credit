# Homework and experiments

The runnable app and reusable capabilities live in [src/credit_monitoring](../src/credit_monitoring/).
This directory groups coursework, demonstrations, and evaluation experiments that use those
capabilities. Financial rules, document processing, assessment, and agents remain shared app code.

| Folder | Start here | Environment |
| --- | --- | --- |
| [notebooks](notebooks/) | `01-setup.ipynb`, `02-rag.ipynb`, then `03-agents.ipynb`; use the project `.venv` kernel | Python 3.14, project environment |
| [monitoring](monitoring/README.md) | Streamlit monitoring/chat exercise using shared agents and telemetry | Python 3.14, project environment |
| [agent-tests](agent-tests/README.md) | Three scenario pairs, ordinary assertions, and structured judge checks | Python 3.14; live tests opt in |
| [evaluation/2026-10-26](evaluation/2026-10-26/README.md) | Dated prepared cases, source corpus, and evaluation runner | Python 3.14; live execution opt in |
| [llm-judges](llm-judges/) | Optional Evidently package; [judge guide](../docs/homework/llm_judges.md) | Separate Python 3.13 environment |

For notebook tools, install `uv sync --group notebooks --group dev --locked`;
this optional group is not required to start the app.

From the repository root, `make test-all` runs offline app and homework checks;
`make test-homework` runs the exercises separately. Model cells and live scenarios need
`OPENAI_API_KEY`; uncached SEC downloads also need `SEC_USER_AGENT`.

```bash
uv run --locked streamlit run homework/monitoring/app.py
uv sync --project homework/llm-judges --group dev --locked
make test-judges
make lint-judges
```

The optional `ml` extra is needed to run the trained-model demonstrations; see the
[assessment guide](../docs/guides/ml_early_warning.md). Logfire is optional; see its
[setup guide](../docs/guides/logfire_setup.md).

App source inputs remain in `data/app/`; expected answers and snapshots live in
`data/evaluation/`. Exercise-specific prepared cases stay alongside the dated experiment.
Runtime files and generated reports are ignored; [data navigation](../data/README.md)
explains what is versioned and what can be recreated. Existing recorded live results
are historical evidence, not a claim that this cleanup reran model requests.
