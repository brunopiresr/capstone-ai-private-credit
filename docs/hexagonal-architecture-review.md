# Hexagonal Architecture Implementation Plan Review

Review date: 2026-10-07.

Reviewed: [implementation plan](authentication-implementation-plan.md), [architecture proposal](architecture-proposal.md), and [ADR 001](decisions/001-hexagonal-authentication.md), cross-checked against the current codebase.

## 1. Executive assessment

**APPROVE WITH CHANGES**

The proposal moves in the right direction: dependency injection, application-owned ports, deterministic domain rules and a small package structure. However, several boundaries remain underspecified. Renaming packages alone would leave important coupling intact.

| Criterion | Score |
|---|---:|
| Hexagonal Architecture alignment | 7/10 |
| Dependency direction | 7/10 |
| Separation of concerns | 6/10 |
| Testability | 7/10 |
| Migration safety | 6/10 |
| Complexity / maintainability | 8/10 |

I independently reran the selected regression suite: **229 passed in 8.15s**. This confirms the existing baseline, not the proposed architecture or authentication. No files were changed during this review.

## 2. What the plan gets right

- **Small structure:** one Python package with domain, application and adapters suits this capstone.
- **Useful existing contracts:** retaining `CovenantReader`, `RiskModel` and `AssessmentNarrator` avoids inventing redundant interfaces.
- **Correct calculation boundary:** deterministic calculations, missing-data rules and verification remain independent of the LLM.
- **Incremental compatibility:** retaining imports and constructor entry points protects scripts and notebooks.
- **Honest workflow separation:** authentication does not imply connecting the synthetic Streamlit demo to the live assessment pipeline.
- **Limited DDD scope:** conceptual contexts are useful; additional aggregates, event infrastructure and ownership models are unnecessary.

## 3. Critical issues

### A. Authentication is not implementation-ready

**Issue:** The plan requires authentication but leaves the mechanism, identity validation and session lifecycle undecided.

**Why it matters:** These choices determine the actual port contract and whether login/logout can be implemented securely.

