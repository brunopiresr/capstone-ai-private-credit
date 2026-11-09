# Agent quality improvement plan

Prepared 9 November 2026. The user subsequently narrowed implementation to a simple
POC. Request guards, evidence-backed answers and required financial summaries are
implemented; the full measurement and ensemble campaign below remains a roadmap.
See [implementation notes](agent_quality_implementation.md) for actual checks and limits.

## Objective and evidence

Make the assessment assistant consistently use the right evidence, execute the
required workflow, and produce complete, attributable answers. Improve the evaluation
enough to distinguish financial correctness, workflow failures, missing citations,
and poor interpretation. Establish a separate quality baseline for the bullish,
bearish, and recommendation agents before changing their analytical behavior.

The [60-case baseline](../../data/evaluation/agent_scenarios/results/2026-11-09-baseline/REPORT.md)
recorded 9 automatic passes, 50 failures, and one execution error. Forty-four cases
failed an exact prose citation check. Thirty-six of 39 cases with structured
references matched them; the other three did not obtain the expected assessment.
Tool contracts passed in 54/60 cases. The judge incorrectly passed 45 answers that
failed deterministic checks and also missed semantic errors in an automatic pass.
These results are a diagnostic development baseline, not a validated accuracy estimate.

The existing prompt already describes most desired behavior. Currently,
`CreditAssessmentAgent` validates a nonblank answer, confidence, and confidence
explanation. `AgentRunState` records actual tools and filing sources, but the answer
has no structured claim-to-evidence contract. Dates and tool order mostly depend on
the model following instructions. The plan moves those invariants into validation
and per-run state while preserving the calculation services.

## Delivery order

Estimates are engineering effort for one implementer, excluding analyst availability
and provider waiting. Each package should be a separately reviewable change.

| Package | Priority | Deliverable | Dependency | Estimate |
| --- | --- | --- | --- | --- |
| Q0 | P0 | Trusted measurement contract and frozen regression set | Existing captures | 0.5–1 day |
| Q1 | P0 | Explicit request context and controlled tool execution | Q0 | 1–2 days |
| Q2 | P0 | Structured claims, validated references, and rendered citations | Q0; integrate with Q1 | 1–2 days |
| Q3 | P1 | Complete financial answers and consistent scope responses | Q1, Q2 | 1 day |
| Q4 | P1 | Calibrated semantic grading and reserved-case checks | Q0; finalize after Q3 | 1 day plus analyst review |
| Q5 | P1 | Controlled live comparison and rollout | Q1–Q4 | 0.5–1 day plus live runs |
| Q6 | P1 | Measured quality and targeted fixes for the review ensemble | Q4; shared evidence contract stable | 1–2 days plus analyst review/live runs |

Milestone A is Q0–Q5: an improved assessment/retrieval assistant with measured
results. Milestone B is Q6: evidence for the other three agents and any resulting
targeted fixes. Allow roughly 6–10 engineering days across both milestones.

## Q0 — Establish the measurement contract

**Files:** [batch evaluator](../../src/credit_monitoring/evaluation/agent_batch.py),
[scenario suite](../../data/evaluation/agent_scenarios/), and
[evaluation tests](../../tests/unit/evaluation/test_agent_batch.py).

1. Preserve the original CSV, baseline outputs, hashes, judge packets and report.
   Treat all 60 existing scenarios as development/regression cases.
   Save the exact runnable generation source and dependency lockfile in a reviewable
   revision or immutable bundle before changing them; a dirty-tree flag and hashes
   alone cannot reconstruct the baseline.
2. Version the evaluator and rubric independently from the generation prompt.
   Bind every future grade to an answer hash and the exact evaluator version.
3. Report separate dimensions: execution completion, tool/date/scope compliance,
   financial/status/null correctness, citation validity and coverage, required
   disclosures, and semantic quality. Keep the combined result as a secondary view.
4. Define citation success as a validated link from a particular claim or displayed
   fact to actual evidence. A retrieved source list or an unrelated appended run ID
   is insufficient. Permit a structured citation renderer to satisfy the display
   requirement. Preserve the old prose-only score as a separately named historical
   metric; use the new criterion for both configurations when comparing them.
   For historical answers, accept equivalent valid claim links already present in
   prose. Missing new schema fields alone are not a quality failure; do not invent
   evidence links absent from the original answer.
