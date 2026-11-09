# POC live smoke — 9 November 2026

All 10 cases completed and passed their deterministic checks. No semantic judge was run;
the saved `needs_review` labels mean ungraded, not failed. This is a development smoke,
not an accuracy or generalization estimate.

Generation revision: `d466321c50934cd0e17e90a2e272518de81abcf5`. Prompt: `credit-assessment-agent-v8-poc`.
Model: `openai-responses:gpt-4o-mini`. Evaluator: `agent-quality-v2`.
Source hashes match the saved manifest. The dirty flag reflects the new output directory.

| Case | Actual tools | Deterministic checks | Requests |
| --- | --- | ---: | ---: |
| H01 | get_financials, assess_covenants | 13/13 | 3 |
| H07 | get_financials, assess_covenants | 13/13 | 3 |
| H08 | get_financials, assess_covenants | 14/14 | 3 |
| H11 | get_financials, assess_covenants | 14/14 | 3 |
| H15 | get_financials, predict_risk | 11/11 | 3 |
| H16 | search_evidence | 6/6 | 2 |
| E04 | none (local response) | 3/3 | 0 |
| B10 | search_evidence | 6/6 | 2 |
| B11 | none (local response) | 4/4 | 0 |
| B12 | get_financials, assess_covenants | 9/9 | 3 |

B12 (unknown configured borrower) executed `get_financials` then `assess_covenants`
and returned the service’s missing-evidence result. Scope switching and ambiguous dates
executed no tools. Filing text and financial values are rendered from actual evidence.

Answers, ordered traces, checks and provider usage are in `cases/`. Input/runtime
copies remain local under the existing ignore rules. Full comparisons, repeat runs,
reserved-case evaluation, independent calibration and ensemble benchmarking are deferred
under the requested POC scope.
