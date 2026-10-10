"""Threshold comparisons and direction-aware headroom."""

from credit_monitoring.domain.analytics_base import ComparisonOperator
from credit_monitoring.observability.logging import logged_operation


@logged_operation()
def compare_threshold(actual: float, threshold: float, operator: ComparisonOperator) -> bool:
    """Apply the source-supported comparison without rounding the inputs."""
    match operator:
        case "<":
            return actual < threshold
        case "<=":
            return actual <= threshold
        case ">":
            return actual > threshold
        case ">=":
            return actual >= threshold
        case "=":
            return actual == threshold


@logged_operation()
def calculate_headroom(
    actual: float,
    threshold: float,
    operator: ComparisonOperator,
) -> float | None:
    """Return signed headroom; equality tests have no directional headroom."""
    if operator in ("<", "<="):
        return threshold - actual
    if operator in (">", ">="):
        return actual - threshold
    return None
