# Agents

The application uses a tool-calling credit-assessment assistant, three independent
credit-review roles, and a follow-up-question generator. They use PydanticAI with
explicit application services and typed outputs. Financial calculations belong to
the deterministic assessment service; agent interpretations remain advisory.

## Roles and responsibilities

| Agent | Inputs and purpose | Output and capabilities |
| --- | --- | --- |
| [`CreditAssessmentAgent`](../../src/credit_monitoring/agents/credit_assessment.py) | An analyst's question, application-selected borrower or issuer scope, optional reporting dates, and available services. Investigates source evidence and explains assessments. | `AgentAnswer` with Markdown, findings, tables, gaps, citations, evidence, usage, and actual tool outcomes. Can discover/read/search/process documents and read financials, calculate compliance, or request a forecast when those services are configured. |
| [`BullishCreditAgent`](../../src/credit_monitoring/agents/credit_review.py) | A frozen assessment evidence snapshot and optional exposure-decision criteria. Develops the strongest supported favorable interpretation while retaining counterevidence and gaps. | `PerspectiveResult` containing a structured `PerspectiveAssessment` and execution metadata. No retrieval or calculation tools. |
| [`BearishCreditAgent`](../../src/credit_monitoring/agents/credit_review.py) | The same snapshot and criteria. Develops the strongest supported cautious interpretation while retaining counterevidence and gaps. | The same perspective contract and execution metadata. Runs independently of the bullish agent and has no retrieval or calculation tools. |
| [`CreditRecommendationAgent`](../../src/credit_monitoring/agents/credit_review.py) | The original snapshot, decision criteria, both perspective results, and allowed actions. Judges every supplied argument and explains the proposed action. | `CreditRecommendation` plus execution metadata. Actions are `maintain`, `increase`, `reduce`, `review`, or `defer`; exposure sizing is excluded. No retrieval or calculation tools. |
| [`FollowUpQuestionAgent`](../../src/credit_monitoring/agents/follow_up_questions.py) | A saved assessment and its matching credit review, when available. Suggests specific questions that help an analyst understand or challenge those results. | One to three distinct questions, each with a reason and JSON-pointer references to supplied findings. It generates questions without answering them or executing tools. |

The analyst and risk-manager chat interfaces reuse the assessment assistant with
their configured scope and services. Their display names do not introduce separate
agent implementations. For exact tool arguments, availability, returned objects,
and saved-data effects, see the [agent tools reference](agent_tools.md).

## Assessment assistant

Configure at least one of `service` (`DocumentProcessingService`) and
`assessment_service` (`AssessmentService`). Document tools become available with
the document service; the four financial tools also require an explicit
`borrower_id`. `document_tool_names` can restrict document capabilities.

