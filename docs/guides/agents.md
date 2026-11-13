# Agents and credit reviews

The analyst needs calculations it can inspect and interpretations it can challenge.
The POC separates those jobs: application services calculate; PydanticAI agents
gather evidence and explain results. Start with the [worked example](../worked-example.md)
or [Notebook 03](../../notebooks/03-agents.ipynb).

## Roles and responsibilities

| Agent | Supplied evidence and responsibility | Output |
| --- | --- | --- |
| [CreditAssessmentAgent](../../src/credit_monitoring/agents/credit_assessment.py) | A question, application-owned borrower/issuer scope, and configured service tools | `AgentAnswer`: Markdown, structured findings/tables, gaps, confidence, sources, and actual tool trace |
| [BullishCreditAgent](../../src/credit_monitoring/agents/credit_review.py) | A frozen assessment and analyst criteria; strongest supported favorable interpretation | `PerspectiveResult`, with arguments, evidence references, counterevidence, and gaps |
| [BearishCreditAgent](../../src/credit_monitoring/agents/credit_review.py) | The same snapshot and criteria; strongest supported cautious interpretation | The same structured perspective contract |
| [CreditRecommendationAgent](../../src/credit_monitoring/agents/credit_review.py) | Original snapshot, both full perspectives, criteria, and allowed actions | An explained `CreditRecommendation` and execution metadata |
| [FollowUpQuestionAgent](../../src/credit_monitoring/agents/follow_up_questions.py) | Saved assessment and matching review | One to three questions with reasons and references to supplied findings |

Web V2's **Analyst Assistant** and **Risk Copilot** reuse the assessment assistant;
their names do not identify separate implementations. They use a saved-assessment
adapter with recalculation disabled and no document service. The broader document
and financial tool combinations are demonstrated in notebooks. See the
[tool reference](../reference/agent-tools.md).

## Assessment assistant

Configure at least one of `service` (document processing) and `assessment_service`.
Financial tools also need explicit `borrower_id`. `ticker` limits issuer research;
`selected_dates` fixes the dates accepted by financial tools. Naming another
borrower in chat does not change application selection.

