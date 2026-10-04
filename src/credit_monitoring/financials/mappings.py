"""Allowlisted input metrics from the quarterly financial CSV.

The source does not declare monetary currency or scale, so monetary units remain
unspecified. Percentage values use percentage points (40 means 40%, not 0.40).
"""

FINANCIAL_METRICS = (
    "total_debt",
    "cash",
    "reported_ebitda",
    "eligible_addbacks",
    "cash_interest",
    "capex",
    "cash_taxes",
    "scheduled_principal",
    "rent",
    "revolver_availability_pct",
    "acquired_ebitda",
    "synergy_addback",
    "financials_debt",
    "compliance_certificate_debt",
)

METRIC_UNITS = {metric: None for metric in FINANCIAL_METRICS}
METRIC_UNITS["revolver_availability_pct"] = "percent"
