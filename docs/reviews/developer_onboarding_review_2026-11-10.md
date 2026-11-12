# Developer onboarding review — 10 November 2026

The documented local and Docker routes reach a working application using the repository's
existing source, lockfile, demo database, source catalog, and trained model. No
application code was changed. The findings below separate documentation and UI
issues from problems introduced by the verification environment.

## Scope and method

- Started with `README.md`, then followed `docs/guides/ui_preview.md`,
  `docs/guides/docker.md`, and `data/README.md`.
- Reviewed commit `8916b186f88cac056b2a8804a99156d9dc08d5da` in an isolated local
  Git clone. The supplied workspace already contained uncommitted README and UI
  changes, plus untracked `navigation.py` and `workspace_ui_helpers.py`. Those
  files were left untouched. A separate snapshot of those working files was
  also exercised, including the two untracked modules.
- Used a new virtual environment and new runtime storage. No existing `.env`,
  saved assessments, SEC cache, or model credentials were copied. Smoke checks
  explicitly disabled Logfire sending and removed model credentials.
- Environment: Linux x86_64, Python 3.14.2, uv 0.12.19, Docker Engine 29.8.0,
  Compose 5.5.1. Container Python was 3.14.10.
- The package download/build cache and Docker cache were available. This verifies
  a fresh project environment, not installation on a machine with empty caches.

## Commands and observed results

| Step | Command or action | Result |
| --- | --- | --- |
| Install | `uv sync --group dev --extra ml --locked` | Passed in the real Git clone with a new `.venv`. |
| Start main app | `make preview` | Started; HTTP `/` and `/_stcore/health` returned 200. Port 8501 was occupied, so Streamlit printed port 8502. |
| First assessment | Portfolio → choose SYN002 and 2025-09-30 → open borrower → run assessment | Passed without API credentials. Net leverage 5.19x, maximum 5.50x, headroom 0.31x; Logistic Regression probability 65.3%. |
| Navigation | Execute all six committed pages with Streamlit AppTest | Passed, including Borrower analysis after an assessment. |
| Persistence | Open a new AppTest session and select the same borrower and period | Restored the same saved assessment ID. |
| Current working UI | Follow current README's Open borrower → Run assessment path | Passed; Portfolio, borrower workspace, Documents, Risk review, Board reports, Help, and Settings executed. Saved assessment survived a new session. |
| Alternate app | `make run` | Started and printed port 8503. |
| Lint | `make lint` | Passed in the real Git clone. |
| Offline app checks | First stage of `make test-all` | 1,007 passed, one skipped, in 294.64 seconds. |
| Homework checks | Second stage of `make test-all` | 93 passed, six live scenarios skipped, in 49.18 seconds. Overall command exited 0. |
| Docker launch | `APP_PORT=18511 docker compose -p credit-onboarding-20261110 up --build -d --wait --wait-timeout 120` | Passed after normalizing temporary build-context directory permissions; container reached healthy state. |
| Docker offline check | `docker compose -p credit-onboarding-20261110 exec -T app python scripts/check_container.py` | Passed: 37 borrowers, Logistic Regression prediction, all six pages. |
| Docker persistence | Recreate with `up -d --force-recreate --wait`, then run the check with `--verify-saved` | Passed: `saved_data_verified: true`, same assessment ID and SEC-cache marker. |

The Docker check saved assessment
`2eea93a4-a3bf-48ed-ae0e-23c21c4ba0ae`; both checks reported `status: passed`
and `pages_checked: 6`. The isolated Compose project was stopped with
`docker compose -p credit-onboarding-20261110 down`; its generated named volumes
were retained. Both temporary local Streamlit servers were also stopped.

The source data and model are tracked files. No database import, model training,
SEC download, or separate database service was needed for the offline workflow.
Local Markdown link targets in the README and the three onboarding documents
above existed; external URLs and section anchors were not checked.

The committed UI uses **Open borrower analysis**, **Documents & data**, and
**User guide**. The uncommitted README/UI use **Open borrower**, **Documents**, and
**Help**. Each version was checked against its corresponding files.

## Problems found

### 1. The local prerequisites omit `make` — low severity

