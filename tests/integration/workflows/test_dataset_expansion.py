"""Independent package expectations, additive workspace upgrades and benchmark selection."""

import csv
import hashlib
import shutil
import sqlite3
from datetime import date

import pytest

from credit_monitoring.application.bootstrap import create_assessment_service
from credit_monitoring.application.demo_assessment_service import (
    build_demo_assessment,
    build_portfolio_snapshot,
    get_borrowers,
)
from credit_monitoring.application.financial_workspace import initialize_working_financials
from credit_monitoring.config.settings import AssessmentSettings
from credit_monitoring.covenants.structured import SyntheticCovenantReader
from credit_monitoring.domain.assessment import FinancialPeriod
from credit_monitoring.financials.repositories import FinancialRepository
from credit_monitoring.paths import (
    APP_SYNTHETIC_DIR,
    BUNDLED_FINANCIAL_DB,
    DATA_ROOT,
    EVALUATION_DIR,
)
from credit_monitoring.verification.verifier import verify_assessment

with (EVALUATION_DIR / "synthetic_bundle_gold_cases.csv").open(newline="") as source:
    GOLD = list(csv.DictReader(source))

STATUS = {
    "PASS": "compliant",
    "BREACH": "breach",
    "INDETERMINATE": "incomplete",
    "UNKNOWN_TRIGGER": "unresolved",
    "NOT_TESTED": "not_tested",
    "WAIVED": "waived",
}


@pytest.fixture(scope="module")
def service(tmp_path_factory):
    return create_assessment_service(
        financial_repository=FinancialRepository(BUNDLED_FINANCIAL_DB),
        covenant_reader=SyntheticCovenantReader(APP_SYNTHETIC_DIR / "synthetic_covenant_terms.csv"),
        settings=AssessmentSettings(
            analytics_database=tmp_path_factory.mktemp("bundle") / "runs.db"
        ),
    )


@pytest.mark.parametrize("gold", GOLD, ids=lambda g: g["gold_case_id"])
def test_all_package_expectations(service, gold):
    period = date.fromisoformat(gold["period_end"])
    assessment = service.assess(gold["borrower_id"], period, period, ml_enabled=False)
    assert assessment.verification.is_valid
    cid = gold["covenant_id"].removeprefix(gold["borrower_id"] + "-")
    result = next(
        r for r in assessment.results if r.covenant_id == f"synthetic:{gold['borrower_id']}:{cid}"
    )
    assert result.compliance_status == STATUS[gold["expected_status"]]
    assert result.threshold == float(gold["threshold"])
    assert result.operator == ("<=" if gold["direction"] == "MAX" else ">=")
    assert result.calculation_version == "bundle_v1"
    assert result.actual_value == (
        pytest.approx(float(gold["expected_ratio"]), abs=5e-7, rel=0)
        if gold["expected_ratio"]
        else None
    )
    if result.compliance_status == "waived":
        underlying = result.financial_inputs["underlying_calculation"]
        assert underlying["compliance_status"] == STATUS[gold["underlying_status"]]
        assert underlying["actual_value"] == result.actual_value
        headroom = underlying["headroom"]
        assert result.headroom is None
    else:
        headroom = result.headroom
    assert headroom == (
        pytest.approx(float(gold["headroom_ratio_points"]), abs=5e-7, rel=0)
        if gold["headroom_ratio_points"]
        else None
    )
    inputs = result.financial_inputs["financial_period"]
    assert (inputs["currency"], inputs["scale"], inputs["available_at"]) == (
        "USD",
        "millions",
        None,
    )
    serialized = assessment.model_dump_json()
    assert "expected_ratio" not in serialized and "input_note" not in serialized
    assert all(r.period_end <= period for r in assessment.history)


def test_integrated_counts_and_benchmark_selection():
    assert len(get_borrowers()) == 37
    items = build_portfolio_snapshot()
    assert len(items) == 42  # 37 borrowers; five have two covenants.
    assert len({i.assessment.borrower_id for i in items}) == 37
    with pytest.raises(ValueError, match="explicit covenant"):
        build_demo_assessment("SYN018", "2025-06-30")
    leverage = build_demo_assessment("SYN018", "2025-06-30", "LEV")
    coverage = build_demo_assessment("SYN018", "2025-06-30", "ICR")
    assert (leverage.status, coverage.status) == ("COMPLIANT", "BREACH")
    assert leverage.history != coverage.history
    assert coverage.early_warning is None
    with sqlite3.connect(BUNDLED_FINANCIAL_DB) as connection:
        assert connection.execute("SELECT count(*) FROM quarterly_financials").fetchone()[0] == 172
    with (DATA_ROOT / "app/sec/public_sec_documents.csv").open() as source:
        sources = list(csv.DictReader(source))
    assert len(sources) == 69 and len({r["source_url"] for r in sources}) == 69
    assert sum(r["document_id"].startswith("SEC-") for r in sources) == 40


def test_additive_upgrade_preserves_working_values_and_is_idempotent(tmp_path):
    target = tmp_path / "financials.sqlite3"
    # Recreate the old schema rather than relying on an ignored local database.
    with sqlite3.connect(target) as connection:
        connection.execute(
            "CREATE TABLE quarterly_financials (borrower_id TEXT, period_end TEXT, "
            "total_debt REAL, notes TEXT, source_file TEXT NOT NULL, source_row INTEGER NOT NULL, "
            "loaded_at TEXT, PRIMARY KEY(borrower_id, period_end))"
        )
        connection.execute(
            "INSERT INTO quarterly_financials VALUES "
            "('SYN001','2025-03-31',999,'Analyst input','custom.csv',2,'retained')"
        )
    initialize_working_financials(BUNDLED_FINANCIAL_DB, target)
    repository = FinancialRepository(target)
    assert repository.get_quarter("SYN001", "2025-03-31")["total_debt"] == 999
    assert len(repository.get_history("SYN037")) == 6
    backups = list((tmp_path / "backups").glob("*.sqlite3"))
    assert len(backups) == 1
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    initialize_working_financials(BUNDLED_FINANCIAL_DB, target)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == before
    assert list((tmp_path / "backups").glob("*.sqlite3")) == backups
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("SELECT total_debt FROM quarterly_financials").fetchall() == [
            (999,)
        ]


