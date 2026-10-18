"""Explicit log projections of assessment data, excluding evidence bodies and notes."""

from credit_monitoring.domain.assessment import (
    CovenantResolution,
    CovenantResult,
    FinancialPeriod,
    ResolvedCovenant,
)


def financial_inputs(financials: FinancialPeriod) -> dict:
    return financials.model_dump(
        mode="json",
        include={
            "borrower_id",
            "period_end",
            "metrics",
            "source_file",
            "source_row",
            "available_at",
            "currency",
            "scale",
        },
    )


def covenant_terms(covenant: ResolvedCovenant | None) -> dict | None:
    if covenant is None:
        return None
    return covenant.model_dump(
        mode="json",
        include={
            "borrower_id",
            "agreement_id",
            "covenant_id",
            "covenant_name",
            "covenant_type",
            "covenant_version",
            "period_end",
            "threshold",
            "operator",
            "unit",
            "formula",
            "measurement_basis",
            "cash_netting_cap",
            "addback_cap_fraction",
            "synergy_cap_fraction",
            "testing_status",
            "reported_actual",
            "available_at",
        },
    )


def calculation_inputs(resolution: CovenantResolution, financials: FinancialPeriod) -> dict:
    return {
        "financials": financial_inputs(financials),
        "terms": covenant_terms(resolution.covenant),
        "issues": list(resolution.issues),
    }


def covenant_output(result: CovenantResult) -> dict:
    fields = result.model_dump(
        mode="json",
        include={
            "actual_value",
            "threshold",
            "operator",
            "unit",
            "headroom",
            "compliance_status",
            "issues",
            "covenant_version",
            "calculation_version",
            "result_id",
        },
    )
    fields["result_basis"] = result.financial_inputs["result_basis"]
    fields["testing_status"] = (
        result.resolved_covenant.testing_status if result.resolved_covenant else "unresolved"
    )
    return fields


def resolution_output(resolution: CovenantResolution) -> dict:
    return {
        "covenant_id": resolution.covenant_id,
        "terms": covenant_terms(resolution.covenant),
        "issues": list(resolution.issues),
    }
