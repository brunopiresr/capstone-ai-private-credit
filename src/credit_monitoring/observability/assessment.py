"""Explicit log projections of assessment data, excluding evidence bodies and notes."""

from typing import Any

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


def calculation_inputs(arguments: dict[str, Any]) -> dict:
    resolution = arguments.get("resolution")
    covenant = resolution.covenant if resolution is not None else arguments.get("covenant")
    return {
        "financials": financial_inputs(arguments["financials"]),
        "terms": covenant_terms(covenant),
        "issues": list(resolution.issues) if resolution is not None else [],
    }


def calculation_context(arguments: dict[str, Any]) -> dict:
    financials = arguments["financials"]
    covenant = arguments.get("resolution") or arguments.get("covenant")
    fields = {
        "borrower_id": financials.borrower_id,
        "period_end": financials.period_end,
        "covenant_id": covenant.covenant_id,
    }
    for name in ("assessment_run_id", "information_cutoff"):
        if name in arguments:
            fields[name] = arguments[name]
    return fields


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


def resolution_context(arguments: dict[str, Any]) -> dict:
    return {
        name: arguments[name]
        for name in (
            "borrower_id",
            "period_end",
            "information_cutoff",
        )
    }


def resolution_inputs(arguments: dict[str, Any]) -> dict:
    return {
        "reader": type(arguments["self"]).__name__,
        "financials": financial_inputs(arguments["financials"]),
    }


def resolution_output(resolution: CovenantResolution) -> dict:
    return {
        "covenant_id": resolution.covenant_id,
        "terms": covenant_terms(resolution.covenant),
        "issues": list(resolution.issues),
    }


def resolution_outputs(resolutions: list[CovenantResolution]) -> dict:
    return {"resolutions": [resolution_output(item) for item in resolutions]}
