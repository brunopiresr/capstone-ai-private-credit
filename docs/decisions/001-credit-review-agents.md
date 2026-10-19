# Decision 001: independent credit perspectives with neutral synthesis

Date: 19 October 2026. Status: accepted and implemented at the application-service boundary.

## Context and agreed scope

The analyst needs two evidence-backed interpretations of one borrower's completed
calculation and ML results, followed by an explained recommendation. The user explicitly
selected independent reviews, a dedicated Recommendation agent, existing-exposure
decision support, and services ready for later UI integration. Both reviewers' full
reasoning must reach the Recommendation agent and remain in the analyst result.
Borrower comparison is a separate proposal and is not a prerequisite.

Implementation follows the accepted project cleanup: deterministic trends and verified
assessment outputs are public contracts, and entry points compose dependencies.
The feature consumes those outputs rather than reaching into repositories or rebuilding
ML features. Current usage and failure contracts are in [credit reviews](../credit_review.md).

## Decisions and rationale

| Decision | Rationale and consequence |
| --- | --- |
| Python-controlled fan-out/fan-in with PydanticAI | A fixed workflow runs two reviewers concurrently, then one synthesizer. Scheduling is explicit, bounded, and testable using the retained framework; no graph framework or autonomous delegator is needed. |
| Three dedicated roles | Bullish and bearish mandates focus attention on mitigants and downside. A separate Recommendation agent evaluates both against original evidence and analyst criteria. The existing question-answer agent and risk narrative service retain their responsibilities. |
| One borrower and one shared snapshot | Both reviewers see identical dates and evidence. No implicit borrower selection, borrower ranking, or comparison occurs. |
| Independent reviewer histories | Neither reviewer sees the other's conclusions before finishing. Different perspectives do not establish statistical independence, especially when using the same model. |
| Full structured analytical explanations | Each argument carries evidence references, rationale, implications, and assumptions. Counterevidence, gaps, and change-of-view conditions remain visible. No summary-only handoff can discard the support for a conclusion. |
| Explicit argument judgments in synthesis | The Recommendation agent assesses every supplied argument, keyed by perspective and ID, explaining acceptance, qualification, or rejection. Opinions are not averaged and agreement is not counted as independent proof. |
| Existing-assessment API plus convenience API | Existing callers can review a completed run without additional calculations or predictions. The convenience path obtains exactly one assessment before invoking the same review workflow. |
| Canonical JSON for nested assessment evidence | Frozen Pydantic models alone do not freeze nested dictionaries. Canonical JSON plus immutable tuples prevents cross-task mutation; parsed views are copies. The public snapshot retains source identifiers and reproducible values. |
| Generated narratives and annotations excluded | Reviews start from structured service outputs and original provenance. Raw source-value rows can carry benchmark annotations; approved financial fields and source hashes/file/row/citations are retained instead. |
| Agents have no function tools | Financial formulas, legal applicability, verification, and ML probabilities remain authoritative upstream. Agents produce interpretations and recommendations, not replacement calculations. |
| Reference validation with explicit limits | Schema and registry membership checks reject invented identifiers, missing rationales, and incomplete argument coverage. They cannot prove that a sentence is entailed by its cited evidence; live evaluation and analyst review remain necessary. |
| Advisory actions for existing exposures | Maintain, increase, reduce, review, and defer express directions without sizing or execution. Credit criteria and constraints are caller-supplied analyst context, not verified financial facts. |
| Missing criteria or failed reviewers force deferral | Analyses can remain useful while evidence, policy context, or a complete pair of perspectives is unavailable. Technical completion is distinct from an affirmative credit recommendation. |
| Preserve partial successful work | Reviewer or synthesizer failures return an incomplete result with a defer recommendation and available explanations. Failed structured verification blocks all agents. Parent cancellation propagates; incomplete model output is never committed as successful analysis. |
| Bounded execution | Default per-role timeout is 60 seconds with one output-validation retry and at most two model requests. Models remain configurable per role. Existing logging captures sanitized execution metadata; no new telemetry infrastructure is introduced. |
| Async typed progress callbacks | Future UI callers can show stage progress independently of existing chat events. Callback failures are reported without discarding completed analysis. |
| Injectable news with an unavailable default | The service defines a concrete extension point without claiming a news search occurred. Failed, empty, available, and unavailable states remain distinct. Explicit borrower mapping and publication provenance are required. |
| UTC day cutoff for news | Existing assessment APIs accept a date. Publication is eligible through that complete UTC date; unknown times and later records are excluded and disclosed. Reporting periods and event dates do not establish publication availability. |
| Services first, no review persistence | Typed results serialize with both analyses, rationale, evidence, and metadata. UI wiring, persistence, live news collection, sizing/pricing, and new-loan underwriting remain deferred. |

## Validation and remaining limits

Offline workflow tests exercise actual SQLite assessments and PydanticAI agents with
scripted models, including concurrent execution, complete rationale handoff, reference
validation, action restrictions, scope, source sanitization, failure handling, and JSON
round trips. Existing calculation, extraction, assessment, ML, and UI checks remain the
regression baseline. Offline success does not establish real-world credit decision
quality, live extraction accuracy, or model/judge calibration.

The optional news provider currently performs no network retrieval. Synthetic-trained
ML limitations remain explicit, and automatic extraction verification stays disabled
as agreed in the cleanup. Neither reviewer explanations nor synthesis overwrite the
assessment's authoritative fields. The credit analyst retains the decision.

Recorded verification on 19 October 2026: the complete root offline suite passed with
**582 passed and 6 opt-in live scenarios skipped**, including 34 credit-review workflow
regressions. `.venv/bin/ruff check .`, formatting checks for the changed Python files,
and `git diff --check` passed. Documentation links were checked and the three Python
usage examples parsed successfully. Tests ran in the existing project environment;
no credentialed live-model or news requests were made.