def test_upgrade_failure_rolls_back_and_can_be_retried(tmp_path, monkeypatch):
    from credit_monitoring.application import financial_workspace as module

    target = tmp_path / "financials.sqlite3"
    shutil.copyfile(BUNDLED_FINANCIAL_DB, target)
    with sqlite3.connect(target) as connection:
        connection.execute("DELETE FROM quarterly_financials WHERE borrower_id = 'SYN037'")
    initialize = module.initialize_financial_schema

    def fail(connection):
        initialize(connection)
        connection.execute("UPDATE quarterly_financials SET total_debt = 999")
        raise ValueError("simulated migration failure")

    with monkeypatch.context() as patch:
        patch.setattr(module, "initialize_financial_schema", fail)
        with pytest.raises(ValueError, match="simulated"):
            initialize_working_financials(BUNDLED_FINANCIAL_DB, target)
    assert FinancialRepository(target).get_quarter("SYN001", "2025-03-31")["total_debt"] == 120
    initialize_working_financials(BUNDLED_FINANCIAL_DB, target)
    assert len(FinancialRepository(target).get_history("SYN037")) == 6
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1


def test_verifier_checks_waived_underlying_results(service):
    period = date(2025, 6, 30)
    assessment = service.assess("SYN031", period, period, ml_enabled=False)
    assessment.results[0].financial_inputs["underlying_calculation"]["headroom"] += 1
    assert not verify_assessment(assessment).is_valid


def test_conflict_metadata_and_missing_trigger_remain_explicit(service):
    p = date(2025, 3, 31)
    conflicting = service.assess("SYN037", p, p, ml_enabled=False).results[0]
    assert "DEBT_SOURCE_CONFLICT" in " ".join(conflicting.issues)
    assert conflicting.financial_inputs["financial_period"]["metrics"]["financials_debt"] is None
    unresolved = service.assess("SYN036", p, p, ml_enabled=False).results[0]
    assert "UNKNOWN_TRIGGER" in " ".join(unresolved.issues)


def test_bundle_boundaries_and_missing_components(service):
    from credit_monitoring.calculations.covenants import calculate_covenant
    from credit_monitoring.domain.assessment import CovenantResolution

    p = date(2025, 3, 31)
    base = service.assess("SYN025", p, p, ml_enabled=False).results[0]
    covenant = base.resolved_covenant.model_copy(
        update={"cash_netting_cap": None, "threshold": 0.0}
    )
    financials = FinancialPeriod.model_validate(base.financial_inputs["financial_period"])
    financials.metrics.update(total_debt=10, cash=20)

    def calculate():
        return calculate_covenant(
            CovenantResolution(
                covenant_id=covenant.covenant_id,
                covenant_type=covenant.covenant_type,
                covenant=covenant,
            ),
            financials,
            assessment_run_id="boundary",
            information_cutoff=p,
        )

    result = calculate()
    assert result.actual_value == 0 and result.compliance_status == "compliant"
    financials.metrics["synergy_addback"] = None
    assert calculate().compliance_status == "incomplete"


def test_future_edits_cannot_change_earlier_calculations(service, tmp_path):
    from credit_monitoring.ingestion.loaders.financials import load_financials

    target = tmp_path / "financials.sqlite3"
    shutil.copyfile(BUNDLED_FINANCIAL_DB, target)
    local = create_assessment_service(
        financial_repository=FinancialRepository(target),
        covenant_reader=service.covenant_reader,
        settings=AssessmentSettings(analytics_database=tmp_path / "analytics.sqlite3"),
    )
    p = date(2025, 9, 30)
    before = local.assess("SYN026", p, p, ml_enabled=False)
    future = tmp_path / "future.csv"
    future.write_text("borrower_id,period_end,total_debt\nSYN026,2026-06-30,999999\n")
    load_financials(future, target)
    after = local.assess("SYN026", p, p, ml_enabled=False)
    assert before.trends == after.trends
    assert before.results[0].actual_value == after.results[0].actual_value


@pytest.mark.parametrize(
    "base,interest,threshold,operator,status",
    [
        (0.3, 0.1, 3.0, ">=", "compliant"),
        (1.0, 3.0, 0.333333, "<=", "breach"),
        (1.0, 0.0, 3.0, ">=", "incomplete"),
    ],
)
def test_comparison_uses_unrounded_decimal_inputs(
    service, base, interest, threshold, operator, status
):
    p = date(2025, 3, 31)
    financials = service.financial_repository.get_period("SYN018", p)
    financials.metrics.update(reported_ebitda=base, interest_expense=interest)
    terms = service.covenant_reader.resolve("SYN018", p, p, financials)
    resolution = next(t for t in terms if t.covenant_id.endswith(":ICR"))
    resolution.covenant.threshold = threshold
    resolution.covenant.operator = operator
    from credit_monitoring.calculations.covenants import calculate_covenant

    result = calculate_covenant(
        resolution, financials, assessment_run_id="precision", information_cutoff=p
    )
    assert result.compliance_status == status
