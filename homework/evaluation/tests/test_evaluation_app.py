"""Drive the complete rating loop through Streamlit without paid model calls."""

import json
from pathlib import Path

import evaluation_backend as backend
import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


def button(app, label):
    return next(item for item in app.button if item.label == label)


def start_and_run(app):
    button(app, "Start evaluation").click().run()
    button(app, "Run question").click().run()


@pytest.fixture
def app(tmp_path, monkeypatch, agent_calls):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setattr("credit_monitoring.observability.configure_observability", lambda: None)
    original = backend.EvaluationRound

    class TestRound(original):
        def __init__(self, **kwargs):
            super().__init__(output_root=tmp_path, **kwargs)

    monkeypatch.setattr(backend, "EvaluationRound", TestRound)
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    return app


def test_no_calls_until_start_and_rerenders_and_invalid_feedback_do_not_regenerate(
    app, agent_calls
):
    assert not agent_calls
    button(app, "Start evaluation").click().run()
    assert not app.exception
    assert not agent_calls and not app.selectbox
    assert [item.label for item in app.button] == ["Run question", "Skip", "Cancel / restart"]
    app.run()
    assert not agent_calls
    button(app, "Run question").click().run()
    assert len(agent_calls) == 1
    assert "Generated answer for E01" in [item.value for item in app.markdown]
    assert [item.label for item in app.button] == ["Submit and next", "Skip", "Cancel / restart"]
    app.run()
    button(app, "Submit and next").click().run()
    assert not app.exception
    assert app.info[0].value == "Choose a response category first."
    assert app.selectbox[0].options == list(backend.RESPONSE_CATEGORIES.values())
    assert not app.feedback
    assert len(agent_calls) == 1
    assert app.session_state["evaluation_ui_round"].index == 0


def test_restart_clears_progress_and_forms_and_generates_fresh_answer(app, agent_calls):
    start_and_run(app)
    old = app.session_state["evaluation_ui_round"]
    app.selectbox[0].set_value("incorrect")
    app.text_area[0].set_value("Needs better citations")
    button(app, "Submit and next").click().run()
    assert old.index == 1 and len(agent_calls) == 1 and not app.selectbox
    button(app, "Run question").click().run()
    assert old.index == 1 and len(agent_calls) == 2
    app.selectbox[0].set_value("unclear")
    app.text_area[0].set_value("Unsent draft comment")
    button(app, "Cancel / restart").click().run()
    assert not app.exception
    assert app.session_state["evaluation_ui_round"] is old and not old._ended
    assert len(agent_calls) == 2
    table = app.dataframe[0].value
    assert table.columns.tolist() == ["Question ID", "Rate", "Comments"]
    assert table.to_dict("records") == [
        {"Question ID": "E01", "Rate": "Incorrect", "Comments": "Needs better citations"},
        {
            "Question ID": "E02",
            "Rate": "Unclear (not submitted)",
            "Comments": "Unsent draft comment",
        },
    ]
    assert not app.expander
    button(app, "Continue evaluating").click().run()
    assert not app.exception and len(agent_calls) == 2
    assert app.selectbox[0].value == "unclear"
    assert app.text_area[0].value == "Unsent draft comment"
    assert not any(item.label == "Proceed to restart" for item in app.button)
    button(app, "Cancel / restart").click().run()
    button(app, "Proceed to restart").click().run()
    new = app.session_state["evaluation_ui_round"]
    assert not app.exception
    assert new.session.session_id != old.session.session_id
    assert old._ended and new.index == 0
    assert new.attempt is None and not app.selectbox and len(agent_calls) == 2
    button(app, "Run question").click().run()
    assert app.selectbox[0].value is None and app.text_area[0].value == ""
    assert len(agent_calls) == 3
    assert len(list(old.folder.glob("**/feedback.json"))) == 1


def test_27_ratings_show_summary_before_new_round(app, agent_calls):
    button(app, "Start evaluation").click().run()
    original = app.session_state["evaluation_ui_round"]
    for index in range(27):
        assert app.session_state["evaluation_ui_round"].index == index
        assert len(agent_calls) == index
        button(app, "Run question").click().run()
        app.selectbox[0].set_value(tuple(backend.RESPONSE_CATEGORIES)[index % 7])
        app.text_area[0].set_value(f"Feedback {index + 1}")
        button(app, "Submit and next").click().run()
        assert not app.exception
    assert original.complete and original._ended
    assert app.session_state["evaluation_ui_round"] is original
    assert len(agent_calls) == 27 and not app.expander
    assert not any(item.label == "Continue evaluating" for item in app.button)
    assert "27 of 27 answers evaluated." in [item.value for item in app.markdown]
    table = app.dataframe[0].value
    assert table.columns.tolist() == ["Question ID", "Rate", "Comments"]
    assert table["Question ID"].tolist() == [case["case_id"] for case in original.cases]
    assert table["Comments"].tolist() == [f"Feedback {i + 1}" for i in range(27)]
    assert not any("Generated answer for" in item.value for item in app.markdown)
    app.run()
    assert not app.exception and len(agent_calls) == 27
    files = list(original.folder.glob("**/feedback.json"))
    assert len(files) == 27
    feedback = [json.loads(path.read_text()) for path in files]
    assert {row["case_id"] for row in feedback} == {case["case_id"] for case in original.cases}
    assert {row["category"] for row in feedback} == set(backend.RESPONSE_CATEGORIES)
    assert all("rating" not in row for row in feedback)
    button(app, "Proceed to restart").click().run()
    assert not app.exception
    current = app.session_state["evaluation_ui_round"]
    assert current.session.session_id != original.session.session_id and current.index == 0
    assert len(agent_calls) == 27 and current.attempt is None
    assert not app.selectbox and not app.text_area
    assert not button(app, "Run question").disabled