Issuer scope (`ticker`) and borrower selection are distinct. Synthetic borrowers
are not automatically linked to real SEC issuers. The application enforces scope;
naming another borrower in a question does not switch it. `selected_dates`, when
provided, fixes the reporting period and information cutoff accepted by financial
tools. See [dates and scope](agent_tools.md#shared-date-arguments) and
[document-backed calculations](ml_early_warning.md#consume-stored-document-covenants).

Each `ask(...)` or `ask_async(...)` call starts fresh. Use
`start_conversation(...)` for follow-ups: it retains successful tool evidence,
citations, message history, and a stable telemetry session in memory. Scope stays
fixed, one question runs at a time, and tool budgets reset each turn. Start another
conversation to change borrower or issuer. `close()` and exact `close`, `done`, or
`quit` messages clear local conversation context. Completed service writes remain
saved even if a later model step fails.

For example, in a notebook with the [document service configured](document_processing.md#process-and-search-documents):

```python
from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent

agent = CreditAssessmentAgent(service=service, model=service.model)
conversation = agent.start_conversation(ticker="FMC")
try:
    answer = await conversation.ask_async("Show the leverage covenant schedule with citations.")
    print(answer.answer)
    print(answer.complete, answer.error, answer.tool_trace)
    follow_up = await conversation.ask_async("Which source supports that schedule?")
    print(follow_up.answer)
finally:
    conversation.close()
```

Use synchronous `ask(...)` outside an active event loop. The
[agents notebook](../../notebooks/03-agents.ipynb) also demonstrates financial
questions, predictions, and conversations.

The default budget is six tool rounds and eight model requests, including output
validation retries; `max_tool_rounds` changes those limits. Refusals, invalid
outputs, model failures, and exhausted limits produce an incomplete answer with an
error code. Inspect `complete` and `error` alongside the response.

Answers are structured before the backend renders Markdown. `sources`, `evidence`,
and `tool_trace` retain executed or previously retained evidence; they do not prove
every sentence is true. Confidence describes evidence support rather than a credit
risk probability. See the [rendering decision](../project/decisions/002-agent-markdown-rendering.md).

`stream_async(...)` emits `model_start`, `tool_call`, `tool_result`,
`answer_update`, and `run_end`. Updates are provisional; `run_end.answer` is the
final result. Use `contextlib.aclosing` when consuming streams that may stop early.
An optional async `event_stream_handler` receives public progress without private
model reasoning. See [streaming and diagnostics](document_processing.md#streaming-and-diagnostics).

## Credit-review workflow

[`CreditReviewService`](../../src/credit_monitoring/application/credit_review_service.py)
orchestrates the three review roles. Create it with
`create_credit_review_service(...)` from `credit_monitoring.application.bootstrap`.
It can review a supplied assessment or calculate one first when an assessment
service is configured.

1. Build a frozen evidence snapshot from the assessment and check identity and
   verification. Generated assessment narratives and benchmark labels are excluded.
2. Run bullish and bearish reviews concurrently against that same evidence.
3. Give both full analyses and the original evidence to the recommendation agent.
4. Return the analyses, recommendation, execution metadata, gaps, and issues for
   human review.

Invalid identity or verification blocks the agents and defers the decision.
Missing criteria, unsupported evidence, or failed roles can also require deferral;
successful analyses remain available. A completed workflow may still recommend
`defer`. Reference validation checks evidence IDs and argument coverage, not the
truth of all generated prose. The default news provider reports unavailable and
performs no external search.

Defaults are 60 seconds per role and one output-validation retry. Shared and
per-role models, `CreditReviewSettings`, a news provider, and progress callbacks
are configurable through the factory. See the [credit-review guide](credit_review.md)
for API examples, result statuses, decision criteria, and failure behavior, or try
the [credit-review notebook](../../notebooks/04-credit-review.ipynb).

## Suggested follow-up questions

[`FollowUpQuestionService`](../../src/credit_monitoring/application/follow_up_question_service.py)
checks that the supplied review matches the assessment's borrower, run, reporting
period, and cutoff. It caches validated questions in the working directory's
`follow_up_questions/` folder, keyed by analysis content, model, and prompt version.
Changing those inputs or requesting regeneration produces a fresh generation.

The question agent has a 60-second timeout, at most two requests, and one
validation retry. Validation checks analysis IDs, distinct questions, and references
to existing supplied findings. Suggested questions explain saved results; they
do not expand the answering assistant's available tools or scope.

## Supporting model calls and homework agents

Two other application paths use PydanticAI without a tool-calling conversation:

- [Document extraction](../../src/credit_monitoring/covenants/extraction.py)
  converts supplied source records into typed covenant facts. Document processing
  calls it for document sections and persists results. Automatic post-extraction
  verification is disabled; see [processing and reuse](document_processing.md#processing-and-reuse).
- [RAG narrative generation](../../src/credit_monitoring/application/rag_service.py)
  answers from retrieved passages supplied by the application. Retrieval happens
  before generation; the narrative model has no retrieval tools.

The [monitoring homework](../../homework/monitoring/README.md) adds two chat modes:
**Evidence Search** reuses `CreditAssessmentAgent` with only listing and search;
**Credit Analysis** uses a separate chat agent with `list_borrowers` and
`run_credit_review` tools. The latter delegates assessment and the three review
roles to application services. Its limits are eight requests and six tool calls.
See [monitoring tools](agent_tools.md#monitoring-homework-tools).

Evaluation judge agents score saved outputs separately from the application
workflow. See [evaluation](../homework/evaluation.md),
[LLM judges](../homework/llm_judges.md), and the
[live scenario results](../../data/evaluation/agent_scenarios/README.md).

## Models and observability

Application agents default to `openai-responses:gpt-4o-mini`; model arguments allow
overrides, and app entry points also read `LLM_MODEL`. Configure `OPENAI_API_KEY`
for the default provider. Constructing agents and browsing saved outputs makes no
model requests; executing an agent incurs provider usage. Uncached SEC downloads
also require an identifying `SEC_USER_AGENT`.

Optional [Logfire telemetry](logfire_setup.md) links model calls, tool activity,
usage, and review execution to sessions. Offline tests use scripted models and
check behavior; they do not establish live answer quality. Deterministic
calculations can run without AI credentials, and people retain responsibility for
credit decisions.
