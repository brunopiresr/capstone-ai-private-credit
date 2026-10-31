"""Connected portfolio UI with real services/SQLite and a controlled model boundary."""

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from portfolio_helpers import portfolio_inputs, review_model
from streamlit.testing.v1 import AppTest

from credit_monitoring.web import portfolio as portfolio_page

APP = Path(__file__).resolve().parents[3] / "src/credit_monitoring/web/preview.py"


def click(app, label):
    next(button for button in app.button if button.label == label).click().run()
    assert not app.exception


def row(app, borrower_id):
    frame = app.dataframe[0].value
    return frame.loc[frame["ID"] == borrower_id].iloc[0]


@pytest.fixture
def connected(monkeypatch, tmp_path):
    root = portfolio_inputs(tmp_path)
    monkeypatch.setattr(portfolio_page, "DEFAULT_DATA_ROOT", root)
    monkeypatch.setattr(portfolio_page, "DEFAULT_WORKING_DIR", tmp_path / "working")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    model = review_model()
    factory = portfolio_page.create_portfolio_service

    def create(**kwargs):
        kwargs["model"] = model
        return factory(**kwargs)

    monkeypatch.setattr(portfolio_page, "create_portfolio_service", create)
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    return app, tmp_path / "working", model


def test_assessments_are_explicit_real_and_restored_after_refresh(connected):
    app, working, model = connected
    assert len(app.dataframe[0].value) == 37
    assert set(app.dataframe[0].value["Compliance"]) == {"Not assessed"}
    assert row(app, "SYN003")["Period"] == "2025-06-30"
    assert model.respond.call_count == 0
    assert app.checkbox(key="portfolio_include_reviews").disabled
    app.selectbox(key="portfolio_period").select("2025-09-30").run()
    app.selectbox(key="portfolio_borrower").select("SYN001").run()
    click(app, "Run selected assessment")
    assert row(app, "SYN001")["Actual"] == "3.12x"
    assert row(app, "SYN001")["Compliance"] == "Compliant"
    assert next(b for b in app.button if b.label == "Run agent review").disabled
    with sqlite3.connect(working / "portfolio.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM portfolio_assessments").fetchone()[0] == 1
    app.text_input(key="portfolio_search").set_value("Harbor").run()
    app.run()
    with sqlite3.connect(working / "portfolio.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM portfolio_assessments").fetchone()[0] == 1
    refreshed = AppTest.from_file(str(APP), default_timeout=20).run()
    refreshed.selectbox(key="portfolio_period").select("2025-09-30").run()
    assert row(refreshed, "SYN001")["Compliance"] == "Compliant"
    assert model.respond.call_count == 0


def test_all_assessments_cover_every_borrower_and_table_click_selects_real_detail(connected):
    app, _, model = connected
    app.selectbox(key="portfolio_period").select("2025-09-30").run()
    app.text_input(key="portfolio_search").set_value("Harbor").run()
    click(app, "Assess all borrowers")
    app.text_input(key="portfolio_search").set_value("").run()
    assert len(app.dataframe[0].value) == 37
    assert "Not assessed" not in set(app.dataframe[0].value["Compliance"])
    assert row(app, "SYN003")["Compliance"] == "Incomplete"
    assert row(app, "SYN003")["Period"] == "2025-09-30"
    assert row(app, "SYN005")["Compliance"] == "Waived"
    assert row(app, "SYN007")["Compliance"] == "Incomplete"
    table = app.dataframe[0]
    index = table.value["ID"].tolist().index("SYN008")
    state = app._tree.get_widget_states()
    state.widgets.add(
        id=table.proto.id, string_value=json.dumps({"selection": {"cells": [[index, "Borrower"]]}})
    )
    app._run(state)
    assert not app.exception
    assert app.selectbox(key="portfolio_borrower").value == "SYN008"
    assert any(item.value == "Atlas Manufacturing" for item in app.header)
    assert model.respond.call_count == 0


def test_review_executes_risk_and_question_agents_and_keeps_snapshot_linkage(
    connected, monkeypatch
):
    app, working, model = connected
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-not-a-real-key")
    app.selectbox(key="portfolio_period").select("2025-09-30").run()
    click(app, "Run selected assessment")
    click(app, "Run agent review")
    assert model.respond.call_count == 4
    assert row(app, "SYN002")["Agent review"] == "Complete"
    assert {"Bullish agent", "Bearish agent", "Recommendation agent"} <= {
        h.value for h in app.subheader
    }
    with sqlite3.connect(working / "portfolio.sqlite3") as connection:
        saved_id = connection.execute("SELECT run_id FROM portfolio_assessments").fetchone()[0]
        assert connection.execute("SELECT run_id FROM portfolio_reviews").fetchone()[0] == saved_id
        assert connection.execute("SELECT COUNT(*) FROM portfolio_assessments").fetchone()[0] == 1
    app.run()
    assert model.respond.call_count == 4
    click(app, "Run selected assessment")
    assert row(app, "SYN002")["Agent review"] == "Not run"
    assert model.respond.call_count == 4
    with sqlite3.connect(working / "portfolio.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM portfolio_reviews").fetchone()[0] == 1


