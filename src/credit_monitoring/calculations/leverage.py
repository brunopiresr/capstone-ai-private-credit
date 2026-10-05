"""Deterministic leverage calculations with explicit contractual adjustments."""

from math import isfinite


class CalculationInputError(ValueError):
    """Required financial inputs are missing or unsuitable for calculation."""


def divide(numerator: float, denominator: float) -> float:
    """Calculate a ratio only when its denominator is positive."""
    if denominator <= 0:
        raise CalculationInputError("The ratio denominator must be positive.")
    ratio = numerator / denominator
    if not isfinite(ratio):
        raise CalculationInputError("The calculated ratio must be finite.")
    return ratio


def adjusted_ebitda(
    reported_ebitda: float,
    eligible_addbacks: float,
    cap_fraction: float | None = None,
) -> float:
    """Apply an optional addback cap to reported EBITDA."""
    if eligible_addbacks < 0:
        raise CalculationInputError("Eligible addbacks must not be negative.")
    if cap_fraction is not None:
        if reported_ebitda <= 0:
            raise CalculationInputError("Capped addbacks require positive reported EBITDA.")
        eligible_addbacks = min(eligible_addbacks, cap_fraction * reported_ebitda)
    return reported_ebitda + eligible_addbacks


def total_leverage(debt: float, ebitda: float) -> float:
    """Divide contractual debt by contractual EBITDA."""
    return divide(debt, ebitda)


def net_leverage(debt: float, cash: float, ebitda: float, cash_cap: float | None) -> float:
    """Deduct eligible cash, subject to the explicit cash-netting cap."""
    if cash < 0:
        raise CalculationInputError("Cash must not be negative.")
    eligible_cash = cash if cash_cap is None else min(cash, cash_cap)
    return divide(debt - eligible_cash, ebitda)


def pro_forma_leverage(
    debt: float,
    reported_ebitda: float,
    acquired_ebitda: float,
    synergy_addback: float,
    synergy_cap_fraction: float,
) -> float:
    """Include acquired EBITDA and contractually capped synergies."""
    if acquired_ebitda < 0 or synergy_addback < 0:
        raise CalculationInputError("Acquired EBITDA and synergies must not be negative.")
    denominator = (
        reported_ebitda
        + acquired_ebitda
        + min(synergy_addback, synergy_cap_fraction * acquired_ebitda)
    )
    return divide(debt, denominator)