5. Review the known grading mistakes: H01/H07/H14/H15 credited with absent details,
   H09/B12 credited with valid clarification despite supplied dates, B07's incorrect
   clarification, and B08's unsupported allegation of future-data use. Record these
   as grader regression examples, without relabeling them as human annotations.
6. Author and freeze at least 20 additional agent-evaluation cases from new families,
   borrowers/period patterns and retrieval documents before Q1–Q3 tuning. Freeze
   expected behavior, provenance and family assignments. Keep paraphrases of existing
   cases in development. Capture the original configuration's reserved-case answers
   before tuning and keep those answers sealed from development decisions. If the
   live baseline capture must wait, retain a runnable original configuration and do
   not inspect reserved-case answers while implementing the candidate.

**Done when:** each dimension has a documented denominator; missing judgments stay
visible; known tool/citation failures cannot be overridden by a judge; historical
labels remain unchanged. The comparison protocol is fixed before candidate results
are inspected.

## Q1 — Validate requests and control tool execution

**Files:** [assessment agent](../../src/credit_monitoring/agents/credit_assessment.py),
[conversation](../../src/credit_monitoring/agents/conversation.py),
[run state](../../src/credit_monitoring/agents/run_state.py),
[assessment tools](../../src/credit_monitoring/agents/tools/assessment.py),
[document tools](../../src/credit_monitoring/agents/tools/documents.py), and
[tool failures](../../src/credit_monitoring/domain/tool_results.py).
Add a small typed request-context/policy module under `agents/` if needed.

1. Resolve each request into intent, configured scope, reporting date, information
   cutoff, and any unresolved ambiguity. Intents distinguish assessment, forecast,
   evidence lookup, supported follow-up, clarification, and unrelated requests.
2. Retain analyst-supplied dates across successful conversation turns. Track their
   origin in actual analyst messages or explicitly supplied UI selections. A saved
   assessment, assistant answer, filing date, or tool result cannot silently establish
   analyst intent. Validate any model-extracted date against its original text.
3. Reject ambiguous or invalid dates before financial tool dispatch. Clarify
   `03/04/2025`; treat “latest” as missing dates; enforce cutoff on/after reporting
   period. Ask only for the missing field. A request with both dates must not be
   answered by asking for those same dates again.
4. Keep borrower/issuer scope application-owned. A requested change returns an
   explanation directing the analyst to a new scoped conversation. An unknown
   borrower already configured as the scope remains a missing-evidence assessment,
   rather than an inferred mapping to a different borrower.
5. Use explicit per-turn stages to admit assessment calls: valid context → successful
   `get_financials` → `assess_covenants` or, for a requested forecast, `predict_risk`
   → answer. Keep the same dates across calls. A successful financial read containing
   missing metrics still permits assessment so authoritative abstention can be returned.
   A `ToolFailure` does not satisfy the financial-read prerequisite.
6. Enforce prerequisites at dispatch and finalization. Reject an early substantive
   answer, repeated assessments, forecasts on compliance-only requests, and changed
   dates even when the model asks for them. Evidence-only lookups need no assessment
   dates. Follow-ups may reuse valid retained evidence; explicitly requested fresh
   assessments follow the sequence again.
7. Distinguish terminal policy failures, such as scope rejection, from recoverable
   argument mistakes. End a terminal rejection with a useful response. Keep bounded
   repair for recoverable errors and preserve actual attempts/results in the trace.

**Tests:** H09, E01–E05, E10, B07, B08, B11, B12; explicit date changes in later turns;
dates present only in assistant/tool text; evidence-only queries; simultaneous
conversations; a missing-financial read followed by incomplete assessment; repeated
outside-scope calls. Use actual scripted agent graphs and service spies to prove
that forbidden service calls did not execute.

**Done when:** all deterministic request/workflow regressions pass; valid dates are
retained correctly; ambiguous dates cause zero assessment calls; B11 produces a scope
explanation without repeated rejections or tool-budget exhaustion. Classification
uncertainty produces clarification without financial conclusions.