In a notebook with the [document service](document-processing.md#process-and-search-documents)
configured:

```python
from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent

agent = CreditAssessmentAgent(service=service, model=service.model)
answer = await agent.ask_async(
    "Show the leverage covenant schedule with citations.", ticker="FMC"
)
print(answer.answer)
print(answer.complete, answer.error, answer.tool_trace)
```

Independent `ask(...)` and `ask_async(...)` calls start fresh. Use synchronous
methods outside an active event loop. For retained multi-turn context in Python:

```python
conversation = agent.start_conversation(ticker="FMC")
try:
    first = await conversation.ask_async("Find the leverage schedule.")
    follow_up = await conversation.ask_async("Which source supports it?")
finally:
    conversation.close()
```

A conversation retains successful messages, evidence, and citations in memory,
with one question at a time and fixed scope. Exact `close`, `done`, or `quit`
messages also close it. Tool budgets reset per turn. Completed service writes
remain saved if a later model step fails. V2's per-question calls do not retain
this multi-turn model history; its [visible transcript](web-v2-workflow.md#ask-the-assistant-and-rate-an-answer)
is browser-session state.

Defaults allow six tool rounds and eight model requests, including output-validation
retries. Failures and exhausted limits return an incomplete answer: inspect
`complete` and `error`. Sources and traces show available/executed evidence, not
semantic verification of every claim. Confidence describes evidence support,
not credit risk or a calibrated probability.

`stream_async(...)` emits `model_start`, `tool_call`, `tool_result`, `answer_update`,
and `run_end`. Updates are provisional; `run_end.answer` is final. Use
`contextlib.aclosing` for streams that may stop early. An optional async
`event_stream_handler` receives public progress without private model reasoning.

## Credit-review workflow

The [credit-review service](../../src/credit_monitoring/application/credit_review_service.py):

1. Builds a frozen evidence snapshot and checks assessment identity and verification.
2. Runs bullish and bearish reviews concurrently, without sharing their conclusions.
3. Gives both full analyses and original evidence to recommendation synthesis.
4. Returns arguments, judgments, gaps, recommendation, and execution metadata.

Review agents have no retrieval or calculation tools. Generated assessment prose,
benchmark labels, and financial/catalog notes are excluded from their evidence.
Independent histories encourage contrasting arguments; they do not establish
statistical independence or measured analytical benefit.

## Review an existing assessment

With a `RiskAssessment` and provider credentials configured:

```python
from credit_monitoring.application.bootstrap import create_credit_review_service
from credit_monitoring.domain.credit_review import ExposureDecisionContext

reviews = create_credit_review_service()
decision = ExposureDecisionContext(
    question="Review the existing exposure and identify missing credit context.",
    credit_criteria=("Check compliance, headroom trends, and evidence gaps.",),
    constraints=("No numerical exposure sizing.",),
)
result = await reviews.review_assessment_async(assessment, decision_context=decision)
print(result.model_dump_json(indent=2))
```

Use `review_assessment(...)` synchronously. With an assessment service configured,
`review(...)`/`review_async(...)` first creates an assessment, then reviews it.
Construction makes no model calls; execution incurs usage.

## Results and boundaries

| Action | Meaning |
| --- | --- |
| `maintain` | Advise retaining the current exposure |
| `increase` / `reduce` | Advise a direction without sizing |
| `review` | Request analyst reassessment |
| `defer` | Evidence, criteria, or completed reviews are insufficient |

These actions are advisory. Covenant evidence alone does not establish repayment
capacity, valuation, portfolio suitability, or the adequacy of exposure advice.
`complete` means the workflow finished; it may still recommend `defer`.

| Condition | Behavior |
| --- | --- |
| Invalid identity or verification | Block agents and defer |
| Missing criteria or supported evidence | Defer and retain available analysis |
| Reviewer or recommendation failure | Return incomplete; preserve successful work and defer |
| Missing news or ML | Disclose the gap and preserve calculation evidence |

Display both perspectives, recommendation, issues, and limits together. Reference
checks validate identifiers and argument coverage, not every sentence's truth.

## Configuration and supporting calls

The default is `openai-responses:gpt-4o-mini`. The factory accepts shared/per-role
models, `CreditReviewSettings`, an optional news provider, and progress callbacks.
Defaults are 60 seconds per role and one output-validation retry. Cancellation
propagates. The default news provider reports unavailable and performs no search.
Injected news requires explicit borrower mapping and publication provenance;
unknown and post-cutoff publication times are excluded.

Follow-up generation checks matching borrower, run, period, cutoff, and references
to existing findings. Validated questions are cached under the workspace's
`follow_up_questions/` by analysis content, model, and prompt version. It has a
60-second timeout, at most two requests, and one validation retry. Suggestions do
not expand the answering assistant's tools.

[Extraction](../../src/credit_monitoring/covenants/extraction.py) produces typed
facts from supplied sections. [RAG generation](../../src/credit_monitoring/application/rag_service.py)
answers from passages retrieved before the model call. Evaluation judges score
captured outputs separately; see [LLM judges](../evaluation/llm-judges.md). Additional
coursework tools are distinguished in the [reference](../reference/agent-tools.md#monitoring-homework-tools).

## Validation and model evaluation

```bash
uv run --locked pytest tests/integration/workflows/test_credit_review.py
```

Scripted-model tests cover orchestration, evidence flow, serialization, and failures.
They do not measure live interpretation quality. Saved live results and known
limitations are in the [results overview](../evaluation/results.md).

For optional question-generation evaluation on a saved review:

```bash
uv run --locked python scripts/evaluate_follow_up_questions.py --live \
  --run-id YOUR_SAVED_ASSESSMENT_ID --output /tmp/follow-up-quality.json
```

This makes model calls and exports questions with a human scoring rubric. Merely
generating questions is not a quality result. See [monitoring](monitoring.md) for
traces and usage.
