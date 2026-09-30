# AI Credit Monitoring POC — Code Agent Implementation Spec

> **Purpose:** This document is the execution specification for a coding agent.  
> It translates the POC definition and architecture into an implementation sequence with explicit boundaries, interfaces, repository structure, and acceptance criteria.

---

# 1. Project context

The long-term vision is an **AI Credit Monitoring platform** that continuously combines legal terms, borrower financials, public information, historical performance, calculations, and analyst feedback to help credit teams identify deterioration earlier and monitor larger portfolios efficiently.

This capstone is a deliberately narrow proof of concept. It should prove that the core architecture works before expanding into broader credit-risk analysis, portfolio prioritization, specialized agents, private-data integrations, or production workflows.

The POC focuses on:

- covenant monitoring;
- deterministic financial calculations;
- covenant headroom and trend analysis;
- retrieval of legal and public evidence;
- an evidence-backed quarterly assessment;
- verification before alerting;
- analyst review and interaction.

The POC is **not** intended to make autonomous lending, investment, or escalation decisions.

---

# 2. POC objective

Given a borrower and reporting quarter, the system should eventually be able to:

1. identify the applicable covenant and supporting legal evidence;
2. retrieve the financial values required for that covenant;
3. calculate the covenant ratio and headroom using deterministic tools;
4. compare results with previous quarters;
5. retrieve relevant public borrower information;
6. assemble an evidence-backed assessment;
7. verify the assessment against sources and calculations;
8. show the result to a credit analyst;
9. optionally allow the analyst to ask grounded follow-up questions about the result.

The coding agent must build this incrementally.

**Do not implement the entire architecture in the first step.**

---

# 3. Primary POC persona

## Credit Analyst

The credit analyst is the primary POC user.

The analyst should eventually be able to:

- select a borrower;
- select a reporting quarter;
- trigger a quarterly monitoring assessment;
- see covenant status and headroom;
- see quarter-over-quarter trends;
- see relevant public information and risk signals;
- inspect source evidence;
- inspect the financial values and calculations used;
- review verification warnings;
- record a note or correction;
- optionally ask follow-up questions about the assessment.

The analyst remains responsible for interpretation, follow-up, and credit decisions.

---

# 4. Architecture principles

The implementation must follow these principles.

## 4.1 Keep deterministic logic outside the LLM

The LLM must not perform financial arithmetic when a deterministic function can do it.

Examples:

- leverage calculation;
- interest coverage calculation;
- threshold comparison;
- headroom;
- quarter-over-quarter delta;
- alert classification rules.

## 4.2 Use the LLM for language and orchestration

The LLM may eventually be used for:

- covenant extraction from retrieved legal evidence;
- query interpretation;
- deciding which approved tools are needed;
- summarizing evidence;
- producing analyst-readable explanations;
- synthesizing legal, financial, trend, and public context.

## 4.3 Evidence is mandatory

Every material legal or public-information claim must preserve provenance.

The system must be able to identify:

- source document;
- source URL or file;
- document type;
- filing/effective date;
- section;
- chunk or evidence ID.

## 4.4 Missing information must remain missing

The system must never invent:

- covenant thresholds;
- financial values;
- waiver status;
- amendment status;
- dates;
- source evidence.

Use explicit `unknown`, `missing`, `not_applicable`, or equivalent states.

## 4.5 Build independent layers before the agent

The recommended sequence is:

```text
Project scaffold
    ↓
Schemas / contracts
    ↓
Document ingestion
    ↓
Retrieval
    ↓
Covenant extraction
    ↓
Financial repository
    ↓
Calculation tools
    ↓
Monitoring workflow / agent
    ↓
Verification
    ↓
Analyst web app
    ↓
Evaluation / monitoring
```

Each layer must be independently testable.

---

# 5. Target high-level architecture

