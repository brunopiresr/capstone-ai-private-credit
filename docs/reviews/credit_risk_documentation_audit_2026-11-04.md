# Credit-risk documentation audit — 4 November 2026

**Verdict: this is a credible covenant-monitoring workflow POC. The documentation
does not yet demonstrate that it produces better credit analysis or better
decisions.** The main weakness is the gap between completing the workflow and
establishing analytical quality.

The review covered the current [root README](../../README.md),
[documentation index](../README.md), linked operating guides, and relevant scope,
evaluation, and implementation records. The audit was read-only and did not rerun
live evaluations. The findings assess the project as a POC.

1. **High — Exposure recommendations go beyond the documented evidence.**

   The agents can recommend **maintain, increase, or reduce exposure**. Yet the
   documented assessment centres on covenant compliance, headroom, trends, and a
   synthetic forecast. There is no documented minimum evidence requirement covering
   repayment capacity, liquidity runway, maturities, security, ranking, or portfolio
   constraints. See the [action definitions](../guides/credit_review.md#results-and-boundaries).

   A borrower can comply with its covenants and still be a poor credit. Calling
   recommendations “advisory” and omitting sizing does not solve the evidence
   problem. Repayment and refinancing capacity are central credit considerations,
   as reflected in the
   [OCC/FDIC lending principles](https://occ.treas.gov/news-issuances/news-releases/2025/nr-ia-2025-119.html).

   **For this POC:** use monitoring actions—routine review, watchlist, escalate,
   request information—or require a small, explicit credit-context package before
   permitting exposure recommendations.

2. **High — The source-to-assessment business case remains incomplete.**

   The walkthrough explicitly says extraction does **not** update financial inputs
   or contractual calculation rules. The assessment guide requires explicit
   bindings and established rules, while legal precedence remains unresolved.
   Those are sensible boundaries. See the
   [document workflow](../guides/ui_preview.md#manage-documents-and-data) and
   [calculation bindings](../guides/ml_early_warning.md#consume-stored-document-covenants).

   However, this leaves two adjacent demonstrations: calculations on prepared
   synthetic data, and extraction from real public filings. Their coexistence does
   not establish reliable document-driven monitoring.

   **For this POC:** demonstrate one complete case from source clause through
   analyst-approved terms and inputs to calculation, exception, and manager
   disposition. Manual approval is entirely acceptable. Clearly distinguish
   independently recalculated results from comparisons using source-reported ratios.

3. **High — “Known quality gaps” understates the recorded quality problem.**

   The README uses that phrase, but the linked historical benchmark records
   **37 failing cases out of 42 evaluable cases**, with extraction-quality acceptance
   still open. The later FMC experiment still passes none of its four cases,
   although the nature of the failures changes. See the
   [README caveat](../../README.md#scope-and-limits) and
   [benchmark findings](public_sec_benchmark_triage.md).

   These are historical case-level results involving extraction, source coverage,
   and matching limitations. They do **not** establish a current 88% extraction
   error rate. They do establish that successful processing is insufficient
   evidence of usable output.

   **For this POC:** say plainly that extraction quality acceptance remains open.
   Identify which facts require source checking before use. A documented human
   check is sufficient; adding another LLM verifier would itself need validation.

4. **High — The credit methodology is too thin in the main guides.**

   The guides explain how to run assessments, but provide little explanation of how
   to interpret them. Important economic definitions—including different calculation
   contracts, addback caps, cash netting, and interest bases—sit in the
   [dataset integration document](../project/dataset_expansion_plan.md#import-and-economic-definitions).

   A risk manager needs clear answers to questions such as:

   - Is EBITDA quarterly, annualised, or trailing twelve months?
   - Which contractual adjustments are included?
   - Did headroom improve through stronger performance or a relaxed threshold?
   - Is the result calculated, borrower-reported, waived, inactive, or unresolved?

   **For this POC:** add one short methodology page and a worked example. Show
   explicitly that increased headroom after covenant relaxation does not demonstrate
   improved repayment strength. Reproducible arithmetic alone cannot establish that
   the selected contractual definition is correct.

5. **Medium — Enabling synthetic ML by default gives it excessive prominence.**

   The main workspace starts with Logistic Regression enabled. The guide properly
   discloses synthetic training and defines the target as next-quarter covenant
   breach. See the
   [default behaviour](../guides/ml_early_warning.md#working-streamlit-review) and
   [training and target](../guides/ml_early_warning.md#generate-and-train-the-synthetic-baseline).

   The challenge is its incremental value: does it outperform a simple rule using
   low headroom, deteriorating EBITDA, and upcoming threshold changes? The
   documentation does not establish that. Its target also differs materially from
   payment default, loss, or refinancing failure.

   **For this POC:** default ML to Off, or make its simulation status unmistakable
   wherever a probability appears. Compare it with a simple monitoring rule before
   treating it as a useful early-warning component.

6. **Medium — The three-agent design has an architectural rationale, but
   insufficient evidence of analytical benefit.**

   Bullish and bearish perspectives can encourage useful challenge. The decision
   record correctly acknowledges that separate histories do not establish
   statistical independence. That is good discipline. See the
   [design rationale](../project/decisions/001-credit-review-agents.md#decisions-and-rationale).

   The unanswered question is whether three agents identify more material risks,
   make fewer unsupported claims, or improve analyst decisions compared with one
   structured reviewer covering risks, mitigants, and missing information.

   **For this POC:** compare both approaches on the same cases. Measure factual
   support, missed material issues, recommendation appropriateness, cost, and
   latency. More arguments and longer explanations are weak success measures.

7. **Medium — The documentation describes features more clearly than success.**

   The scope lists capabilities, and the evaluation guide separates software
   behaviour from answer quality appropriately. Neither gives the reader a concise
   business hypothesis and acceptance result. See the
   [scope](../project/poc_definition.md) and [evaluation guide](../homework/evaluation.md).

   “37 borrowers, 172 records, 69 references” describes demonstration breadth. It
   says little about correctness or usefulness.

   **For this POC:** define success around a small, independently checked case set:
   ordinary compliance, deterioration before breach, amendment or waiver,
   springing-test boundary, and missing or conflicting evidence. Record expected
   outcomes, actual outcomes, unsupported conclusions, analyst corrections, and
   preparation time against the existing manual process.

The documentation has several strengths worth preserving: explicit missing-data
states, separation of fictional borrowers from public issuers, frozen submissions,
version-specific decisions, and clear limits on what verification proves. The
count-based portfolio disclosure also correctly avoids treating borrower debt as
portfolio exposure. See the
[reporting boundary](../guides/ui_preview.md#prepare-a-board-report).

The root README is readable, and the documentation index is easy to navigate. During
the audit, **55 local link targets** across both READMEs and the guides were checked;
none had a missing destination. The three headline dataset counts also matched the
CSVs. This check established destination-path existence, not anchor validity or
content accuracy.

**The priority is to add a concise credit-methodology page, one complete
source-backed worked case, and a dated POC acceptance scorecard before adding
further analytical features.** SQLite, Streamlit, local storage, and the absence
of authentication or PDF export are reasonable choices for this POC.
