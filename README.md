# AI Credit Monitoring

A proof of concept (POC) for reviewing borrower covenants: calculate compliance and
headroom, inspect source evidence, compare bullish and bearish AI reviews, and prepare
analyst, risk manager, and board reports. Analysts make the decisions.

The demo includes **37 fictional borrowers**, **172 quarterly financial records**, and
**69 public SEC source references**. Synthetic borrowers are separate from real SEC issuers.

## Run the app

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/). From the repository root:

```bash
uv sync --group dev --extra ml --locked
make preview
```

Open the URL printed in the terminal. In **Portfolio**, choose reporting dates and a
borrower, then run an assessment. Calculations and the bundled Logistic Regression model
work without API keys, downloads, or training. Saved work stays in `data/runtime/portfolio/`.

| Page | Use it to |
| --- | --- |
| Portfolio | Assess borrowers and inspect saved results |
| Borrower analysis | Review calculations, ask questions, validate, flag, and submit a report |
| Documents & data | Register and link sources, process HTML filings, and inspect evidence |
| Risk review | Record manager decisions and request further analysis |
| Board report | Save and finalize a report from reviewed cases and pending items |

Open **User guide** in the sidebar for help, or read the [walkthrough](docs/guides/ui_preview.md).
The original single-borrower app is available with `make run`; its prediction mode starts at **Off**.
The main workspace starts with **Logistic Regression** selected.

## Optional services

Copy [.env.example](.env.example) to `.env` and fill in only the settings you need.

| Setting | Enables |
| --- | --- |
| `OPENAI_API_KEY` | AI reviews, assistant replies, extraction, and generated follow-up questions |
| `LLM_MODEL` | Model override; default: `openai-responses:gpt-4o-mini` |
| `SEC_USER_AGENT` | SEC downloads; use your name or organization and contact email |
| `LOGFIRE_TOKEN` | Optional telemetry; see [Logfire setup](docs/guides/logfire_setup.md) |

Model requests incur provider usage. Browsing saved results does not run assessments
or agents. Keep `.env` and local runtime files out of shared commits.

## Scope and limits

Financial calculations are deterministic. Missing inputs, conflicts, waivers, and
unavailable forecasts remain visible. AI reviews are advisory. The risk model is trained
on synthetic data; its scores do not establish real-world forecasting performance.
Automatic post-extraction verification is disabled, and public-source extraction has
[known quality gaps](docs/reviews/public_sec_benchmark_triage.md).

This local POC has no authentication, external notifications, or PDF export.

## Find your way around

- [Documentation](docs/README.md): guides, architecture, decisions, and historical notes.
- [Data](data/README.md): inputs, benchmarks, models, and local storage.
- [Homework](homework/README.md): notebooks, monitoring demo, and evaluation exercises.
- [Source](src/credit_monitoring/), [scripts](scripts/), and [tests](tests/).

## Check the project

```bash
make test-all      # Offline app and homework checks; live scenarios skip
make lint
```

See [evaluation](docs/homework/evaluation.md) for optional ML, live, and judge checks.
Offline tests check behavior; they do not measure live answer quality.

The [60-scenario live evaluation](data/evaluation/agent_scenarios/README.md) includes
the scenario CSV, saved answers and traces, and a report of the observed failures.

See the [capstone rubric review and open-issue plan](docs/project/rubric_gap_resolution_plan.md)
for current evidence, verification findings, and prioritized follow-up work.
