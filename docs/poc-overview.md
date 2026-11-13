# The problem and the POC

Private credit is lending negotiated outside public bond markets. Loan agreements
can require a borrower to keep financial ratios within agreed limits. These
conditions are called **covenants**. Meeting them is one part of a credit review;
it does not establish that a borrower can repay or refinance its debt.

An analyst needs to identify the terms that apply, find the financial inputs,
calculate results, and explain exceptions. Amendments change terms. Waivers may
excuse a particular failure without improving the underlying finances. A manager
needs enough evidence to challenge the analysis before recording a decision.

## Users and their questions

| Persona | Question | What the POC provides |
| --- | --- | --- |
| Credit analyst | Which limit applies, what is the result, and what is missing? | Calculations, trends, source references, assistant answers, and saved findings. |
| Risk manager | Does the submission support the proposed action? | An exception queue, frozen submissions, observations, flags, and review decisions. |
| Board or credit committee | Which cases need attention and what action is proposed? | A versioned report of exceptions, pending reviews, and manager recommendations. |

Web V2 represents these roles in one local app. Its role switcher is navigation,
not authentication or an access-control boundary.

## What the POC tests

The business hypothesis is that bringing evidence, repeatable calculations, and
review records together can reduce repeated investigation and make disagreements
easier to resolve. Review time and decision outcomes have not been measured.

The demonstrated technical capabilities are:

- Retrieve filing passages and generate answers from supplied evidence.
- Extract structured covenant facts from HTML documents and save them for reuse.
- Calculate supported ratios and headroom outside the LLM, preserving missing and conflicting inputs.
- Let a tool-calling assistant inspect evidence and explain an assessment.
- Run bullish and bearish interpretations against the same snapshot, then synthesize an advisory action.
- Record analyst findings, risk-manager review, and board-report versions.
- Inspect tests, evaluation captures, model/tool traces, and user feedback.

The [worked example](worked-example.md) demonstrates these review tasks. The
[results page](evaluation/results.md) separates implemented behavior from measured
quality. No single pass rate establishes completion of the business hypothesis.

## Terms used in the guides

| Term | Meaning here |
| --- | --- |
| Leverage | Debt relative to the earnings measure defined by the agreement. |
| EBITDA | Earnings before interest, taxes, depreciation, and amortization; contractual adjustments vary. |
| Headroom | Remaining room before a covenant limit is reached, expressed in ratio points for ratio tests. |
| Interest coverage | The agreement's earnings measure divided by its interest measure. |
| Amendment | A change to agreement terms, potentially including future limits. |
| Waiver | Relief for a specified failure or period; it does not make the failed ratio compliant. |
| Springing test | A covenant tested only when a contractual trigger is met. |
| Reporting period | The financial period being assessed. |
| Information cutoff | The latest date information may be considered; a period end is not necessarily a publication date. |

## Data and boundaries

The bundle includes **37 fictional borrowers and 172 quarterly financial records**.
Their prepared terms support deterministic assessments. The separate SEC catalog
contains **69 public source references**. Catalog membership does not mean the
document has been downloaded, processed, or verified.

Synthetic borrower IDs are not real issuer identities. Source links and
document-backed calculation bindings must be explicit. Extraction does not
automatically replace financial inputs or establish the correct contractual formula.
Gold answers, scenario notes, and later outcomes are evaluation material rather
than runtime financial evidence. See [data layout](../data/README.md).

The optional Logistic Regression model predicts a **next-quarter covenant breach**
from synthetic histories. It does not estimate payment default or loss. AI reviews
can suggest exposure directions, but the POC does not establish that covenant-only
evidence supports a lending decision. People must assess missing credit context.

Automatic post-extraction verification is disabled, and extraction quality
acceptance remains open. The local POC has no authentication, external notifications,
PDF export, live-news retrieval, or private-data integration.

## Wider vision

A fuller credit-monitoring platform would combine private borrower data, agreement
terms, public information, historical performance, and analyst feedback. It could
support continuous monitoring and portfolio prioritization. This POC demonstrates
selected building blocks; it does not implement that wider platform. Specific
follow-up proposals are kept in [v2-plan](../v2-plan/README.md).