The README's **Run the app** section lists Python 3.14 and uv, then requires
`make preview`. The Makefile also supplies the documented check commands.
Someone with Python and uv but no Make installation cannot run those commands.
Make was already installed here, so this was a documentation gap rather than an
observed missing-tool failure.

Suggested documentation follow-up: list Make as a prerequisite or include the
equivalent direct launch command beside the quick start:

```bash
uv run --locked --extra ml streamlit run src/credit_monitoring/web/preview.py
```

### 2. Changing reporting period logs a widget-state warning — low severity

In the current uncommitted UI snapshot, start with a fresh workspace and select
`2025-09-30` in Portfolio's reporting-period picker. Streamlit logs:

```text
The widget with key "portfolio_cutoff" was created with a default value but also had its value set via the Session State API.
```

The stack points to `src/credit_monitoring/web/portfolio.py:332`, where the date
input receives a default, alongside the new navigation/session-state handling.
The assessment, navigation, and persistence still passed. This is a nonblocking
warning observed through AppTest; visual browser presentation was not assessed.

Suggested follow-up: reconcile the date widget's default with the restored
session value. No implementation changes were made during this review.

### 3. New UI files are not yet part of a checkout — delivery-state observation

At review start, `src/credit_monitoring/web/navigation.py` and
`tests/workspace_ui_helpers.py` were untracked, while modified tracked files
imported them. A clone of the committed project runs its older, consistent UI;
it does not contain the current working UI described by the modified README.
Sharing only the tracked-file patch would omit required modules.

Suggested follow-up: include the new modules with the related UI/documentation
changes when those changes are eventually committed. Nothing was staged or
committed as part of this audit.

## Verification-environment problems and recovery

These observations should not be counted as failures of the normal application
workflow.

- **Interrupted dependency installation:** the first attempt in an exported copy
  exited 143. Repeating ordinary `uv sync` completed, but Narwhals retained 70
  missing files from the interrupted attempt. Opening a saved assessment then
  raised `ModuleNotFoundError: No module named 'narwhals._enum'`. Checking wheel
  `RECORD` entries identified only Narwhals as incomplete. The following repaired
  the temporary environment; the page and persistence checks then passed:

  ```bash
  uv sync --group dev --extra ml --locked --reinstall-package narwhals
  ```

  A subsequent fresh `.venv` in the real Git clone installed successfully without
  that repair. The README does not discuss recovery from interrupted installs.
- **Docker daemon access:** the sandbox initially denied `/var/run/docker.sock`.
  Access outside that sandbox succeeded. This was a verifier permission issue.
- **Temporary directory permissions:** directories created by the verification
  environment had mode `0756`. Docker preserved that mode when copying source
  into an image owned by root. UID 10001 could not traverse the package
  directories, and Streamlit misleadingly reported that `preview.py` did not
  exist, although inspection as root found it. The temporary clone's input
  directories were normalized to `0755`; no file contents or original workspace
  permissions were changed. This establishes sensitivity to build-context
  permissions, rather than a missing tracked entry point.
- **Export versus checkout:** the preliminary `git archive` copy lacked `.git`.
  Two evaluation checks failed because they require Git metadata, while 1,005
  app tests passed and one skipped. Those results were superseded by verification
  in a real local clone and are not reported as checkout test failures.
- **Occupied local port:** Streamlit selected 8502 automatically. The README
  correctly instructs the reader to use the printed URL, and the walkthrough
  provides an explicit `--server.port` example. Docker used isolated host port
  18511 and Compose project `credit-onboarding-20261110` to avoid existing apps.
- **Cross-filesystem cache:** uv warned that hardlinks were unavailable and fell
  back to copying. Installation still completed. `UV_LINK_MODE=copy` is the
  tool's suggested way to suppress that warning in this environment.

## Limits

Page execution and UI interaction were checked with Streamlit AppTest plus HTTP
readiness requests, not a visual browser review. Optional live AI reviews,
assistant replies, extraction, SEC downloads, Logfire delivery, and paid model
quality were outside the offline onboarding check. macOS, Windows, other Python
versions, remote repository access, and empty download caches were not tested.

All generated local assessments were confined to temporary copies. Existing
workspace source, configuration, credentials, and runtime data were preserved.
