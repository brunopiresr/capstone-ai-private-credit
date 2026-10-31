"""Calculate one covenant while preserving abstentions and exact inputs."""

import logging
from datetime import date
from decimal import Decimal
from math import isfinite

from credit_monitoring.domain.assessment import (
    CovenantResolution,
    CovenantResult,
    FinancialPeriod,
    ResolvedCovenant,
)
from credit_monitoring.observability.assessment import (
    calculation_inputs,
    covenant_output,
)
from credit_monitoring.observability.logging import log_event, log_step, logging_context

from .coverage import fixed_charge_coverage, interest_coverage
from .headroom import calculate_headroom, compare_threshold
from .leverage import (
    CalculationInputError,
    adjusted_ebitda,
    net_leverage,
    pro_forma_leverage,
    total_leverage,
)

logger = logging.getLogger(__name__)


def _metric(financials: FinancialPeriod, name: str) -> float:
    value = financials.metrics.get(name)
    log_event(
        logger,
        "financial_metric",
        inputs={"metric": name},
        outputs={"value": value, "status": "missing" if value is None else "provided"},
    )
    if value is None:
        raise CalculationInputError(f"Missing financial input: {name}.")
    return value


def _debt(financials: FinancialPeriod) -> float:
    figures = [
        financials.metrics.get(name)
        for name in (
            "total_debt",
            "financials_debt",
            "compliance_certificate_debt",
        )
    ]
    provided = [value for value in figures if value is not None]
    log_event(
        logger,
        "debt_sources",
        inputs=dict(zip(("total_debt", "financials_debt", "compliance_certificate_debt"), figures)),
        outputs={"conflict": len(set(provided)) > 1},
    )
    if len(set(provided)) > 1 or financials.debt_source_status == "CONFLICTING":
        raise CalculationInputError("DEBT_SOURCE_CONFLICT: debt sources disagree.")
    return _metric(financials, "total_debt")


def calculate_actual(covenant: ResolvedCovenant, financials: FinancialPeriod) -> float:
    """Dispatch only typed, allowlisted formulas; never interpret formula text."""
    if covenant.calculation_contract == "bundle_v1":
        return _bundle_actual(covenant, financials)
    reported_ebitda = _metric(financials, "reported_ebitda")
    if covenant.formula == "pro_forma_leverage":
        if covenant.synergy_cap_fraction is None:
            raise CalculationInputError("Missing contractual synergy cap.")
        return pro_forma_leverage(
            _debt(financials),
            reported_ebitda,
            _metric(financials, "acquired_ebitda"),
            _metric(financials, "synergy_addback"),
            covenant.synergy_cap_fraction,
        )
    ebitda = adjusted_ebitda(
        reported_ebitda,
        _metric(financials, "eligible_addbacks"),
        covenant.addback_cap_fraction,
    )
    match covenant.formula:
        case "total_leverage":
            return total_leverage(_debt(financials), ebitda)
        case "net_leverage":
            return net_leverage(
                _debt(financials),
                _metric(financials, "cash"),
                ebitda,
                covenant.cash_netting_cap,
            )
        case "interest_coverage":
            return interest_coverage(ebitda, _metric(financials, "cash_interest"))
        case "fixed_charge_coverage":
            return fixed_charge_coverage(
                ebitda,
                _metric(financials, "capex"),
                _metric(financials, "cash_taxes"),
                _metric(financials, "cash_interest"),
                _metric(financials, "scheduled_principal"),
                _metric(financials, "rent"),
            )
        case _:
            raise CalculationInputError("Unsupported contractual calculation formula.")


