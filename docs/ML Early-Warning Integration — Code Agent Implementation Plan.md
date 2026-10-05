# ML Early-Warning Integration — Implementation Plan

## Objective and implementation boundaries

Add an optional ML service after period-specific covenant resolution, deterministic calculations,
and persisted history. The implementation uses existing structured extractions, financial storage,
and synthetic covenant inputs. There is no separate SEC integration milestone or new ingestion
pipeline. The document agent and mocked analyst UI keep their existing behavior.

The implementation establishes application services and tests, generates independent simulated
histories from the PoC templates, trains a Logistic Regression baseline, and integrates its saved
artifact at runtime. It supports net, total, and pro-forma leverage, interest coverage, and
fixed-charge coverage. Outcome labels and artifacts are offline files; SHAP, additional models,
ML-agent orchestration and UI integration remain later work. A prediction never replaces
deterministic compliance.

Follow PEP 8 and existing project conventions. Favor clarity over brevity, use readable names and
simple control flow, maintain docstrings with their code, and keep comments direct and useful.
Review changes for style consistency. Do not create git commits. Investigation of monitoring-agent
timeouts and existing extraction inconsistencies is out of scope.

## Target flow and historical data

```text
Existing structured covenants → Period-specific resolution ──┐
                                                             ↓
Existing financial data → Deterministic calculations → Stored results
                                                             ↓
                                    Current + historical structured state
                                                             ↓
                                         Feature snapshot → ML prediction
                                                             ↓
                                         Risk/trend assessment → Verification
```

Financial history exists independently of covenant resolution. For every historical period,
resolve the terms applicable to that period, combine them with its financial inputs, and persist a
`CovenantResult`. Never apply current terms to all previous periods. Save current calculations before
building features. Each assessment backfills available periods chronologically within a new run.

RAG remains available for source evidence and document questions. Calculations, history, features,
and predictions come from structured services and repositories. Assessments read complete current
extractions; they do not download documents or call extraction models.

## Domain models across layers

| Layer | Domain models | Persistence |
| --- | --- | --- |
| Source evidence | Existing `RetrievedRecord`, `SourceEvidence`, documents and chunks | Existing source files/storage |
| Structured extraction | Existing `CovenantExtraction`, `CovenantTerm`, `ThresholdScheduleEntry`, `AgreementAmendment`, `CovenantTestingEvent`, `ComplianceDisclosure`, `CreditFacilityTerm`, `FinancialMetricDefinition`, `ReportedFinancialValue` | Existing extraction cache |
| Resolved credit state | `ResolvedCovenant`, `FinancialPeriod`; `CovenantResolution` represents successful resolution or abstention | Existing financial storage; applied terms copied into results |
| Derived analytics | `CovenantResult`, `CovenantRiskFeatures`, `BorrowerRiskFeatures`, `BorrowerFeatureSnapshot`, `RiskPrediction`, `RiskAssessment` | Results, feature snapshots, predictions persisted; assessment returned |
| Offline training | Simulated borrower metadata, feature rows, outcome labels, dataset manifest, fitted preprocessing/classifier and model manifest | Generated CSV/JSONL/JSON files and local joblib artifacts; no additional SQL tables |
| Processing and verification | Existing `DocumentExtraction`, `ExtractionResult`, `ValidationReport`, `ValidationIssue`, and batch wrappers | Existing processing state; issues captured in results |
| Agent interaction | Existing `AgentAnswer`, `SourceReference`, `ToolExecution` | Existing behavior |

Borrower, agreement, covenant, version, period, run, and snapshot identifiers connect these records.
A standalone `Borrower` model remains outside this implementation.

## Implementation order and service interfaces

### 1. Typed inputs and storage

Reuse existing financial dictionaries through `FinancialPeriod.from_repository_row()`, which
allowlists metric names and excludes notes. `SyntheticCovenantReader` reads the existing covenant CSV
and uses explicit formula mappings. `ExtractionCovenantReader` consumes existing extraction models
through `ExtractionBinding` records identifying borrower, agreement, covenant, document, and exact
covenant name. Optional `CalculationRules` declare an approved formula and measurement basis.

Do not automatically join synthetic borrowers to SEC issuers, infer formulas from name similarity,
replace existing repository APIs, or duplicate extraction records. Repeated identical or conflicting
applicable document candidates remain unresolved rather than selecting an arbitrary record.

### 2. Period-specific covenant resolution

