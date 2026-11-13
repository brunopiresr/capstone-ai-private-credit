# AI Credit Monitoring

## Problem

Private-credit lenders need to check whether borrowers comply with loan covenants:
contractual conditions such as limits on leverage or minimum interest coverage.
Analysts must gather financial reports and loan terms, identify which conditions
apply to the reporting period, calculate ratios against those limits, and explain
the results to risk managers.

The evidence can be spread across filings, amendments, and financial records.
Missing inputs, conflicting figures, changing thresholds, and unclear source
references make assessments harder to verify and can obscure emerging compliance
issues. Reviewers need to understand both the calculation and the evidence behind
it before deciding how to manage an exposure.

## Impact of the solution

This proof of concept brings source evidence, deterministic covenant calculations,
and human review into one workflow. It supports the review process in four ways:

- **Traceable assessments:** inspect inputs, applied terms, ratios, compliance, and
  headroom alongside source references and visible evidence gaps.
- **Reusable evidence:** search filing passages and reuse saved extracted facts
  when investigating questions or reviewing a later assessment.
- **Broader credit review:** compare bullish and bearish AI interpretations of the
  same assessment, then inspect their synthesized recommendation.
- **Clear handoffs:** save analyst observations and validation, submit a frozen
  assessment for risk-manager review, and prepare board reports from saved cases.

The intended impact is less repeated evidence gathering and clearer, more
consistent review. These are POC capabilities; reductions in review time and
improvements in credit outcomes have not been measured. AI reviews remain advisory,
and people make the decisions.

The demo includes **37 fictional borrowers**, **172 quarterly financial records**, and
**69 public SEC source references**. Synthetic borrowers are separate from real SEC issuers.

### Long-term vision

The ambition is an AI Credit Monitoring platform that continuously combines legal
terms, borrower financials, public information, historical performance, and analyst
feedback to help credit teams identify deterioration earlier and monitor larger
portfolios efficiently. It would extend beyond covenant compliance into broader
credit-risk analysis, portfolio prioritization, specialized agents, private-data
integrations, and production workflows.

The capstone demonstrates a foundation for that vision: evidence retrieval,
deterministic calculations, advisory agent reviews, and analyst-to-manager handoffs.
Continuous monitoring, integrated private data, and the broader risk-analysis
capabilities remain future work.

## Target personas

| Persona | Need | How the platform helps |
| --- | --- | --- |
| Credit analyst | Investigate borrower compliance and prepare a defensible assessment. | Retrieve evidence, inspect calculations, ask follow-up questions, record observations, and validate and submit a case. |
| Risk manager | Review the analyst's conclusions and resolve issues before completing a case. | Inspect the submitted evidence and AI perspectives, record a recommendation, and request further analysis. |
| Board or credit committee member | Understand reviewed cases, unresolved risks, and proposed actions. | Read reports containing case summaries, open flags, analyst observations, and manager recommendations. |

## From RAG to Agents: course concepts in the project

This capstone for **From RAG to Agents** applies the course concepts to a
private-credit business case: helping analysts turn financial documents and source
evidence into traceable covenant assessments and advisory credit reviews. Each
technique below addresses a specific step in that review.

| Course topic | What was developed | Business purpose |
| --- | --- | --- |
| RAG | [Retrieve filing excerpts and generate cited monitoring notes](src/credit_monitoring/application/rag_service.py). | Answer analysts' questions using supplied source evidence and disclose missing information. |
| Evidence search | [MinSearch lexical retrieval](src/credit_monitoring/retrieval/lexical/sec.py) over local Markdown, with issuer filters. | Locate passages supporting covenant terms and disclosures for analyst inspection. |
| Document processing and extraction | [Convert HTML filings to Markdown, extract structured covenant facts from document sections, and persist results in SQLite](docs/guides/document_processing.md#processing-and-reuse). | Make reported terms and threshold schedules reusable for repeatable document review. |
| Agents | [A credit-assessment assistant](src/credit_monitoring/agents/credit_assessment.py) with bounded tool calls and follow-up conversations. | Let analysts investigate evidence and ask follow-up questions within an explicit borrower or issuer scope. |
| Agent tools | [Document tools](src/credit_monitoring/agents/tools/documents.py) discover, read, search, and process sources; [assessment tools](src/credit_monitoring/agents/tools/assessment.py) retrieve financials, assess covenants, and request optional risk predictions. | Give the assistant access to application services for evidence gathering and deterministic calculations. |
| Multi-agent workflow | [Independent bullish and bearish reviews followed by a recommendation agent](docs/guides/credit_review.md). All three use the same saved assessment evidence; the recommendation also receives both analyses. | Compare supporting and opposing arguments before an analyst decides how to manage the exposure. |

For example, an analyst investigating a leverage covenant retrieves supporting
filing passages and inspects the extracted terms and threshold schedule. With
explicitly linked borrower inputs and supported calculation rules, the analyst
runs a deterministic covenant assessment, compares the bullish and bearish reviews
and their synthesized recommendation, then submits the analyst's conclusion for
manager review. Source-to-borrower links must be explicit; synthetic borrowers are
not automatically matched to real SEC issuers.

RAG produces evidence-backed narrative notes; extraction produces structured facts;
the calculation service determines supported ratios, headroom, and compliance.
AI recommendations remain advisory. For the course progression, inspect the
[RAG notebook](notebooks/02-rag.ipynb), then the
[agents notebook](notebooks/03-agents.ipynb), then the
[bullish and bearish credit review](notebooks/04-credit-review.ipynb). The
[workspace walkthrough](docs/guides/ui_preview.md) shows the analyst and manager workflow.

## Test the platform with notebooks

The [notebooks](notebooks/) are the simplest way for project reviewers to test the
platform's capabilities. They contain guided examples and many questions to try,
covering retrieval, evidence inspection, agent tools, covenant calculations,
predictions, follow-up conversations, and multi-agent credit review.

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/). From the repository root:

