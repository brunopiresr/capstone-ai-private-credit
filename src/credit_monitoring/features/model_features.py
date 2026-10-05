"""Convert typed covenant features into the same columns for training and inference."""

from math import isfinite
from statistics import mean

from credit_monitoring.domain.risk_features import BorrowerRiskFeatures

MODEL_FEATURE_SCHEMA_VERSION = "logistic-v1"
FORMULA_FAMILIES = (
    "net_leverage",
    "total_leverage",
    "pro_forma_leverage",
    "interest_coverage",
    "fixed_charge_coverage",
)
NUMERIC_FIELDS = (
    "actual_value",
    "threshold",
    "metric_change_qoq",
    "headroom_change_qoq",
    "threshold_change_qoq",
)
STATUSES = (
    "compliant",
    "breach",
    "waived",
    "not_tested",
    "incomplete",
    "unresolved",
    "unsupported",
)
BORROWER_FIELDS = (
    "reported_ebitda_growth_qoq",
    "reported_ebitda_growth_yoy",
    "total_debt_growth_qoq",
    "total_debt_growth_yoy",
    "liquidity",
    "liquidity_change_qoq",
)


def _mean_present(values: list[float | None]) -> float | None:
    """Average observed values without substituting for missing observations."""
    observed = [value for value in values if value is not None]
    return mean(observed) if observed else None


def model_feature_row(features: BorrowerRiskFeatures) -> dict[str, float | None]:
    """Aggregate by formula family, excluding identities and future outcomes.

    Unknown formula families require an explicit feature-schema upgrade. Missingness
    columns have fixed positions even when training never observed a particular gap.
    """
    features = BorrowerRiskFeatures.model_validate(features)
    if any(covenant.covenant_type not in FORMULA_FAMILIES for covenant in features.covenants):
        raise ValueError("Unsupported covenant family for the model feature schema.")
    row = {field: getattr(features, field) for field in BORROWER_FIELDS}
    row["information_availability_known"] = float(features.information_availability_known)
    for family in FORMULA_FAMILIES:
        covenants = [item for item in features.covenants if item.covenant_type == family]
        prefix = f"{family}__"
        row[prefix + "covenant_count"] = float(len(covenants))
        for field in NUMERIC_FIELDS:
            row[prefix + "mean_" + field] = _mean_present(
                [getattr(item, field) for item in covenants]
            )
        normalized_headroom = [
            item.headroom / abs(item.threshold)
            for item in covenants
            if item.headroom is not None and item.threshold is not None and item.threshold != 0
        ]
        row[prefix + "min_normalized_headroom"] = (
            min(normalized_headroom) if normalized_headroom else None
        )
        for status in STATUSES:
            row[prefix + status + "_count"] = float(
                sum(item.compliance_status == status for item in covenants)
            )
        row[prefix + "basis_changed_count"] = float(sum(item.basis_changed for item in covenants))
        for field in ("previous_breach", "previous_waiver"):
            row[prefix + field + "_count"] = float(
                sum(getattr(item, field) is True for item in covenants)
            )
            row[prefix + field + "_unknown_count"] = float(
                sum(getattr(item, field) is None for item in covenants)
            )
    for column, value in list(row.items()):
        row[column + "__missing"] = float(value is None)
    if any(value is not None and not isfinite(value) for value in row.values()):
        raise ValueError("Model features must be finite or missing.")
    return row


def has_usable_current_inputs(features: BorrowerRiskFeatures) -> bool:
    """Require at least one current covenant with an actual and applicable threshold."""
    return any(
        item.actual_value is not None and item.threshold is not None for item in features.covenants
    )


FEATURE_COLUMNS = tuple(
    model_feature_row(
        BorrowerRiskFeatures(
            borrower_id="schema", period_end="2025-03-31", information_cutoff="2025-03-31"
        )
    )
)