Select explicit effective ranges and schedules. Named schedule dates take precedence over ranges;
undated schedules cannot resolve applicability. Preserve amendment versions, testing conditions,
waivers, suspensions, and supporting evidence. Missing, stale, conflicting, unsupported, or
ambiguous inputs return explicit resolution issues. Selected extraction quotes and citations must
match the stored document. This validation does not repair extraction output.

### 3. Deterministic calculations and historical results

Use allowlisted implementations; never execute formula strings. Support contractual cash-netting,
addback, and synergy caps, and preserve missing inputs and debt-source conflicts as abstentions.

Maximum-covenant headroom is `threshold - actual`; minimum-covenant headroom is `actual - threshold`.
Equality tests have no directional headroom. Strict comparison boundaries remain strict. Invalid
or nonpositive denominators and nonfinite results cannot establish compliance.

Waived and inactive tests retain their applicability state. A calculable informational actual does
not establish an active compliance conclusion. Source-reported actuals can be compared to resolved
thresholds, but are labeled `reported`, never independently `calculated`.

### 4. Feature engineering

`RiskFeatureBuilder` reads persisted calculation inputs from a bounded assessment run, not mutable
financial rows or raw documents. Support multiple separate covenants per borrower-period.

Calculate comparable metric/headroom changes and reported EBITDA/total debt growth against exact
prior-quarter/year dates. Preserve missing history and unknown prior breach/waiver state as null.
Suppress ratio/headroom changes across incompatible formulas, units, operators, or result bases.
Expose threshold changes separately. Revenue, liquidity, and unavailable metrics remain missing.

Exclude financial notes, borrower scenarios, expected results, gold labels, and future outcomes
from feature vectors and narrative inputs.

### 5. ML protocol, factory, and exact snapshots

```python
class RiskModel(Protocol):
    def predict(self, features: BorrowerRiskFeatures) -> RiskPrediction:
        ...
```

`RiskModelFactory` registers constructors and creates a configured implementation without changing
workflow code. Defaults are `ml_enabled=False` and `RiskModelConfig(type="stub", version="v1")`.

The deterministic stub returns status `stub`, null probabilities/scores, and risk level `unknown`.
It proves integration, not forecasting accuracy. The initial target is `any_covenant_breach` in the
next quarter. Reject unexpected horizons, identity mismatches, invalid probability bounds,
nonfinite output, and fabricated stub forecasts.

Persist the exact feature snapshot before invoking a model. Pass a separate copy to the model so
model-side mutation cannot change the stored vector. Model or prediction-storage failure leaves
deterministic results available with explicit failure metadata.

### 6. Assessment, narrative, and verification

```python
AssessmentService.assess(
    borrower_id: str,
    period_end: date,
    information_cutoff: date,
    *,
    ml_enabled: bool | None = None,
) -> RiskAssessment

RiskFeatureBuilder.build(
    borrower_id: str,
    period_end: date,
    information_cutoff: date,
    *,
    assessment_run_id: str,
) -> BorrowerRiskFeatures
```

A null ML override uses `AssessmentSettings.ml_enabled`, which defaults to false. Explicit false
disables ML even if settings enable it. Constructor dependencies include a financial repository,
covenant reader, settings, optional model factory, and optional narrator.

Return current results, bounded historical results, optional feature snapshot/prediction, issues,
narrative, and verification. `AssessmentNarrator.summarize(context)` receives a detached context
containing current financials, deterministic results, history, features, predictions, and evidence.
It cannot mutate authoritative results. The default narrative is deterministic and requires no LLM.

Verification replays stored calculations, checks identities, provenance presence, cutoff bounds,
and model metadata. It does not certify semantic entailment of arbitrary injected narrative prose.
Source availability remains explicitly unknown when not supplied.

### 7. Independent synthetic training dataset

`generate_dataset(source_directory, output_directory, seed=42, borrowers_per_scenario=50)` generates
600 simulated borrowers and 4,800 quarterly observations from 2025 Q1 through 2026 Q4. Each existing
PoC scenario supplies 50 templates with varied scale, initial headroom, trends, recoveries and
shocks. Original files remain unchanged. Preserve the existing contractual formulas, caps,
amendments, holiday and springing condition. Complete numeric inputs only for newly simulated
borrowers; preserve missing-input and conflict examples and original SYN010 abstentions.

Write borrower metadata, financial inputs, terms, typed features, flattened training rows,
next-quarter outcomes, reproducible calculation records and a manifest to
`data/synthetic_training/`. The manifest records the seed, generator/schema versions, simulation
assumptions, source/output checksums, counts, partition labels and missingness. Reporting-date
availability is a disclosed simulation assumption; actual publication dates remain unknown.

