"""Allowlisted input metrics from the quarterly financial CSV.

Legacy records omit currency/scale; explicitly supplied metadata remains attached
to expanded records. Percentage values use percentage points (40 means 40%, not 0.40).
"""

from credit_monitoring.domain.financials import FINANCIAL_METRICS

METRIC_UNITS = {metric: None for metric in FINANCIAL_METRICS}
METRIC_UNITS["revolver_availability_pct"] = "percent"
