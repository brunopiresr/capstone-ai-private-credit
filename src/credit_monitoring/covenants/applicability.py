"""Select periods from explicit schedules without inventing applicability dates."""

import re
from datetime import date


def applies_to_period(entry, period_end: date) -> bool:
    """Named dates take precedence over ranges; undated entries cannot resolve a period."""
    if entry.period_end_dates:
        return period_end in entry.period_end_dates
    if entry.from_period_end is not None:
        return entry.from_period_end <= period_end and (
            entry.through_period_end is None or period_end <= entry.through_period_end
        )
    return False


def parse_ratio(value: str) -> float:
    """Normalize unambiguous ratio notation without accepting arbitrary expressions."""
    number = r"([+-]?\d+(?:\.\d+)?)"
    ratio = re.fullmatch(number + r"\s*(?:to|:)\s*(\d+(?:\.\d+)?)", value.strip(), re.I)
    if ratio:
        denominator = float(ratio[2])
        if denominator <= 0:
            raise ValueError("Ratio notation requires a positive denominator.")
        return float(ratio[1]) / denominator
    scalar = re.fullmatch(number + r"\s*(?:x|times)?", value.strip(), re.I)
    if scalar:
        return float(scalar[1])
    raise ValueError(f"Unsupported ratio notation: {value}")