```text
                       ┌─────────────────────────┐
                       │    Credit Analyst       │
                       │      Web App            │
                       └────────────┬────────────┘
                                    │
                    Trigger / inspect / ask
                                    │
                                    ▼
                       ┌─────────────────────────┐
                       │ Monitoring Orchestrator │
                       │       / Agent           │
                       └──────────┬───┬──────────┘
                                  │   │
                  ┌───────────────┘   └─────────────────┐
                  ▼                                     ▼
       ┌─────────────────────┐                ┌─────────────────────┐
       │ Legal / Public RAG  │                │ Financial Repository │
       │ text + vector search│                │ quarterly facts      │
       └──────────┬──────────┘                └──────────┬──────────┘
                  │                                      │
                  │                                      ▼
                  │                           ┌─────────────────────┐
                  │                           │ Calculation Tools   │
                  │                           │ ratios / headroom   │
                  │                           └──────────┬──────────┘
                  │                                      │
                  └──────────────────┬───────────────────┘
                                     ▼
                          ┌─────────────────────┐
                          │ Assessment / Trend  │
                          │ synthesis           │
                          └──────────┬──────────┘
                                     ▼
                          ┌─────────────────────┐
                          │ Verification        │
                          │ evidence + math     │
                          └──────────┬──────────┘
                                     ▼
                          ┌─────────────────────┐
                          │ Analyst Result      │
                          │ + optional chat     │
                          └─────────────────────┘
```

---

# 6. Recommended POC technology choices

These choices favor simplicity, inspectability, and fast iteration.

| Layer | Recommended POC approach | Notes |
|---|---|---|
| Language | Python | Main implementation language. |
| Dependency management | `uv` or equivalent | Keep dependencies explicit and reproducible. |
| Configuration | Environment variables + typed settings | Never hard-code API keys. |
| Document conversion | MarkItDown or equivalent | Existing project direction. |
| Legal/public text retrieval | BM25/text search + vector search | Start simple; hybrid retrieval when both are ready. |
| Vector storage | Lightweight local vector store or SQLite/PostgreSQL vector extension | Avoid unnecessary infrastructure for the capstone. |
| Structured database | SQLite initially | PostgreSQL is a later migration path. |
| Data models | Pydantic or equivalent typed models | Shared contracts across layers. |
| Financial calculations | Plain Python deterministic functions | Unit-testable; no LLM arithmetic. |
| Agent | One orchestrator with explicit tools | Avoid multi-agent complexity in the POC. |
| Web interface | Streamlit recommended | Fastest route to a useful analyst-facing POC. |
| Tests | Pytest | Unit, integration, retrieval and end-to-end tests. |
| Evaluation data | Versioned Markdown / CSV / JSONL | Human-readable and reproducible. |
| Logging | Standard structured application logs | Add model/tool traces later as needed. |

The specific libraries may be replaced if there is a clear project reason, but the architecture and contracts should remain stable.

---

# 7. Analyst interaction — recommended POC approach

A simple web application is recommended.

The web app should be considered an **interaction layer**, not the business-logic layer. It should call application services and must not contain covenant logic, calculations, retrieval logic, or prompt logic directly in UI code.

## 7.1 Recommended POC UI

Use a lightweight Streamlit application with three main areas.

### A. Assessment trigger

The analyst selects:

- borrower;
- reporting quarter.

Then chooses:

**Run assessment**

Eventually this should call the monitoring workflow.

### B. Assessment view

Display:

- overall status: `COMPLIANT`, `WATCH`, `BREACH`, or `INCOMPLETE`;
- covenant metric;
- threshold;
- calculated value;
- headroom;
- previous-quarter value;
- trend;
- key risk/context signals;
- verification status;
- missing data warnings.

### C. Evidence and calculation details

Use expandable sections or tabs for:

- covenant clause;
- amendment evidence;
- financial inputs;
- calculation formula;
- prior-quarter comparison;
- public-information evidence;
- verification results.

This is important because traceability is one of the main values of the POC.

---

# 8. Optional analyst chat — nice-to-have

A chat interface can be added after the core assessment works.

The embedded analyst assistant should **not** be a general-purpose chat agent.

It should answer questions grounded in:

1. the selected borrower;
2. the selected quarter;
3. the generated assessment;
4. retrieved legal/public evidence;
5. structured financial data;
6. deterministic calculation outputs.

Example analyst questions:

- "Why is this borrower in WATCH?"
- "Show me the covenant clause."
- "How did leverage change from last quarter?"
- "Which financial values were used?"
- "Was the covenant amended?"
- "What public information contributed to this warning?"
- "What evidence supports the weaker-demand statement?"
- "What would leverage be if EBITDA were 5% lower?"

For the last example, the system should invoke a deterministic scenario calculation tool rather than ask the LLM to calculate it.

## Chat guardrails

The chat must:

- stay scoped to the selected borrower/assessment;
- cite or expose evidence IDs for material factual claims;
- use tools for calculations;
- say when information is unavailable;
- distinguish source facts from model interpretation;
- avoid autonomous credit recommendations.

A useful mental model is:

