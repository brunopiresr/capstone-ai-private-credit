# Implementation plan

Proposal only. Apply on a feature branch; preserve all files and `master`. Reference: [ADR 001](decisions/001-hexagonal-authentication.md), [target architecture](architecture-proposal.md).

## Incremental delivery

| Step | Changes | Completion condition |
|---|---|---|
| 1. Access boundary | Add frozen `AnalystPrincipal`, injected `AnalystAccessPolicy`, `AccessService` and an authentication port used by it. Port exposes authenticated identity, login and logout without a provider-specific contract. | Approved `analyst_id` admitted; anonymous, unknown and malformed identities denied. No credit model changes. |
| 2. Authentication choice | Select the concrete login mechanism, stable analyst identifiers and session/logout behavior before implementing login. Configure approved analysts server-side. No provider adapter or authentication dependency is selected in this proposal. | The chosen mechanism validates identity server-side. Configuration/authentication failures deny access; test doubles are used only in tests. |
| 3. Streamlit integration | Implement the selected authentication boundary and guarded `AnalystWorkspace`. Wrap current app execution in an entry function. Authorize before benchmark loading/rendering, side-effectful workflow wiring and protected callbacks. Clear chat, active case, pending focus, selection/filter state on logout or identity change. | Every rerun and browser-facing operation checks access; denied paths make zero protected data/storage/model calls. Existing authorized mock behavior remains. Verify actual login/logout in the intended host. |
| 4. Dependency cleanup | Reuse/move `CovenantReader`, `RiskModel`, `AssessmentNarrator` into application ports. Add financial and analytics ports; inject repositories and model creation rather than constructing them in services. Bootstrap checks source/analytics database separation. | Existing assessment, model-failure and persistence regressions pass with equivalent results. |
| 5. Concept segregation | Add target modules and retain old imports as wrappers. Move metric vocabulary and pure rules inward; row mapping, CSV readers, extraction/search/SDK work outward. Split history access from pure feature building. Introduce document ports only for operations the service consumes. | Scripts/notebooks/imports remain usable; schemas, identifiers, provenance, cutoff semantics and cache keys stay compatible. |
| 6. Documentation and validation | Link the accepted proposal from existing architecture/docs when implementation lands; separate pure unit tests from adapter/integration tests. | Target dependencies are enforced and all relevant regressions pass. Live UI wiring remains a separate feature. |

Keep credentials and session secrets outside principal models, prompts and logs. Select session handling alongside the authentication mechanism rather than assuming a provider protocol or adding a session database in advance.

## Minimum meaningful tests

| Level | Acceptance coverage |
|---|---|
| Domain unit | Principal is immutable with a nonblank identifier; policy uses exact `analyst_id`, never display name/email. |
| Application unit | Fake authentication port: anonymous/unapproved/malformed/authentication-error states deny before protected reads, writes or tools; approved operations execute normally. |
| Adapter/UI | Use only server-validated identity, never unvalidated widget/query/session-state claims. Reject missing/non-string analyst identifiers. `AppTest` covers approved/denied pages, reruns, logout, identity changes, state cleanup and zero protected calls on denial. Fake secrets must never reach models, prompts or logs. |
| Architecture | One import check on new core modules prohibits adapter/UI/SQLite/OpenAI imports and imports through legacy wrappers. Bootstrap and wrappers for existing callers are outside that restriction. |
| Regression | Keep deterministic results, missing-data behavior, cutoff/provenance, extraction cache, optional-model failures and borrower tool scope/concurrency checks. Offline CLI/notebooks require no browser login. |
| Host smoke | Actual login → approved workspace → logout; cancelled/failed login denies access. Verify the selected mechanism's session lifecycle separately from fake/UI tests. |

Observed baseline: **229 passed in 50.32s**, using existing dependencies and no network:

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/unit \
  tests/integration/workflows/test_assessment.py \
  tests/integration/workflows/test_structured_assessment_inputs.py \
  tests/test_package_import.py
```

This verifies current behavior, not authentication. Authentication and Streamlit UI tests still need implementation. Deliver access steps 1–3 independently, then migrate structure in steps 4–6; no big-bang refactor or file deletions.