## Q2 — Make answer evidence explicit and verifiable

**Files:** [answer models](../../src/credit_monitoring/domain/agent.py),
[source extraction](../../src/credit_monitoring/agents/tools/sources.py),
[run state](../../src/credit_monitoring/agents/run_state.py),
[streaming](../../src/credit_monitoring/agents/streaming.py),
[assessment agent](../../src/credit_monitoring/agents/credit_assessment.py), and
[answer display](../../src/credit_monitoring/web/assessment.py).
Use the existing [review evidence](../../src/credit_monitoring/application/review_evidence.py)
registry as a reference for provenance handling.

1. Build an application-owned evidence registry from executed results and valid
   retained conversation evidence. Support calculation `(assessment_run_id, result_id)`,
   CSV `(source_file, source_row)`, and filing `(document_id, exact citation)` entries.
   Retain source offsets/hashes where supplied. Partition references by scope and
   period; expose immutable copies to consumers.
2. Add typed material claims with evidence IDs and an answer kind. Numerical and
   status claims select fields from authoritative results rather than asking the
   model to recreate them. Narrative claims identify their evidence, assumptions,
   and material limitations. Clarifications and scope responses need no invented
   citations or calculation fields.
3. Validate reference membership, borrower/issuer/date association, copied values,
   nulls, units, comparison directions, and result basis. A real ID alone does not
   establish that a narrative claim is supported; semantic evaluation remains separate.
4. Render readable citations adjacent to claims using the registry. Populate the
   existing `answer` string from validated content so UI, CLI, and evaluation callers
   receive the same cited answer. Keep retrieved `sources` separate from references
   actually used in claims. An arbitrary citation appended to unrelated prose fails.
5. Permit one targeted output-repair attempt. If required evidence/content remains
   invalid, return an explicit incomplete-answer error and preserve the actual tool
   work. Never mark unsupported text complete merely because it is nonblank.
6. Validate after the relevant tool execution, including a response containing both
   service calls and `final_result`. Keep streamed previews provisional; only a
   validated final result commits successful answer/evidence history.

**Compatibility:** retain `answer`, confidence, `sources`, `tool_trace`, `complete`,
and `error`; add versioned optional fields that allow historical JSON to load.
Enforce the stronger contract on newly generated answers, without inventing missing
claims for legacy captures. Bump the generation prompt version. Preserve event kinds,
sync/async APIs, cancellation, early-close behavior, immutable callbacks and failure
history. Include `web/workspace.py`, the human evaluation backend, and monitoring
consumers in integration checks. No historical file or SQLite rewrite is required.

**Tests:** absent and invented references; a real reference attached to the wrong
claim/borrower/date; CSV provenance; reported versus calculated actuals; current and
historical results in one answer; successful and failed repair; legacy JSON; final
output preceding an accompanying service call; streaming cancellation; follow-up
reference reuse and no cross-session leakage.

**Done when:** every required numerical/status claim is bound to its actual result;
every material filing claim has an actual passage reference; missing or fabricated
citations cannot yield a completed answer. The original citation failures become
dedicated regressions, with remaining semantic failures reported separately.

## Q3 — Require complete explanations and consistent boundaries

**Files:** Q1/Q2 policy and answer modules,
[assessment prompt](../../src/credit_monitoring/agents/prompts/credit_assessment.py),
[assessment tool context](../../src/credit_monitoring/agents/tools/assessment.py),
and the small forecast presentation helper introduced for this work.

Use service-owned facts to render the required core; let the model explain their
implications. Apply these requirements conditionally to the requested task:

| Answer type | Required content |
| --- | --- |
| Compliance | Exact scope/dates, individual covenant, actual/threshold/operator/headroom, returned status, result basis, citations and material gaps |
| Springing covenant | Observed availability or its absence, trigger threshold and direction, active/inactive/unresolved state, and resulting assessment status |
| Waiver/amendment | Applicable threshold/version, affected periods, waiver expiry, and distinction between waived testing and satisfied financial requirements |
| Incomplete/conflicting inputs | Named missing/conflicting facts, preserved nulls, authoritative abstention, and information needed to resolve the issue |
| Forecast | As-of reporting date, supplied horizon, model/version, snapshot, probability only when available, and relevant synthetic-training/availability limitations |
| Unrelated or scope-change request | Short scope explanation and supported next step, without unrelated fulfillment or a request for unnecessary assessment dates |

