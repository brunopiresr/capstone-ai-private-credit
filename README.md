# AI Credit Monitoring

A proof of concept (POC) for reviewing borrower covenants: calculate compliance and
headroom, inspect source evidence, compare bullish and bearish AI reviews, and prepare
analyst, risk manager, and board reports. Analysts make the decisions.

The demo includes **37 fictional borrowers**, **172 quarterly financial records**, and
**69 public SEC source references**. Synthetic borrowers are separate from real SEC issuers.

## Problem

Private-credit analysts must determine whether borrowers comply with loan covenants
using financial reports and supporting documents. This requires gathering evidence,
calculating ratios against contractual limits, and explaining findings to risk
managers. Missing inputs, conflicting figures, and unclear source references make
those assessments harder to verify and can obscure emerging compliance issues.
This project brings calculations, source evidence, and human review into one
workflow so analysts can produce traceable covenant assessments.

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

## Run with Docker Compose

Requires Docker Engine or Docker Desktop with Compose 2.24 or newer. From the
repository root:

```bash
docker compose up --build
```

Open [http://localhost:8501](http://localhost:8501). The image includes Python 3.14,
locked application and ML dependencies, the borrower data, SEC source catalog, and
trained model. SQLite runs inside the app; no separate database service is needed.
The default demo works without a `.env` file. To enable AI reviews or SEC downloads,
configure the settings below, then recreate the container with `docker compose up -d`.
The optional `.env` file is passed at runtime and excluded from the image.

Named volumes preserve saved assessments, reports, working databases, and downloaded
SEC sources across container replacement. `docker compose down` stops and removes
the container while keeping those volumes. `docker compose down --volumes` deletes
the saved Docker data. Local runs under `data/runtime/` use separate storage.

Use `docker compose ps` to check health and `docker compose logs -f app` to read logs.
To run in the background and wait for health, use `docker compose up --build -d --wait`.
If port 8501 is occupied, set `APP_PORT=8502` in `.env` and open port 8502 instead.
The service binds to the local machine's loopback interface.

To check the bundled model, all six pages, and storage persistence without AI calls:

```bash
docker compose exec -T app python scripts/check_container.py
docker compose up -d --force-recreate --wait
docker compose exec -T app python scripts/check_container.py --verify-saved
```

The check saves one SYN002 assessment and small verification markers in the Docker
volumes. See [container verification](docs/guides/docker.md) for details.

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

GitHub Actions runs these checks on every push and pull request using locked
dependencies. The Python 3.14 job includes the ML extra; a separate Python 3.13
job runs `make lint-judges` and `make test-judges` with the judge lockfile.
CI requires no API keys and leaves live evaluations disabled. See the
[CI workflow](.github/workflows/ci.yml) for the commands.

See [evaluation](docs/homework/evaluation.md) for optional ML, live, and judge checks.
Offline tests check behavior; they do not measure live answer quality.

The [60-scenario live evaluation](data/evaluation/agent_scenarios/README.md) includes
the scenario CSV, saved answers and traces, and a report of the observed failures.

See the [capstone rubric review and open-issue plan](docs/project/rubric_gap_resolution_plan.md)
for current evidence, verification findings, and prioritized follow-up work.