```text
Assessment page
      │
      ├── Evidence viewer
      ├── Calculation viewer
      └── Grounded analyst chat
               │
               ├── assessment context
               ├── retrieval
               └── approved tools
```

This feature is optional for the capstone and should not block the core monitoring workflow.

---

# 9. Domain contracts

The following domain concepts should exist in the design, even if their complete implementation comes later.

Exact field names may evolve, but do not collapse these concepts into unstructured dictionaries.

## 9.1 Borrower

Suggested fields:

```text
borrower_id
legal_name
ticker
cik
website
industry
active
```

## 9.2 ReportingPeriod

```text
period_id
borrower_id
fiscal_year
fiscal_quarter
period_end_date
```

## 9.3 SourceDocument

```text
document_id
borrower_id
document_type
title
source_url
filing_date
effective_date
local_path
content_hash
```

## 9.4 DocumentChunk

```text
chunk_id
document_id
borrower_id
section
text
sequence
metadata
```

## 9.5 Evidence

```text
evidence_id
chunk_id
document_id
source_type
quoted_or_referenced_text
section
source_url
```

## 9.6 Covenant

```text
covenant_id
borrower_id
name
covenant_type
operator
threshold
numerator_definition
denominator_definition
test_frequency
effective_from
effective_to
source_document_id
source_evidence_ids
supersedes_covenant_id
```

POC covenant types should be limited to the agreed benchmark, initially:

- maximum net leverage;
- minimum interest coverage or fixed-charge coverage.

## 9.7 FinancialFact

```text
financial_fact_id
borrower_id
period_id
metric_name
value
unit
source_document_id
source_reference
data_quality_status
```

## 9.8 CalculationResult

```text
calculation_id
borrower_id
period_id
calculation_type
formula_id
inputs
result
unit
threshold
headroom
status
validation_errors
```

## 9.9 PublicEvent

```text
event_id
borrower_id
event_date
event_type
summary
source_document_id
source_evidence_ids
relevance
```

## 9.10 Assessment

```text
assessment_id
borrower_id
period_id
status
covenant_results
trend_summary
public_context
missing_data
evidence_ids
verification_status
created_at
```

## 9.11 VerificationResult

```text
verification_id
assessment_id
passed
issues
unsupported_claims
calculation_mismatches
missing_evidence
```

## 9.12 AnalystFeedback

```text
feedback_id
assessment_id
analyst_action
note
correction
created_at
```

---

# 10. Application boundaries

Keep domain responsibilities separated.

## Ingestion

Responsible for:

- fetching or loading source documents;
- conversion to normalized Markdown/text;
- metadata preservation;
- chunk generation.

Must not calculate financial ratios.

## Retrieval

Responsible for:

- text/BM25 search;
- vector search;
- metadata filtering;
- result merging/deduplication;
- returning evidence objects.

Must not invent covenant terms.

## Covenant extraction

Responsible for:

- transforming retrieved legal evidence into the supported covenant schema;
- preserving source evidence IDs;
- returning missing fields as unknown.

Must not calculate borrower performance.

## Financial repository

Responsible for:

- borrower financial facts;
- reporting-period lookup;
- data-quality state;
- source lineage.

Must not contain generated narrative assessments.

## Calculation layer

Responsible for deterministic calculations.

Must not call an LLM.

## Monitoring orchestrator

Responsible for coordinating approved services and tools.

Must not directly implement retrieval algorithms or formulas.

## Verification

Responsible for checking:

- calculation consistency;
- covenant applicability;
- evidence support;
- required inputs;
- unsupported claims.

## UI

Responsible for:

- analyst inputs;
- presentation of assessment;
- evidence inspection;
- interaction.

Must not contain domain calculation or retrieval implementations.

---

# 11. Proposed repository structure

The first implementation task is to create this project structure.