def _bundle_divide(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        raise CalculationInputError("The ratio denominator must be positive.")
    ratio = float(Decimal(str(numerator)) / Decimal(str(denominator)))
    if not isfinite(ratio):
        raise CalculationInputError("The calculated ratio must be finite.")
    return ratio


def _bundle_actual(covenant: ResolvedCovenant, financials: FinancialPeriod) -> float:
    base = _metric(financials, "reported_ebitda")
    addbacks = _metric(financials, "eligible_addbacks")
    synergies = _metric(financials, "synergy_addback")
    acquired = _metric(financials, "acquired_ebitda")
    if covenant.addback_cap_fraction is not None:
        addbacks = min(addbacks, max(base, 0) * covenant.addback_cap_fraction)
    if covenant.synergy_cap_fraction is not None:
        synergies = min(synergies, max(base, 0) * covenant.synergy_cap_fraction)
    ebitda = base + addbacks + acquired + synergies
    match covenant.formula:
        case "total_leverage":
            return _bundle_divide(_debt(financials), ebitda)
        case "net_leverage":
            debt, cash = _debt(financials), _metric(financials, "cash")
            eligible = (
                cash if covenant.cash_netting_cap is None else min(cash, covenant.cash_netting_cap)
            )
            return _bundle_divide(max(0, debt - eligible), ebitda)
        case "interest_coverage":
            return _bundle_divide(ebitda, _metric(financials, "interest_expense"))
        case "fixed_charge_coverage":
            return _bundle_divide(
                _metric(financials, "fixed_charge_numerator"), _metric(financials, "fixed_charges")
            )
        case _:
            raise CalculationInputError("Unsupported bundle calculation formula.")


def calculate_covenant(
    resolution: CovenantResolution,
    financials: FinancialPeriod,
    *,
    assessment_run_id: str,
    information_cutoff: date,
) -> CovenantResult:
    """Calculate with scoped diagnostics; never project domain data when INFO is disabled."""
    with (
        logging_context(
            borrower_id=financials.borrower_id,
            period_end=financials.period_end,
            covenant_id=resolution.covenant_id,
            assessment_run_id=assessment_run_id,
            information_cutoff=information_cutoff,
        ),
        log_step(logger, "Calculate covenant", covenant_id=resolution.covenant_id),
    ):
        result = _calculate_covenant(
            resolution,
            financials,
            assessment_run_id=assessment_run_id,
            information_cutoff=information_cutoff,
        )
        if logger.isEnabledFor(logging.INFO):
            log_event(
                logger,
                "calculate_covenant",
                inputs=calculation_inputs(resolution, financials),
                outputs=covenant_output(result),
            )
        return result


def _calculate_covenant(
    resolution: CovenantResolution,
    financials: FinancialPeriod,
    *,
    assessment_run_id: str,
    information_cutoff: date,
) -> CovenantResult:
    """Return a calculated, reported, or explicitly incomplete period result."""
    covenant = resolution.covenant
    result = CovenantResult(
        assessment_run_id=assessment_run_id,
        borrower_id=financials.borrower_id,
        covenant_id=resolution.covenant_id,
        covenant_type=resolution.covenant_type,
        period_end=financials.period_end,
        information_cutoff=information_cutoff,
        compliance_status="unresolved",
        resolved_covenant=covenant,
        financial_inputs={
            "financial_period": financials.model_dump(mode="json"),
            "result_basis": "unavailable",
        },
        evidence=resolution.evidence,
        issues=list(resolution.issues),
    )
    if covenant is None:
        return result
    if (
        covenant.borrower_id != financials.borrower_id
        or covenant.period_end != financials.period_end
    ):
        raise ValueError(
            "Resolved terms and financial inputs must identify the same borrower-period."
        )
    result.agreement_id = covenant.agreement_id
    if covenant.calculation_contract == "bundle_v1":
        result.calculation_version = "bundle_v1"
    result.covenant_version = covenant.covenant_version
    result.threshold, result.operator, result.unit = (
        covenant.threshold,
        covenant.operator,
        covenant.unit,
    )
    result.evidence = covenant.evidence + covenant.reported_evidence
    result.compliance_status = "incomplete"
    if covenant.testing_status == "unresolved":
        result.compliance_status = "unresolved"
        if covenant.calculation_contract == "bundle_v1":
            result.issues.append("UNKNOWN_TRIGGER: springing availability is missing.")
        log_event(
            logger,
            "covenant_testing",
            outputs={
                "testing_status": covenant.testing_status,
                "reason": "Testing conditions could not be resolved.",
            },
        )
        return result
    inactive_status = {
        "waived": "waived",
        "suspended": "not_tested",
        "inactive": "not_tested",
    }.get(covenant.testing_status)
    if inactive_status:
        result.compliance_status = inactive_status
        log_event(
            logger,
            "covenant_testing",
            outputs={
                "testing_status": covenant.testing_status,
                "reason": "Compliance comparison and headroom are skipped for this test.",
            },
        )
        if covenant.calculation_contract == "bundle_v1" and inactive_status == "not_tested":
            return result
    try:
        if covenant.formula is None:
            if covenant.reported_actual is None:
                result.compliance_status = inactive_status or "unsupported"
                result.issues.append("No supported formula or source-reported actual is available.")
                return result
            result.actual_value = covenant.reported_actual
            result.financial_inputs["result_basis"] = "reported"
        else:
            result.actual_value = calculate_actual(covenant, financials)
            result.financial_inputs["result_basis"] = "calculated"
    except CalculationInputError as error:
        result.issues.append(str(error))
        if covenant.calculation_contract == "bundle_v1" and inactive_status == "waived":
            result.financial_inputs["underlying_calculation"] = {
                "compliance_status": "incomplete",
                "actual_value": None,
                "headroom": None,
            }
        return result
    if not inactive_status:
        result.compliance_status = (
            "compliant"
            if compare_threshold(result.actual_value, covenant.threshold, covenant.operator)
            else "breach"
        )
        result.headroom = calculate_headroom(
            result.actual_value,
            covenant.threshold,
            covenant.operator,
        )
    elif covenant.calculation_contract == "bundle_v1" and inactive_status == "waived":
        result.financial_inputs["underlying_calculation"] = {
            "compliance_status": "compliant"
            if compare_threshold(result.actual_value, covenant.threshold, covenant.operator)
            else "breach",
            "actual_value": result.actual_value,
            "headroom": calculate_headroom(
                result.actual_value, covenant.threshold, covenant.operator
            ),
        }
    return CovenantResult.model_validate(result.model_dump())
