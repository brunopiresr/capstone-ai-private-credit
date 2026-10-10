"""Calculate one covenant while preserving abstentions and exact inputs."""

import logging
from datetime import date

from credit_monitoring.domain.assessment import (
    CovenantResolution,
    CovenantResult,
    FinancialPeriod,
    ResolvedCovenant,
)
from credit_monitoring.observability.assessment import (
    calculation_context,
    calculation_inputs,
    covenant_output,
)
from credit_monitoring.observability.logging import log_event, logged_operation

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
    if len(set(provided)) > 1:
        raise CalculationInputError("DEBT_SOURCE_CONFLICT: debt sources disagree.")
    return _metric(financials, "total_debt")


@logged_operation(inputs=calculation_inputs, context=calculation_context)
def calculate_actual(covenant: ResolvedCovenant, financials: FinancialPeriod) -> float:
    """Dispatch only typed, allowlisted formulas; never interpret formula text."""
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


@logged_operation(inputs=calculation_inputs, outputs=covenant_output, context=calculation_context)
def calculate_covenant(
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
    return CovenantResult.model_validate(result.model_dump())
