# Recorded results and remaining limits

These experiments measure different things. Counts below retain their original
dates and do not describe current application accuracy. No new paid evaluation
campaign was run for this documentation revision.

## Agent baseline and smoke

| Run | Result | What it supports |
| --- | --- | --- |
| [60-case baseline, 9 Nov 2026](../../data/evaluation/agent_scenarios/results/2026-11-09-baseline/REPORT.md) | 9 automatic passes, 50 failures, 1 execution error | Diagnostic behavior and grading findings for that captured configuration |
| [10-case smoke, 9 Nov 2026](../../data/evaluation/agent_scenarios/results/2026-11-09-poc-final/REPORT.md) | 10 completed; all deterministic checks passed; semantic grades unavailable | A narrow behavioral smoke, not 100% semantic accuracy |

The baseline's 59 completed answers included only 10 deterministic passes, while
the model judge labeled 54 answers as passing. That disagreement matters: 44 cases
failed exact prose citation checks, but many underlying calculations matched their
structured references. Passing calculations and failing attribution can coexist.
The judge also missed semantic failures. These labels are automated proxies,
not independent analyst judgments.

Inspect [baseline answers](../../data/evaluation/agent_scenarios/results/2026-11-09-baseline/results.csv),
[summary](../../data/evaluation/agent_scenarios/results/2026-11-09-baseline/summary.json),
and [manifest](../../data/evaluation/agent_scenarios/results/2026-11-09-baseline/manifest.json).
The [suite guide](../../data/evaluation/agent_scenarios/README.md) explains actual
tools, reference isolation, synthetic sources, and how cases are graded.

The smoke's summary classifies all ten cases as `needs_review`, because the
semantic judge was intentionally omitted. Its ten deterministic passes must not
be presented as ten fully graded passes. It uses selected cases and a different
configuration, so it is not a comparable improvement from 9/60 to 10/10.

Later agent changes are described in the
[implementation record](../../v2-plan/archive/quality/agent-quality-implementation.md).
Its November 12 observations still include invented historical cutoffs, ambiguous
dates interpreted without clarification, and unreliable waiver explanations.
Those captures are local `/tmp` evidence, not a portable final evaluation.

## Public-source extraction

The [18 October triage](../../v2-plan/archive/quality/public-sec-benchmark-triage.md)
records **37 failing comparisons out of 42 evaluable cases**, with five matches on
supported facts. It reports 215 matched, 39 mismatched, and 115 missing supported
fields; 117 populated assessment targets fall outside the extraction contract.
None of the five matches establishes complete assessment accuracy.

The failure count combines extraction errors, source gaps, name/projection
matching, and benchmark-contract limitations. It is not a current 88% model error
rate. All 29 selected Markdown sources were present in that run, which does not
prove they contained every needed exhibit.

| FMC-only experiment | Matched fields | Mismatched | Missing | Passing cases |
| --- | ---: | ---: | ---: | ---: |
| Frozen observations | 32 | 8 | 4 | 0/4 |
| v2.2, small model, complete documents | 31 | 10 | 3 | 0/4 |
| v2.3, GPT-4.1, complete documents | 32 | 0 | 12 | 0/4 |

The final experiment changes both model and input instructions, preventing causal
attribution to either one. Zero mismatched fields did not make its cases pass:
expanded metric names and agreement-wide disclosures still failed the comparator's
individual targets. Matching was not weakened to produce a passing score.

The historical [SQLite snapshot](../../data/evaluation/snapshots/sec/covenants.sqlite3)
and portable [FMC fixtures](../../tests/fixtures/public_sec_snapshot/README.md) remain
available. Full historical reports and original Markdown may require ignored local
artifacts. **Extraction quality acceptance remains open.** Check source clauses,
schedule completeness, metric identity, and actual-versus-limit distinctions before
using extracted facts in a review.

## Fifty-case exercise and judge agreement

The [50-case response report](../../evaluations/EVALUATION_REPORT.md) records
**35/50 heuristic passes** on 9 November 2026. The labels come from
[`label_response`](../../evaluations/run_and_label.py), which uses text markers,
special-case rules, and broad fallback checks. They are not independent human
ground truth or complete verification against tool evidence.

The [judge report](../../evaluations/JUDGE_VALIDATION_REPORT.md) records **27/50
agreement (54%)** on 10 November. The judge flagged all 15 heuristic failures,
but also rejected 23 heuristic passes. Its 100% recall is relative to those
heuristic labels. It does not establish calibrated defect detection. The judge
receives the question and answer rather than a complete independent evidence pack;
on provider errors the script assigns `bad`, further limiting interpretation.

The category table also shows only **2/8** heuristic passes on out-of-scope cases
and **3/8** on breaking cases. Broad claims of consistent refusal or robust
guardrails are unsupported by those results. Keep this exercise distinct from
the 60-case runner and its different evidence/checking contract.

## What is demonstrated, and what is still open

| Area | Demonstrated | Remaining limitation |
| --- | --- | --- |
| Software behavior | Calculation replay, workflows, controlled tool tests, V2 feedback tests, and offline CI | Scripted tests do not establish live answer quality |
| Credit methodology | Prepared-input arithmetic and explicit missing/waived/inactive states | Correct legal interpretation and complete source-driven review need human checking |
| AI review | Independent histories and complete argument handoff | Benefit over one reviewer has not been measured |
| ML | Synthetic training, held-apart borrowers/time windows, compatible runtime artifact | No real-world forecasting result or simple-rule comparison |
| Monitoring | Instrumented workflows, exported session identity, and V2 feedback | Hosted dashboard inspection and durable feedback delivery are separate |
| Business value | A reproducible analyst-to-manager demonstration | No measured time savings, decision improvement, or operational acceptance study |

See [capture details](../assets/README.md) for the current no-key demonstration,
[evaluation commands](README.md) for reproduction, and
[future proposals](../../v2-plan/README.md) for follow-up work.