```text
ai-credit-monitoring/
│
├── README.md
├── pyproject.toml
├── .python-version
├── .gitignore
├── .env.example
├── Makefile
│
├── docs/
│   ├── architecture.md
│   ├── poc_definition.md
│   ├── data_sources.md
│   ├── evaluation.md
│   └── decisions/
│       └── README.md
│
├── data/
│   ├── raw/
│   │   ├── sec/
│   │   ├── issuer/
│   │   └── synthetic/
│   ├── processed/
│   │   ├── markdown/
│   │   ├── chunks/
│   │   └── indexes/
│   └── benchmark/
│       ├── synthetic_loan_agreement.md
│       ├── synthetic_amendment_01.md
│       ├── synthetic_financials.csv
│       ├── synthetic_events.jsonl
│       ├── synthetic_expected_results.csv
│       └── synthetic_missing_data.csv
│
├── src/
│   └── credit_monitoring/
│       ├── __init__.py
│       ├── config/
│       │   ├── __init__.py
│       │   └── settings.py
│       ├── domain/
│       │   ├── __init__.py
│       │   ├── borrower.py
│       │   ├── covenant.py
│       │   ├── documents.py
│       │   ├── financials.py
│       │   ├── evidence.py
│       │   ├── assessment.py
│       │   └── feedback.py
│       ├── ingestion/
│       │   ├── __init__.py
│       │   ├── loaders/
│       │   │   └── __init__.py
│       │   ├── converters/
│       │   │   └── __init__.py
│       │   ├── cleaners/
│       │   │   └── __init__.py
│       │   └── chunking/
│       │       └── __init__.py
│       ├── retrieval/
│       │   ├── __init__.py
│       │   ├── lexical/
│       │   │   └── __init__.py
│       │   ├── vector/
│       │   │   └── __init__.py
│       │   ├── hybrid/
│       │   │   └── __init__.py
│       │   └── repositories.py
│       ├── covenants/
│       │   ├── __init__.py
│       │   ├── extraction.py
│       │   ├── applicability.py
│       │   └── repositories.py
│       ├── financials/
│       │   ├── __init__.py
│       │   ├── repositories.py
│       │   └── mappings.py
│       ├── calculations/
│       │   ├── __init__.py
│       │   ├── leverage.py
│       │   ├── coverage.py
│       │   ├── headroom.py
│       │   └── trends.py
│       ├── public_context/
│       │   ├── __init__.py
│       │   ├── retrieval.py
│       │   └── events.py
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── monitoring.py
│       │   ├── prompts/
│       │   │   └── README.md
│       │   └── tools/
│       │       └── __init__.py
│       ├── verification/
│       │   ├── __init__.py
│       │   ├── rules.py
│       │   └── verifier.py
│       ├── application/
│       │   ├── __init__.py
│       │   ├── assessment_service.py
│       │   ├── evidence_service.py
│       │   └── analyst_chat_service.py
│       ├── persistence/
│       │   ├── __init__.py
│       │   ├── database.py
│       │   ├── schema.py
│       │   └── migrations/
│       ├── observability/
│       │   ├── __init__.py
│       │   └── logging.py
│       └── web/
│           ├── __init__.py
│           ├── app.py
│           ├── pages/
│           │   ├── assessment.py
│           │   ├── evidence.py
│           │   └── chat.py
│           └── components/
│               └── __init__.py
│
├── tests/
│   ├── unit/
│   │   ├── ingestion/
│   │   ├── retrieval/
│   │   ├── covenants/
│   │   ├── financials/
│   │   ├── calculations/
│   │   └── verification/
│   ├── integration/
│   │   ├── retrieval/
│   │   ├── persistence/
│   │   └── workflows/
│   ├── evaluation/
│   │   ├── retrieval/
│   │   ├── extraction/
│   │   └── end_to_end/
│   ├── fixtures/
│   │   └── README.md
│   └── conftest.py
│
└── scripts/
    ├── ingest_documents.py
    ├── load_financials.py
    ├── build_indexes.py
    ├── run_assessment.py
    └── run_evaluation.py
```

---

# 12. Step 1 — Project scaffold only

## Goal

Create the repository structure and development skeleton.

**Do not implement business methods, RAG, database queries, calculations, agents, prompts, or UI behavior in this step.**

The purpose of Step 1 is to establish clean boundaries so later implementation can proceed safely.

## Step 1 tasks

The coding agent should:

1. Create the repository structure described above.
2. Create the Python package structure and `__init__.py` files.
3. Create `pyproject.toml`.
4. Configure a supported Python version.
5. Add development/test dependencies only as necessary for the scaffold.
6. Add `.gitignore`.
7. Add `.env.example` with placeholder configuration names only.
8. Add an initial `README.md`.
9. Create empty/stub domain model files.
10. Create empty/stub service/module files matching the architecture.
11. Create the test directory structure.
12. Add a minimal test confirming the package imports successfully.
13. Add benchmark filenames or empty placeholders where appropriate.
14. Add documentation placeholders under `docs/`.
15. Ensure formatting/lint/test commands can run without implementation code.

## Allowed content in stub modules

For Step 1, modules may contain:

