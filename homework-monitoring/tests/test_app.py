from pathlib import Path

import monitoring_backend as backend_module
import pytest
from demo_models import QUESTION, REVIEW_ARGS, review_model, text_response
from model_helpers import ScriptedModel, model_response
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture
def working_app(monkeypatch, data_root, tmp_path):
    model = ScriptedModel()
    instances = []
    original = backend_module.ChatBackend

    def factory(**kwargs):
        chat = original(
            model=model,
            review_model=review_model(),
            data_root=data_root,
            runtime_root=tmp_path / "runtime",
        )
        instances.append(chat)
        return chat

    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setattr("credit_monitoring.observability.configure_observability", lambda: None)
    monkeypatch.setattr(backend_module, "ChatBackend", factory)
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    return app, model, instances


def button(app, label):
    return next(item for item in app.button if item.label == label)


def test_samples_copy_without_executing_and_missing_key_disables_chat(working_app, monkeypatch):
    app, model, _ = working_app
    button(app, "Find covenant terms").click().run()
    assert app.chat_input[0].proto.set_value
    assert "FMC" in app.chat_input[0].proto.value
    assert not app.chat_message
    model.respond.assert_not_called()
    button(app, "Credit Analysis").click().run()
    assert not app.date_input and not app.text_input and not app.selectbox
    button(app, "Full credit review").click().run()
    assert "SYN001" in app.chat_input[0].proto.value
    assert not app.chat_message
    monkeypatch.delenv("OPENAI_API_KEY")
    app.run()
    assert app.chat_input[0].disabled
    assert any("OPENAI_API_KEY" in item.value for item in app.info)


def test_evidence_answer_progress_and_sources_survive_reruns(working_app):
    app, model, instances = working_app
    model.respond.side_effect = [
        model_response(("search_evidence", {"query": "maximum leverage", "ticker": "SYN"})),
        model_response(answer="The local SYN agreement states maximum leverage of 4.0."),
    ]
    app.chat_input[0].set_value("Find leverage evidence for SYN, with exact citations.").run()
    assert not app.exception, app.exception
    turn = app.session_state["monitoring_ui_messages"]["Evidence Search"][-1]["turn"]
    assert turn.finished and not turn.error
    assert len(app.chat_message) == 2
    assert any("maximum leverage of 4.0" in item.value for item in app.markdown)
    assert any(item.label == "Sources" for item in app.expander)
    assert any("search_evidence" in item.value for item in app.markdown)
    assert not app.session_state["monitoring_ui_busy"]
    assert not app.chat_input[0].disabled
    calls = model.respond.call_count
    app.run()
    assert model.respond.call_count == calls
    button(app, "Credit Analysis").click().run()
    assert not app.chat_message
    button(app, "Evidence Search").click().run()
    assert len(app.chat_message) == 2
    old = instances[0]
    old_id = old.session.session_id
    button(app, "Reset session").click().run()
    assert old._closed and old.evidence.closed
    assert app.session_state["monitoring_ui_session_id"] != old_id
    assert not app.chat_message


def test_credit_ui_renders_authoritative_review_and_reuses_followups(working_app):
    app, model, instances = working_app
    button(app, "Credit Analysis").click().run()
    model.respond.side_effect = [
        model_response(("run_credit_review", REVIEW_ARGS)),
        text_response(),
    ]
    app.chat_input[0].set_value(QUESTION).run()
    assert not app.exception, app.exception
    turn = app.session_state["monitoring_ui_messages"]["Credit Analysis"][-1]["turn"]
    assert turn.review is not None and not turn.error
    assert {item.label for item in app.expander} >= {
        "Tools called",
        "Calculations, verification and ML",
        "Bullish analysis",
        "Bearish analysis",
        "Final recommendation and limitations",
        "Review evidence and source records",
    }
    assert any(item.label == "Actual" and item.value == "3.12x" for item in app.metric)
    assert any("stub" in item.value for item in app.markdown)
    original = instances[0]._review.review_id
    model.respond.side_effect = [text_response("The review reports positive headroom.")]
    app.chat_input[0].set_value("Explain the headroom from that review.").run()
    assert not app.exception, app.exception
    assert instances[0]._review.review_id == original
    assert len(app.chat_message) == 4
    calls = model.respond.call_count
    app.run()
    assert model.respond.call_count == calls
    second = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not second.exception
    assert not second.chat_message
    assert instances[-1].session.session_id != instances[0].session.session_id


def test_failure_preserves_chat_and_reenables_controls(working_app):
    app, model, _ = working_app
    button(app, "Credit Analysis").click().run()
    model.respond.side_effect = RuntimeError("synthetic provider failure")
    app.chat_input[0].set_value(QUESTION).run()
    assert not app.exception
    assert len(app.chat_message) == 2
    assert not app.chat_input[0].disabled
    assert not button(app, "Reset session").disabled
    assert any("could not complete" in item.value for item in app.markdown)
