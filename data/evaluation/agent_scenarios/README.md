# Agent scenario batch

The [60-scenario CSV](scenarios.csv) applies the lesson framework to the deployed
`CreditAssessmentAgent`. Each of six supported topics has three happy paths and
two phrasing variants, with additional edge and breaking cases.

The [9 November baseline report](results/2026-11-09-baseline/REPORT.md) records the
completed live batch: 9 automatic passes, 50 failures and one execution error.
See the [saved results CSV](results/2026-11-09-baseline/results.csv) for every answer.
The [agent quality improvement plan](../../../docs/project/agent_quality_improvement_plan.md)
turns these findings into implementation packages, tests and release criteria.

| Category | Count |
| --- | ---: |
| Happy path | 18 |
| Varied phrasing | 12 |
| Edge cases | 12 |
| Out of scope | 6 |
| Breaking scenarios | 12 |

Topics cover compliance/headroom, coverage and contractual definitions, springing
tests, amendments/waivers, next-quarter forecasts, and evidence retrieval. Variants
include direct, vague and wrong-terminology questions. Breaking cases include
injection in a question and retrieved text, fabricated citations, scope changes,
future-information leakage, ignored caps, and an obsolete answer-key assertion.

## Run

For a small POC check without semantic grading, add `--skip-judge --cases H01,H07,H08,H11,H15,H16,E04,B10,B11,B12`
to the run command below. Missing semantic grades remain visible. The command exits
nonzero if execution or a deterministic check fails. See the
[POC implementation notes](../../../docs/project/agent_quality_implementation.md)
for the implemented scope and deferred evaluation work.

From the repository root, using the locked Python 3.14 environment:

```bash
uv run --locked python -m credit_monitoring.evaluation.agent_batch validate
uv run --locked pytest tests/unit/evaluation/test_agent_batch.py -q
uv run --locked python -m credit_monitoring.evaluation.agent_batch run \
  --output data/evaluation/agent_scenarios/results/new-run --env-file .env
```

`run` makes live API calls and requires `OPENAI_API_KEY`; credentials are never
copied to output. Generation defaults to `openai-responses:gpt-4o-mini`, with
`openai-responses:gpt-4.1-mini` as the automated judge. Override `--model` and
`--judge-model` explicitly. `--cases H01,H16,O01` selects a smoke batch. The runner
uses four concurrent cases with 150-second generation and 60-second judge limits;
change `--concurrency`, `--timeout` and `--judge-timeout` as needed.

Use a new output directory each time. The runner refuses to overwrite a run.
It writes completed rows immediately to `results.jsonl`, then produces ordered
`results.csv` and `summary.json` at completion. Execution failures return exit 1;
completed answers with quality failures remain in the report and return exit 0.
An interrupted run retains case captures and completed JSONL rows; select any
remaining IDs into a **new** run rather than overwriting earlier evidence.

## What is measured

Every question gets a fresh agent and separate financial, analytics or document
database. Generation sees the question, configured scope and application inputs.
Expected behavior, numeric references, other cases and judge labels stay outside
generation. Financial metrics are loaded through the application allowlist.

The deterministic checks evaluate actual execution completion, tool order, exact
analyst dates, borrower/issuer scope, numeric/status/null references, calculation
citations, exact document citations and injection markers. Numeric references are
authored from the versioned contracts, raw inputs and existing gold calculations;
the offline preflight detects disagreement without generating references from the
agent being evaluated. Sensible rounding is accepted in prose; stored tool values
use a much tighter numeric tolerance.

The judge then checks answer meaning against the expected behavior and captured
tool evidence. Its prompt and model are saved. A pass requires a completed answer,
every deterministic check, and an explicit judge pass. Judge errors and
insufficient evidence become `needs_review`; they remain in the denominator.
Execution errors are reported separately. `deterministic_pass` and `judge_label`
remain separate columns so disagreements are inspectable.

Each `cases/<ID>/` contains the actual request, answer with ordered tool trace and
sources, checks, judge input/output, and flattened result. `response_sha256` binds
the grading to the exact saved `answer.json` bytes. The manifest saves revision,
dirty-tree status, input/source/lockfile hashes, selected IDs and prompt/rubric
versions. Input snapshots and SQLite state are retained locally but ignored by Git;
the CSV, answers, checks, judge packets, manifest and summary are shareable results.

## Interpretation and limits

This is an agent-authored diagnostic baseline, with automated proxy grading, not
human labels or a calibrated judge. A different judge model reduces identical-model
bias but does not eliminate correlated mistakes. Inspect the saved explanations and
traces before making decisions. Neither failed nor missing cases are dropped.

The borrowers and retrieval sources are fictional. `sources/` is a small, versioned
packet with explicit actual/limit, metric, issuer and waiver distinctions. The
source contains a deliberate malicious paragraph. Retrieval uses the real local
search and scoping services with only `list_documents` and `search_evidence`
registered; extraction, processing, SEC downloading and retrieval recall across the
full public corpus are outside this suite. The Logistic Regression artifact is
trained on synthetic data and has no established real-world forecasting accuracy.

The older `synthetic_gold_labels.csv` SYN010 FCCR assertion of 1.10x is unsupported
by current raw inputs. B05 deliberately checks that the agent uses missing-input
abstention instead. The older label file is preserved, not silently rewritten.

The cases have no reserved holdout and are not 60 statistically independent tasks:
phrasing variants intentionally share question families. Use the failures to guide
changes and reserve new families before claiming improved generalization. One
generation per case does not measure run-to-run stability. Generation token usage
is not exposed by the current agent facade, so this report makes no cost claim.
