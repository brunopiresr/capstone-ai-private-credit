# Agent quality: POC implementation

The user requested a simple POC during implementation. This delivers the core
Q1–Q3 behavior and useful Q0/Q4 evaluator checks; it does not claim completion of
the full research, calibration or release campaign in the original plan.

- Saved the pre-existing changes first in `ee650a5`.
- The assessment assistant is one agent. Instructions handle request interpretation,
  contextual dates, clarification, scope explanations, tool order and avoiding repeats.
  There is no request classifier, pending-intent override or dispatch state machine.
- Python validates concrete tool inputs: required fields/types, valid calendar dates,
  configured tool arguments and cutoff on/after the reporting date. Financial calculation
  and verification services remain unchanged. Assessment-agent evidence, copied-value,
  quotation and result-identity checks have been removed.
- Conversation history retains questions and answers; copied executed results and selected
  assessments supply context. Failed document-processing statuses are retained too.
  Only successful completed turns commit new history/evidence; cancellation does not.
- The model returns plain structured summary, findings/citation data, optional tables,
  gaps, diligence questions and confidence. The application renders the same data for
  streaming and final answers, escaping source text and table cells. It formats supplied
  citations without checking membership or semantic support. Instructions and scenarios
  cover evidence quality rather than runtime evidence enforcement.
- New answers use `agent-answer-v3`. `AgentAnswer.answer` remains application-rendered
  Markdown for UI, notebooks and evaluators; historical answers and v2 claims still load.
  Explanations with numbers are retained, and follow-ups do not automatically repeat the
  whole assessment or retrieved passages.

The original source, lockfile and inputs are frozen with hashes. The additional 20
reserved cases remain unopened. Grading separates dimensions and rejects invented
answer excerpts; automated semantic grades remain provisional without analyst labels.

The Q1 development capture and exploratory Q2 capture are retained. The latter
exposed fragility in asking the model to author detailed fact selectors (45 execution
errors); this motivated the smaller draft contract. These captures do not establish
final POC accuracy. Detailed failed Q2 case files remain local; its manifest and summary
are versioned. The final smoke uses deterministic checks without a semantic judge.

Full 60-case final comparisons, repeated runs, reserved-case evaluation, independent
grader calibration and a separate review-ensemble benchmark are deferred under the
POC scope. No changes to the bullish/bearish/recommendation roles are claimed.

## V3 verification

- Tool input, structured-rendering, Streamlit, historical-answer and conversation tests
  cover the simplified agent; custom policy/evidence enforcement tests were removed.
- App suite: 999 passed. Lint and diff whitespace checks passed.
- Homework checks: 102 passed; six opt-in live agent/judge tests skipped.
- Eight fresh live development scenarios completed using `openai-responses:gpt-4o-mini`:
  H01, H15, V02, V03, V05, V07, V11 and E01. Rechecking their captured answers with
  evaluator v3 passed all deterministic checks. No semantic judge was run.
- The scorer now reads escaped v3 source text and accepts status capitalization,
  sentence punctuation and ratio units; citation coverage can use a cited actual,
  threshold or headroom. Numerical service-result comparisons remain independent.
- Separate live checks rendered a source matrix with three diligence questions and
  completed clarification → date reply → saved-evidence follow-up without recalculation.
- Local captures: `/tmp/credit-agent-v3-smoke-20261111-final/rechecked-v3.json`,
  `/tmp/agent-date-probe-y7dp6s96/answer.json`, and
  `/tmp/agent-date-probe-anmy6220/turn-1.json` through `turn-3.json`.

These are POC smoke checks, not a measured production accuracy claim. Earlier prompt
iterations still guessed dates or omitted details; workflow and evidence quality
remain instruction-driven rather than guaranteed by Python checks.

## Discovery follow-up (2026-11-12)

