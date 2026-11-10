# Container setup and verification

Follow [Run with Docker Compose](../../README.md#run-with-docker-compose) for launch,
configuration, health checks, and storage commands. The app is available at
`http://localhost:8501` by default.

## Image and storage

The Dockerfile uses Python 3.14 on Debian Bookworm and a versioned uv binary to
install the committed lockfile with the ML extra. The final image contains the
application, bundled synthetic CSVs and financial database, public SEC catalog,
trained model, Streamlit settings, and utility scripts. Build tools and uv remain
in the builder stage. The app runs as an unprivileged user with UID 10001.

The build context excludes `.env`, local credential directories, virtual
environments, caches, saved runtime output, and evaluation artifacts. Compose
optionally reads the root `.env` at container creation. Changing credentials
requires recreating the container; rebuilding the image is unnecessary.

| Compose volume | Container path | Contents |
| --- | --- | --- |
| `runtime` | `/app/data/runtime` | Working SQLite databases, assessments, reviews, reports, and backups |
| `sec-cache` | `/app/data/cache/sec` | Downloaded HTML, converted Markdown, and conversion markers |

Compose prefixes volume names with the project name. Keep the same project name
to reuse saved work. Bundled files under `/app/data/app` and `/app/data/models`
come from the image; volumes do not hide those inputs. Local Python runs use
their own host directories and do not share the named volumes.

SQLite is embedded, so the default system requires one service. Live AI and
telemetry use optional externally hosted providers configured in `.env`.

## Repeat the checks

From the repository root:

```bash
docker compose up --build -d --wait
docker compose ps
docker compose exec -T app python scripts/check_container.py
docker compose up -d --force-recreate --wait
docker compose exec -T app python scripts/check_container.py --verify-saved
docker compose down
```

Both check commands must print a JSON object with `"status": "passed"`. The
second must include `"saved_data_verified": true` and the same `assessment_run_id`.
Failures exit nonzero. The check disables model credentials and telemetry in its
own process and makes no AI requests or SEC downloads. It:

- Calls the running Streamlit health endpoint.
- Loads all 37 borrowers and the 69-entry source catalog from the image.
- Runs a SYN002 assessment for 30 September 2025, verifies its structured results,
  and requires an available probability from the bundled Logistic Regression model.
- Executes Portfolio, Borrower analysis, Documents & data, Risk review, Board
  report, and User guide through Streamlit's AppTest inside the image.
- Saves the assessment and verification markers, then reads them after container
  recreation to check both volumes.
- Checks that `/app/.env` was not baked into the image.

The script adds a real demo assessment to the Docker workspace. It is a startup
and persistence check, not a live LLM quality evaluation. The HTTP health check
alone only establishes server readiness; AppTest executes the page code.

`docker compose down` preserves the volumes. Only use
`docker compose down --volumes` when you intend to delete their saved data.

## Recorded verification: 10 November 2026

The image built from the committed dependency lockfile with Docker Engine 29.8.0,
Compose 5.5.1, Python 3.14.10, and uv 0.12.19. The container reached healthy state.
Port 8501 was already occupied, so verification used port 18501 and an isolated
Compose project:

```bash
APP_PORT=18501 docker compose -p credit-monitoring-container-check up --build -d --wait --wait-timeout 120
docker compose -p credit-monitoring-container-check exec -T app python scripts/check_container.py
APP_PORT=18501 docker compose -p credit-monitoring-container-check up -d --force-recreate --wait --wait-timeout 120
docker compose -p credit-monitoring-container-check exec -T app python scripts/check_container.py --verify-saved
```

Both check runs passed: all six pages executed, all 37 borrowers and 69 source
references loaded, and SYN002 produced verified covenant results plus a completed
Logistic Regression prediction. The recreated container read the same saved
assessment (`291eece7-1cbb-4c99-8113-8419b175a92a`) and SEC-cache marker.
The published health endpoint at `http://127.0.0.1:18501/_stcore/health` also
returned `ok` from the host. Neither check called a live model or downloaded
sources. The temporary verification container was stopped afterward; its named
volumes were retained.
