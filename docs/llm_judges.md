# Offline LLM judges with Evidently

This version adds three custom Evidently judges to evaluate captured project outputs:
extraction, retrieval, and answers. The judges run after an experiment, independently
of the monitoring workflow. They do not change covenant facts, calculations, compliance
states, predictions, or analyst answers. There is no UI integration or live quality gate.

## Why these judges, and where they apply

| Judge | Methods whose outputs can be captured | Purpose and supplied data |
| --- | --- | --- |
| Extraction | `extract_covenants()`, `extract_all_companies()`, completed `DocumentProcessingService.process_document()` results | Compare extracted JSON with the original passages actually processed. Check supported facts, attribution, units, schedules, definitions, waiver disclosures, citations, and material omissions within that scope. Preserve historical amendment versions; do not select a governing amendment. |
| Retrieval | `DocumentProcessingService.search_evidence()` and the retrieval step in `rag()` | Compare returned passages with the question. Check useful evidence, issuer identity and relevant dates. An optional evaluator reference can identify missing required evidence; without one, this judges relevance of returned passages, not corpus recall. |
| Answer | `CreditAssessmentAgent.ask()` / `ask_async()`, `rag()` answers, optional LLM narratives from `RiskAnalysisService.analyze()` | Check task completion, claim support, citations, uncertainty, and faithful reporting of actual tool outputs. Distinguish disclosed facts, calculations, and forecasts; flag invented probabilities, ignored failures, and unsupported compliance or legal conclusions. |

These are three grading roles using three different rubrics, not additional production
agents. Each applicable snapshot makes one evaluation request for both its label and
explanation, before any provider/library retries. The model defaults to `gpt-4o-mini`
and is configurable independently of the generating model.

Arithmetic, exact field comparisons, schema validity, and ML predictive performance
remain matters for the existing deterministic tests and statistical evaluation.
`verify_assessment()` checks structured results, not arbitrary prose. The judges do
not restore the currently disabled automatic post-extraction verification.

## Implementation and environment

The project runs Python 3.14. During integration, Evidently 0.7.23 failed to import
on that runtime: its internal Pydantic v1 models raised a `ConfigError` for the
`relative` field. The judge tool therefore has its own Python 3.13 environment and
locked dependencies under `tools/llm_judges/`. The project's Python requirement and
root dependency files are unchanged.

`scripts/run_evaluation.py` forwards arguments to that environment using `uv`.
The project-side `credit_monitoring.evaluation.judge_inputs` adapters export JSONL;
they do not import Evidently or call a model. The standalone evaluator validates
snapshots, uses Evidently `LLMEval` descriptors with
`MulticlassClassificationPromptTemplate`, and builds local `Dataset`/`Report` artifacts.

