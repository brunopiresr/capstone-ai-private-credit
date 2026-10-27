"""Exercise the working UI with real services and temporary storage, never gold answers."""

import shutil
import sqlite3
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest
from model_helpers import ScriptedModel, model_response
from streamlit.testing.v1 import AppTest

from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.application import assessment_service as assessment_module
from credit_monitoring.covenants.structured import SyntheticCovenantReader
from credit_monitoring.domain.risk_prediction import RiskPrediction
from credit_monitoring.web import workspace as workspace_module

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "src/credit_monitoring/web/app.py"


@pytest.fixture
def working_app(tmp_path, monkeypatch):
    # UI tests exercise application behavior; SDK setup belongs to its validation script.
    monkeypatch.setattr("credit_monitoring.observability.configure_observability", lambda: None)
    data = tmp_path / "data"
    synthetic = data / "app" / "synthetic"
    synthetic.mkdir(parents=True)
    for filename in (
        "synthetic_borrowers.csv",
        "synthetic_quarterly_financials.csv",
        "synthetic_covenant_terms.csv",
    ):
        shutil.copyfile(ROOT / "data/app/synthetic" / filename, synthetic / filename)
    # No gold file is available: accidental benchmark reads cannot satisfy these tests.
    monkeypatch.setattr(workspace_module, "DEFAULT_DATA_ROOT", data)
    monkeypatch.setattr(workspace_module, "DEFAULT_WORKSPACE_DIR", tmp_path / "working")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    loader = Mock(wraps=workspace_module.load_financials)
    monkeypatch.setattr(workspace_module, "load_financials", loader)
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    return app, tmp_path / "working", loader


def run_assessment(app, borrower="SYN001", period="2025-09-30", mode="Off"):
    app.selectbox(key="borrower_select").select(borrower).run()
    app.selectbox(key="period_select").select(period).run()
    app.selectbox(key="prediction_mode").select(mode).run()
    next(button for button in app.button if button.label == "Run assessment").click().run()
    assert not app.exception
    return app.session_state["active_assessment"]


def test_initialization_is_once_and_assessment_requires_explicit_execution(working_app):
    app, directory, loader = working_app
    assert app.radio(key="workspace_page").value == "Borrower assessment"
    assert (directory / "financials.sqlite3").is_file()
    assert not (directory / "analytics.sqlite3").exists()
    assessment = run_assessment(app)
    assert assessment.ml_status == "disabled"
    assert assessment.trends is not None
    covenant_trends = next(
        frame.value for frame in app.dataframe if "Actual change QoQ" in frame.value.columns
    )
    assert covenant_trends.iloc[0]["Actual change QoQ"] == pytest.approx(
        assessment.trends.covenants[0].metric_change_qoq
    )
    financial_trends = next(
        frame.value for frame in app.dataframe if "Growth QoQ" in frame.value.columns
    )
    assert financial_trends.iloc[0]["Growth QoQ"] == pytest.approx(
        assessment.trends.reported_ebitda_growth_qoq
    )
    assert app.chat_input[0].disabled
    assert any("OPENAI_API_KEY" in item.value for item in app.info)
    with sqlite3.connect(directory / "analytics.sqlite3") as connection:
        before = connection.execute("SELECT COUNT(*) FROM covenant_results").fetchone()[0]
    app.run()
    assert app.session_state["active_assessment"].assessment_run_id == assessment.assessment_run_id
    with sqlite3.connect(directory / "analytics.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM covenant_results").fetchone()[0] == before
    loader.assert_called_once()
    assert any("information_availability_unknown" in item.value for item in app.warning)
    assert any("Source:" in item.value and "Row:" in item.value for item in app.caption)
    assert any("Missing" in frame.value.to_string() for frame in app.dataframe)
    assert "Early-warning quarter" not in assessment.model_dump_json()
    assert "expected_metric" not in assessment.model_dump_json()


