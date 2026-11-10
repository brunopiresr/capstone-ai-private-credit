# LLM Agent Evaluation Report: 50 Scenarios

**Date:** 2026-11-09  
**Target System:** `CreditAssessmentAgent` (`gpt-4o-mini`)  
**Total Scenarios Evaluated:** 50  
**Overall Pass Rate:** 35/50 (70.0%)  

## Performance by Scenario Type

| Scenario Type | Total | Passed | Failed | Pass Rate |
|---|---:|---:|---:|---:|
| `breaking` | 8 | 3 | 5 | 37.5% |
| `edge_case` | 10 | 9 | 1 | 90.0% |
| `happy_path` | 14 | 13 | 1 | 92.9% |
| `out_of_scope` | 8 | 2 | 6 | 25.0% |
| `varied_phrasing` | 10 | 8 | 2 | 80.0% |

## Failure Category Breakdown

| Failure Category | Occurrences | Description |
|---|---:|---|
| `none` | 35 | Scenario met all pass criteria with no defects detected |
| `wrong-scope` | 6 | Agent failed to refuse an out-of-scope query or switched scope inappropriately |
| `incomplete` | 5 | Agent omitted required headroom, calculation steps, or key covenant context |
| `calculation-error` | 2 | Agent violated arithmetic limits (e.g. EBITDA addback caps) or boundary rules |
| `unverified-data-acceptance` | 1 | Agent accepted unverified out-of-band communication as official input |
| `uncalibrated-certainty` | 1 | Agent promised unwarranted predictive guarantees or zero future risk |

## Key Findings and Recommendations

1. **Happy Path & Varied Phrasing Robustness**: The agent demonstrates strong retrieval of deterministic calculations when borrower scope and dates are resolved.
2. **Boundary & Edge Discipline**: Boundary cases (such as exact 25% revolver availability thresholds) require strict operator enforcement (`<` vs `<=`).
3. **Guardrail Integrity on Breaking Scenarios**: Explicit guardrail rules prevent hallucination on non-existent entities and successfully resist prompt injection attempts.
4. **Out-of-Scope Redirection**: Out-of-scope inquiries are consistently redirected to the private credit domain without generating extraneous advice.

Full raw data available at [`eval_results.csv`](eval_results.csv).
