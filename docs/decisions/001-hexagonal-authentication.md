# ADR 001: Small hexagonal structure and analyst authentication

Status: Proposed. Scope: this private-credit capstone; no implementation or deployment.

## Context and evidence

The existing [POC scope](../poc_definition.md) prioritizes traceable covenant monitoring and analyst review. The [implementation specification](../../06_POC_Code_Agent_Implementation_Spec.md) establishes the Credit Analyst persona. Authentication is required by the current request; its implementation mechanism remains unspecified.

| Review | Finding | Evidence |
|---|---|---|
| Agent 1: business | One analyst workspace; UI uses synthetic cases and fixed replies | `README.md`, `web/app.py` |
| Agent 2: domain | Credit models exist; borrower/feedback models are placeholders | `domain/assessment.py`, `domain/borrower.py`, `domain/feedback.py` |
| Agent 3: tests | No authentication/UI tests; selected offline baseline: 229 passed | `tests/unit/`, `tests/integration/workflows/`, `tests/test_package_import.py` |
| Agent 4: maintainability | Application constructs storage; domain translates database rows | `application/assessment_service.py`, `application/document_processing_service.py`, `domain/assessment.py` |

Source paths above are relative to `src/credit_monitoring/` unless otherwise stated.

The original proposal underwent four-agent cross-review. Retained refinements: correct placeholder terminology, an application-owned authentication boundary, lazy wiring, validated identity, and prevention of indirect adapter imports through wrappers. This revision removes the earlier identity-provider choice.

## Decisions and rationale

| Decision | Rationale and consequence |
|---|---|
| One package with `domain`, `application`, `adapters`, and `bootstrap.py` | Makes layers visible without separate services or elaborate hierarchies. Concepts stay visible in module names. |
| Application owns small ports; bootstrap injects implementations | Removes SQLite/SDK construction from use cases and makes substitution/test doubles straightforward. Reuse existing `CovenantReader`, `RiskModel`, and `AssessmentNarrator` contracts. |
| Retain Pydantic contracts and pure deterministic rules | Fits existing code. Move metric vocabulary inward and repository-row conversion outward; avoid a wholesale model rewrite. |
| Authentication behind an application-owned port | Keep the required login/logout behavior independent of the UI and any identity-provider protocol. Select the concrete mechanism before implementing login; this proposal prescribes no provider adapter or authentication library. |
| Immutable `AnalystPrincipal` plus an `analyst_id` allowlist | Proposed minimum access rule: approved analysts share the capstone workspace. A stable identifier from successfully validated authentication grants access; display name/email do not. Application policy decides workspace access. |
| Guard browser entry points; keep local workflows trusted | Prevents anonymous/unapproved UI reads and tool execution without adding identity arguments to credit calculations or offline scripts. |
| Add modules incrementally; retain old imports and constructor entry points as wrappers | Preserves notebooks, scripts, tests and docs. No deletions, schema redesign, or cache-version changes are needed. |

Alternatives deferred: context-per-service architecture is excessive for this POC; custom account/session storage is not selected without a concrete login requirement; package moves before dependency cleanup create churn without fixing coupling.

## Scope and limits

Protect portfolio, borrower assessments, evidence and mock chat before data reads, service construction with side effects, or tool calls. Deny missing/malformed identities and unavailable authentication. Clear analyst UI state on logout or identity change; recheck access each rerun. Browser authentication does not connect the mocked UI to the live pipeline.

Roles, tenancy, borrower ACLs, registration/reset and account administration are outside the documented scope. Authentication mechanism, session lifetime, logout behavior and approved analyst identifiers are implementation inputs. No provider callbacks, token formats or browser cookie behavior are assumed.

Related: [architecture and DDD language](../architecture-proposal.md), [implementation plan](../authentication-implementation-plan.md).