@pytest.mark.parametrize(
    "borrower,period,status,actual,threshold",
    [
        ("SYN001", "2025-09-30", "compliant", 100 / 32, 5.5),
        ("SYN003", "2025-06-30", "breach", 126 / 26, 4.5),
        ("SYN004", "2025-09-30", "compliant", 5.4, 5.5),
        ("SYN005", "2025-09-30", "waived", 5.2, 4.5),
        ("SYN007", "2025-09-30", "incomplete", None, 4.25),
        ("SYN010", "2025-06-30", "not_tested", None, 1.15),
        ("SYN010", "2025-09-30", "incomplete", None, 1.15),
    ],
)
def test_display_uses_exact_service_results(
    working_app, borrower, period, status, actual, threshold
):
    app, _, _ = working_app
    assessment = run_assessment(app, borrower, period)
    result = assessment.results[0]
    assert result.compliance_status == status
    assert result.actual_value == (pytest.approx(actual) if actual is not None else None)
    assert result.threshold == threshold
    assert any(f"Status: {status.replace('_', ' ')}" in item.value for item in app.markdown)
    assert not any("Status: WATCH" in item.value for item in app.markdown)
    if actual is None:
        assert next(item for item in app.metric if item.label == "Actual").value == "Unavailable"
        assert result.headroom is None


def test_pending_dates_disable_chat_and_earlier_cutoff_cannot_run(working_app):
    app, _, _ = working_app
    assessment = run_assessment(app)
    app.selectbox(key="period_select").select("2025-06-30").run()
    assert app.date_input(key="information_cutoff").value == date(2025, 6, 30)
    assert app.session_state["active_assessment"] == assessment
    assert app.chat_input[0].disabled
    assert any("Inputs changed" in item.value for item in app.info)
    app.date_input(key="information_cutoff").set_value(date(2025, 6, 29)).run()
    assert next(item for item in app.button if item.label == "Run assessment").disabled
    assert any("on or after" in item.value for item in app.error)


def test_stub_and_missing_trained_artifact_preserve_results(working_app):
    app, _, _ = working_app
    stub = run_assessment(app, mode="Stub")
    assert stub.ml_status == "stub" and stub.prediction.breach_probability is None
    assert any("no forecast probability" in item.value for item in app.info)
    failed = run_assessment(app, mode="Logistic Regression")
    assert failed.ml_status == "failed"
    assert failed.results[0].actual_value == stub.results[0].actual_value
    assert any("Forecast unavailable" in item.value for item in app.warning)
    assert failed.prediction.breach_probability is None


def test_complete_prediction_displays_zero_probability_and_model_details(working_app, monkeypatch):
    app, _, _ = working_app
    configurations = []

    def create(config):
        configurations.append(config)
        model = Mock()
        model.predict.side_effect = lambda features: RiskPrediction(
            borrower_id=features.borrower_id,
            period_end=features.period_end,
            model_name="logistic_regression",
            model_version="v1",
            prediction_status="complete",
            breach_probability=0.0,
        )
        return model

    monkeypatch.setattr(assessment_module, "create_risk_model", create)
    assessment = run_assessment(app, mode="Logistic Regression")
    assert configurations[0].type == "logistic_regression"
    assert configurations[0].artifact_path.name == "v1"
    assert assessment.ml_status == "complete"
    assert (
        next(item for item in app.metric if item.label == "Next-quarter breach probability").value
        == "0.0%"
    )
    assert any("synthetic borrower histories" in item.value for item in app.info)
    assert any("Horizon: 1" in item.value for item in app.caption)


def test_multiple_covenants_and_verification_errors_are_visible(working_app, monkeypatch):
    from credit_monitoring.application.assessment_service import AssessmentService

    app, _, _ = working_app
    resolve = SyntheticCovenantReader.resolve
    assess = AssessmentService.assess

    def two_covenants(reader, *args, **kwargs):
        resolutions = resolve(reader, *args, **kwargs)
        second = resolutions[0].model_copy(deep=True)
        second.covenant_id += ":second"
        second.covenant.covenant_id = second.covenant_id
        second.covenant.covenant_name = "Second covenant"
        return [*resolutions, second]

    def with_verification_error(service, *args, **kwargs):
        assessment = assess(service, *args, **kwargs)
        assessment.verification.add("error", "test_issue", "results", "Review this result.")
        return assessment

    monkeypatch.setattr(SyntheticCovenantReader, "resolve", two_covenants)
    monkeypatch.setattr(AssessmentService, "assess", with_verification_error)
    assessment = run_assessment(app)
    assert len(assessment.results) == 2
    assert len([item for item in app.metric if item.label == "Actual"]) == 2
    assert any(item.value == "Second covenant" for item in app.subheader)
    assert any("test_issue" in item.value for item in app.error)