Calculate outcomes through the existing covenant services. A next-quarter established breach is
`1`. A negative label requires at least one active test and all relevant outcomes establishing no
breach. Missing, unresolved and wholly inactive outcomes remain null with reasons. The final
quarter is unlabeled. Gold labels and notes do not define generated outcomes or features.

At default size, assign 35 training, 7 validation and 8 test borrowers within each scenario,
reproducibly shuffled. Training feature periods end in 2025 Q3, so outcomes end by 2025 Q4.
Validation features are 2026 Q1-Q2 and test features 2026 Q3. Other periods and unknown labels
receive split `unused`. Current inputs unusable at runtime are also excluded from evaluation.
Borrowers are disjoint across partitions. Generation uses temporary analytics storage.

### 8. Shared model feature conversion

`model_feature_row(BorrowerRiskFeatures)` defines the ordered numeric contract `logistic-v1`,
distinct from typed feature schema `v1`. Use the same converter for dataset export and prediction.
Aggregate covenants by the five supported formula families: count, mean actual/threshold,
minimum headroom divided by absolute threshold, mean comparable changes, compliance-state
counts, prior breach/waiver counts and unknown counts, and basis-change counts. Include existing
borrower growth/liquidity fields and the information-availability flag. Add fixed missingness
columns. Reject unsupported families and nonfinite derived values. Do not include IDs, scenarios,
notes, generation parameters or future outcomes. Do not fit preprocessing while exporting data.

### 9. Offline Logistic Regression training and artifact

`train_model(dataset_directory, artifact_directory, version="v1", seed=42)` validates schema,
checksum, unique borrower-period keys, observed binary targets, partition identity and temporal
boundaries. Train only eligible training rows; require both classes. Fit median imputation with
missingness indicators and retained empty columns, standard scaling, and Logistic Regression
(`C=1`, `max_iter=1000`, no class weighting). Validation and test data do not affect fitting.

Report partition counts, prevalence, precision/recall at 0.5, average precision (PR-AUC), ROC-AUC,
log loss and Brier score, plus a constant training-prevalence baseline. AUC metrics are null when
required classes are absent; empty partitions carry a reason. Evaluation measures the simulation.

Save `pipeline.joblib` and `manifest.json` under `data/models/logistic_regression/v1/` by default.
Metadata includes model/version, ordered columns, feature schemas, target/horizon, seed,
synthetic origin, Python/library versions, dataset fingerprint, evaluation, and pipeline SHA-256.
Load trusted local outputs of this workflow. Generated datasets/artifacts are ignored by Git.
Declare the optional `ml` extra with locked scikit-learn, NumPy, SciPy and joblib versions.
Training uses CPU resources and never invokes an LLM.

### 10. Trained-model runtime integration

Register `LogisticRegressionRiskModel` under factory type `logistic_regression`. Configure
`RiskModelConfig(type="logistic_regression", version="v1", artifact_path=...)`; artifact paths
identify directories. Validate metadata, numerical-library/Python compatibility and the pipeline
checksum before loading. Load once per adapter instance and apply the shared converter and saved
preprocessing. Validate the loaded pipeline's feature order and binary classifier classes.

Return next-quarter breach probability with version/hash. Leave risk level unknown and drivers
empty until policies are validated; deterioration probability and anomaly score remain null.
Without usable current numeric covenant inputs, return `unavailable`. Missing, incompatible or
corrupt artifacts preserve deterministic assessments through existing failure handling.

Add assessment CLI options `--model-type`, `--model-version`, and `--model-artifact`. Model execution
still requires `--ml`; default settings retain disabled ML and the stub. Training does not activate
a model automatically. The default narrative identifies synthetic training. Save predictions in
the existing `risk_predictions` table linked to their exact feature snapshots; no migration or
new prediction table is required. Additional models can later register without changing the
assessment workflow; Isolation Forest needs distinct anomaly target semantics.

## Persisted entities and SQLite DDL

Keep the existing extraction and financial databases. Store the three new analytics tables together
in `data/processed/analytics.sqlite3`, separate from the financial database.

| Table | Stored entity |
| --- | --- |
| `document_extractions` | Complete extraction and processing state |
| `document_extraction_sections` | Section extraction cache |
| `quarterly_financials` | Current financial snapshot per borrower-period |
| `covenant_results` | Historical calculations with applied terms, exact inputs, and evidence |
| `risk_feature_snapshots` | Exact model input and supporting result identifiers |
| `risk_predictions` | Model output linked to its feature snapshot |

