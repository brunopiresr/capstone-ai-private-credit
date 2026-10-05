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