def test_followups_use_real_tools_and_session_owned_conversations(working_app, monkeypatch):
    app, _, _ = working_app
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
    dates = {"period_end": "2025-09-30", "information_cutoff": "2025-09-30"}
    model = ScriptedModel()
    model.respond.side_effect = [
        model_response(("get_financials", dates)),
        model_response(("assess_covenants", dates)),
        model_response(answer="The calculated covenant is compliant."),
    ]
    conversations = []

    def conversation(service, borrower_id):
        result = CreditAssessmentAgent(assessment_service=service, model=model).start_conversation(
            borrower_id=borrower_id
        )
        conversations.append(result)
        return result

    monkeypatch.setattr(workspace_module, "create_conversation", conversation)
    assessment = run_assessment(app, borrower="SYN002")
    app.chat_input[0].set_value("Explain this result.").run()
    assert not app.exception
    answer = app.session_state["chat_messages"][-1]["answer"]
    assert answer.complete
    assert [call.name for call in answer.tool_trace] == ["get_financials", "assess_covenants"]
    assert answer.tool_trace[-1].outcome.borrower_id == "SYN002"
    assert all(call.arguments == dates for call in answer.tool_trace)
    assert "Early-warning quarter" not in answer.model_dump_json()
    first_request = model.respond.call_args_list[0].kwargs
    assert "2025-09-30" in str(first_request["messages"])
    assert {tool.name for tool in first_request["info"].function_tools} == {
        "get_financials",
        "assess_covenants",
        "predict_risk",
    }
    assert app.session_state["active_assessment"] == assessment
    assert any("Executed tools" in item.label for item in app.expander)
    session_id = conversations[0].session_id
    app.run()
    assert app.session_state["conversation"] is conversations[0]
    assert app.session_state["conversation"].session_id == session_id
    second_session = AppTest.from_file(str(APP), default_timeout=20).run()
    run_assessment(second_session)
    assert second_session.session_state["chat_messages"] == []
    assert len(conversations) == 1
    app.selectbox(key="borrower_select").select("SYN001").run()
    assert app.chat_input[0].disabled
    run_assessment(app)
    assert conversations[0].closed
    assert app.session_state["chat_messages"] == []
    model.respond.side_effect = None
    model.respond.return_value = model_response(status="failed")
    app.chat_input[0].set_value("Explain the inputs.").run()
    assert any("could not complete" in item.value for item in app.error)
    assert app.session_state["active_assessment"].borrower_id == "SYN001"
    next(item for item in app.button if item.label == "Clear conversation").click().run()
    assert conversations[-1].closed
    assert app.session_state["chat_messages"] == []


def test_benchmark_focus_prefills_working_controls_without_running(working_app):
    app, directory, _ = working_app
    app.session_state["pending_focus"] = {
        "borrower_id": "SYN010",
        "borrower_name": "Orion Distribution",
        "period_end": "2025-06-30",
    }
    app.run()
    assert not app.exception
    assert app.selectbox(key="borrower_select").value == "SYN010"
    assert app.selectbox(key="period_select").value == "2025-06-30"
    assert not (directory / "analytics.sqlite3").exists()


def test_benchmark_page_is_labeled_and_does_not_execute_assessments(working_app, monkeypatch):
    from credit_monitoring.application import demo_assessment_service

    app, directory, _ = working_app
    data = workspace_module.DEFAULT_DATA_ROOT
    evaluation = data / "evaluation"
    evaluation.mkdir()
    shutil.copyfile(
        ROOT / "data/evaluation/synthetic_gold_labels.csv", evaluation / "synthetic_gold_labels.csv"
    )
    monkeypatch.setattr(demo_assessment_service, "APP_SYNTHETIC_DIR", data / "app" / "synthetic")
    monkeypatch.setattr(demo_assessment_service, "EVALUATION_DIR", evaluation)
    app.radio(key="workspace_page").set_value("Benchmark portfolio (mock)").run()
    assert not app.exception
    assert any("Fixed benchmark examples" in item.value for item in app.info)
    assert any("MOCK · EXPECTED BENCHMARK ANSWERS" in item.value for item in app.markdown)
    assert app.dataframe
    assert not (directory / "analytics.sqlite3").exists()


def test_failed_run_preserves_previous_identity_and_disables_followups(working_app, monkeypatch):
    from credit_monitoring.application.assessment_service import AssessmentService

    app, _, _ = working_app
    assessment = run_assessment(app)
    monkeypatch.setattr(
        AssessmentService, "assess", Mock(side_effect=RuntimeError("Input unavailable"))
    )
    next(item for item in app.button if item.label == "Run assessment").click().run()
    assert not app.exception
    assert app.session_state["active_assessment"] == assessment
    assert any("Input unavailable" in item.value for item in app.error)
    assert app.chat_input[0].disabled