- module docstrings;
- TODO comments;
- empty typed models if needed to validate package layout;
- abstract/protocol/interface declarations with no implementation;
- `NotImplementedError` placeholders only where an interface absolutely requires a callable body.

Do not create fake business logic simply to make the structure look complete.

## Explicit Step 1 non-goals

Do **not**:

- call an LLM;
- configure an LLM provider beyond environment-variable placeholders;
- fetch SEC documents;
- convert documents;
- build embeddings;
- build BM25 indexes;
- create a vector store;
- implement covenant extraction;
- implement formulas;
- implement production database queries;
- implement the monitoring agent;
- implement prompts;
- implement verification rules;
- implement Streamlit screens beyond an optional empty shell;
- implement chat;
- generate synthetic benchmark contents unless separately instructed.

---

# 13. Step 1 README requirements

The initial `README.md` should explain:

## Project

AI Credit Monitoring POC.

## Objective

Prove that legal/public retrieval, structured financial data, deterministic tools, and an agent workflow can generate a traceable covenant and early-warning assessment.

## Architecture

Include the high-level architecture diagram from this specification.

## Scope

Clearly separate:

- current capstone scope;
- long-term platform vision.

## Development philosophy

State:

- deterministic calculations;
- evidence-backed LLM outputs;
- independently testable layers;
- one orchestrator agent;
- analyst remains in control.

## Current implementation status

For Step 1:

```text
Status: Project scaffold only.
No business capabilities have been implemented yet.
```

---

# 14. Step 1 configuration placeholders

`.env.example` may define names such as:

```text
APP_ENV=
LOG_LEVEL=

LLM_PROVIDER=
LLM_MODEL=
LLM_API_KEY=

EMBEDDING_PROVIDER=
EMBEDDING_MODEL=

DATABASE_URL=

SEC_USER_AGENT=

VECTOR_STORE_PATH=
DATA_ROOT=
```

Do not include real credentials.

The scaffold must not require an API key to run import tests.

---

# 15. Step 1 acceptance criteria

Step 1 is complete when all of the following are true.

## Repository

- The documented folder structure exists.
- The Python package imports successfully.
- There are no circular imports introduced by the scaffold.
- The package structure clearly separates domain, retrieval, calculations, agents, verification, application, persistence, and web UI.

## Tooling

- Dependency installation succeeds.
- Formatting/lint commands are defined.
- `pytest` starts and passes the scaffold tests.
- The project does not require external services just to run tests.

## Architecture

- No financial calculation logic exists yet.
- No LLM calls exist yet.
- No retrieval implementation exists yet.
- No database workflow logic exists yet.
- No agent behavior exists yet.
- No UI business behavior exists yet.

## Documentation

- README explains project purpose and boundaries.
- The architecture document exists.
- The next implementation step is clearly identified.

---

# 16. Deliverable expected from the coding agent for Step 1

The coding agent should return:

1. a summary of the repository structure created;
2. files added;
3. dependencies added;
4. commands to install, lint, and test;
5. confirmation that tests pass;
6. any deviations from this specification and why;
7. no implementation of Step 2 unless explicitly requested.

---

# 17. Future implementation sequence

These steps provide direction for later prompts. They are **not part of Step 1**.

## Step 2 — Domain schemas and contracts

Finalize typed domain models and validation rules.

Primary outputs:

- borrower;
- source document;
- document chunk;
- evidence;
- covenant;
- reporting period;
- financial fact;
- calculation result;
- assessment;
- verification result.

## Step 3 — Document ingestion

Implement:

```text
source document
    ↓
fetch/load
    ↓
convert to Markdown
    ↓
clean
    ↓
preserve headings/tables
    ↓
chunk
    ↓
store metadata
```

Start with synthetic and manually downloaded SEC documents before automating discovery.

## Step 4 — Retrieval

Implement lexical retrieval first.

Then vector retrieval.

Then hybrid retrieval if both improve benchmark performance.

Required filters:

- borrower;
- document type;
- date/effective period;
- optional section.

Retrieval returns evidence objects, never only plain strings.

## Step 5 — Covenant extraction

Use retrieved evidence only.

Produce structured covenant records.

Store evidence IDs.

Do not extract unsupported fields from model intuition.

Handle amendment lineage.

## Step 6 — Financial data repository

Load structured quarterly financial data into the database.

Separate:

- raw/source facts;
- normalized facts;
- calculated metrics.

## Step 7 — Calculation tools

Implement deterministic, independently tested tools for the supported covenant types.

Examples:

