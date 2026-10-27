from pathlib import Path

import monitoring_backend as backend_module
import pytest
from demo_models import QUESTION, REVIEW_ARGS, review_model, text_response
from model_helpers import ScriptedModel, model_response
from streamlit.testing.v1 import AppTest
from user_events import UserEvents

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture
def event_records(monkeypatch):
    records = []

    def emit(self, event_name, mode, **attributes):
        records.append(
            {
                "event_name": event_name,
                "mode": mode,
                "session_id": self.session.session_id,
                **attributes,
            }
        )

    monkeypatch.setattr(UserEvents, "_emit", emit)
    return records


@pytest.fixture
def working_app(monkeypatch, data_root, tmp_path, event_records):
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


def test_user_feedback_sources_and_followups_are_linked_without_rerun_duplicates(
    working_app, event_records
):
    app, model, instances = working_app
    button(app, "Find covenant terms").click().run()
    assert event_records[-1]["target"] == "sample_question"
    assert event_records[-1]["sample_index"] == 0
    model.respond.side_effect = [
        model_response(("search_evidence", {"query": "maximum leverage", "ticker": "SYN"})),
        model_response(answer="The SYN agreement states maximum leverage of 4.0."),
    ]
    app.chat_input[0].set_value("Find leverage evidence for SYN.").run()
    assert not app.exception
    first = app.session_state["monitoring_ui_messages"]["Evidence Search"][-1]["turn"]
    button(app, "View citation 1").click().run()
    assert not app.exception
    assert event_records[-1]["target"] == "source"
    assert event_records[-1]["interaction_id"] == first.interaction_id
    # Closing a citation does not falsely record another source inspection.
    count = len(event_records)
    button(app, "View citation 1").click().run()
    assert len(event_records) == count

    app.feedback[0].set_value(0)
    next(item for item in app.selectbox if item.label == "Reason (optional)").select("Unclear")
    app.text_area[0].set_value("PRIVATE USER COMMENT")
    button(app, "Send feedback").click().run()
    assert not app.exception
    feedback = event_records[-1]
    assert feedback["event_name"] == "user.feedback"
    assert feedback["interaction_id"] == first.interaction_id
    assert feedback["rating"] == "negative" and feedback["reason"] == "Unclear"
    assert "PRIVATE USER COMMENT" not in str(event_records)
    count = len(event_records)
    app.run()
    assert len(event_records) == count

    next(item for item in app.selectbox if item.label.startswith("Next question")).select(
        "Clarification"
    ).run()
    model.respond.side_effect = [model_response(answer="The limit is 4.0 times.")]
    app.chat_input[0].set_value("Explain that limit.").run()
    assert not app.exception
    followup = next(record for record in event_records if record["event_name"] == "user.follow_up")
    assert followup["previous_interaction_id"] == first.interaction_id
    assert followup["follow_up_type"] == "Clarification"
    assert followup["session_id"] == instances[0].session.session_id
    # Another mode starts its own question history within the shared session.
    button(app, "Credit Analysis").click().run()
    model.respond.side_effect = [text_response("Which borrower should I review?")]
    app.chat_input[0].set_value("Review a borrower.").run()
    assert sum(record["event_name"] == "user.follow_up" for record in event_records) == 1


def test_retry_and_reset_record_old_session_before_starting_new_one(working_app, event_records):
    app, model, _ = working_app
    button(app, "Credit Analysis").click().run()
    model.respond.side_effect = RuntimeError("PRIVATE PROVIDER FAILURE")
    app.chat_input[0].set_value(QUESTION).run()
    assert not app.exception
    first = app.session_state["monitoring_ui_messages"]["Credit Analysis"][-1]["turn"]
    old_id = app.session_state["monitoring_ui_session_id"]
    model.respond.side_effect = [text_response("Which information should I use?")]
    button(app, "Retry question").click().run()
    assert not app.exception
    retry = next(record for record in event_records if record["event_name"] == "user.retry")
    assert retry["retry_of"] == retry["previous_interaction_id"] == first.interaction_id
    assert retry["previous_error"] == "RuntimeError"
    assert retry["session_id"] == old_id
    assert "PRIVATE PROVIDER FAILURE" not in str(event_records)
    button(app, "Reset session").click().run()
    assert not app.exception
    reset = event_records[-3]
    assert reset["event_name"] == "user.reset_context"
    assert reset["session_id"] == old_id
    assert reset["cleared_turn_count"] == 2
    assert reset["cleared_modes"] == ["Evidence Search", "Credit Analysis"]
    assert reset["interaction_id"] == retry["interaction_id"]
    assert event_records[-2]["event_name"] == "user.ended"
    assert event_records[-2]["session_id"] == old_id
    assert event_records[-1]["event_name"] == "user.started"
    assert event_records[-1]["session_id"] != old_id
    assert event_records[-1]["previous_chat_id"] == old_id


def test_rerun_and_reset_upgrade_stale_tracker_without_resetting_context(
    working_app, event_records
):
    app, _, instances = working_app
    current = app.session_state["monitoring_ui_events"]

    class OldUserEvents(UserEvents):
        def _emit(self, *args, **kwargs):
            raise AssertionError("Stale emitter: User event: {event_name}")

    old = OldUserEvents(current.session)
    old.__dict__.update(vars(current))
    app.session_state["monitoring_ui_events"] = old
    count = len(event_records)
    app.run()
    assert not app.exception
    assert len(instances) == 1 and len(event_records) == count
    assert type(app.session_state["monitoring_ui_events"]) is UserEvents
    button(app, "Find covenant terms").click().run()
    assert not app.exception
    assert event_records[-1]["target"] == "sample_question"
    # Streamlit callbacks run before initialization; reset must upgrade too.
    app.session_state["monitoring_ui_events"] = old
    button(app, "Reset session").click().run()
    assert not app.exception
    assert event_records[-3]["event_name"] == "user.reset_context"
    assert event_records[-3]["cleared_turn_count"] == 0
    assert len(instances) == 2