The existing `financial_facts` view is retained. `ResolvedCovenant` is captured inside each result;
no separate resolved-covenant table is required. `RiskAssessment` is returned rather than persisted.
Outcome labels and training manifests are offline files, not additional SQL entities.

### Existing tables — reference DDL

```sql
CREATE TABLE document_extractions (
                    document_id TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    configuration_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_sections INTEGER NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (document_id, cache_key)
                );

CREATE TABLE document_extraction_sections (
                    document_id TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    section_index INTEGER NOT NULL,
                    result_json TEXT NOT NULL,
                    PRIMARY KEY (document_id, cache_key, section_index),
                    FOREIGN KEY (document_id, cache_key)
                        REFERENCES document_extractions(document_id, cache_key) ON DELETE CASCADE
                );

CREATE TABLE quarterly_financials (
            borrower_id TEXT NOT NULL,
            period_end TEXT NOT NULL,
            total_debt REAL,
cash REAL,
reported_ebitda REAL,
eligible_addbacks REAL,
cash_interest REAL,
capex REAL,
cash_taxes REAL,
scheduled_principal REAL,
rent REAL,
revolver_availability_pct REAL,
acquired_ebitda REAL,
synergy_addback REAL,
financials_debt REAL,
compliance_certificate_debt REAL,
            notes TEXT,
            source_file TEXT NOT NULL,
            source_row INTEGER NOT NULL,
            loaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            PRIMARY KEY (borrower_id, period_end)
        ) STRICT
    ;
```

### New analytics tables

