# Frozen comparison protocol, 9 November 2026

Original runnable source and lockfile: `original-configuration.tar.gz`, verified
against every generation source hash in the original capture. The checkpoint is
`ee650a5`. The bundle also contains the original financial, terms, model and retrieval
inputs. `original.json` binds all files and the bundle to SHA-256 hashes.

All original 60 scenarios are development cases. The 20 cases in `reserved.csv`
and their new retrieval documents were authored before any generation changes.
`reserved-manifest.json` freezes their families, requirements and provenance.
Reserved answers stay unopened during tuning. If original generation is delayed,
execute the preserved configuration before comparing the frozen candidate.

Use evaluator `agent-quality-v2` and semantic rubric `agent-semantic-v2` for both
configurations. Each case reports execution, workflow/date/scope, financial/status/
null, citation validity/coverage, required disclosures, and semantic quality.
Each deterministic dimension's denominator is its applicable assertions, including
failed executions. Semantic denominator is all selected cases; missing/insufficient
judgments remain missing. Aggregate case rates use all selected cases, never just
completed answers. No judge can override deterministic failures. The historical
prose-only citation check is a separate metric, excluded from the combined verdict.

Citations must connect a specific displayed fact or claim to executed evidence.
Historical prose links are accepted without requiring new schema fields. A retrieved
source list or unrelated appended ID is insufficient. Semantic entailment remains
separate from membership/equality checks. Original grades and labels never change.

Final candidate: all 60 development cases; 12 specified critical cases repeated
three times (H07,H08,H11,H12,H14,H15,E04,E08,B04,B07,B10,B11), with every repeat
reported. Then compare original and frozen candidate on all 20 reserved cases.
Do not tune on revealed reserved answers; retire any such family to development.
Use identical data/model artifacts, generation model, timeouts and tool budgets.
Save any configuration difference explicitly. Record latency, requests and measured
provider usage; unknown usage/cost remains unknown.

Grader calibration is separate from agent holdout: the known grader mistakes
H01/H07/H14/H15 (credited omissions), H09/B12 (unnecessary clarification), B07
(scope change), B08 (unsupported future-data accusation) are agent-authored grader
regressions, **not human labels**. At least 20 captured answers need independent
analyst review, split calibration/reserved before rubric changes. Bind all reviews
to answer hashes; report false passes/disagreement and denominator by requirement.
Until those exist all semantic grades are provisional and semantic release remains
open. Review-ensemble evaluation uses a distinct snapshot suite and scorecard.
