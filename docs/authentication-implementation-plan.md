# Implementation plan

Proposal only. Apply on a feature branch; preserve all files and `master`. Reference: [ADR 001](decisions/001-hexagonal-authentication.md), [target architecture](architecture-proposal.md).

## Incremental delivery

| Step | Changes | Completion condition |
|---|---|---|
| 1. Access boundary | Add frozen `AnalystPrincipal`, injected `AnalystAccessPolicy`, `AccessService` and an identity port used by it. Port exposes current identity, login and logout; provider claims stay in the adapter. | Approved `(issuer, subject)` admitted; anonymous, unknown, malformed and wrong-issuer identities denied. No credit model changes. |
| 2. Configuration | Choose one OIDC provider and callback URL; configure approved identities server-side. Require compatible `streamlit[auth]`; current installed Streamlit is 1.64.0, while declared `>=1.41.0` alone does not guarantee native APIs. Add an example secrets file and ignore real `.streamlit/secrets.toml`. | Provider setup supplies validated issuer/subject claims. Configuration failures deny access; fake identity adapter is used only in tests. |
| 3. Streamlit integration | Add native OIDC adapter and guarded `AnalystWorkspace`. Wrap current app execution in an entry function. Authorize before benchmark loading/rendering, side-effectful workflow wiring and protected callbacks. Clear chat, active case, pending focus, selection/filter state on logout or identity change. | Every rerun and browser-facing operation checks access; denied paths make zero protected data/storage/model calls. Existing authorized mock behavior remains. Verify real login/logout in the intended host. |
| 4. Dependency cleanup | Reuse/move `CovenantReader`, `RiskModel`, `AssessmentNarrator` into application ports. Add financial and analytics ports; inject repositories and model creation rather than constructing them in services. Bootstrap checks source/analytics database separation. | Existing assessment, model-failure and persistence regressions pass with equivalent results. |
| 5. Concept segregation | Add target modules and retain old imports as wrappers. Move metric vocabulary and pure rules inward; row mapping, CSV readers, extraction/search/SDK work outward. Split history access from pure feature building. Introduce document ports only for operations the service consumes. | Scripts/notebooks/imports remain usable; schemas, identifiers, provenance, cutoff semantics and cache keys stay compatible. |
| 6. Documentation and validation | Link the accepted proposal from existing architecture/docs when implementation lands; separate pure unit tests from adapter/integration tests. | Target dependencies are enforced and all relevant regressions pass. Live UI wiring remains a separate feature. |

Provider credentials, redirect URI and cookie secret are deployment inputs; never put raw tokens or secrets into principal models, prompts or logs. Login configuration and the authentication extra are documented in [Streamlit's API reference](https://docs.streamlit.io/develop/api-reference/user/st.login). Browser session lifecycle belongs to Streamlit; do not add a local session database.

## Minimum meaningful tests

| Level | Acceptance coverage |
|---|---|
| Domain unit | Principal is immutable with nonblank identity; policy uses exact issuer/subject, never display name/email. |
| Application unit | Fake identity port: anonymous/unapproved/malformed/provider-error states deny before protected reads, writes or tools; approved operations execute normally. |
| Adapter/UI | Use only Streamlit's validated provider identity, never widget/query/session-state claims. Reject missing/non-string issuer or subject; verify issuer against configuration. `AppTest` covers approved/denied pages, reruns, logout, identity changes, state cleanup and zero protected calls on denial. Fake secrets must never reach models, prompts or logs. |
| Architecture | One import check on new core modules prohibits adapter/UI/SQLite/OpenAI imports and imports through legacy wrappers. Bootstrap and wrappers for existing callers are outside that restriction. |
| Regression | Keep deterministic results, missing-data behavior, cutoff/provenance, extraction cache, optional-model failures and borrower tool scope/concurrency checks. Offline CLI/notebooks require no browser login. |
| Host smoke | Real configured provider login → approved workspace → logout; cancelled/failed login denies access. Do not claim cross-tab logout or provider revocation from fake tests. |

Observed baseline: **229 passed in 50.32s**, using existing dependencies and no network:

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/unit \
  tests/integration/workflows/test_assessment.py \
  tests/integration/workflows/test_structured_assessment_inputs.py \
  tests/test_package_import.py
```

This verifies current behavior, not authentication. Authentication and Streamlit UI tests still need implementation. Deliver access steps 1–3 independently, then migrate structure in steps 4–6; no big-bang refactor or file deletions.