**Evidence:** [Implementation plan, step 2](authentication-implementation-plan.md#L10) explicitly leaves these decisions open.

**Recommended change:** Resolve the mechanism before implementing the authentication port. Keep browser presentation and session cleanup in the web adapter; `AccessService` should evaluate validated identity and workspace access.

**UNVERIFIED:** Authentication feasibility requires a selected mechanism, its integration contract and a real login/logout test. This does not block independent structural cleanup.

### B. Document and RAG boundaries are incomplete

**Issue:** The plan promises outward movement of infrastructure but does not specify how all remaining application services will consume it.

**Why it matters:** Injecting `client: Any` or relocating a helper does not remove infrastructure dependency.

**Evidence:** [DocumentProcessingService](../src/credit_monitoring/application/document_processing_service.py#L49) owns filesystem paths, constructs storage, reads files and manages retrieval indexes. [rag_service.py](../src/credit_monitoring/application/rag_service.py#L10) directly calls `client.responses.create()`.

**Recommended change:** Identify consumed capabilities for document content, extraction storage, extraction and evidence search. Give RAG an application-owned generation contract. Keep files, indexes, SDK response handling and SQL-row decoding inside implementations. Group related capabilities rather than adding an interface per helper.

### C. Covenant readers contain business rules

**Issue:** Moving the readers wholesale into adapters would move business decisions outward too.

**Why it matters:** Adapters should retrieve and translate source data; applicable thresholds, ambiguity handling and waiver rules belong inward.

**Evidence:** [ExtractionCovenantReader](../src/credit_monitoring/covenants/structured.py#L229) resolves applicability and conflicts. Its `_candidate()` also handles effective dates and testing events while reading Markdown.

**Recommended change:** Extract the resolution rules into pure functions accepting typed facts and source content. Keep CSV/document acquisition in adapters. Apply the same distinction to `SyntheticCovenantReader`.

### D. Model injection could change failure behavior

**Issue:** Moving model construction into bootstrap could load a trained artifact before assessment starts.

**Why it matters:** Currently, model-loading failures preserve persisted deterministic results. Eager construction could prevent those results entirely.

**Evidence:** [AssessmentService._run_ml()](../src/credit_monitoring/application/assessment_service.py#L136) creates the model inside its failure boundary, after saving the snapshot. Runtime configuration also contains [database and artifact paths](../src/credit_monitoring/config/settings.py#L10).

**Recommended change:** Inject a lazy model provider or lazy adapter and retain the current failure boundary. Keep paths and artifact selection in bootstrap; pass only required application options inward. Do not introduce another generic factory framework.

### E. Persistence semantics need explicit preservation

**Issue:** The plan says persistence behavior stays compatible without defining the transaction contract.

**Why it matters:** A single transaction around the whole assessment would change behavior and could hold a database transaction during model execution.

**Evidence:** [CovenantResultRepository.save_all()](../src/credit_monitoring/persistence/analytics_repositories.py#L46) saves results atomically. Snapshots and predictions use separate transactions; existing ML-failure tests expect calculations to remain stored.

**Recommended change:** Preserve atomic result batches, separate snapshot/prediction commits and calculation survival after optional ML failure. Keep external calls outside database transactions. A generic unit-of-work abstraction is unnecessary here.

### F. Compatibility needs stronger migration gates

**Issue:** Wrappers alone do not protect resource paths, constructor behavior or complete dependency convergence.

**Why it matters:** Package relocation can break runtime behavior while imports still succeed.

**Evidence:** The [demo service](../src/credit_monitoring/application/demo_assessment_service.py#L9) derives its data root from module depth; analytics storage loads an adjacent SQL file. The [architecture test proposal](authentication-implementation-plan.md#L25) covers only "new core modules."

**Recommended change:** Preserve resource lookup and package SQL resources explicitly. Keep one implementation behind compatibility wrappers. Check every migrated core module, then the entire target core—not merely newly created files.

## 4. Architectural smells

| Severity | Smell | Assessment |
|---|---|---|
| High | `DocumentProcessingService` combines acquisition, caching, extraction and index management | Preserve workflow orchestration; extract infrastructure responsibilities. |
| Medium | `AssessmentService` manages assessment, features, prediction persistence and failure records | The proposed feature service helps, provided orchestration has one clear owner. |
| Medium | Pydantic extraction schemas and processing DTOs are labelled "domain" | The domain is not framework-free. Accept this pragmatic dependency explicitly; distinguish business contracts from processing outcomes. |
| Medium | Permanent compatibility wrappers | Useful migration tools, but core code must never depend on them or duplicate implementations. |
| Low | One growing `ports.py` | Appropriate initially; split by capability only when readability requires it. |

No ORM annotations or HTTP request models were found in the inspected domain types. Existing financial row conversion is genuine leakage; provenance fields and stable fingerprints are not automatically leakage.

## 5. Missing considerations

- **Errors:** Specify how storage/SDK failures become existing processing statuses, assessment issues and agent errors without importing infrastructure exceptions into core code.
- **Cache identity:** Preserve configuration fingerprints, section resume behavior, forced extraction and failed-run semantics.
- **Concurrency:** Retain per-question borrower/tool isolation. Do not share authenticated identity or chat state through globally cached services.
- **Retries:** Assessments create new run identifiers. A retry must not silently become an idempotent overwrite or duplicate an existing run.
- **Configuration:** Distinguish business options from filesystem/database/model-artifact configuration.
- **Test separation:** Add use-case tests with small fakes, alongside real SQLite adapter tests. Existing passing tests frequently exercise infrastructure.

Domain events, message brokers and distributed transactions are unnecessary for the demonstrated workflows.

## 6. Dependency review

Intended **source dependencies**:

```text
Streamlit / CLI / notebook entry adapters
                  ↓
        Application use-case methods
                  ↓
       Domain rules and typed contracts

Application → application-owned outbound ports
Concrete outbound adapters → those ports and domain contracts

Bootstrap → application and concrete adapters
```

Runtime calls can reach an adapter through a port; that does not reverse source dependency direction.

The following would remain violations unless explicitly corrected:

- Application → concrete repositories, SDK clients or retrieval indexes.
- Domain → financial adapter vocabulary or repository-row mapping.
- New core → legacy wrappers or bootstrap.
- Application → deployment paths and concrete model factories.

The proposal's flowchart should be labelled as runtime flow, rather than treated as a dependency diagram.

## 7. Proposed architecture after implementation

| Element | Project-specific destination |
|---|---|
| Domain | `FinancialPeriod`, `ResolvedCovenant`, `CovenantResult`, deterministic calculations, covenant resolution and pure verification |
| Application | `AssessmentService`, `DocumentProcessingService`, `RiskAnalysisService`; a small feature orchestration service |
| Inbound ports | Existing public methods such as `assess()`, `process_document()` and `search_evidence()`; additional interface classes are optional |
| Outbound ports | Financial history, covenant inputs, analytics persistence, document acquisition/extraction/search, `RiskModel`, `AssessmentNarrator` |
| Inbound adapters | Streamlit, CLI handlers and notebook entry points |
| Outbound adapters | SQLite repositories, SEC/filesystem access, retrieval implementations and model/SDK integration |
| Bootstrap | Dependency construction, paths, model selection and database-separation checks |

Keep `AnalystWorkspace` limited to browser-facing access coordination. It should not become a second assessment orchestrator.

Use existing typed contracts across boundaries where they already fit. Add mapping for SQL rows and SDK responses; avoid parallel DTOs for every layer.

## 8. Implementation sequencing review

The proposed incremental approach is sensible, but authentication-first mixes new behavior with the architectural migration.

A safer sequence is:

1. Establish regression and dependency baselines.
2. Move metric vocabulary inward and financial row mapping outward.
3. Inject assessment storage and lazy model dependencies; preserve transactions and failure behavior.
4. Separate document infrastructure and covenant resolution rules.
5. Relocate implementations behind compatibility wrappers; validate resources and entry points.
6. Deliver authentication separately after its mechanism is decided.
7. Enforce dependency rules across the complete target core.

Run relevant regression and boundary tests after each step. Existing files remain; wrappers delegate to one implementation.

## 9. Final recommendation

**Must change before implementation**

- Resolve authentication decisions before implementing that feature.
- Define the remaining document/RAG capabilities and typed boundaries.
- Separate covenant business rules from source adapters.
- Preserve lazy model failure handling and existing transaction semantics.
- Extend migration checks to resources, constructors and all migrated core modules.

**Should change**

- Clarify the accepted Pydantic dependency.
- Specify error translation, retry behavior and shared-state ownership.
- Prevent `AnalystWorkspace` and compatibility wrappers from becoming alternative orchestration layers.

**Can remain as proposed**

- One package and a shallow hierarchy.
- Existing domain contracts and deterministic rules.
- Small application-owned protocols.
- Constructor injection without a DI framework.
- Compatibility wrappers, unchanged storage schemas and separate mock/offline workflows.