```bash
uv sync --group notebooks --group dev --extra ml --locked
uv run --locked --group notebooks --extra ml jupyter lab notebooks/
```

Select the project's `.venv` kernel and run each notebook's cells in order. Start
with setup, then follow the sequence below; notebooks 03 and 04 can also run independently.
Change the example questions to explore other capabilities and inspect the answers,
source evidence, and tool traces.

| Notebook | What to test |
| --- | --- |
| [01 — Setup](notebooks/01-setup.ipynb) | Check the environment and model connection. |
| [02 — RAG](notebooks/02-rag.ipynb) | Retrieve SEC filing evidence, generate cited answers, and extract covenant facts. |
| [03 — Agents](notebooks/03-agents.ipynb) | Ask research and assessment questions; inspect tool calls, calculations, predictions, and follow-ups. |
| [04 — Credit review](notebooks/04-credit-review.ipynb) | Calculate an assessment, compare bullish and bearish analyses, and inspect the recommendation. |

Set `OPENAI_API_KEY` in the root `.env` file for model calls. Uncached SEC downloads
also need `SEC_USER_AGENT` with your name or organization and contact email. Model
calls incur API usage. Notebook 04's sections 1–4 run without API credentials or
SEC downloads. Use the [app walkthrough](docs/guides/ui_preview.md) to test the
analyst, manager, and board-reporting screens.

## Run the app

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/). From the repository root:

```bash
uv sync --group dev --extra ml --locked
make preview
```

Open the URL printed in the terminal. In **Portfolio**, choose reporting dates and a
borrower, choose **Open borrower**, then **Run assessment**. Calculations and the bundled Logistic Regression model
work without API keys, downloads, or training. Saved work stays in `data/runtime/portfolio/`.

| Page | Use it to |
| --- | --- |
| Portfolio | Find borrowers and open their workspace; run portfolio batches |
| Borrower workspace (from Portfolio) | Assess, inspect evidence, ask questions, validate, and submit |
| Documents | Register and link sources, process HTML filings, and inspect evidence |
| Risk review | Record manager decisions and request further analysis |
| Board reports | Save and finalize a report from reviewed cases and pending items |

Open **Help** in the sidebar for help, or read the [walkthrough](docs/guides/ui_preview.md).
The original single-borrower app is available with `make run`; its prediction mode starts at **Off**.
The main workspace starts with **Logistic Regression** selected.

The task-focused V3 interface is available with `make preview-v3`. It adds analyst
work queues, editable document checklists, a wide assistant, and separate risk-manager
case pages while sharing existing saved work. See the [V3 walkthrough](docs/guides/ui_v3.md).

### Search evidence

In the main workspace (`make preview`), open **Documents → Evidence index**. Enter
a term or phrase in **Search evidence**, such as `maximum leverage` or
`interest coverage`, then choose **Search index**. Results show matching source
passages and citations for inspection.

Search covers all cataloged sources with local Markdown text, including unlinked
sources and sources linked to other borrowers. The selected borrower does not
filter this search, and no document selection is required. MinSearch ranks matches
using lexical retrieval and returns up to ten passages, with at most two per filing.

Searching existing local text requires no API key, model call, or download. If no
passages match, try different terms or use **Inventory & processing** to process a
source into local Markdown (processing requires `OPENAI_API_KEY`; uncached SEC
downloads also require `SEC_USER_AGENT`). Search results persist across page
reruns until another search replaces them. Retrieved passages are excerpts; inspect
the source and stored extraction for complete covenant schedules. See
[document processing and search](docs/guides/document_processing.md#process-and-search-documents)
for the Python API and optional ticker filtering.

### User feedback

The V2 analyst and risk-manager assistants let users rate individual answers. Start
V2 with `make preview-v2`, open an assistant, and ask a question. Under its answer:

- **Rate this answer:** choose thumbs up or thumbs down, then **Send feedback**.
- **Add detailed review:** choose a **Review score (1–5)** and **Review category**,
  optionally enter a message of up to 2,000 characters, then **Submit review**.
  Categories are Helpful, Accuracy, Relevance, Completeness, Clarity,
  Evidence/citations, and Other.

Each answer accepts one thumbs rating and one detailed review, in either order.
Submitted controls become disabled without running the assistant again. Feedback
stays in the current chat transcript; **Clear Chat** removes that local state.
Rule-based fallback answers can also be rated; errors and status messages cannot.

With Logfire configured, feedback is exported as evaluation events linked to the
original response, with borrower, assessment, and session context. Written review
messages are included even when `LOGFIRE_CAPTURE_CONTENT=false`. Submission works
without telemetry, but there is no durable feedback queue or retry, and the thank-you
message does not confirm cloud delivery. See [Logfire response feedback](docs/guides/logfire_setup.md#v2-response-feedback)
for setup, event fields, and queries.

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
- [Notebooks](notebooks/): guided capability testing and reviewer questions.
- [Homework](homework/README.md): monitoring demo and evaluation exercises.
- [Source](src/credit_monitoring/), [scripts](scripts/), and [tests](tests/).

## Check the project

```bash
make test-all      # Offline app, notebook, and homework checks; live scenarios skip
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
