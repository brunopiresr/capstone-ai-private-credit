# Capstone rubric review and open-issue plan

Reviewed 8 November 2026 against the rubric supplied in chat. Repository baseline:
`353e5a6`, including the uncommitted application/test changes present during review.
Those changes were preserved. The working tree also changed concurrently during
the review; the candidate R01 fix and targeted retest are recorded below. This
review adds a plan; implementation acceptance tasks below remain open.

**The project already covers most of the core rubric. Prioritize a reliable test
command, accessible evaluation evidence, monitoring dashboard instructions, and a
clean-checkout rehearsal.** Containerization, deployment, and additional features
can follow after that baseline is demonstrated.

## Rubric coverage

These are conservative evidence-based estimates, not an official scorer result.
Points for having tests/evaluation do not establish that all tests or quality gates
pass. Full-suite acceptance remains open after the observed failure; see R01 for
the concurrent candidate fix and targeted retest.

| Criterion | Estimate | Existing evidence | Remaining work |
| --- | ---: | --- | --- |
| Problem description | 2/2 | [README](../../README.md) explains covenant review, headroom, evidence, users, and reports. | Make the manual-review pain and intended benefit explicit in the submission overview. |
| Knowledge base and retrieval | 1/2 | [Document guide](../guides/document_processing.md), local SEC Markdown, [lexical search](../../src/credit_monitoring/retrieval/lexical/sec.py), and [retrieval tests](../../tests/unit/retrieval/test_sec_search.py). | No documented quantitative comparison establishes the best search configuration. See R05. |
| Agents and LLM | 3/3 | [Document tools](../../src/credit_monitoring/agents/tools/documents.py) expose `list_documents`, `get_document_extraction`, `search_evidence`, and `process_document`; [assessment tools](../../src/credit_monitoring/agents/tools/assessment.py) expose `get_financials`, `assess_covenants`, and `predict_risk`. The guide describes scopes and behavior. | Preserve a representative actual tool trace in the submission evidence. Multiple reviewer agents alone are not the evidence for this criterion. |
| Code organization | 2/2 | Installable `src/credit_monitoring` package, separated services/domain/storage/UI, [architecture](architecture.md), scripts, and tests. | Add a concise directory map to the submission overview. |
| Testing | 2/2 | Unit/integration tests and [live judge scenarios](../../homework/agent-tests/README.md), with commands linked through [evaluation](../homework/evaluation.md). | Fix the observed full-suite failure; make offline checks and opt-in live judging easy to distinguish. See R01/R02. |
| Evaluation | 2/3 | Ground-truth cases, [27-case exercise](../../homework/evaluation/2026-10-26/README.md), structured judging, and [Evidently runner](../homework/llm_judges.md). [FMC experiments](../reviews/public_sec_benchmark_triage.md#follow-up-experiments-and-deferred-scope) informed prompt/input changes. | Historical tuning may justify the third point, but the experiments changed multiple variables and their full artifacts are ignored. Publish a clear comparison and selection decision. See R02/R06. |
| Monitoring | 1/2 | [Logfire setup](../guides/logfire_setup.md), SDK instrumentation, validation script, and [user-event demo](../../homework/monitoring/README.md). | Dashboard access, displayed logs, and a reproducible walkthrough are not demonstrated in the current guide; dashboards are listed as deferred. See R03. |
| Reproducibility | 2/2 | Locked uv setup, Python requirement, app commands, `.env.example`, [bundled data/model](../../data/README.md), and tests. | Verify from a fresh checkout without ignored caches or runtime files, including the separate Python 3.13 judge setup. See R04. |
| **Base total** | **15/18** | **14 points from the core categories highlighted in the supplied rubric, plus 1 retrieval point.** | **R03 brings the core estimate to 15; R06 to 16. R05 can bring the overall base estimate to 18.** |

Bonus evidence is separate from the base score:

| Bonus | Current evidence / conservative estimate | Action |
| --- | --- | --- |
| Hand-crafted ground truth | Demo cases are described as hand-authored, but authorship of the main datasets is not established as human rather than agent-generated. **Unclaimed: 0/2.** | R08: document actual provenance; human verification of generated cases is distinct from human authorship. |
| Manual ground-truth evaluation | A human rating app exists. The dated exercise explicitly calls its historical Business Agent labels specialist-agent reviews. **Unclaimed: 0/2.** | R08: complete and publish a genuine human review. |
| User feedback | Rating/comment collection is implemented and documented in the monitoring and human-evaluation apps. **1/1**, scoped to those apps. | Preserve a sanitized example; broader main-workspace coverage is optional. |
| Logs to evaluation dataset | Candidate signals are documented, but no automatic export-to-evaluation workflow was found. **0/2.** | R09. |
| Containerization / Compose | Dockerfile and Compose launch the main app with locked dependencies, bundled inputs/model, health checks, and persistent volumes. **1/1 and 2/2.** | R11 completed 10 November 2026; [container verification](../guides/docker.md#recorded-verification-10-november-2026) records build, page, model, and persistence checks. |
| Makefile / dependency environment | Make targets, uv, virtual environments, and both lockfiles. **1/1 and 1/1.** | Preserve and verify through R04. |
| CI/CD | No tracked `.github/workflows` configuration or other pipeline definition found. **0/2.** | R10, optional but useful. |
| Agent UI | Streamlit workspace and documented launch command. **1/1.** | Verify through R04. |
| Cloud deployment | No reproducible deployment evidence found. **0/2.** | R12, optional. |

The conservative bonus estimate is **7 points**. Human-authorship and manual-review
points should remain unclaimed until their specific evidence exists.

## Checks performed during this review

| Check | Observed result |
| --- | --- |
| `make lint` | Passed. |
| Initial `make test-all` | Stopped in the app suite: **938 passed, 1 failed** out of 939. Its dependent homework target was not reached. A full rerun after the concurrent R01 fix is pending. |
| `make test-homework` run separately | **93 passed, 6 skipped**. The skipped scenarios require opt-in live model/judge execution. |
| `make test-judges` | **18 passed** in the isolated Python 3.13 environment, with dependency deprecation warnings. |
| `.venv/bin/python scripts/validate_logfire.py` | Passed offline validation with 1,032 in-memory spans and five questions. This does not verify cloud display. |
| Judge runner dry run on `data/evaluation/judges/demo_cases.jsonl` | Validated nine cases covering extraction, retrieval, and answer judges; no LLM quality measurement. |
| Document-resume test alone | Initially passed at default logging and failed with `--log-level=INFO`. After a concurrent edit added `caplog.clear()`, the INFO-level check passed: **1 passed**. See R01. |

Review verification used the existing environments. Live models, SEC downloads,
cloud dashboard display, and a fresh dependency installation were not exercised.
The isolated uv commands needed access to a cache outside the sandbox; that was an
environment permission issue, separate from the test failure.

## First milestone: demonstrate the passing baseline

Complete R01–R04 first. They strengthen the existing application and evidence rather
than requiring a new architecture. Effort estimates are active work and exclude
waiting for credentials, provider availability, or reviewer time.

### R01 — Fix the logging-dependent document-resume test

**Priority:** P0. **Effort:** 1–2 hours. **Dependency:** none.

The failing test is
[`test_failed_sections_resume_without_publishing_partial_facts`](../../tests/unit/covenants/test_document_processing.py).
It asserts that section 1 was not extracted during the resumed call.
Its `caplog.text` also contains section 1's valid extraction during the original
failed call when INFO logging is already enabled. Earlier state, completed-section,
and model-call-count assertions pass; the observed failure does not demonstrate
that cached sections were re-extracted.

**Current status:** a concurrent workspace edit, outside this review's documentation
changes, added `caplog.clear()` before resuming. The targeted INFO-level test now
passes (1 passed in 0.44 seconds), and lint passes. Full-suite verification remains
pending, so R01 stays open for acceptance.

- Retain the reset that scopes captured logs to the resumed call. Preserve the
  state and model-call-count assertions.
- Check whether app/bootstrap tests leave process-wide logging configuration behind
  and restore it where needed.
- Validate the targeted test at default and INFO levels, then run `make test-all`
  and `make lint` once the change is complete.

**Done when:** both targeted runs and the complete documented offline command pass;
six opt-in live skips are explained. Keep this open until the full run is green.

### R02 — Publish a compact submission and evaluation evidence guide

**Priority:** P0. **Effort:** 0.5–1 day. **Dependency:** R01 for final test evidence;
live credentials for a current answer-quality run.

Use the existing [evaluation guide](../homework/evaluation.md) as the entry point.
Add a short tracked submission guide and a dated evaluation report, both directly
linked from the root README. Proposed locations: `docs/project/submission_evidence.md`
and `docs/reviews/agent_evaluation_results.md`.

- Map every rubric item to a command, implementation, and observed result. State
  who uses the app, what makes manual covenant review difficult, and what the POC
  is expected to improve. Include a short source/test/data directory map.
- Pick the existing 27-case workbench as the main answer-quality experiment.
  Explain that the 60 general tasks, 42 public extraction cases, nine judge demos,
  and three live scenarios serve different purposes and have different denominators.
- Capture current answers and ordered tool traces, attach evaluator-only references
  after generation, run the judge, and retain failures and unavailable cases.
  Report pass/fail/insufficient-evidence counts, coverage, model/prompt versions,
  source and response hashes, latency, and available usage/cost.
- Publish a small sanitized set of actual inputs, outputs, and judgments in a
  tracked location such as `data/evaluation/results/`. Leave sensitive or bulky
  raw runs ignored and document where authorized reviewers can obtain them.
- Preserve the historical baseline of **19 fail, 5 pass, 3 insufficient evidence**
  as historical. The prepared sources changed afterward; rerun a baseline on the
  same source snapshot before comparing a candidate configuration.
- Treat exposed development/holdout results honestly. Existing holdout cases have
  already appeared in historical runs and the rating UI; use a fresh held-back set
  for any claim of a previously unseen final evaluation.

**Done when:** a reviewer can follow README links, run unit and judge checks, run a
ground-truth evaluation, and inspect a dated result without access to ignored local
files. Quality failures must remain visible; a functioning judge is not a quality pass.

### R03 — Demonstrate logs in the monitoring dashboard

**Priority:** P0. **Effort:** 2–4 hours. **Dependency:** access to a Logfire project.

Extend [Logfire setup](../guides/logfire_setup.md) using the existing hosted Logfire
views. A custom dashboard is unnecessary if the supplied views clearly display
the application's collected logs and traces.

- Explain the path from app/service events and native model/tool instrumentation
  through SDK export to the project view. Distinguish logging level from content capture.
- Document how to open the project UI, obtain access, choose the environment and
  service, find a session/trace, and inspect a tool call, error, latency, and usage.
  Provide a shareable project/view URL if permitted, or explicit navigation steps
  plus a sanitized screenshot. Never publish send credentials.
- Run `scripts/validate_logfire.py --live`, then inspect its IDs in the UI. This
  command tests telemetry transport with scripted models, so it can demonstrate
  dashboard access without paying for model generation.
- Show one actual app interaction and how its events relate to the displayed logs.
  Apply the documented token aggregation rules and distinguish synthetic validator
  usage from actual provider usage.

**Done when:** an authorized reviewer can launch the documented workflow and find
its collected logs in a visible monitoring view. Record the date and evidence.
This resolves the conservative monitoring estimate from 1 to 2 points.

### R04 — Rehearse reproduction from a fresh checkout

**Priority:** P0. **Effort:** 2–4 hours. **Dependency:** R01; package-download access.

- Use an isolated fresh checkout with no `.env`, downloaded SEC cache, or runtime
  files. Follow README commands verbatim: install Python 3.14/uv, locked sync,
  `make preview`, and a bundled borrower assessment.
- Confirm saved results, a restart, and bundled ML artifact loading. Verify the
  documented CLI example and offline checks against bundled data.
- Follow the optional agent/judge instructions separately, including the locked
  Python 3.13 environment. Document external credentials and source preparation
  needed for each live path. Keep the offline demo usable without them.
- Record commands, versions, expected outputs, and any fixes in the submission
  guide. Add troubleshooting only for issues actually encountered.
- Run the module 5 project scorer if its tool/command is available, and reconcile
  its findings with this evidence table. No scorer implementation or invocation
  was identified in this repository, so the estimates above are a manual audit.

**Done when:** a fresh checkout reproduces the app and offline checks, and optional
live/evaluation paths have complete prerequisites. R01–R04 are the stopping point
for the first milestone: an estimated **15 core points, 16 including retrieval**,
with the existing bonus evidence separate.

## Second milestone: improve measured quality and evidence

### R05 — Evaluate retrieval and select the measured winner

**Priority:** P1. **Effort:** 0.5–1 day. **Dependency:** frozen corpus and reviewed references.

Reuse source-anchored search cases and prepared Markdown. Add a small retrieval
runner under `scripts/` or the evaluation package, with documented commands.

- Freeze expected relevant document IDs and supporting passage offsets. Use enough
  cross-issuer, wrong-period, similar-metric, waiver, and incomplete-summary cases
  to exercise the actual corpus. Preserve family splits and reserve new cases if needed.
- Compare the current lexical configuration with a small set of lexical/chunking
  alternatives on identical inputs. Measure hit rate/recall at k and MRR, scope
  errors, latency, and corpus coverage; define how overlapping passages count.
- Tune on development cases, select the best result, and confirm it on reserved
  cases. Document tradeoffs and adopt the winner, including retaining the current
  implementation if it wins. Vector or hybrid infrastructure is optional.

**Done when:** a repeatable report supports the chosen search configuration.
Controlled ranking unit tests and an LLM relevance opinion alone do not establish
retrieval recall. Potential gain: **1 base point**.

### R06 — Demonstrate evaluation-driven tuning

**Priority:** P1. **Effort:** 0.5–1 day plus live runs. **Dependency:** R02 baseline;
R05 only if retrieval is the chosen tuning variable.

Reuse the workbench and capture/judge adapters. Choose one material variable, such
as the answer prompt, tool budget, extraction prompt, or model. Change one variable
at a time; keep corpus, cases, evidence budget, and judging configuration fixed.

Compare the baseline and candidate on development cases, including failed tool
use, unsupported conclusions, omissions, citation support, coverage, latency, and
cost. Record the actual parameter/prompt diff and selection decision. Use genuine
reserved cases for final validation; small samples require modest claims. Preserve
both configurations and a replay command. A negative experiment is useful evidence;
do not adopt a worse configuration merely to demonstrate a change.

**Done when:** the report connects evaluation findings to an explicit tuning and
selection decision. Explain the confounding in historical FMC model/prompt runs.
Potential gain: **1 base point**, bringing the core estimate to 16.

### R07 — Close the most important domain-quality findings

**Priority:** P1 for the narrow demonstration; broader extraction repair can follow.
**Effort:** scope after selecting a worked case.

The [4 November audit](../reviews/credit_risk_documentation_audit_2026-11-04.md)
identifies quality issues distinct from rubric coverage. Carry them forward:

| Open finding | Concrete action and acceptance evidence |
| --- | --- |
| Exposure recommendations exceed the demonstrated credit evidence | Define monitoring actions, or require an explicit credit-context package before exposure advice. Verify appropriate deferral on missing evidence. |
| No complete source-to-assessment example | Publish one source clause → analyst-approved terms/inputs → calculation → exception → manager disposition case. Keep public issuers separate from fictional borrowers; identify synthetic material explicitly. |
| Public extraction acceptance remains open | Group the historical 37/42 failures by extraction, missing source, matching, and unsupported assessment target. Preserve the frozen benchmark. Improve selected supported facts in isolated runs and report the residual failures and coverage. |
| Credit methodology is hard to find | Add a concise methodology page and worked arithmetic covering measurement periods, addback/cash caps, amendment/waiver treatment, provenance, and why a relaxed limit is not improved repayment strength. |
| Synthetic ML value is unproven | Compare against a simple headroom/trend rule on separated synthetic histories. Keep the simulation status visible; decide whether Off should be the default. |
| Benefit of three reviewers is unmeasured | Compare one structured reviewer with the three-agent review on the same evidence; measure supported findings, missed risks, action appropriateness, latency, and cost. |
| POC success lacks an acceptance result | Publish a small independently checked scorecard covering compliance, deterioration, amendment/waiver, springing boundaries, and missing/conflicting inputs, plus corrections and preparation time where measured. |

The historical extraction failures are case-comparison results, not a current
88% model error rate. The prior triage records deferred catalog/benchmark changes;
preserve that baseline and make any later corrections explicitly versioned. Do not
weaken matching, project agreement-wide compliance onto individual covenants, or
feed expected answers to generation to obtain a passing result.

## Optional bonus work

| ID | Priority / effort | Work and definition of done | Dependencies / possible points |
| --- | --- | --- | --- |
| R08 | P2 / 0.5–1 day plus human review | Record dataset authorship and preparation history. Where human authorship cannot be established, create a small genuinely human-authored source-backed set. Have a human rate actual captured answers against references using the existing app; retain response hashes, reasons, reviewer/date, and aggregate results. Keep agent-proxy labels distinct. | Human author/reviewer; R02. Up to **2 authorship + 2 manual-evaluation** points. |
| R09 | P2 / 1–2 days | Add an export command selecting negative feedback, corrections, or retries from logs, joining each interaction to its actual answer/tool/evidence snapshot, deduplicating it, and emitting review candidates. Have reviewers supply expected answers, then pass approved records to the existing evaluation runner. Demonstrate the full export → review → evaluation path on captured events. Never use the original answer or a low rating as the expected answer. | R02/R03; access to exported events and complete captured evidence. Up to **2 points**. |
| R10 | P2 / 0.5 day | Add CI for locked Python 3.14 lint/app/homework checks and a separate Python 3.13 judge job. Run offline checks on pull requests with no secrets; make any paid live evaluation an explicit opt-in job. Include a documented successful CI run and failure behavior. | R01/R04. Up to **2 points**. |
| R11 | Completed 10 November 2026 | Added an app image and Compose configuration with the uv lockfile, bundled data/model, health check, and persistent runtime/SEC-cache volumes. Verified build/start, six pages, bundled ML assessment, and saved data after container recreation. [Commands and results](../guides/docker.md). | **1 container + 2 full-system Compose** points supported for the main app. The isolated homework judge environment remains separate. |
| R12 | P3 / estimate after hosting choice | Prepare hosting configuration and a reviewable deployment, define persistence/access and required credentials, then publish only with the user's authorization for the selected external deployment. Verify the hosted assessment and document the URL and reproduction steps. | Hosting choice/account; R04 and any required deployment packaging. Up to **2 points**. |

## Delivery order and acceptance

1. **Restore reliable verification:** R01; record the green full-suite result.
2. **Make the current submission reviewable:** R02/R03/R04, with a direct README
   evidence link and the dashboard walkthrough. Reassess the rubric estimate here.
3. **Choose focused improvements:** R05/R06 for measurable retrieval and tuning;
   the methodology/worked-case portion of R07 for analytical credibility.
4. **Select bonuses deliberately:** genuine human review and CI are useful next
   candidates. Logs-to-evaluation, containers, and cloud hosting can remain future work.

Final acceptance evidence should identify the revision, corpus/configuration
versions, commands, observed results, remaining quality failures, and the rubric
items actually demonstrated. Update this plan's checkboxes only after that evidence
exists:

- [ ] R01: full offline checks pass, including INFO-level resume behavior.
- [ ] R02: README-linked submission guide and current evaluation report are reviewable.
- [ ] R03: exported logs are visible through documented dashboard access.
- [ ] R04: fresh-checkout app, data, and check commands reproduce successfully.
- [ ] R05/R06, if selected: measured retrieval choice and evaluation-driven tuning.
- [ ] R07, if selected: methodology, complete worked case, and explicit acceptance findings.
- [ ] Selected bonuses have evidence meeting their individual requirements.
