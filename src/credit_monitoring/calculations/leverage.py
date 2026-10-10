"""Deterministic leverage calculations with explicit contractual adjustments."""

import logging
from math import isfinite

from credit_monitoring.observability.logging import log_event, logged_operation

logger = logging.getLogger(__name__)


class CalculationInputError(ValueError):
    """Required financial inputs are missing or unsuitable for calculation."""


@logged_operation()
def divide(numerator: float, denominator: float) -> float:
    """Calculate a ratio only when its denominator is positive."""
    if denominator <= 0:
        raise CalculationInputError("The ratio denominator must be positive.")
    ratio = numerator / denominator
    if not isfinite(ratio):
        raise CalculationInputError("The calculated ratio must be finite.")
    return ratio


@logged_operation()
def adjusted_ebitda(
    reported_ebitda: float,
    eligible_addbacks: float,
    cap_fraction: float | None = None,
) -> float:
    """Apply an optional addback cap to reported EBITDA."""
    if eligible_addbacks < 0:
        raise CalculationInputError("Eligible addbacks must not be negative.")
    original_addbacks = eligible_addbacks
    if cap_fraction is not None:
        if reported_ebitda <= 0:
            raise CalculationInputError("Capped addbacks require positive reported EBITDA.")
        eligible_addbacks = min(eligible_addbacks, cap_fraction * reported_ebitda)
    log_event(
        logger,
        "apply_addback_cap",
        inputs={
            "reported_ebitda": reported_ebitda,
            "eligible_addbacks": original_addbacks,
            "cap_fraction": cap_fraction,
        },
        outputs={"eligible_addbacks": eligible_addbacks},
    )
    return reported_ebitda + eligible_addbacks


@logged_operation()
def total_leverage(debt: float, ebitda: float) -> float:
    """Divide contractual debt by contractual EBITDA."""
    return divide(debt, ebitda)


@logged_operation()
def net_leverage(debt: float, cash: float, ebitda: float, cash_cap: float | None) -> float:
    """Deduct eligible cash, subject to the explicit cash-netting cap."""
    if cash < 0:
        raise CalculationInputError("Cash must not be negative.")
    eligible_cash = cash if cash_cap is None else min(cash, cash_cap)
    log_event(
        logger,
        "apply_cash_cap",
        inputs={"debt": debt, "cash": cash, "cash_cap": cash_cap},
        outputs={"eligible_cash": eligible_cash, "net_debt": debt - eligible_cash},
    )
    return divide(debt - eligible_cash, ebitda)


@logged_operation()
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
    log_event(
        logger,
        "apply_synergy_cap",
        inputs={
            "reported_ebitda": reported_ebitda,
            "acquired_ebitda": acquired_ebitda,
            "synergy_addback": synergy_addback,
            "synergy_cap_fraction": synergy_cap_fraction,
        },
        outputs={
            "eligible_synergies": min(synergy_addback, synergy_cap_fraction * acquired_ebitda),
            "pro_forma_ebitda": denominator,
        },
    )
    return divide(debt, denominator)
