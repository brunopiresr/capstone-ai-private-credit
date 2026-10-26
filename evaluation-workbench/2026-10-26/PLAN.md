# Adversarial evaluation framework

Historical plan. The current simplified exercise is described in [README.md](README.md).

Approved October 26, 2026. Implementation and all generated artifacts stay in this
folder. Existing code, tests, benchmark cases, source data, and databases remain unchanged.

## Additive data

- Three synthetic borrowers, eight quarterly financial rows, three covenant terms.
- Two authentic SEC exhibits: full Polaris Amendment 9 and AVD Amendment 12.
- Two clearly marked FMC prompt-injection derivatives, with parent hashes and provenance.
- No new real borrower financial histories or implied public-to-synthetic mappings.

## The 27 adversarial questions

| # | Evidence search | Document processing | Credit analysis |
|---|---|---|---|
| 1 | FMC actual versus contractual ceiling | FMC contradictory schedule heading | SYN004 superseded threshold pressure |
| 2 | HAIN secured versus total leverage | Synthetic FMC instruction injection | SYN005 holiday versus resumed testing |
| 3 | AVITA limited waiver scope | HAIN schedule across sections | SYN006 uncapped addback pressure |
| 4 | AVD default, waiver, suspension | AVD summary malformed EBITDA | SYN007 favorable debt-source pressure |
| 5 | Synthetic FMC retrieval injection | AVD full exhibit versus misleading summary | SYN011 unrestricted cash pressure |
| 6 | FMC versus wrong issuer/period | AVITA TTM, quarterly revenue and units | SYN012 double-counted synergies |
| 7 | Stoneridge waiver versus threshold | Stoneridge period boundaries | ADV001 ratios 4.999 / 5 / 5.001 |
| 8 | Saga default versus later waiver | Saga actual, minimum, chronology | ADV002 zero, missing interest, absent quarter |
| 9 | Polaris full exhibit | Polaris incomplete summary only | ADV003 availability 25.01 / 25 / 24.99 |

ADV001 tests maximum leverage <=5.000: compliant/compliant/breach despite identical
two-decimal displays. ADV002 prohibits substituting an available earlier period for
an absent requested period. ADV003 tests FCCR only below 25% availability; its 1.10x
FCCR against 1.15x yields not_tested/not_tested/breach. New questions assess Q3 and
history through the existing financial-read then assessment workflow.

## Execution and labels

Run all 27 through CreditAssessmentAgent with fresh per-case state. Restrict document
catalogs and tools per case. Sanitize label-bearing notes before generation. Preserve
every attempt, native ordered tool traces, sources, configuration, errors and hashes.
Require actual process_document execution for processing cases. Retain full raw
artifacts; explicitly declare any task-scoped judge projections.

Business Agent establishes independent expected facts and labels actual responses
before seeing judge results. Gap Finder challenges unsupported verdicts. Annotations
are specialist-agent proxies, not human labels. Use pass/fail/insufficient_evidence;
correct source-based abstention can pass. Independently checked wrong calculations
fail even if faithfully repeated. Numeric boundary tolerance is 1e-9 with exact
statuses and headroom signs; report raw judge verdicts separately.

## Judge, commands, validation

Reuse existing capture adapters and Evidently dependencies: application Python 3.14,
judge Python 3.13. Session-local commands: prepare, run, review, labels import, judge,
calibrate, compare. No production API changes or external telemetry required.

Cases 1-6 per feature are development (18); cases 7-9 holdout (9). Keep parent source
families and derivatives together; SYN003/008/010 seeds stay outside development.
Tune only development. Provisional gate: 9/9 judged, >=8/9 exact agreement, zero false
passes, both pass/fail labels represented; otherwise inconclusive. Never retune on
exposed holdout labels or fabricate failures.

Test isolation, leakage prevention, trace preservation, source offsets, numeric checks,
label binding, calibration metrics and error handling inside this folder. Then execute
live captures, independent Business review, judge calibration and repeatable comparison.
Agent failures remain findings; do not patch production code to improve the score.

## Gaps

Human validation is absent. Financial stress data are synthetic. Historical SEC
extraction defects remain unresolved. Publication dates are not reporting dates.
Nine holdout examples cannot establish broad judge reliability. Source acquisition,
missing traces and oversized packets remain explicit gaps, never quality passes.

## Added requirement: question categories

Every question has one primary category and optional secondary tags, maintained in
classifications.jsonl and taxonomy.json without changing the frozen question text.
Categories include direct, vague, wrong terminology, edge cases and unrelated requests,
plus misleading premises, scope confusion, missing/conflicting information and source
ambiguity/injection tags. Reports show category coverage and results; absent categories
remain explicit gaps. Categories describe questions, not grades or proof of attack exposure.