The executable schema is `src/credit_monitoring/persistence/analytics_schema.sql`.

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS covenant_results (
    result_id TEXT PRIMARY KEY,
    assessment_run_id TEXT NOT NULL,
    borrower_id TEXT NOT NULL,
    agreement_id TEXT,
    covenant_id TEXT NOT NULL,
    covenant_version TEXT,
    covenant_type TEXT NOT NULL,
    period_end TEXT NOT NULL,
    information_cutoff TEXT NOT NULL,
    actual_value REAL,
    threshold REAL,
    operator TEXT CHECK (operator IN ('<', '<=', '>', '>=', '=')),
    unit TEXT,
    headroom REAL,
    compliance_status TEXT NOT NULL CHECK (compliance_status IN (
        'compliant', 'breach', 'waived', 'not_tested', 'incomplete', 'unresolved', 'unsupported'
    )),
    calculation_version TEXT NOT NULL,
    resolved_covenant_json TEXT CHECK (
        resolved_covenant_json IS NULL OR json_valid(resolved_covenant_json)
    ),
    financial_inputs_json TEXT NOT NULL CHECK (json_valid(financial_inputs_json)),
    evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
    issues_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(issues_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (assessment_run_id, borrower_id, covenant_id, period_end)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_covenant_history
    ON covenant_results (borrower_id, covenant_id, period_end, information_cutoff);

CREATE TABLE IF NOT EXISTS risk_feature_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    assessment_run_id TEXT NOT NULL,
    borrower_id TEXT NOT NULL,
    period_end TEXT NOT NULL,
    information_cutoff TEXT NOT NULL,
    feature_schema_version TEXT NOT NULL,
    features_json TEXT NOT NULL CHECK (json_valid(features_json)),
    source_result_ids_json TEXT NOT NULL CHECK (json_valid(source_result_ids_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_feature_history
    ON risk_feature_snapshots (borrower_id, period_end);

CREATE TABLE IF NOT EXISTS risk_predictions (
    prediction_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES risk_feature_snapshots(snapshot_id),
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    model_artifact_hash TEXT,
    prediction_target TEXT NOT NULL DEFAULT 'any_covenant_breach',
    horizon_quarters INTEGER NOT NULL DEFAULT 1 CHECK (horizon_quarters > 0),
    prediction_status TEXT NOT NULL CHECK (prediction_status IN (
        'stub', 'complete', 'unavailable', 'failed'
    )),
    breach_probability REAL CHECK (breach_probability BETWEEN 0 AND 1),
    deterioration_probability REAL CHECK (deterioration_probability BETWEEN 0 AND 1),
    anomaly_score REAL,
    risk_level TEXT NOT NULL CHECK (risk_level IN ('low', 'medium', 'high', 'unknown')),
    top_drivers_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(top_drivers_json)),
    error TEXT,
    generated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_prediction_snapshot ON risk_predictions (snapshot_id);
```

### Persistence rules

- Generate UUIDs for runtime runs, results, snapshots, and predictions. Every assessment rerun
  receives a new run ID. Offline simulations use deterministic identifiers and timestamps so
  regenerated dataset files are reproducible.
- Use stable agreement-specific covenant identifiers. Synthetic IDs include borrower and covenant.
- Analytics repositories append records; they do not update or delete earlier runs. SQL administrators
  can still modify tables directly; immutability is enforced by the repository API.
- Save an entire calculation run in one transaction. Capture exact financial inputs because source
  financial reloads replace matching borrower-period rows.
- Predictions obtain borrower/period from their linked feature snapshot.
- Validate JSON shape and referenced result ownership, run, and period bounds in application code.
  JSON references are not SQL foreign keys. Source references do not require cross-database joins.
- Use ISO dates, UTC timestamps, and null for unknown information.

## Existing-data limits and later work

Existing-source assessments use the supplied inputs only. `SYN010` lacks numeric FCCR inputs:
its inactive Q2 test returns `not_tested`,
and its active Q3 test returns `incomplete`. Do not obtain 1.10x from notes or gold labels and do not
invent replacement benchmark rows. Separately generated borrowers use explicit simulation
assumptions. This original-source abstention differs from the supplied benchmark label.

Reporting dates and financial load timestamps do not establish historical information availability.
`information_cutoff` records the requested cutoff, not proof of point-in-time accuracy. Apply known
availability dates and identify missing ones. Historical restatement vintages are not reconstructed;
exact run inputs and feature snapshots preserve reproducibility from the time they are recorded.

The synthetic baseline supplies separately defined outcomes and temporal evaluation. Reliable
real-world predictions still require representative historical data and independently verified
outcomes. Anomaly detection does not substitute for a calibrated breach-probability model.
Boosting, anomaly models, SHAP, UI changes and ML-agent orchestration remain later work.

## Tests and acceptance criteria

- Existing synthetic cases cover leverage, interest coverage, FCCR, caps, pro-forma adjustments,
  amendments, waivers, springing conditions, and conflicting debt sources.
- Gold labels are test expectations only; early-warning labels do not redefine compliance.
- Verify missing inputs, invalid denominators, exact threshold boundaries, missing quarters,
  multiple covenants, and incompatible measurement bases.
- Verify existing stored extractions are consumed without reprocessing, reported actuals remain
  distinguishable, invalid evidence/ambiguous terms abstain, and mappings prevent borrower leakage.
- Verify results exist before feature construction; snapshots and earlier runs survive source reloads.
- Exercise schema initialization, JSON constraints, duplicate/atomic inserts, reference ownership,
  probability bounds, and snapshot foreign keys against temporary SQLite files.
- Exercise model replacement, malformed outputs, model/storage failures, and detached narrator inputs.
- Confirm calculations remain available when ML is disabled or fails. Stub probabilities remain null.
- Confirm existing processing APIs and mocked UI remain independent. No commits are created.
- Verify reproducible generation, source preservation, contractual edge cases and unknown outcomes.
- Verify borrower/temporal separation and that changing future inputs cannot change earlier features.
- Verify held-out inputs cannot change fitted preprocessing or classifier parameters.
- Verify shared conversion, multiple-covenant aggregation, artifact round trips, schema/version/hash
  rejection, missing-current-input abstention, and persisted trained predictions/failure records.
- Smoke test the full generator, trainer, financial loader and assessment CLI workflow.

Run the scoped checks without the excluded monitoring-agent and local SEC evaluation investigations:

```bash
uv run --extra ml pytest tests/unit tests/integration tests/test_package_import.py \
  --ignore=tests/unit/covenants/test_monitoring_agent.py
uv run ruff check .
```

Generate and train the baseline separately:

```bash
uv sync --extra ml --locked
uv run --extra ml python scripts/generate_training_dataset.py
uv run --extra ml python scripts/train_risk_model.py
```

See [training and runtime usage](ml_early_warning.md#generate-and-train-the-synthetic-baseline) for
generated file contracts, CLI options, artifact selection and an isolated assessment example.

## Usage

First load the existing financial CSV using the existing loader, if it has not been loaded:

```bash
uv run python -m credit_monitoring.ingestion.loaders.financials \
  --csv data/synthetic_quarterly_financials.csv \
  --db data/processed/financials.sqlite3
```

Run the service through the command entry point; omit `--ml` for calculations only:

```bash
uv run python scripts/run_assessment.py \
  --borrower-id SYN002 \
  --period-end 2025-09-30 \
  --information-cutoff 2025-09-30 \
  --ml
```

The command prints the complete typed assessment and appends analytics records. It does not call
an LLM, download sources, change benchmark CSVs, or connect the mocked analyst UI.
