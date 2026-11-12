"""Portfolio discovery, explicit borrower runs, and clearly scoped batch actions."""

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


def row(app, borrower_name):
    frame = app.dataframe[0].value
    return frame.loc[frame["Borrower"] == borrower_name].iloc[0]


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
        return factory(**{**kwargs, "model": model})

    monkeypatch.setattr(portfolio_page, "create_portfolio_service", create)
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    return app, tmp_path / "working", model


def test_discovery_has_six_columns_and_no_inline_assessment(connected):
    app, _, model = connected
    assert list(app.dataframe[0].value.columns) == [
        "Borrower",
        "Sector",
        "Period",
        "Compliance",
        "Workflow status",
        "Last assessed",
    ]
    assert len(app.dataframe[0].value) == 37
    assert set(app.dataframe[0].value["Compliance"]) == {"Not assessed"}
    assert not any(b.label == "Run selected assessment" for b in app.button)
    assert len(app.dataframe) == 1
    assert app.checkbox(key="portfolio_include_reviews").disabled
    assert model.respond.call_count == 0


def test_borrower_run_and_refresh_preserve_results_without_implicit_work(connected):
    app, working, model = connected
    app.selectbox(key="portfolio_period").select("2025-09-30").run()
    app.selectbox(key="portfolio_borrower").select("SYN001").run()
    click(app, "Open borrower")
    assert app.selectbox(key="analysis_borrower").value == "SYN001"
    click(app, "Run assessment")
    assert next(b for b in app.button if b.label == "Generate AI review").disabled
    assert (
        next(t for t in app.tabs if t.label == "Evidence").dataframe[0].value["Actual"][0] == 3.125
    )
    click(app, "Back to portfolio")
    assert row(app, "Harbor Components")["Compliance"] == "Compliant"
    app.text_input(key="portfolio_search").set_value("Harbor").run()
    app.run()
    with sqlite3.connect(working / "portfolio.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM portfolio_assessments").fetchone()[0] == 1
    fresh = AppTest.from_file(str(APP), default_timeout=20).run()
    fresh.selectbox(key="portfolio_period").select("2025-09-30").run()
    assert row(fresh, "Harbor Components")["Compliance"] == "Compliant"
    assert model.respond.call_count == 0


def test_batch_ignores_filters_and_table_selection_requires_explicit_open(connected):
    app, _, model = connected
    app.selectbox(key="portfolio_period").select("2025-09-30").run()
    app.text_input(key="portfolio_search").set_value("Harbor").run()
    assert any("all 37 registered borrowers" in c.value for c in app.caption)
    click(app, "Assess all borrowers (37)")
    app.text_input(key="portfolio_search").set_value("").run()
    assert "Not assessed" not in set(app.dataframe[0].value["Compliance"])
    assert row(app, "Elmwood Services")["Compliance"] == "Incomplete"
    table = app.dataframe[0]
    index = table.value["Borrower"].tolist().index("Atlas Manufacturing")
    states = app._tree.get_widget_states()
    states.widgets.add(
        id=table.proto.id, string_value=json.dumps({"selection": {"cells": [[index, "Borrower"]]}})
    )
    app._run(states)
    assert not app.exception
    assert app.selectbox(key="portfolio_borrower").value == "SYN008"
    assert app.session_state.preview_page == "Portfolio"
    click(app, "Open borrower")
    assert app.selectbox(key="analysis_borrower").value == "SYN008"
    assert any(t.value == "Atlas Manufacturing" for t in app.title)
    assert model.respond.call_count == 0


def test_optional_ai_review_uses_exact_saved_version(connected, monkeypatch):
    app, working, model = connected
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    app.selectbox(key="portfolio_period").select("2025-09-30").run()
    click(app, "Open borrower")
    click(app, "Run assessment")
    click(app, "Generate AI review")
    assert model.respond.call_count == 4
    assert {"Bullish agent", "Bearish agent", "Recommendation agent"} <= {
        h.value for h in app.subheader
    }
    assert any(
        e.label == "Supporting AI arguments and evidence" and not e.proto.expanded
        for e in app.expander
    )
    with sqlite3.connect(working / "portfolio.sqlite3") as connection:
        saved = connection.execute("SELECT run_id FROM portfolio_assessments").fetchone()[0]
        assert connection.execute("SELECT run_id FROM portfolio_reviews").fetchone()[0] == saved
    app.run()
    assert model.respond.call_count == 4
    click(app, "Run new assessment")
    assert not any(h.value == "AI recommendation" for h in app.subheader)
    assert model.respond.call_count == 4


def test_invalid_cutoff_does_not_run_services(connected):
    app, working, model = connected
    app.selectbox(key="portfolio_period").select("2025-12-31").run()
    app.date_input(key="portfolio_cutoff").set_value(date(2025, 9, 30)).run()
    assert not app.exception
    assert any("cutoff must be on or after" in e.value for e in app.error)
    assert not any(b.key == "portfolio_assess_all" for b in app.button)
    with sqlite3.connect(working / "portfolio.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM portfolio_assessments").fetchone()[0] == 0
    assert model.respond.call_count == 0


def test_batch_can_include_ai_reviews_and_rerender_never_runs_work(connected, monkeypatch):
    app, working, model = connected
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    app.selectbox(key="portfolio_period").select("2025-09-30").run()
    app.checkbox(key="portfolio_include_reviews").check().run()
    app.text_area(key="portfolio_batch_criteria").set_value(
        "Assess compliance and liquidity."
    ).run()
    click(app, "Assess all borrowers (37)")
    with sqlite3.connect(working / "portfolio.sqlite3") as connection:
        assessments = connection.execute("SELECT run_id FROM portfolio_assessments").fetchall()
        reviews = connection.execute("SELECT run_id FROM portfolio_reviews").fetchall()
    assert len(assessments) == len(reviews) == 37
    assert {item[0] for item in assessments} == {item[0] for item in reviews}
    calls = model.respond.call_count
    assert calls >= 3
    assert len(app.session_state.portfolio_outcomes) == 37
    app.run()
    assert model.respond.call_count == calls


def test_blank_batch_criteria_block_work(connected, monkeypatch):
    app, working, model = connected
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    app.run()
    app.checkbox(key="portfolio_include_reviews").check().run()
    app.text_area(key="portfolio_batch_criteria").set_value("  ").run()
    assert app.button(key="portfolio_assess_all").disabled
    with sqlite3.connect(working / "portfolio.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM portfolio_assessments").fetchone()[0] == 0
    assert model.respond.call_count == 0
