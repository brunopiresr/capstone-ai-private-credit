"""Independent known-value assessments exercise active verification rejections."""

from datetime import date

import pytest

from credit_monitoring.domain.assessment import CovenantResult, ResolvedCovenant, RiskAssessment
from credit_monitoring.domain.risk_features import BorrowerFeatureSnapshot, BorrowerRiskFeatures
from credit_monitoring.domain.risk_prediction import RiskPrediction
from credit_monitoring.verification.verifier import verify_assessment

PERIOD = date(2025, 9, 30)
FUTURE = date(2025, 10, 1)


@pytest.fixture
def assessment():
    evidence = [{"source_file": "independent-terms.csv", "source_row": 2}]
    covenant = ResolvedCovenant(
        borrower_id="TEST",
        agreement_id="agreement",
        covenant_id="net",
        covenant_name="Maximum Net Leverage",
        covenant_type="net_leverage",
        covenant_version="v1",
        period_end=PERIOD,
        threshold=5,
        operator="<=",
        formula="net_leverage",
        cash_netting_cap=20,
        evidence=evidence,
        available_at=PERIOD,
    )
    result = CovenantResult(
        assessment_run_id="run",
        borrower_id="TEST",
        covenant_id="net",
        covenant_type="net_leverage",
        period_end=PERIOD,
        information_cutoff=PERIOD,
        actual_value=4,
        threshold=5,
        operator="<=",
        headroom=1,
        compliance_status="compliant",
        resolved_covenant=covenant,
        evidence=evidence,
        financial_inputs={
            "result_basis": "calculated",
            "financial_period": {
                "borrower_id": "TEST",
                "period_end": PERIOD.isoformat(),
                "available_at": PERIOD.isoformat(),
                "metrics": {
                    "total_debt": 100,
                    "cash": 20,
                    "reported_ebitda": 20,
                    "eligible_addbacks": 0,
                },
            },
        },
    )
    return RiskAssessment(
        assessment_run_id="run",
        borrower_id="TEST",
        period_end=PERIOD,
        information_cutoff=PERIOD,
        results=[result],
    )


def assert_rejected(assessment, code, field=None):
    # Revalidate to distinguish schema-valid tampering from invalid test objects.
    report = verify_assessment(RiskAssessment.model_validate(assessment.model_dump()))
    assert not report.is_valid
    assert any(
        issue.code == code
        and issue.severity == "error"
        and (field is None or issue.path.endswith(f".{field}"))
        for issue in report.issues
    )


def test_independent_known_values_and_unknown_availability(assessment):
    assert verify_assessment(assessment).issues == []
    assessment.results[0].financial_inputs["financial_period"]["available_at"] = None
    report = verify_assessment(assessment)
    assert report.is_valid
    assert [(issue.code, issue.severity) for issue in report.issues] == [
        ("information_availability_unknown", "warning")
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("borrower_id", "OTHER"),
        ("assessment_run_id", "other"),
        ("period_end", FUTURE),
        ("information_cutoff", FUTURE),
    ],
)
def test_result_scope(assessment, field, value):
    setattr(assessment.results[0], field, value)
    assert_rejected(assessment, "result_scope_mismatch")


@pytest.mark.parametrize(
    "field,value",
    [
        ("actual_value", 3.0),
        ("headroom", 2.0),
        ("threshold", 6.0),
        ("operator", ">="),
        ("compliance_status", "breach"),
    ],
)
@pytest.mark.parametrize("historical", [False, True])
def test_calculation_replay(assessment, field, value, historical):
    setattr(assessment.results[0], field, value)
    if historical:
        assessment.period_end = FUTURE
        assessment.information_cutoff = FUTURE
        assessment.history = assessment.results
        assessment.results = []
    assert_rejected(assessment, "calculation_mismatch", field)


@pytest.mark.parametrize(
    "source,code",
    [
        ("financial", "future_financial_inputs"),
        ("covenant", "future_covenant_terms"),
    ],
)
def test_future_availability(assessment, source, code):
    result = assessment.results[0]
    if source == "financial":
        result.financial_inputs["financial_period"]["available_at"] = FUTURE.isoformat()
    else:
        result.resolved_covenant.available_at = FUTURE
    assert_rejected(assessment, code)


def test_missing_provenance(assessment):
    assessment.results[0].evidence = []
    assert_rejected(assessment, "missing_provenance")


def test_reported_actual_requires_its_own_evidence(assessment):
    result = assessment.results[0]
    result.financial_inputs["result_basis"] = "reported"
    result.resolved_covenant.formula = None
    result.resolved_covenant.reported_actual = 4
    result.resolved_covenant.reported_evidence = result.evidence.copy()
    assert verify_assessment(assessment).is_valid
    result.resolved_covenant.reported_evidence = []
    assert_rejected(assessment, "missing_reported_evidence")


def test_unresolved_terms_cannot_establish_compliance(assessment):
    assessment.results[0].resolved_covenant = None
    assert_rejected(assessment, "unresolved_compliance")


@pytest.fixture
def stub_assessment(assessment):
    assessment.feature_snapshot = BorrowerFeatureSnapshot(
        assessment_run_id="run",
        source_result_ids=[assessment.results[0].result_id],
        features=BorrowerRiskFeatures(
            borrower_id="TEST",
            period_end=PERIOD,
            information_cutoff=PERIOD,
        ),
    )
    assessment.prediction = RiskPrediction(
        borrower_id="TEST",
        period_end=PERIOD,
        snapshot_id=assessment.feature_snapshot.snapshot_id,
        model_name="stub",
        model_version="v1",
        prediction_status="stub",
    )
    assert verify_assessment(assessment).is_valid
    return assessment


@pytest.mark.parametrize(
    "field,value",
    [
        ("snapshot_id", "other"),
        ("borrower_id", "OTHER"),
        ("period_end", FUTURE),
        ("missing_snapshot", None),
    ],
)
def test_prediction_identity(stub_assessment, field, value):
    if field == "missing_snapshot":
        stub_assessment.feature_snapshot = None
    else:
        setattr(stub_assessment.prediction, field, value)
    assert_rejected(stub_assessment, "prediction_identity_mismatch")


@pytest.mark.parametrize(
    "field,value",
    [
        ("breach_probability", 0.2),
        ("deterioration_probability", 0.3),
        ("anomaly_score", 0.5),
        ("risk_level", "low"),
    ],
)
def test_stub_cannot_supply_forecasts(stub_assessment, field, value):
    setattr(stub_assessment.prediction, field, value)
    assert_rejected(stub_assessment, "stub_forecast")
