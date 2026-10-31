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

**Borrower analysis** shares those saved results and supports calculation evidence,
prediction controls, version history, real assistant conversations, validation,
flags and analyst report submission. **Documents & data** now supports a persistent
working catalog, explicit borrower links, HTML fetch/extraction, cache retries,
source inspection and backed-up database/index rebuilds. Downloads need
`SEC_USER_AGENT`; extraction also needs `OPENAI_API_KEY`. **Risk review** now saves
manager observations, recommendations, reviewed decisions and flag resolutions against
exact submitted versions. Further-analysis requests support context-only agent reruns
or analyst recalculation, validation and resubmission. **Board report** saves draft
and final snapshots containing open flags, older cases, untriaged breaches and explicit
pending items. Saved reports can be opened using `?report_id=...`. **Reset navigation**
retains all saved records.
See the [POC walkthrough](docs/guides/ui_preview.md).

Open **User guide** in the sidebar for the first-assessment walkthrough, task help
and troubleshooting. Collapsed **How to…** sections explain controls beside the work.
After each credit review, an additional read-only agent generates up to three
follow-up questions from the saved calculations and bullish, bearish and recommendation
analyses. In **Borrower analysis → Credit assistant**, expand **Suggested follow-up questions**,
select a question and edit the
**Question draft**, then **Send question**. Existing saved analyses offer **Generate
follow-up questions**. Generation uses model credentials and incurs provider usage;
saved questions are reused when browsing. Answers receive the matching saved risk analysis.

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

The connected `make preview` app enables the bundled **Logistic Regression** forecast
by default. Existing assessments saved with ML off can be updated using **Run
assessment with ML**, followed by **Run agent review** for the new version. The
original `make run` app still defaults to **Off**. Model details, SEC downloads, credit perspective reviews,
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
