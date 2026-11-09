# Agent quality: POC implementation

The user requested a simple POC during implementation. This delivers the core
Q1–Q3 behavior and useful Q0/Q4 evaluator checks; it does not claim completion of
the full research, calibration or release campaign in the original plan.

- Saved the pre-existing changes first in `ee650a5`.
- Request context owns scope, analyst/UI dates and intent. Invalid or ambiguous dates
  stop before financial dispatch. Financial reads must succeed before one assessment
  or forecast; changed dates and repeated assessments cannot reach the service.
- Conversation memory retains analyst dates and validated evidence separately.
  Selected saved assessments support follow-ups without recalculation and cannot
  establish analyst date intent. Scope rejections end with a useful next step.
- The application builds financial facts and citations from executed or selected
  service results. The model has a small draft schema: explanation, confidence,
  evidence IDs and exact filing quotations. It does not recreate financial tables.
  Unknown references and nonmatching quotations get one repair, then an explicit
  incomplete answer. Provisional streaming output never commits successful history.
- Required summaries preserve each status, null, unit, comparison and result basis;
  disclose springing observations/triggers, selected terms, limited testing relief,
  missing inputs and forecast limitations. Forecast dates are labeled as-of dates.
  Addback explanations reuse the existing calculation helper. Formulas, covenant
  selection and risk artifacts are unchanged.
- Historical JSON still loads. UI, CLI, evaluation and monitoring share the cited
  final answer. Retrieved filing sources remain separate from citations actually used.

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

## Verification

The final lint, full test results and live smoke outcomes are recorded here when complete.