```text
calculate_net_leverage
calculate_interest_coverage
calculate_headroom
compare_to_prior_quarters
```

Each calculation result should preserve:

- inputs;
- formula;
- output;
- threshold;
- status;
- validation errors.

## Step 8 — Monitoring workflow / agent

Input:

```text
borrower_id
reporting_period
```

The orchestrator should eventually:

1. load applicable covenant;
2. load required financial facts;
3. call deterministic tools;
4. retrieve relevant public context;
5. retrieve prior-quarter context;
6. assemble a structured draft assessment.

Use one orchestrator agent.

Do not introduce specialist agents unless a later evaluation demonstrates a concrete need.

## Step 9 — Verification

Verify:

- formulas;
- thresholds;
- effective covenant version;
- financial completeness;
- evidence support;
- unsupported claims.

A failed verification should return explicit issues.

## Step 10 — Analyst web application

Implement the POC web interface only after application services work independently.

Recommended first version:

```text
Borrower selector
Quarter selector
Run Assessment button

Assessment summary
Covenant table
Trend
Public context
Verification status

Evidence tab
Calculation tab
```

## Step 11 — Grounded analyst chat

Nice-to-have.

Add only when:

- assessments are reliable;
- evidence retrieval is working;
- deterministic tools are exposed;
- the chat can be scoped to one borrower/assessment.

## Step 12 — Evaluation and monitoring

Connect the existing POC test cases to automated regression evaluation.

Track:

- retrieval recall@k;
- extraction accuracy;
- calculation accuracy;
- alert classification;
- evidence completeness;
- unsupported claims;
- latency;
- model/tool failures.

---

# 18. POC benchmark data

Use both real and synthetic data.

## Real public data

Primary sources:

- SEC EDGAR credit agreements and amendments;
- SEC 10-K / 10-Q / 8-K filings;
- SEC Submissions API;
- SEC XBRL Company Facts;
- issuer investor-relations pages;
- issuer public website.

Real documents are used to validate retrieval on authentic, noisy material.

## Synthetic benchmark

Expected files:

```text
synthetic_loan_agreement.md
synthetic_amendment_01.md
synthetic_financials.csv
synthetic_events.jsonl
synthetic_expected_results.csv
synthetic_missing_data.csv
```

Synthetic data provides exact ground truth for:

- compliant scenarios;
- low headroom;
- breaches;
- amendments;
- trend deterioration;
- missing data;
- invalid denominator;
- irrelevant public information;
- contradictory evidence.

---

# 19. Core POC test categories

The eventual implementation must support the existing evaluation suite covering:

- legal retrieval;
- interest coverage retrieval;
- amendment retrieval;
- noise resistance;
- covenant extraction;
- effective-date applicability;
- missing legal data;
- financial-period selection;
- healthy calculation;
- near-breach calculation;
- breach calculation;
- invalid denominator;
- trend deterioration;
- public-event retrieval;
- irrelevant-event filtering;
- contradictory evidence;
- calculation verification;
- unsupported-claim verification;
- healthy end-to-end assessment;
- WATCH assessment;
- BREACH assessment;
- missing-data assessment;
- amended-covenant assessment.

Step 1 does not implement these tests. It should create locations for them.

---

# 20. Status model

Use a small, explicit status vocabulary.

For covenant/assessment outputs:

```text
COMPLIANT
WATCH
BREACH
INCOMPLETE
```

Potential implementation details can be finalized later.

Do not introduce a model-generated free-form status taxonomy.

---

# 21. Definition of POC completion

The capstone is complete when a credit analyst can trigger a quarterly assessment and the system reliably demonstrates the following end-to-end pattern:

```text
Legal / public documents
        +
Structured financial facts
        ↓
Retrieval
        ↓
Covenant interpretation
        +
Deterministic calculations
        ↓
Trend / context synthesis
        ↓
Verification
        ↓
Traceable analyst assessment
```

A simple web interface should make the result usable and inspectable.

Grounded analyst chat is a valuable extension, but it is not required to prove the core architecture.

---

# 22. Instruction to the coding agent

When this specification is first provided to a coding agent, use the following execution constraint:

> **Implement Step 1 only. Build the repository/project scaffold described in this specification. Do not implement any business method, RAG capability, financial calculation, database workflow, agent behavior, prompt, verification rule, or analyst-chat logic. Stop after the scaffold is created, tests/import checks pass, and the README/docs placeholders are in place. Report what you created and wait for the next implementation instruction.**