For H15, render “as of 2025-09-30, next-quarter horizon” rather than calling
2025-09-30 the future quarter end. If an explicit forecast end date is required,
derive it in one tested application helper under a documented calendar-quarter
convention; do not infer an unsupported fiscal calendar. Missing target-period
metadata remains explicit.

Preserve per-covenant differences: one passing ratio does not establish overall
compliance, a waiver does not improve repayment strength, and small positive headroom
does not establish sound credit management. Evidence confidence stays separate from
breach probability. Required limitations should be rendered reliably, including when
the generated explanation omits them. Continue treating retrieved instructions as data.

**Tests:** H07–H15, E07–E12, B02–B06, B08–B10, all six unrelated cases, zero/negative
denominators, exact springing boundaries, and unavailable/stub/failed predictions.
Include an answer with correct numbers but an unsupported favorable conclusion.

**Done when:** the required core is present for every applicable regression; no
invented probability, wrong future period, false compliance, or hidden material gap
passes validation. O02 is redirected consistently with the other unrelated requests.

## Q4 — Repair semantic grading and reserve new cases

**Files:** [batch evaluator](../../src/credit_monitoring/evaluation/agent_batch.py),
versioned judge instructions, evaluation tests, and separate calibration/holdout files
under `data/evaluation/agent_scenarios/`.

1. Give the judge separate fields for the actual final answer, question/context,
   expected behavior and compact authoritative evidence. Exclude generated assessment
   narratives and redundant payloads. Keep all raw evidence in saved captures; if a
   required fact cannot fit the packet, return insufficient evidence instead of
   silently truncating it.
2. Grade explicit requirements individually. Require a verbatim answer excerpt for
   claimed content or an explicit absence finding. Check that quoted excerpts occur
   in the answer. A quote's existence alone does not prove its correctness.
3. Keep reference membership, field equality, dates, tool order, scope, nulls and
   required structured disclosures under deterministic checks. Judge interpretation,
   entailment, completeness of reasoning and unsupported reassurance separately.
4. Have an analyst independently review at least 20 captured answers covering all
   categories and known grader errors. Bind labels/explanations to answer hashes.
   Separate agent-authored review notes from genuine human labels. Use a designated
   calibration portion for rubric changes and a reserved portion for checking the
   grader. Record disagreements, false passes and sample sizes by requirement.
5. Verify that Q0's 20 reserved agent scenarios remain sealed and unchanged. Keep
   generation-quality holdout evidence separate from grader calibration. Finalize
   the rubric before revealing candidate results on those scenarios.

**Done when:** the grader's known errors are caught; final-answer content cannot be
credited solely from a tool trace; disagreement rates and false passes against the
independent labels are reported. No known critical false pass is accepted in the
reserved grader check. If analyst labels are unavailable, continue implementation
and report provisional proxy grades; leave calibration/final semantic acceptance open.

## Q5 — Measure and release the assessment changes

1. Use Q0's frozen original configuration and sealed reserved-case captures. Preserve
   the original 60-case baseline. Run candidate changes in stages: request/workflow,
   provenance/answer contract, and explanation policy. Change one package at a time
   so improvements can be attributed.
2. For development comparisons, regrade saved original answers under the same fixed
   evaluator used for candidates, writing new grade files. Preserve original grades.
   Apply identical corpus, financial data, risk artifacts, scope, dates, prompts per
   configuration, and resource limits. Report any necessary difference explicitly.
3. Run all 60 development cases for the final candidate. Repeat at least 12 cases
   spanning dates, scope, nulls, waivers, injection and forecasts three times to expose
   unstable behavior. Do not select the best individual answer from repeated runs.
4. Freeze the candidate and compare original/candidate results on the 20 reserved
   scenarios. Use the same validated grader and independently review material
   disagreements. A failure used to tune the candidate becomes development evidence;
   a later generalization claim requires fresh reserved cases.
