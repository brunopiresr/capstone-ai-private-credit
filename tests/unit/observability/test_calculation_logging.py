"""Structured calculation records explain actual execution without evidence bodies."""

import inspect
import json
import logging
from datetime import date
from pathlib import Path

import pytest

from credit_monitoring.calculations.covenants import calculate_covenant
from credit_monitoring.calculations.leverage import CalculationInputError, divide
from credit_monitoring.calculations.trends import difference, growth, previous_period
from credit_monitoring.covenants.structured import SyntheticCovenantReader
from credit_monitoring.domain.assessment import (
    CovenantResolution,
    FinancialPeriod,
    ResolvedCovenant,
)

PERIOD = date(2025, 9, 30)
TERMS = Path(__file__).resolve().parents[3] / "data/synthetic_covenant_terms.csv"


@pytest.fixture
def inputs():
    covenant = ResolvedCovenant(
        borrower_id="TEST",
        agreement_id="agreement",
        covenant_id="leverage",
        covenant_name="Leverage",
        covenant_type="net_leverage",
        covenant_version="version-1",
        period_end=PERIOD,
        threshold=5,
        operator="<=",
        formula="net_leverage",
        cash_netting_cap=20,
        addback_cap_fraction=0.2,
        synergy_cap_fraction=0.5,
        evidence=[{"document_id": "source", "evidence_quote": "PRIVATE EVIDENCE BODY"}],
    )
    financials = FinancialPeriod(
        borrower_id="TEST",
        period_end=PERIOD,
        source_file="financials.csv",
        source_row=2,
        metrics={
            "reported_ebitda": 50,
            "eligible_addbacks": 20,
            "total_debt": 300,
            "cash": 35,
            "cash_interest": 10,
            "capex": 5,
            "cash_taxes": 2,
            "scheduled_principal": 4,
            "rent": 1,
            "acquired_ebitda": 10,
            "synergy_addback": 8,
        },
    )
    resolution = CovenantResolution(
        covenant_id="leverage",
        covenant_type="net_leverage",
        covenant=covenant,
    )
    return resolution, financials


def calculate(inputs):
    return calculate_covenant(
        *inputs,
        assessment_run_id="run-1",
        information_cutoff=PERIOD,
    )


def completed(caplog, operation):
    return [
        r
        for r in caplog.records
        if getattr(r, "operation", None) == operation and r.status == "complete"
    ]


def test_capped_calculation_records_exact_inputs_steps_and_result(inputs, caplog):
    caplog.set_level(logging.INFO, logger="credit_monitoring")
    result = calculate(inputs)
    events = completed(caplog, "apply_addback_cap")
    assert events[0].inputs == {
        "reported_ebitda": 50,
        "eligible_addbacks": 20,
        "cap_fraction": 0.2,
    }
    assert events[0].outputs == {"eligible_addbacks": 10}
    assert completed(caplog, "adjusted_ebitda")[0].outputs == {"result": 60}
    assert completed(caplog, "apply_cash_cap")[0].outputs == {
        "eligible_cash": 20,
        "net_debt": 280,
    }
    assert completed(caplog, "divide")[0].inputs == {"numerator": 280, "denominator": 60}
    assert completed(caplog, "compare_threshold")[0].outputs == {"result": True}
    final = completed(caplog, "calculate_covenant")[0]
    assert final.outputs["actual_value"] == result.actual_value == 280 / 60
    assert final.outputs["headroom"] == result.headroom == 5 - 280 / 60
    assert final.outputs["compliance_status"] == "compliant"
    assert final.outputs["result_basis"] == "calculated"
    assert final.outputs["covenant_version"] == "version-1"
    for record in caplog.records:
        assert record.assessment_run_id == "run-1"
        assert record.borrower_id == "TEST"
        assert record.period_end == PERIOD.isoformat()
        assert record.covenant_id == "leverage"
    data = json.dumps([{"inputs": r.inputs, "outputs": r.outputs} for r in caplog.records])
    assert "PRIVATE EVIDENCE BODY" not in data
    assert "evidence_quote" not in data
    assert "notes" not in data
    # Snapshots in earlier records do not change if callers mutate their inputs later.
    inputs[1].metrics["total_debt"] = 999
    assert final.inputs["financials"]["metrics"]["total_debt"] == 300
    assert str(inspect.signature(divide)) == "(numerator: float, denominator: float) -> float"


@pytest.mark.parametrize(
    "formula,expected",
    [
        ("total_leverage", 5),
        ("interest_coverage", 6),
        ("fixed_charge_coverage", 53 / 15),
        ("pro_forma_leverage", 300 / 65),
    ],
)
def test_formula_dispatch_logs_named_inputs_and_outputs(inputs, caplog, formula, expected):
    caplog.set_level(logging.INFO, logger="credit_monitoring")
    inputs[0].covenant.formula = formula
    result = calculate(inputs)
    assert result.actual_value == pytest.approx(expected)
    assert completed(caplog, formula)[0].outputs["result"] == pytest.approx(expected)
    if formula == "pro_forma_leverage":
        assert completed(caplog, "apply_synergy_cap")[0].outputs == {
            "eligible_synergies": 5,
            "pro_forma_ebitda": 65,
        }


