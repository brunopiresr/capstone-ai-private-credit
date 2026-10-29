# AI Credit Monitoring POC

An analyst POC for covenant monitoring: deterministic financial calculations and trends,
SEC document extraction and lexical retrieval, optional synthetic-trained risk prediction,
and PydanticAI follow-ups. Missing and conflicting inputs remain visible; the analyst
retains responsibility for decisions.

## Run the app

To use the new Streamlit POC workspace, run:

```bash
make preview
```

**Portfolio** is connected to the calculation services and bullish, bearish and
recommendation agents. Choose reporting dates, run one borrower or the whole portfolio,
and inspect saved results. Enable **Include agent reviews** when requesting assessments
to run all three agents for each newly assessed borrower. The option is off by default.
Assessments use bundled synthetic inputs without model
credentials. Agent reviews require `OPENAI_API_KEY` in `.env` or the environment;
`LLM_MODEL` optionally selects the model. Results survive browser refresh in ignored
`data/runtime/portfolio/` storage. Opening/filtering the page does not run assessments
or agents.

The remaining pages are still a UI preview with illustrative session-only data.
**Reset sample screens** clears those samples while retaining connected portfolio
results. See the [POC walkthrough](docs/guides/ui_preview.md).

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/). From the repository root:

```bash
uv sync --group dev --extra ml --locked
make run
```

Choose a borrower, reporting period, and information cutoff, then **Run assessment**.
The financial SQLite database and trained ML pipeline are included in Git. The working
page copies the bundled database into ignored local storage; no credentials, downloads,
database import, data generation, or model training are needed. Select **Logistic Regression**
to use the bundled trained model. The separate **Benchmark portfolio (mock)** page shows fixed,
pre-labeled examples.

For analyst follow-ups, copy [.env.example](.env.example) to `.env` and set
`OPENAI_API_KEY`. `LLM_MODEL` optionally changes the default
`openai-responses:gpt-4o-mini`. Conversation memory belongs to each browser session
and clears on a new assessment or **Clear conversation**.

Prediction defaults to **Off**. Model details, SEC downloads, credit perspective reviews,
and Logfire setup are documented in the [usage guides](docs/README.md#usage-guides).
Synthetic model results do not establish real-world forecasting performance.

## Find your way around

| Directory | Purpose |
| --- | --- |
| [src/credit_monitoring](src/credit_monitoring/) | Shared app code: services, financial rules, agents, storage, and UI |
| [data](data/README.md) | App inputs, evaluation answers, training data, models, and ignored local output, explicitly separated |
| [tests](tests/) | App regressions and controlled fixtures |
| [homework](homework/README.md) | Notebooks, monitoring exercise, agent tests, dated evaluation work, and optional judges |
| [scripts](scripts/) | Assessment, download, training, and evaluation commands |
| [docs](docs/README.md) | Current project context, usage guides, homework guidance, reviews, and archived plans |

Start with the [current architecture](docs/project/architecture.md) and
[POC scope](docs/project/poc_definition.md). The [complexity review](docs/reviews/poc_simplification_review.md)
records the cleanup and remaining opportunities; the
[deferred simplification plan](docs/project/deferred-simplification-plan.md) covers larger follow-up work.

## Check the project

```bash
make test-all      # App and homework checks; live scenarios skip.
make lint
```

These checks need no model credentials or local SEC cache. Optional training checks,
live scenarios, and the separate Python 3.13 judges environment are described in
[homework](homework/README.md) and [evaluation](docs/homework/evaluation.md).
Passing controlled tests does not establish live extraction or answer quality.