This follows Evidently's [LLM evaluation workflow](https://docs.evidentlyai.com/quickstart_llm)
and [custom judge configuration](https://docs.evidentlyai.com/metrics/customize_llm_judge).
Evidently supplies prompt templating, model execution, parsing and reports; this
project supplies the credit-monitoring rubrics and snapshot adapters.

## Which data is evaluated

The runner consumes **observed outputs**, not benchmark questions alone. The existing
`data/evaluation_tasks.jsonl` contains 60 tasks, and `data/public_sec_gold_cases.csv`
contains 42 public cases. They can provide questions, identifiers, evaluation scope,
and reviewed references. They are not directly accepted as judge snapshots because
they do not contain captured method outputs and original source passages.

Each JSONL row has this contract:

| Field | Meaning |
| --- | --- |
| `case_id`, `judge`, `question` | Case identifier, `extraction`/`retrieval`/`answer`, and the requested scope. |
| `output` | Captured output as text; structured extractions/passages are JSON-encoded strings. Null or blank means no completed output and is skipped. `[]` is a completed empty retrieval result and can be judged. |
| `context` | Original passages with required `document_id`, `citation`, and `text`; optional `ticker`, `source_start`, and `source_end`. Citation IDs alone are not evidence. |
| `tool_trace` | Optional list of actual tool executions and returned data, especially calculation/prediction results used in an answer. |
| `reference` | Optional evaluator-only reference text. Add it after generation. It is a comparison target, not proof that a source contains a claim. |
| `metadata` | Optional snapshot scope, prompt version, issuer/date limits, or structured assessment context. |
| `expected_label` | Optional manually reviewed `pass`/`fail`/`insufficient_evidence` label for judge calibration. It is excluded from the model prompt. |

The snapshot reader rejects unknown top-level fields and duplicate `(case_id, judge)`
pairs before evaluation. Missing captures, oversized inputs and judge failures remain
visible in reports. The default input limit is 100,000 characters across supplied
prompt data, excluding the rubric; larger inputs are skipped rather than truncated.
For large filings, capture each processed section with its actual context and explicitly
limit any document-level claims to the reviewed scope.

The supplied `data/judges/demo_cases.jsonl` contains nine **controlled synthetic**
cases. Candidate outputs are hand-authored, including deliberate threshold errors,
unrelated retrieval, an empty retrieval, a missing answer, and a fabricated prediction
from a stub model. Source passages reuse the existing synthetic fixture. These cases
demonstrate wiring and obvious grading behavior; they do not measure live extraction
accuracy, public SEC benchmark performance, or production judge reliability.

For temporal evaluation, capture only evidence available at the information cutoff.
Do not send later outcome documents, `future_event_*` labels, benchmark rationale,
or synthetic gold notes to the generating method. The adapters omit catalog notes
from source passages. Review traces and metadata as well: they are supplied as-is,
and may contain annotations that should be excluded from a benchmark experiment.
Unknown source availability must remain unknown.

## Run the working judges

From the repository root, validate the supplied snapshots without API calls:

```bash
python scripts/run_evaluation.py --input data/judges/demo_cases.jsonl --dry-run
```

Run real LLM evaluations, loading an existing key explicitly from `.env`:

```bash
python scripts/run_evaluation.py \
  --input data/judges/demo_cases.jsonl \
  --env-file .env \
  --output-dir data/processed/judges-demo
```

Use `OPENAI_API_KEY` in the shell instead if preferred. An Evidently Cloud account
or API key is not needed. The runner never uploads a dataset or report to Evidently
Cloud; real judging sends the selected snapshot data to the configured OpenAI model
through Evidently. Credentials are not written into artifacts.

Select a role, model or small experiment:

```bash
python scripts/run_evaluation.py \
  --input data/judges/demo_cases.jsonl --env-file .env \
  --judge answer --model gpt-4o-mini --limit 2 \
  --output-dir data/processed/judges-answers
```

`--model` overrides `EVIDENTLY_JUDGE_MODEL`; otherwise the default is used.
`--max-input-chars` adjusts the size limit. `.env` is loaded only with `--env-file`;
shell values take priority. Output directories are reused and their artifact files
are overwritten; choose a distinct directory when comparing experiments.

The direct isolated entry point is also available:

```bash
uv run --project tools/llm_judges --locked credit-judges \
  --input data/judges/demo_cases.jsonl --dry-run
```

## Capture this project's outputs

In the existing project environment or RAG notebook, capture outputs after running
the methods you already want to evaluate:

```python
from pathlib import Path
from credit_monitoring.application.rag_service import llm, build_prompt
from credit_monitoring.evaluation.judge_inputs import (
    capture_answer, capture_extraction, capture_retrieval, write_judge_inputs,
)

# service is your existing configured DocumentProcessingService instance.
question = "What covenant thresholds are disclosed for this issuer?"
records = service.search_evidence(question, ticker="FMC")
answer = llm(build_prompt(question, records), client=service.client, model=service.model)
document = service.get_document_extraction("DOC_FMC_AMD3_2025")

cases = [capture_retrieval("FMC_SEARCH", question, records)]
# This answer was generated from exactly these records.
cases.append(capture_answer("FMC_ANSWER", question, answer, records))

if document.result is not None:
    original_document = {
        "document_id": document.document_id,
        "citation": document.citation,
        "content": Path(service.markdown_dir / f"{document.document_id}.md").read_text(),
    }
    cases.append(capture_extraction(
        "FMC_EXTRACTION", "Extract every supported covenant fact from this document.",
        document.result, [original_document],
    ))

write_judge_inputs(Path("/tmp/credit-judge-inputs.jsonl"), cases)
```

For a RAG string answer, pass that string to `capture_answer()` with the exact passages
used to build its generation prompt. For batch extraction, `capture_extraction()`
accepts `AllCompanyExtractionResult` too. For a narrator string, attach the exact
`assessment_context(assessment)` to the snapshot's `metadata["assessment_context"]`.
That gives the judge the authoritative structured results to compare with the prose.
An incomplete `AgentAnswer` is exported with a null output and its failure metadata.
For a completed agent run, pass the `AgentAnswer` and all original passages supporting
its actual tool trace. The adapter retains the executed tool results. A separate
search with the same question may return different passages and is not a substitute
for capturing that run's evidence.

References can be added to the resulting dictionaries before writing. Join existing
benchmark tasks by `case_id` and include only applicable, reviewed reference fields.
Do not force an active-amendment or early-warning target when the current application
cannot establish it. Missing capabilities and unsupported targets need explicit review.

## Results, calibration and validation

Each completed judge returns `pass`, `fail`, or `insufficient_evidence`, plus an
explanation. Status is separately `evaluated`, `skipped`, or `error`; provider/parse
errors never become a quality pass or a source-evidence abstention.

The output directory contains:

- `inputs.jsonl`: selected snapshots for review and reruns.
- `results.jsonl`: per-case judgments, explanations and evaluation status.
- `summary.json`: counts by role, decisive coverage, pass rate, and manual-label agreement.
- `manifest.json`: model, Evidently version, rubric text/version, input hash and run time.
- `report.html` and `report.json`: actual local Evidently reports summarizing role, status and label.

Pass rate uses only decisive pass/fail judgments. Decisive coverage divides those
judgments by all selected cases, so errors, skips and insufficient evidence remain
visible. Agreement uses evaluated cases carrying manual labels; it is not credit
model accuracy. Review explanations in `results.jsonl` alongside the saved inputs.

Normal exit status is 0 for a completed evaluation, even when candidates fail. Input,
provider, parsing or report errors return 2. Add `--fail-on-quality` to return 1 when
any case fails, lacks sufficient evidence, or is skipped; infrastructure errors still
return 2. The demo intentionally contains failures, so it should not pass that gate.

Use manually labeled project examples to validate and refine the rubrics before
relying on aggregate scores. Evidently describes this process in its
[judge alignment tutorial](https://www.evidentlyai.com/blog/how-to-align-llm-judge-with-human-labels)
and explains judge limitations in its
[LLM-as-a-judge guide](https://www.evidentlyai.com/llm-guide/llm-as-a-judge).
All external documentation used for this addition is on Evidently's website.

Run the automated checks:

```bash
uv run --locked pytest tests/unit/evaluation -q
uv run --project tools/llm_judges --locked pytest \
  -c tools/llm_judges/pyproject.toml tools/llm_judges/tests -q
uv run --locked ruff check .
uv run --project tools/llm_judges --locked ruff check \
  tools/llm_judges/src tools/llm_judges/tests --config tools/llm_judges/pyproject.toml
```

The automated tests use the real Evidently descriptors, parser and report builder
with mocked model replies, and test snapshot adapters using actual project types.
Credentialed smoke runs are separate from the mocked tests.

### Validation record

- Five project adapter tests and eighteen isolated judge tests passed. Both Ruff
  checks and `git diff --check` passed.
- Real `gpt-4o-mini` requests exercised all three judges and wrote local Evidently
  HTML/JSON reports. Controlled examples covered positive judgments, deliberate
  factual/retrieval/prediction failures, missing-output skips, and insufficient
  evidence for empty retrieval without a reference.
- An existing cached FMC amendment extraction was exported using the project
  adapter and evaluated against its full local source. The judge returned a failure
  flag concerning the leverage schedule. This is a review finding, not a confirmed
  correction of the legal interpretation or source extraction.
- The complete project suite encountered 37 failures in existing public SEC
  cache-versus-gold comparisons. Running those tests from an isolated archive of
  the starting `main` commit against the same read-only cache reproduced all 37
  failures. The benchmark tests, cached extractions and production extraction code
  were not changed by this addition.

Generated reports live under ignored `data/processed/judges*/` directories. The
controlled smoke checks establish executable integration, not production judge
accuracy or an evaluation of all 60 benchmark tasks.
