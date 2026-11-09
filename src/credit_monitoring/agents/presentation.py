"""Required explanation facts projected from service outputs and exact source terms.

Never choose governing terms, change compliance, or supply forecasts. The optional
addback explanation reuses the existing calculation function on recorded inputs.
Calendar dates are never inferred from a fiscal calendar.
"""

import json
import re
from typing import TYPE_CHECKING

from credit_monitoring.calculations.leverage import CalculationInputError, adjusted_ebitda
from credit_monitoring.domain.agent import MaterialClaim

if TYPE_CHECKING:
    from credit_monitoring.agents.evidence import EvidenceRegistry

PRESENTATION_VERSION = "assessment-explanations-v1"


def calculation_details(data: dict) -> dict:
    covenant = data.get("resolved_covenant") or {}
    financials = data.get("financial_inputs", {}).get("financial_period", {})
    metrics = financials.get("metrics", {})
    source = next(
        (
            e.get("source_values", {})
            for e in data.get("evidence", [])
            if e.get("source_hash") == data.get("covenant_version")
        ),
        {},
    )
    terms = {
        k: source[k]
        for k in (
            "effective_start",
            "effective_end",
            "testing_condition",
            "waiver_or_special_rule",
            "waived_periods",
            "addback_rule",
            "cash_netting_rule",
        )
        if source.get(k)
    }
    details = {"version": PRESENTATION_VERSION, "source_terms": terms}
    trigger = source.get("springing_trigger_pct")
    condition = source.get("testing_condition", "")
    legacy_trigger = re.fullmatch(r"only if revolver_availability_pct < (\d+(?:\.\d+)?)", condition)
    if trigger or legacy_trigger or "springing" in covenant.get("covenant_name", "").casefold():
        details["springing"] = {
            "observed_availability_pct": metrics.get("revolver_availability_pct"),
            "trigger_threshold_pct": float(trigger or legacy_trigger.group(1))
            if trigger or legacy_trigger
            else None,
            "trigger_direction": "<" if trigger or legacy_trigger else None,
            "testing_status": covenant.get("testing_status", "unresolved"),
            "assessment_status": data["compliance_status"],
            "boundary": "Equality does not activate a below-threshold trigger."
            if trigger or legacy_trigger
            else "Trigger terms were not supplied.",
        }
    periods = json.loads(source.get("waived_periods") or "[]")
    if not periods:
        periods = (
            re.findall(r"\d{4}-\d{2}-\d{2}", source.get("waiver_or_special_rule", ""))
            if "waived" in source.get("waiver_or_special_rule", "").casefold()
            else []
        )
    if periods or covenant.get("testing_status") == "waived":
        details["testing_relief"] = {
            "explicit_test_periods": periods,
            "last_explicit_test_period": max(periods) if periods else None,
            "legal_expiry_date": None,
            "limitation": "A separate legal expiry is not supplied. Testing relief applies only "
            "to the stated tests; it does not establish compliance or repayment strength.",
        }
    if (
        data.get("financial_inputs", {}).get("result_basis") == "calculated"
        and covenant.get("calculation_contract") == "legacy_v1"
        and covenant.get("formula") != "pro_forma_leverage"
        and metrics.get("reported_ebitda") is not None
        and metrics.get("eligible_addbacks") is not None
    ):
        try:
            adjusted = adjusted_ebitda(
                metrics["reported_ebitda"],
                metrics["eligible_addbacks"],
                covenant.get("addback_cap_fraction"),
            )
        except CalculationInputError:
            pass
        else:
            details["ebitda_explanation"] = {
                "method": "calculations.leverage.adjusted_ebitda",
                "base_ebitda": metrics["reported_ebitda"],
                "supplied_addbacks": metrics["eligible_addbacks"],
                "cap_fraction": covenant.get("addback_cap_fraction"),
                "allowed_addbacks": adjusted - metrics["reported_ebitda"],
                "covenant_ebitda": adjusted,
                "currency": financials.get("currency"),
                "scale": financials.get("scale"),
            }
    return details


def forecast_label(prediction: dict) -> str:
    quarters = prediction["horizon_quarters"]
    horizon = "next-quarter horizon" if quarters == 1 else f"{quarters}-quarter horizon"
    return (
        f"Forecast as of {prediction['period_end']}, {horizon}. "
        "Target period end is not supplied; no fiscal calendar is inferred."
    )


def required_claims(registry: EvidenceRegistry, assessment_ids: set[str]) -> list[MaterialClaim]:
    claims = []
    prediction_ids = {
        e.data.get("prediction", {}).get("prediction_id")
        for e in registry.entries
        if e.kind == "assessment"
        and e.data["assessment_run_id"] in assessment_ids
        and e.data.get("prediction")
    }
    for entry in registry.entries:
        data = entry.data
        if entry.kind == "calculation" and data["assessment_run_id"] in assessment_ids:
            paths = ["issues"]
            if data.get("resolved_covenant"):
                paths += [
                    "covenant_version",
                    "resolved_covenant.testing_status",
                    "resolved_covenant.measurement_basis",
                ]
            owner = registry.get("assessment:" + data["assessment_run_id"])
            if entry.period_end == owner.period_end:
                for section, values in data["presentation"].items():
                    if isinstance(values, dict):
                        paths += [
                            f"presentation.{section}.{key}"
                            for key in values
                            if key not in {"version", "method"}
                        ]
        elif entry.kind == "assessment" and data["assessment_run_id"] in assessment_ids:
            paths = ["verification.is_valid", "verification.issues", "ml_status"]
        elif entry.kind == "prediction" and data["prediction_id"] in prediction_ids:
            paths = [
                "model_name",
                "model_version",
                "prediction_status",
                "period_end",
                "horizon_quarters",
                "snapshot_id",
                "breach_probability",
                "error",
            ]
        else:
            continue
        claims.extend(
            MaterialClaim(
                claim_id=f"policy:{entry.evidence_id}:{path}",
                kind="fact",
                evidence_ids=[entry.evidence_id],
                field_path=path,
            )
            for path in paths
        )
    return claims