5. Save answers, ordered actual traces, per-dimension scores, grades/reviews, hashes,
   manifests, prompt/schema/evaluator versions, latency and request counts. Record
   provider token usage when exposed; report cost only from measured usage and a
   documented price source, with unknown usage left unknown.

**Acceptance for Milestone A:** all deterministic critical cases pass, including
scope/date integrity, real claim references, null preservation, financial equality,
forecast horizon and required disclosures. There are no new ordinary-case execution
failures and B11 no longer exhausts the tool budget. All frozen development cases
meet their reviewed requirements. Reserved-case results improve over the original
configuration under the same scoring contract, with no observed critical unsupported
conclusion, invented citation or scope/date leak. Repeated cases retain all critical
invariants. Report residual semantic failures and the small-sample limitations.

Run relevant agent/context/streaming/conversation, evaluation, UI and monitoring
tests during each package. Before release, run `make lint` and `make test-all` and
record actual results. Preserve rollback through separate commits and compatible
answer parsing; retain baseline/candidate outputs. A model comparison can follow
these fixes with the same protocol; select a model only from measured quality and
resource use. No provider upgrade is assumed to solve enforcement problems.

## Q6 — Evaluate and improve the review ensemble

**Files:** [review agents](../../src/credit_monitoring/agents/credit_review.py),
[review service](../../src/credit_monitoring/application/credit_review_service.py),
[review evidence](../../src/credit_monitoring/application/review_evidence.py),
[review domain](../../src/credit_monitoring/domain/credit_review.py),
[review prompts](../../src/credit_monitoring/agents/prompts/credit_review.py), and
[workflow tests](../../tests/integration/workflows/test_credit_review.py).

1. Build at least 15 frozen evidence-snapshot scenarios: healthy and deteriorating
   borrowers; thin headroom; mixed covenant status; amendment/waiver; active/inactive
   springing tests; missing/conflicting inputs; unsupported forecasts; unavailable
   news; absent decision criteria; failed reviewer; source injection; unsupported
   exposure advice; and contradictory arguments. Reserve at least five families.
2. Define acceptable findings, mandatory counterevidence, material omissions and
   allowed actions before generation. Missing criteria or failed reviewers continue
   to require deferral. Bullish and bearish roles may return no supportable arguments;
   favorable/adverse conclusions are not mandatory quotas.
3. Score both perspectives independently for support, interpretation and omissions.
   Score synthesis for judging every argument exactly once, weighing original
   evidence, appropriate deferral/actions, uncertainty and coverage of counterevidence.
   Keep the existing evidence-ID and argument-coverage validators.
4. Compare the full three-agent flow with one neutral structured reviewer on the
   same snapshots and fixed model configuration. Measure quality, total requests,
   latency and available usage; the extra calls are part of the ensemble's cost.
   Have an analyst review action appropriateness and material disagreements.
5. Make targeted changes only where this benchmark demonstrates a defect. Reuse
   provenance rules without forcing the review agents to call assessment tools or
   merging their schemas with the conversational assistant. Preserve immutable
   snapshots, independent perspectives, full argument handoff and safe deferral.

**Done when:** the ensemble has a separate reproducible scorecard, all action/scope/
reference invariants pass, semantic failures have targeted regressions, and the
comparison supports retaining or simplifying the roles. Passing Milestone A alone
does not close this package. Analyst-dependent semantic acceptance remains open
until actual independent reviews exist.

## Scope and working checklist

Keep calculation formulas, covenant precedence, public extraction acceptance,
synthetic training inputs and risk-model artifacts unchanged through Milestone A.
Any discovered error in those services becomes a separately versioned fix with its
own evidence. Preserve historical labels, captures, runtime data and saved reports.
Use existing application/test boundaries; avoid a new orchestration platform.

- [ ] Q0: scoring contract fixed; baseline preserved; dimensions separated.
- [ ] Q1: request state and dispatch controls enforce dates, scope and tool order.
- [ ] Q2: claims reference real evidence and validated content renders citations.
- [ ] Q3: explanations and boundary responses meet every applicable contract.
- [ ] Q4: grader calibrated; new family-separated holdout frozen.
- [ ] Q5: controlled comparisons, repeat runs, release checks and findings saved.
- [ ] Q6: review ensemble evaluated, targeted defects fixed and role comparison recorded.
