"""Check boundary conditions and period-specific calculation rules."""

from datetime import date
from pathlib import Path

import pytest

from credit_monitoring.calculations.covenants import calculate_covenant
from credit_monitoring.calculations.coverage import fixed_charge_coverage, interest_coverage
from credit_monitoring.calculations.headroom import calculate_headroom, compare_threshold
from credit_monitoring.calculations.leverage import (
    CalculationInputError,
    adjusted_ebitda,
    divide,
    net_leverage,
    pro_forma_leverage,
    total_leverage,
)
from credit_monitoring.calculations.trends import difference, growth, previous_period
from credit_monitoring.covenants.structured import SyntheticCovenantReader
from credit_monitoring.domain.assessment import (
    CovenantResolution,
    FinancialPeriod,
    ResolvedCovenant,
)

TERMS = Path(__file__).resolve().parents[3] / "data/synthetic_covenant_terms.csv"


def test_amendments_resolve_for_their_own_periods():
    reader = SyntheticCovenantReader(TERMS)
    for period, threshold in ((date(2025, 6, 30), 4.75), (date(2025, 7, 1), 5.5)):
        financials = FinancialPeriod(borrower_id="SYN004", period_end=period)
        covenant = reader.resolve("SYN004", period, period, financials)[0].covenant
        assert covenant.threshold == threshold


def test_conflicting_versions_abstain():
    reader = SyntheticCovenantReader(TERMS)
    reader.rows.append(next(item for item in reader.rows if item[1]["borrower_id"] == "SYN001"))
    period = date(2025, 9, 30)
    financials = FinancialPeriod(borrower_id="SYN001", period_end=period)
    resolution = reader.resolve("SYN001", period, period, financials)[0]
    assert resolution.covenant is None
    result = calculate_covenant(
        resolution, financials, assessment_run_id="run", information_cutoff=period
    )
    assert result.compliance_status == "unresolved"


def test_zero_ebitda_prevents_compliance():
    period = date(2025, 9, 30)
    financials = FinancialPeriod(
        borrower_id="SYN001",
        period_end=period,
        metrics={"total_debt": 100, "cash": 10, "reported_ebitda": 0, "eligible_addbacks": 0},
    )
    resolution = SyntheticCovenantReader(TERMS).resolve("SYN001", period, period, financials)[0]
    result = calculate_covenant(
        resolution, financials, assessment_run_id="run", information_cutoff=period
    )
    assert result.actual_value is None
    assert result.compliance_status == "incomplete"


@pytest.mark.parametrize("denominator", [0, -1])
def test_invalid_denominators(denominator):
    with pytest.raises(CalculationInputError):
        divide(10, denominator)


def test_overflow_is_an_incomplete_input():
    with pytest.raises(CalculationInputError, match="finite"):
        divide(1e308, 1e-308)


@pytest.mark.parametrize(
    "operator,compliant,headroom",
    [
        ("<", False, 0),
        ("<=", True, 0),
        (">", False, 0),
        (">=", True, 0),
        ("=", True, None),
    ],
)
def test_exact_threshold_boundaries(operator, compliant, headroom):
    assert compare_threshold(5, 5, operator) == compliant
    assert calculate_headroom(5, 5, operator) == headroom


def test_minimum_covenant_headroom():
    assert calculate_headroom(2.7, 3, ">=") == pytest.approx(-0.3)


def test_quarter_and_year_end_alignment():
    assert previous_period(date(2025, 6, 30)) == date(2025, 3, 31)
    assert previous_period(date(2024, 5, 31)) == date(2024, 2, 29)
    assert previous_period(date(2025, 9, 30), 4) == date(2024, 9, 30)


def test_contractual_caps_and_all_formula_families_have_independent_known_values():
    ebitda = adjusted_ebitda(50, 20, 0.2)
    assert ebitda == 60
    assert net_leverage(300, 35, ebitda, 20) == pytest.approx(280 / 60)
    assert total_leverage(300, ebitda) == 5
    assert interest_coverage(ebitda, 10) == 6
    assert fixed_charge_coverage(ebitda, 5, 2, 10, 4, 1) == pytest.approx(53 / 15)
    assert pro_forma_leverage(300, 50, 10, 8, 0.5) == pytest.approx(300 / 65)
    assert divide(numerator=280, denominator=60) == pytest.approx(280 / 60)


def test_known_trends_and_missing_values():
    assert difference(5, 4) == 1
    assert growth(120, 100) == pytest.approx(0.2)
    assert growth(1, 0) is None
    assert difference(None, 4) is None


@pytest.mark.parametrize(
    "formula,expected",
    [
        ("net_leverage", 280 / 60),
        ("total_leverage", 5),
        ("interest_coverage", 6),
        ("fixed_charge_coverage", 53 / 15),
        ("pro_forma_leverage", 300 / 65),
    ],
)
def test_dispatch_preserves_contractual_formula_results_without_logging(formula, expected):
    period = date(2025, 9, 30)
    covenant = ResolvedCovenant(
        borrower_id="TEST",
        agreement_id="agreement",
        covenant_id="test",
        covenant_name="Test covenant",
        covenant_type=formula,
        covenant_version="v1",
        period_end=period,
        threshold=5,
        operator="<=",
        formula=formula,
        cash_netting_cap=20,
        addback_cap_fraction=0.2,
        synergy_cap_fraction=0.5,
    )
    financials = FinancialPeriod(
        borrower_id="TEST",
        period_end=period,
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
    result = calculate_covenant(
        CovenantResolution(covenant_id="test", covenant_type=formula, covenant=covenant),
        financials,
        assessment_run_id="run",
        information_cutoff=period,
    )
    assert result.actual_value == pytest.approx(expected)
    assert result.headroom == pytest.approx(5 - expected)