@pytest.mark.parametrize(
    "problem,expected_status,reason",
    [
        ("missing", "incomplete", "Missing financial input"),
        ("zero", "incomplete", "denominator must be positive"),
        ("conflict", "incomplete", "DEBT_SOURCE_CONFLICT"),
        ("unsupported", "unsupported", "No supported formula"),
        ("unresolved", "unresolved", "Ambiguous terms"),
    ],
)
def test_abstentions_still_log_final_outcomes(inputs, caplog, problem, expected_status, reason):
    caplog.set_level(logging.INFO, logger="credit_monitoring")
    resolution, financials = inputs
    if problem == "missing":
        financials.metrics["reported_ebitda"] = None
    elif problem == "zero":
        financials.metrics.update(reported_ebitda=0, eligible_addbacks=0)
        resolution.covenant.addback_cap_fraction = None
    elif problem == "conflict":
        financials.metrics["compliance_certificate_debt"] = 310
    elif problem == "unsupported":
        resolution.covenant.formula = None
    else:
        resolution.covenant = None
        resolution.issues.append("Ambiguous terms")
    result = calculate(inputs)
    final = completed(caplog, "calculate_covenant")[0]
    assert final.outputs["compliance_status"] == result.compliance_status == expected_status
    assert final.outputs["actual_value"] is None
    assert reason in " ".join(final.outputs["issues"])
    if problem == "conflict":
        assert completed(caplog, "debt_sources")[0].outputs == {"conflict": True}
    if problem == "zero":
        failure = next(
            r for r in caplog.records if r.operation == "divide" and r.status == "failed"
        )
        assert failure.error_type == "CalculationInputError"


@pytest.mark.parametrize(
    "testing_status,status",
    [
        ("waived", "waived"),
        ("inactive", "not_tested"),
        ("suspended", "not_tested"),
        ("unresolved", "unresolved"),
    ],
)
def test_testing_status_explains_skipped_comparisons(inputs, caplog, testing_status, status):
    caplog.set_level(logging.INFO, logger="credit_monitoring")
    inputs[0].covenant.testing_status = testing_status
    result = calculate(inputs)
    final = completed(caplog, "calculate_covenant")[0]
    assert final.outputs["testing_status"] == testing_status
    assert final.outputs["compliance_status"] == result.compliance_status == status
    assert final.outputs["headroom"] is None
    assert completed(caplog, "covenant_testing")[0].outputs["reason"]
    assert not completed(caplog, "compare_threshold")


def test_reported_actual_is_explicit_and_not_recalculated(inputs, caplog):
    caplog.set_level(logging.INFO, logger="credit_monitoring")
    inputs[0].covenant.formula = None
    inputs[0].covenant.reported_actual = 4.5
    calculate(inputs)
    final = completed(caplog, "calculate_covenant")[0]
    assert final.outputs["actual_value"] == 4.5
    assert final.outputs["result_basis"] == "reported"
    assert not completed(caplog, "calculate_actual")


def test_synthetic_resolution_logs_selected_and_rejected_versions(caplog):
    caplog.set_level(logging.INFO, logger="credit_monitoring")
    reader = SyntheticCovenantReader(TERMS)
    financials = FinancialPeriod(borrower_id="SYN004", period_end=PERIOD)
    resolution = reader.resolve("SYN004", PERIOD, PERIOD, financials)[0]
    versions = completed(caplog, "synthetic_version")
    assert [event.outputs["applicable"] for event in versions] == [False, True]
    selected = completed(caplog, "covenant_resolution")[0]
    assert selected.outputs["terms"]["threshold"] == 5.5
    assert selected.outputs["terms"]["covenant_version"] == resolution.covenant.covenant_version
    assert selected.source_row == 6
    reader.rows.append(reader.rows[4])
    caplog.clear()
    assert reader.resolve("SYN004", PERIOD, PERIOD, financials)[0].covenant is None
    assert completed(caplog, "covenant_resolution")[0].outputs["issues"]


def test_trend_records_preserve_missing_values(caplog):
    caplog.set_level(logging.INFO, logger="credit_monitoring")
    assert previous_period(PERIOD) == date(2025, 6, 30)
    assert difference(5, 4) == 1
    assert growth(120, 100) == 0.2
    assert growth(1, 0) is None
    assert difference(None, 4) is None
    assert completed(caplog, "previous_period")[0].outputs == {"result": "2025-06-30"}
    assert completed(caplog, "growth")[-1].outputs == {"result": None}
    assert completed(caplog, "growth_unavailable")[0].outputs["reason"]
    assert completed(caplog, "difference_unavailable")[0].outputs["reason"]


def test_warning_level_suppresses_steps_and_preserves_errors(inputs, caplog):
    caplog.set_level(logging.WARNING, logger="credit_monitoring")
    assert calculate(inputs).actual_value == 280 / 60
    with pytest.raises(CalculationInputError):
        divide(1, 0)
    assert not caplog.records