def test_cancel_before_any_classification_does_not_submit_feedback(app, agent_calls):
    start_and_run(app)
    original = app.session_state["evaluation_ui_round"]
    button(app, "Cancel / restart").click().run()
    assert not app.exception and len(agent_calls) == 1
    assert "0 of 27 answers evaluated." in [item.value for item in app.markdown]
    assert app.dataframe[0].value.to_dict("records") == [
        {"Question ID": "E01", "Rate": "Not evaluated", "Comments": ""}
    ]
    assert not list(original.folder.glob("**/feedback.json"))
    button(app, "Proceed to restart").click().run()
    assert not app.exception and len(agent_calls) == 1
    assert not list(original.folder.glob("**/feedback.json"))


def test_missing_credentials_allow_preview_and_skip_but_disable_run(app, monkeypatch, agent_calls):
    monkeypatch.delenv("OPENAI_API_KEY")
    app.run()
    assert not button(app, "Start evaluation").disabled
    button(app, "Start evaluation").click().run()
    assert button(app, "Run question").disabled
    assert not button(app, "Skip").disabled
    button(app, "Skip").click().run()
    assert not app.exception and app.session_state["evaluation_ui_round"].case["case_id"] == "E02"
    assert not agent_calls


def test_reloaded_app_accepts_categories_for_existing_answer(app, agent_calls):
    start_and_run(app)
    original = app.session_state["evaluation_ui_round"]
    attempt = original.attempt

    class PreviousVersion:
        def rate(self, rating, comment):
            raise AssertionError("The app must use the updated category submission method.")

    previous = PreviousVersion()
    previous.__dict__.update(vars(original))
    app.session_state["evaluation_ui_round"] = previous
    app.run()
    assert not app.exception and len(agent_calls) == 1
    assert (
        app.session_state["evaluation_ui_round"].session.session_id == original.session.session_id
    )
    app.selectbox[0].set_value("unsupported_claims")
    button(app, "Submit and next").click().run()
    assert not app.exception and len(agent_calls) == 1
    assert app.session_state["evaluation_ui_round"].index == 1
    assert (
        json.loads((attempt.folder / "feedback.json").read_text())["category"]
        == "unsupported_claims"
    )


def test_failed_answer_offers_retry_without_advancing(app, monkeypatch, agent_calls):
    monkeypatch.setattr(backend.workbench, "missing_sources", lambda _: ["MISSING"])
    start_and_run(app)
    assert not app.exception and not app.selectbox
    assert app.session_state["evaluation_ui_round"].index == 0
    assert not agent_calls
    monkeypatch.setattr(backend.workbench, "missing_sources", lambda _: [])
    button(app, "Retry answer").click().run()
    assert not app.exception and len(agent_calls) == 1
    assert app.selectbox[0].value is None


def test_skipping_all_questions_opens_summary_without_model_calls(app, agent_calls):
    button(app, "Start evaluation").click().run()
    current = app.session_state["evaluation_ui_round"]
    for index in range(27):
        assert current.index == index
        button(app, "Skip").click().run()
        assert not app.exception and not agent_calls
    assert current.complete and current._ended
    assert app.dataframe[0].value["Rate"].tolist() == ["Skipped"] * 27
    assert app.dataframe[0].value["Comments"].tolist() == [""] * 27
    assert "0 of 27 answers evaluated." in [item.value for item in app.markdown]
    assert len(list(current.folder.glob("*/skip.json"))) == 27
    assert not list(current.folder.glob("**/feedback.json"))
    button(app, "Proceed to restart").click().run()
    assert not app.exception and not agent_calls
    assert app.session_state["evaluation_ui_round"].index == 0


def test_skip_after_answer_discards_unsent_classification_and_previews_next(app, agent_calls):
    start_and_run(app)
    current = app.session_state["evaluation_ui_round"]
    app.selectbox[0].set_value("incorrect")
    app.text_area[0].set_value("Unsent comment")
    button(app, "Skip").click().run()
    assert not app.exception and len(agent_calls) == 1
    assert current.case["case_id"] == "E02" and current.attempt is None
    assert not app.selectbox and not list(current.folder.glob("**/feedback.json"))
    button(app, "Cancel / restart").click().run()
    assert not app.exception and len(agent_calls) == 1
    assert app.dataframe[0].value.to_dict("records") == [
        {"Question ID": "E01", "Rate": "Skipped", "Comments": ""},
        {"Question ID": "E02", "Rate": "Not run", "Comments": ""},
    ]