The shared `credit-assessment-agent-v15-discovery` instructions describe a general
decision process: identify the requested outcome, resolve the necessary target and
inputs, discover what is available, and ask only for the remaining prerequisites.
There are no request keywords, per-scenario examples, routing agent or Python workflow
gates. The structured-answer tool explicitly supports answering or clarifying as the
first action. Its description reaches the real provider request in the transport test.

`list_financial_periods` reads reporting periods and nullable availability dates from
the active repository adapter. It returns no financial metrics, performs no assessment
and writes no data. Saved-assessment discovery remains limited to its snapshot/history.
Assessment and prediction load their own inputs; `get_financials` is optional.

Turn context includes registered capabilities, missing application selection, source
identity, selected dates and today's date in Europe/Lisbon. Borrower-bound tools remain
unavailable without application selection. Instructions permit today's cutoff only
for latest/current requests without an existing cutoff, require disclosure of that
default, and distinguish historical or ambiguous requests. Issuer evidence requires an
explicit borrower relationship in context. Financial calculation services and the
default model remain unchanged; runtime evidence validation has not been reintroduced.

Active evaluation contracts accept optional discovery/financial reads and require the
appropriate final operation rather than an exact sequence. E01 now independently
expects the latest stored quarter (2025-12-31), today's cutoff and 5.6x leverage against
5.5x. Captures record their date so rechecking does not move the reference cutoff.
Discovery metadata is not counted as an executed assessment. Historical captures and
their authored expectations are unchanged.

Verification and observed limitations:

- Targeted agent/evaluation/provider suites: 306 passed. The final direct-answer tool
  description and discovery checks subsequently passed all 21 focused tests.
- Full app suite: 1,027 passed.
- Homework suites: 105 passed, six opt-in live tests skipped. Repository lint and diff
  whitespace checks passed.
- An eight-case live development smoke completed all requests; five passed deterministic
  checks. After the direct-answer description change, E01 and V03 both passed their
  deterministic checks. E02 still assumed a cutoff for a historical request, and E04
  still interpreted an ambiguous date instead of asking. No semantic judge was run.
- The exact missing-borrower notebook question now asks for selection without tool calls
  or choosing an issuer. The document-schedule question runs without borrower/calculation
  dates and retrieves the schedules and reported ratios. These observations do not
  establish complete source coverage or presentation quality.
- The waiver explanation remains incorrect in live testing: it starts an unnecessary
  assessment with invented dates and can recommend a breach alert from an incomplete
  result. Earlier iterations also used an unrelated issuer's filing. Instructions now
  explicitly prohibit filling a borrower gap with unlinked issuer evidence, but the
  conceptual-versus-execution distinction is still unreliable.
- A diagnostic run using the existing evaluation model (`gpt-4.1-mini`) also failed the
  date cases; it did not change the application's configured model. Neither model run
  establishes that prompt-only handling of these cases is reliable.

Local captures are under `/tmp/credit-agent-discovery-final-20261112`,
`/tmp/credit-agent-discovery-output-description-20261112`,
`/tmp/credit-agent-discovery-comparison-20261112` and
`/tmp/notebook-question-regressions-vlwbb309`. The complete document-schedule capture
is `/tmp/notebook-question-regressions-edqrzvzm/document_schedules.json`.
The root `agent-discovery-plan.md` remains untracked and has not been staged.

The discovery architecture is implemented; live instruction-following validation is
not fully passing. These remaining failures are recorded rather than hidden by
weaker expectations, replacement policy rules or automatic answer rejection.

## Historical verification before the v3 simplification

- `make lint`: passed.
- `make test-all`: 1,004 main tests and 93 homework tests passed; six opt-in live
  agent/judge tests skipped.
- [Final live smoke](../../data/evaluation/agent_scenarios/results/2026-11-09-poc-final/REPORT.md):
  10/10 cases completed and passed every deterministic check, including the unknown
  borrower, source injection, ambiguous dates, scope switching, waiver and forecast.
  Semantic grades are intentionally unavailable. Generation source hashes match
  the saved manifest at revision `d466321`.
