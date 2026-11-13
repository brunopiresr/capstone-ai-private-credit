# Set up the notebooks and Web V2

Run commands from the repository root. Local setup requires **Python 3.14**, **uv**,
and **make** for the shortcut commands. The bundled inputs and trained model are
already included; imports and retraining are unnecessary.

## Notebooks

```bash
uv sync --group notebooks --group dev --extra ml --locked
uv run --locked --group notebooks --extra ml jupyter lab notebooks/
```

Select the `.venv` kernel. Run each notebook's cells in order. Notebook 01 checks
the model connection; 02 demonstrates RAG and extraction; 03 adds tools and
assessments; 04 compares bullish and bearish credit reviews. Notebooks 03 and 04
can run independently of earlier notebooks.

Notebook 04 **sections 1–4** run without API credentials or SEC downloads. Section 5
starts the live review. Notebook 02 includes whole-catalog processing cells: those
can make many extraction calls, so start with a selected document instead.
Notebook 03 currently sets `USE_TRAINED_MODEL = True`; setting it to `False` selects
the stub, which supplies no probability. Changing the model requires rerunning
the configuration cells.

## Web V2

```bash
uv sync --group dev --extra ml --locked
make preview-v2
```

Open the printed URL. The landing role is **Credit Analyst**. Choose a reporting
period, information cutoff, and borrower; **Run Analysis & Covenants → Run Full
Assessment** runs the deterministic assessment and bundled Logistic Regression
model. No keys are needed. See the [workflow](web-v2-workflow.md).

If `make` is unavailable, use the underlying command:

```bash
uv run --locked --extra ml streamlit run src/credit_monitoring/web_v2/app.py
```

For another port, append `--server.port 8502`. After application updates, stop and
restart Streamlit if imports fail; browser refresh can retain old Python modules.

## Optional services

Copy [.env.example](../../.env.example) to `.env`. Fill only the settings needed.
Never commit credentials. Entry points load `.env`; exported values take priority.

| Setting | Enables |
| --- | --- |
| `OPENAI_API_KEY` | Generative assistant answers, extraction, credit reviews, and generated questions |
| `LLM_MODEL` | V2 model override; default `openai-responses:gpt-4o-mini` |
| `SEC_USER_AGENT` | Uncached SEC downloads; identify your organization or name and contact email |
| `LOGFIRE_TOKEN` | Optional telemetry export to the matching Logfire region |

Notebook model selection uses its `MODEL` cell. Model requests incur provider
usage. Browsing saved assessments or local evidence does not run models.
Without a key, V2 assistant answers use a rule-based saved-assessment fallback.
Telemetry is optional; see [monitoring](monitoring.md) for capture settings.

## Docker

Requires Docker Engine/Desktop with **Compose 2.24 or later**. Python and uv are
included in the image; no host Python setup is required.

```bash
docker compose up --build
```

Open [localhost:8501](http://localhost:8501). The image launches Web V2 and includes
the financial bundle, source catalog, and model. SQLite is embedded. An optional
root `.env` supplies runtime configuration and is excluded from the image. Recreate
the container after changing it; no image rebuild is required for credentials.

Useful checks:

```bash
docker compose ps
docker compose logs -f app
docker compose exec -T app python scripts/check_container.py
docker compose up -d --force-recreate --wait
docker compose exec -T app python scripts/check_container.py --verify-saved
```

The check prints JSON with `status: passed`; the second run also verifies the saved
assessment and SEC-cache marker. It executes V2 views, checks the bundled model,
and saves a SYN002 assessment without AI or downloads. It changes the Docker demo
workspace. A healthy HTTP endpoint alone does not verify the views.

If port 8501 is occupied, set `APP_PORT=8502` in `.env`. Compose binds to loopback.
Use `docker compose up --build -d --wait` for background startup.

## Saved work

| Run | Saved assessments and workflow | Downloaded sources |
| --- | --- | --- |
| Local | `data/runtime/portfolio/` | `data/cache/sec/` |
| Docker | Named `runtime` volume | Named `sec-cache` volume |

Local and Docker storage are separate. Docker prefixes volume names with the
Compose project; retain that project name to reuse data. `docker compose down`
keeps volumes. Adding `--volumes` deletes their saved work. Chat and local rating
state last only for the browser session. See [data layout](../../data/README.md).

## Check the installation

```bash
make test-all
make lint
```

These are offline checks. Live scenarios skip unless enabled separately. Optional
Evidently judges use an isolated Python 3.13 environment; they are not required
to run V2. See [evaluation](../evaluation/README.md).
