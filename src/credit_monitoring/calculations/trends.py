"""Date-aligned changes without filling missing reporting periods."""

from calendar import monthrange
from datetime import date


def previous_period(period_end: date, quarters: int = 1) -> date:
    """Shift a reporting date by quarters, preserving month-end dates."""
    month_index = period_end.year * 12 + period_end.month - 1 - 3 * quarters
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    last_day = monthrange(year, month)[1]
    is_month_end = period_end.day == monthrange(period_end.year, period_end.month)[1]
    day = last_day if is_month_end else min(period_end.day, last_day)
    return date(year, month, day)


def difference(current: float | None, previous: float | None) -> float | None:
    """Subtract known values; missing values remain missing."""
    return None if current is None or previous is None else current - previous


def growth(current: float | None, previous: float | None) -> float | None:
    """Return fractional growth against a positive prior value."""
    if current is None or previous is None or previous <= 0:
        return None
    return (current - previous) / previous
