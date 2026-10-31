"""Source financial records and a normalized, queryable facts view."""

import sqlite3

from credit_monitoring.domain.financials import FINANCIAL_METADATA
from credit_monitoring.financials.mappings import FINANCIAL_METRICS, METRIC_UNITS


def initialize_financial_schema(connection: sqlite3.Connection) -> None:
    """Create the financial schema without committing the caller's transaction."""
    metric_columns = ",\n".join(f"{metric} REAL" for metric in FINANCIAL_METRICS)
    connection.execute(f"""
        CREATE TABLE IF NOT EXISTS quarterly_financials (
            borrower_id TEXT NOT NULL,
            period_end TEXT NOT NULL,
            {metric_columns},
            notes TEXT,
            source_file TEXT NOT NULL,
            source_row INTEGER NOT NULL,
            loaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            PRIMARY KEY (borrower_id, period_end)
        ) STRICT
    """)
    existing = {row[1] for row in connection.execute("PRAGMA table_info(quarterly_financials)")}
    for name in (*FINANCIAL_METRICS, *FINANCIAL_METADATA):
        if name not in existing:
            kind = "REAL" if name in FINANCIAL_METRICS else "TEXT"
            connection.execute(f"ALTER TABLE quarterly_financials ADD COLUMN {name} {kind}")
    # Identifiers and units come only from the fixed metric mapping above.
    selects = []
    for metric in FINANCIAL_METRICS:
        unit = "NULL" if METRIC_UNITS[metric] is None else f"'{METRIC_UNITS[metric]}'"
        if metric != "revolver_availability_pct":
            unit = (
                "CASE WHEN scale IS NULL THEN NULL ELSE "
                "trim(coalesce(currency, '') || ' ' || scale) END"
            )
        selects.append(f"""
            SELECT borrower_id, period_end, '{metric}' AS metric_name,
                   {metric} AS value, {unit} AS unit, source_file, source_row,
                   CASE WHEN {metric} IS NULL THEN 'missing' ELSE 'provided' END
                       AS data_quality_status
            FROM quarterly_financials
        """)
    connection.execute("DROP VIEW IF EXISTS financial_facts")
    connection.execute("CREATE VIEW financial_facts AS " + " UNION ALL ".join(selects))
