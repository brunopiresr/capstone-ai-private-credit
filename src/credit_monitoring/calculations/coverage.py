"""Deterministic interest and fixed-charge coverage calculations."""

from .leverage import divide


def interest_coverage(ebitda: float, cash_interest: float) -> float:
    """Measure EBITDA relative to cash interest."""
    return divide(ebitda, cash_interest)


def fixed_charge_coverage(
    ebitda: float,
    capex: float,
    cash_taxes: float,
    cash_interest: float,
    scheduled_principal: float,
    rent: float,
) -> float:
    """Measure cash earnings relative to the specified fixed charges."""
    return divide(ebitda - capex - cash_taxes, cash_interest + scheduled_principal + rent)
