# Capstone Evaluation Scenarios

A simplified benchmark suite of 50 evaluation scenarios designed specifically for the AI Private Credit Monitoring agents.

## Overview

The dataset in [eval_scenarios.csv](file:///workspaces/capstone-ai-private-credit/evaluations/eval_scenarios.csv) evaluates agent accuracy, robustness, and epistemic humility across core credit assessment workflows.

### Schema

| Column | Description |
|---|---|
| `question` | The prompt or inquiry submitted to the credit assessment agent |
| `category` | The functional domain or topic of the question |
| `type` | The scenario type: `happy_path`, `varied_phrasing`, `edge_case`, `out_of_scope`, `breaking` |

### Scenario Breakdown

| Type | Count | Purpose |
|---|---:|---|
| `happy_path` | 14 | Direct, well-formed inquiries covering core calculations, ratios, and contractual terms |
| `varied_phrasing` | 10 | Conversational, informal, and jargon-heavy phrasing representing real-world analyst usage |
| `edge_case` | 10 | Threshold boundary conditions, exact limits, missing data, and transition periods |
| `out_of_scope` | 8 | Irrelevant inquiries (equities, crypto, code debugging, legal drafting) that must be declined |
| `breaking` | 8 | Adversarial prompts, false premises, non-existent borrowers, future dates, and jailbreak attempts |
| **Total** | **50** | |

### Tested Domains (`category`)

- `compliance_headroom`: Leverage calculation, headroom quantification, and threshold breaches.
- `coverage_definitions`: Interest coverage (ICR), fixed charge coverage (FCCR), and EBITDA addback caps.
- `springing_tests`: Revolver availability trigger boundaries and conditional covenant activation.
- `amendments_waivers`: Contractual amendments, covenant holiday waivers, and waiver expirations.
- `risk_forecasts`: Machine learning default/breach probability modeling and horizon disclosures.
- `evidence_retrieval`: Locating definitions and clauses in credit agreements and compliance filings.
- `out_of_scope`: Domain negative controls.
- `breaking`: Guardrail integrity and hallucination resistance.