def test_invalid_cutoff_does_not_run_services(connected):
    app, working, model = connected
    app.selectbox(key="portfolio_period").select("2025-12-31").run()
    app.date_input(key="portfolio_cutoff").set_value(date(2025, 9, 30)).run()
    assert not app.exception
    assert any("cutoff must be on or after" in item.value for item in app.error)
    assert not any(button.label == "Assess all borrowers" for button in app.button)
    with sqlite3.connect(working / "portfolio.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM portfolio_assessments").fetchone()[0] == 0
    assert model.respond.call_count == 0


@pytest.mark.parametrize(
    "scope,expected", [("Run selected assessment", 1), ("Assess all borrowers", 37)]
)
def test_assessment_can_include_agent_reviews_for_selected_or_all_borrowers(
    connected,
    monkeypatch,
    scope,
    expected,
):
    app, working, model = connected
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-not-a-real-key")
    app.selectbox(key="portfolio_period").select("2025-09-30").run()
    app.checkbox(key="portfolio_include_reviews").check().run()
    app.text_area(key="portfolio_batch_criteria").set_value(
        "Assess compliance and liquidity."
    ).run()
    click(app, scope)
    with sqlite3.connect(working / "portfolio.sqlite3") as connection:
        assessments = connection.execute("SELECT run_id FROM portfolio_assessments").fetchall()
        reviews = connection.execute("SELECT run_id, result_json FROM portfolio_reviews").fetchall()
    assert len(assessments) == len(reviews) == expected
    assert {item[0] for item in assessments} == {item[0] for item in reviews}
    complete = sum(json.loads(item[1])["status"] == "complete" for item in reviews)
    assert complete >= 1
    assert model.respond.call_count >= 3
    assert len(app.session_state.portfolio_outcomes) == expected
    assert all(
        item["Agent review"] in {"Complete", "Incomplete", "Blocked"}
        for item in app.session_state.portfolio_outcomes
    )
    if expected == 1:
        assert model.respond.call_count == 4
        assert row(app, "SYN002")["Agent review"] == "Complete"
    calls = model.respond.call_count
    app.run()
    assert model.respond.call_count == calls  # A checked option never runs work on rerender.


def test_blank_batch_review_settings_do_not_start_work(connected, monkeypatch):
    app, working, model = connected
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-not-a-real-key")
    app.run()
    app.checkbox(key="portfolio_include_reviews").check().run()
    app.text_area(key="portfolio_batch_criteria").set_value("  ").run()
    assert any("at least one credit criterion" in item.value for item in app.warning)
    assert next(b for b in app.button if b.label == "Assess all borrowers").disabled
    with sqlite3.connect(working / "portfolio.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM portfolio_assessments").fetchone()[0] == 0
    assert model.respond.call_count == 0


def test_service_upgrade_between_reruns_does_not_keep_legacy_assess_signature(
    monkeypatch, tmp_path
):
    root = portfolio_inputs(tmp_path)
    working = tmp_path / "working"
    monkeypatch.setattr(portfolio_page, "DEFAULT_DATA_ROOT", root)
    monkeypatch.setattr(portfolio_page, "DEFAULT_WORKING_DIR", working)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-not-a-real-key")
    model = review_model()
    factory = portfolio_page.create_portfolio_service
    upgraded = False
    created = []

    class LegacyService:
        def __init__(self, service):
            self.service = service

        def __getattr__(self, name):
            return getattr(self.service, name)

        def assess(self, borrower_ids, *, period_end, cutoff, progress=None):
            return self.service.assess(
                borrower_ids,
                period_end=period_end,
                cutoff=cutoff,
                progress=progress,
            )

    def create(**kwargs):
        kwargs["model"] = model
        current = factory(**kwargs)
        created.append(current)
        return current if upgraded else LegacyService(current)

    monkeypatch.setattr(portfolio_page, "create_portfolio_service", create)
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    assert len(created) == 1
    upgraded = True
    app.checkbox(key="portfolio_include_reviews").check().run()
    click(app, "Run selected assessment")
    assert len(created) >= 3  # New service code is picked up on each rerun.
    assert model.respond.call_count == 4
    assert row(app, "SYN002")["Agent review"] == "Complete"
    with sqlite3.connect(working / "portfolio.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM portfolio_assessments").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM portfolio_reviews").fetchone()[0] == 1
