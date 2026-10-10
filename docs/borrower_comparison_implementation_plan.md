# Borrower Comparison Implementation Plan

Status: Planned; not implemented.

## 1. Goal and scope

Support both prompts through the assessment agent:

- “Compare SYN002, SYN004 and SYN006.”
- “Compare all borrowers.”

Return a factual comparison of covenant results, headroom, data gaps and optional
predictions, using a shared reporting period and information cutoff.

Deliver through the agent and `notebooks/03-agents.ipynb`. Defer Streamlit
integration, company-name resolution, automated rankings, downloadable reports and
production-scale portfolio processing.

“All borrowers” means every distinct borrower ID in the configured financial
repository. It does not mean issuers in the document catalog, borrowers in training
datasets, or cases in the mocked portfolio UI.

## 2. Repository, service and result interfaces

### Borrower discovery

Add `FinancialRepository.list_borrower_ids() -> list[str]`, querying distinct IDs
from `quarterly_financials`, ordered by ID.

Do not filter this list to borrowers with data for the requested quarter: missing
reporting-period data must remain visible.

### Comparison service

Add `BorrowerComparisonService`, wrapping the configured `AssessmentService`, with:

```python
compare(
    *,
    period_end: date,
    information_cutoff: date,
    borrower_ids: list[str] | None = None,
    all_borrowers: bool = False,
    include_predictions: bool = False,
) -> BorrowerComparison
```

Behavior:

- Require exactly one selection mode: explicit IDs or `all_borrowers=True`.
- Resolve the selection once at invocation. Deduplicate explicit IDs while
  preserving order; use repository order for “all.”
- Require at least two distinct borrowers. Return a descriptive validation error
  for empty or single-borrower selections.
- Validate all explicit IDs and dates before creating assessment runs. Unknown IDs
  reject the request and identify which IDs need correction.
- Execute `AssessmentService.assess()` sequentially, once per selected borrower,
  with identical dates and `ml_enabled=include_predictions`.
- Reuse existing formulas, covenant resolution, verification, model configuration
  and persistence.
- Capture expected borrower-level operational failures, preserving successful
  assessments. Unexpected programming errors continue to propagate.
- Retain returned incomplete, waived, not-tested and unavailable states without
  converting them into operational failures.
- Never substitute another reporting period or silently omit a borrower.

### Typed result

Introduce `BorrowerComparison` containing:

- Selection mode, resolved borrower IDs, shared dates and prediction flag.
- Ordered entries containing `borrower_id` and exactly one of a `RiskAssessment`
  or a structured error.
- Deterministically computed selected, returned-assessment and failed counts.

A returned assessment may contain incomplete results; distinguish that from a
failed service call.

Reuse existing analytics persistence. Do not introduce comparison database tables
or migrations.

## 3. Agent integration and output

### Tool registration and scope

Add a `compare_borrowers` tool with the comparison service’s arguments.

Expose it only when an assessment service is configured and no fixed `borrower_id`
is supplied. Keep existing single-borrower tools and conversation restrictions
unchanged.

Ticker remains an independent document filter. It neither selects comparison
borrowers nor establishes borrower-to-issuer relationships.

### Prompt and conversation behavior

Update agent instructions to:

- Extract explicit borrower IDs from the analyst’s prompt or established
  conversation context.
- Use `all_borrowers=True` for “all”; let the service discover IDs rather than
  asking the model to enumerate them.
- Ask for missing or ambiguous reporting dates and information cutoffs. Retain
  explicit dates for follow-ups.
- Request forecasts only when the analyst asks for predictions.
- Allow unrestricted comparison conversations to add or remove borrower IDs
  through subsequent prompts.
- Resolve “all” again on each new comparison invocation, because repository
  membership may change.
- Reuse previous results for explanation-only follow-ups without rerunning
  assessments.
- Require a new unrestricted conversation when a fixed single-borrower
  conversation requests a comparison.

### Structured tool output

Serialize a compact projection of each returned assessment containing current
covenant results, verification, issues, provenance, run IDs and prediction
metadata. Include the feature snapshot ID when available.

Omit historical result arrays, feature vectors and generated assessment narratives
from this projection. Preserve the full typed assessments in the service result.

Aggregate document citations through the existing tool-result `sources` mechanism.
Keep CSV provenance within result data.

Preserve `AgentAnswer`; structured comparison output remains available through its
tool trace.

### Analyst-facing answer

Return:

1. Reporting period, information cutoff and coverage counts.
2. A table with one row per borrower and current covenant: borrower ID, covenant
   type, actual, threshold/operator, unit, headroom and compliance.
3. An explicit row or explanation for borrowers without usable results.
4. A separate prediction table when requested, including model/version, horizon,
   probability and availability.
5. A short explanation of breaches, limited headroom, missing inputs and
   differences in calculation basis, with source and assessment/result references.

Do not merge distinct covenants, compare incompatible monetary units, treat net
and total leverage as interchangeable, or invent a universal ranking. Preserve
existing qualifications concerning synthetic models and unknown source
availability.

## 4. Notebook, documentation and validation

Add named-borrower and “all borrowers” examples to the agents notebook, plus an
optional unrestricted interactive comparison conversation. Keep interactive cells
disabled during Run All.

Update usage documentation to explain selection modes, required dates, output,
persistence side effects and the distinction between live assessment results and
mocked benchmark labels.

Implement meaningful tests covering:

- Repository discovery: distinct IDs, stable ordering and empty repositories.
- Named comparisons: ordering, duplicates, unknown IDs and date validation.
- “All”: all 12 bundled borrowers included, including borrowers without
  requested-period data.
- Result parity with independent assessments, ignoring generated IDs and
  timestamps.
- One assessment call per borrower; no calls after selection validation fails.
- Partial operational failures, missing financials, unresolved terms, waivers and
  inactive tests.
- Disabled, stub, successful, unavailable and failed predictions.
- Compact output preserving provenance and excluding benchmark notes and outcome
  labels.
- Tool registration, fixed-scope enforcement and independent ticker scope.
- Clarification turns, remembered selections/dates and explanation-only follow-ups.
- Notebook schema, syntax and nonblocking interactive defaults.

Use temporary databases and mocked model responses for automated tests. Run
affected repository, assessment, agent, conversation and notebook tests, then the
full pytest suite and Ruff checks.

## 5. Implementation order and acceptance

Implement repository discovery and typed results first, then the comparison
service, tool integration and prompt changes, followed by notebook examples,
documentation and regression checks. Preserve existing working-tree changes.

Accept the feature when a single prompt can compare three named borrowers or all
loaded borrowers, every selected borrower is accounted for, calculations match
existing assessment behavior, and the answer exposes missing data and provenance.

The first release targets the bundled POC dataset. Larger portfolios, pagination,
background execution and exports remain separate follow-up work.
