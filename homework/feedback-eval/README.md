# Logs → ground truth → eval demo

A standalone Streamlit playground. All new code lives in this folder; it does not
modify or run the main application's agents, tools, databases, or configuration.
It uses the existing locked dependencies. Local cases/results live in ignored
`data/runtime/feedback-eval/`.

```bash
uv run --locked streamlit run homework/feedback-eval/app.py
```

1. **Import:** load four fictional demo cases, upload JSON/JSONL, or fetch reviewed
   interactions from Logfire. Imports are always pending; repeated imports preserve
   existing local reviews.
2. **Review cases:** inspect the question, captured answer, user review and source
   evidence. Correct the expected answer, enter your name, select **approved**, and
   save. A rating never automatically approves an answer. You can exclude a case.
3. **Evaluate:** compare fresh baseline/candidate answers using different prompts or
   models. Both receive the same frozen source context. An LLM judge receives the
   expected answer too and labels each output pass/fail/insufficient evidence.
   Alternatively, grade captured answers to diagnose the original failures.
4. Read the side-by-side answers and reasons. Download the comparison report and
   save which configuration you would keep and why. Use development cases for
   tuning; freeze the candidate before checking the holdout split.

The fictional examples start unapproved, with draft references. They demonstrate
waiver interpretation, leverage headroom, missing forecasts and a springing-test
boundary. They are not production observations or independent human ground truth.
Review/approval works without credentials. Evaluation uses paid model requests.

## Credentials and Logfire import

The root `.env` is loaded without overriding exported environment variables:

```dotenv
OPENAI_API_KEY=...
LOGFIRE_READ_TOKEN=...
LOGFIRE_BASE_URL=https://logfire-eu.pydantic.dev
```

Use the region matching your project. The existing Logfire write token cannot query
records. Export/import does not need a model key; model evaluation does not need
Logfire access. The demo sends selected question/evidence/reference content to the
chosen model provider during evaluation; it does not export new telemetry.

The fetch form selects service, environment and feedback date range. It fetches
related traces with a 30-day lookback and rejects oversized exports; narrow the
range if needed. A saved Query API `{"rows": [...]}` JSON export also works. Records
need `attributes.interaction_id`; feedback uses `event_name = user.feedback`.
Native `gen_ai.input.messages`/`gen_ai.output.messages` and tool response parts are
recognized. Serialized JSON attributes are supported. Raw structured final outputs
remain JSON for review rather than being passed through the main application's
renderer. Unattributed trace records are attached only when there is one unambiguous
interaction in that trace. Multiple reviews on one response become one case.

Missing/scrubbed content remains blank for the reviewer to resolve. Verify source
facts and add any prior conversation required by follow-up questions. Never label a
newly searched document as the evidence used by the original response. Approval
requires a question, evidence, reference and reviewer. Related groups cannot be
approved in both development and holdout splits. Group related documents/paraphrases
manually as well as conversation turns. Re-importing a reviewed dataset resets its
approval; the existing local dataset keeps its approvals.

Normalized JSONL has this small schema:

```json
{"case_id":"trace-turn-1","question":"What is the status?","answer":"Original answer","evidence":"SOURCE-1: the test is waived.","expected":"Explain waived is not compliant; cite SOURCE-1.","group":"conversation-1","split":"dev","status":"pending"}
```

## CLI and saved evidence

After approving cases in the UI:

```bash
uv run --locked python homework/feedback-eval/backend.py
uv run --locked python homework/feedback-eval/backend.py --captured
uv run --locked python homework/feedback-eval/backend.py --split holdout
```

`--model` and `--judge-model` select models; `--cases` accepts another reviewed JSONL
file. `--fail-on-quality` exits nonzero unless every case passes. Report-only runs
preserve failed grades and execution errors without treating them as successful
answers. No approved cases is an error before any model requests.

Each run saves an immutable dataset/configuration snapshot in `manifest.json`,
per-case answers/grades/tokens in `results.jsonl`, `summary.json`, and `REPORT.md`.
The UI can also save your configuration choice and rationale in `decision.json`.
Hashes bind the dataset, local runner and dependency lock. Partial results are saved
as each answer finishes; an interrupted manifest remains `running`. Pass rate uses
all selected cases, including errors and insufficient evidence, as its denominator.
To reproduce the inputs, use the manifest's `cases` and exact prompts/models.

## Deliberate demo limits

This implements the small demonstration path: logs, reviewed references, automatic
LLM scoring, and a prompt/model comparison.
Generation is a standalone evidence-grounded LLM call, **not a measurement of the
full application or retrieval pipeline**. Chunking experiments, automatic promotion,
scheduled CI, hosted datasets, queues, authentication, judge calibration campaigns
and full conversation replay are left out to keep this small.

The judge is an uncalibrated proxy. Its exact excerpt is checked, but semantic and
numeric correctness still depend on the judge and reviewed reference. Human-review
important disagreements. No runtime data or human approval is shipped as measured
production accuracy. The UI is for a trusted local user; run one reviewer at a time.
Runs are sequential, limited to 30 cases/two configurations, with one request per
generation/judge, a 60-second request timeout, and a 1,200-output-token limit. Token
usage includes generation and judging; dollar cost is not estimated.

## Checks

```bash
uv run --locked pytest homework/feedback-eval/tests -q
uv run --locked ruff check --config 'include=["**/*.py"]' homework/feedback-eval
```

Tests use scripted models and temporary storage, including Streamlit review actions.
No paid evaluation or Logfire connection is required.

Verified on 14 November 2026: the offline tests exercise review/import and evaluation
results; a read-only live Logfire smoke imported four pending cases (three with
questions/answers, two with captured tool evidence). A fictional live model smoke
completed generation and reference-based judging with a validated answer excerpt.
These are integration checks, not a calibrated quality benchmark. Live exports and
smoke outputs remain in ignored runtime storage.
