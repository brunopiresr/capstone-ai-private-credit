"""Exercise V3 public controls with isolated storage and offline model boundaries."""

from datetime import date
from pathlib import Path

import pytest
from portfolio_helpers import portfolio_inputs, review_model
from streamlit.testing.v1 import AppTest

from credit_monitoring.agents.follow_up_questions import FollowUpQuestionAgent
from credit_monitoring.application.bootstrap import create_credit_review_service
from credit_monitoring.application.follow_up_question_service import FollowUpQuestionService
from credit_monitoring.web_v3 import services as wiring

APP = Path(__file__).resolve().parents[3] / "src/credit_monitoring/web_v3/app.py"


def click(app, key):
    app.button(key=key).click().run()
    assert not app.exception
    return app


def nav(app, page):
    app.radio(key="v3_nav").set_value(page).run()
    assert not app.exception


@pytest.fixture
def workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(wiring, "DATA_ROOT", portfolio_inputs(tmp_path))
    monkeypatch.setattr(wiring, "WORKING_DIR", tmp_path / "working")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    monkeypatch.setattr("credit_monitoring.observability.configure_observability", lambda: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    services = wiring.get_services()
    monkeypatch.setattr(wiring, "get_services", lambda: services)
    return services


@pytest.fixture
def app(workspace):
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    app.selectbox(key="v3_period").select("2025-09-30")
    app.date_input(key="v3_cutoff").set_value(date(2025, 9, 30)).run()
    assert not app.exception
    return app


def open_borrower(app, bid="SYN002"):
    click(app, f"v3btn_open_{bid}")
    assert app.session_state.v3_page == "Borrower"


def assess(app):
    click(app, "v3btn_assess")
    assert app.selectbox(key="v3_borrower").value == "SYN002"


def review_section(app):
    click(app, "v3btn_review")
    assert app.radio(key="v3_section").value == "Review and submit"


def fill_and_submit(app):
    review_section(app)
    findings = next(c for c in app.text_area if c.label == "Findings and proposed recommendation")
    findings.set_value("Reviewed the saved evidence; continue monitoring with exceptions.")
    next(c for c in app.text_area if c.label.startswith("Breach triage decision")).set_value(
        "Monitor this breach while requesting remediation."
    )
    next(c for c in app.text_area if c.label == "Validation notes / exceptions").set_value(
        "Missing evidence and availability limits explicitly reviewed."
    )
    for check in app.checkbox:
        check.check()
    app.run()
    click(app, "v3btn_validate")
    click(app, "v3btn_submit")


def test_browsing_never_invokes_work(app, workspace, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("Browsing must not launch work")

    monkeypatch.setattr(workspace.analyst, "assess", forbidden)
    monkeypatch.setattr(workspace.analyst.portfolio, "review", forbidden)
    monkeypatch.setattr(workspace.documents, "run_documents", forbidden)
    monkeypatch.setattr("requests.sessions.Session.request", forbidden)
    app.text_input(key="v3_search").set_value("northstar").run()
    assert len([b for b in app.button if b.label == "Open borrower"]) == 1
    app.selectbox(key="v3_filter").select("Missing documents").run()
    assert any("No borrowers match" in i.value for i in app.info)
    app.selectbox(key="v3_filter").select("All borrowers").run()
    open_borrower(app)
    for page in ["Documents", "Risk manager", "Board reports", "Settings", "Help", "Analyst queue"]:
        nav(app, page)
    assert app.text_input(key="v3_search").value == "northstar"
    assert "preview_page" not in app.session_state


def test_document_checklist_empty_and_linked_attachment(app, workspace):
    open_borrower(app)
    click(app, "v3btn_docs")
    save = next(b for b in app.button if b.label == "Save document checklist")
    save.click().run()
    assert not app.exception
    period = date(2025, 9, 30)
    assert workspace.checklists.load("SYN002", period) == []
    assert any("no required documents" in i.value for i in app.info)
    app.multiselect[0].select("Credit agreement").run()
    next(b for b in app.button if b.label == "Save document checklist").click().run()
    assert not app.exception
    assert workspace.checklists.load("SYN002", period)[0]["document_id"] is None
    click(app, "v3btn_documents_back")
    assert app.session_state.v3_page == "Borrower"
    assert workspace.checklists.load("SYN002", period)[0]["document_id"] is None


def test_draft_survives_navigation_and_missing_checklist_does_not_block(app, workspace):
    open_borrower(app)
    assess(app)
    review_section(app)
    findings = next(c for c in app.text_area if c.label == "Findings and proposed recommendation")
    findings.set_value("Unsaved draft survives leaving the page.").run()
    rid = workspace.analyst.portfolio.repository.assessment_history("SYN002")[0][
        0
    ].assessment_run_id
    nav(app, "Documents")
    nav(app, "Analyst queue")
    open_borrower(app)
    review_section(app)
    assert (
        app.text_area(key=f"v3_findings_{rid}").value == "Unsaved draft survives leaving the page."
    )
    click(app, "v3btn_draft")
    assert workspace.analyst.repository.events(rid, "draft")[0]["payload"]["text"].startswith(
        "Unsaved"
    )
    fill_and_submit(app)
    assert workspace.analyst.repository.submissions("SYN002")
    assert workspace.checklists.load("SYN002", date(2025, 9, 30)) is None


def test_manager_queue_case_request_response_and_signoff(app, workspace, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    model = review_model()
    portfolio = workspace.analyst.portfolio
    portfolio.review_service = create_credit_review_service(
        assessment_service=portfolio.assessment_service, model=model
    )
    portfolio.follow_up_service = FollowUpQuestionService(
        wiring.WORKING_DIR, FollowUpQuestionAgent(model)
    )
    open_borrower(app)
    assess(app)
    click(app, "v3btn_ai")
    next(b for b in app.button if b.label == "Generate analysis").click().run()
    assert not app.exception
    fill_and_submit(app)
    nav(app, "Risk manager")
    app.text_input(key="v3_risk_search").set_value("northstar").run()
    click(app, "v3btn_case_SYN002")
    sid = workspace.analyst.repository.submissions("SYN002")[0]["submission_id"]
    app.text_input(key=f"v3_request_question_{sid}_False").set_value("Explain the evidence limits.")
    next(b for b in app.button if b.label == "Create analyst request").click().run()
    assert not app.exception
    request = workspace.manager.pending_requests("SYN002")[0]
    assert app.button(key="v3btn_case_back")
    assert next(b for b in app.button if b.label == "Complete manager review").disabled
    click(app, "v3btn_case_analyst")
    rid = request["request_id"]
    click(app, f"v3btn_request_run_{rid}")
    app.text_area(key=f"v3_response_{rid}").set_value("Reviewed the supplementary evidence limits.")
    next(b for b in app.button if b.label == "Submit response").click().run()
    assert not app.exception
    nav(app, "Risk manager")
    assert app.text_input(key="v3_risk_search").value == "northstar"
    click(app, "v3btn_case_SYN002")
    click(app, f"v3btn_accept_{rid}")
    app.text_area(key=f"v3_manager_comment_{sid}").set_value("Evidence and exceptions reviewed.")
    app.text_area(key=f"v3_manager_recommendation_{sid}").set_value("Continue monitoring.")
    next(b for b in app.button if b.label == "Complete manager review").click().run()
    assert not app.exception
    assert workspace.manager.state(workspace.manager.repository.submission(sid)) == "Reviewed"
    click(app, "v3btn_case_back")
    assert app.text_input(key="v3_risk_search").value == "northstar"


def test_assistant_unavailable_and_version_isolation(app, workspace):
    open_borrower(app)
    assess(app)
    first = workspace.analyst.portfolio.repository.assessment_history("SYN002")[0][0]
    click(app, "v3btn_assistant")
    assert app.session_state.v3_page == "Assistant"
    app.text_area(key=f"v3_chat_draft_{first.assessment_run_id}").set_value(
        "My question draft"
    ).run()
    assert app.button(key="v3btn_chat_send").disabled
    click(app, "v3btn_assistant_back")
    assess(app)
    click(app, "v3btn_assistant")
    assert len(app.session_state.v3_chats) == 2
    assert app.text_area[0].value == ""


def test_board_report_save_and_finalize(app, workspace):
    nav(app, "Board reports")
    click(app, "v3btn_board_generate")
    next(b for b in app.button if b.label == "Save report draft").click().run()
    assert not app.exception
    next(b for b in app.button if b.label == "Finalize report").click().run()
    assert not app.exception
    assert workspace.manager.repository.board_reports()[0]["state"] == "final"
    nav(app, "Analyst queue")
    assert app.session_state.v3_page == "Analyst queue"


def test_readiness_priorities_and_optional_metrics(workspace):
    from credit_monitoring.web_v3.readiness import project

    period = date(2025, 9, 30)

    def readiness():
        entry = next(
            e
            for e in workspace.analyst.portfolio.snapshot(period_end=period, cutoff=period)
            if e.borrower_id == "SYN002"
        )
        return project(workspace, entry, period, workspace.documents.inventory())

    assert readiness().action == "Set up documents"
    workspace.checklists.save("SYN002", period, [], [])
    assert readiness().action == "Run covenant assessment"
    assessment = workspace.analyst.assess("SYN002", period, period)
    assert "Missing financial inputs" not in readiness().categories
    assert readiness().action == "Review and submit findings"
    rid = assessment.assessment_run_id
    workspace.analyst.validate(rid, checks=(True, True, True), notes="Checked evidence.")
    assert "Needs action" in readiness().categories
    workspace.analyst.save_report(rid, text="Monitoring recommendation.")
    assert "Ready to submit" in readiness().categories
    sid = workspace.analyst.save_report(rid, text="Monitoring recommendation.", submit=True)
    workspace.manager.request_analysis(sid, kind="context", question="Explain the risks.")
    workspace.checklists.save(
        "SYN002", period, [{"document_type": "10-Q", "document_id": None}], []
    )
    assert readiness().action == "Respond to manager"
    assert {"Manager requests", "Missing documents"} <= readiness().categories


def test_manager_cases_include_unsubmitted_flags_and_sort_by_priority(workspace):
    from credit_monitoring.web_v3.readiness import manager_cases

    period = date(2025, 9, 30)
    for bid, severity, due in [
        ("SYN001", "High", date(2026, 12, 3)),
        ("SYN002", "High", date(2026, 12, 1)),
        ("SYN003", "Critical", None),
    ]:
        assessment = workspace.analyst.assess(bid, period, period)
        rid = assessment.assessment_run_id
        workspace.analyst.flag(
            rid,
            category="Performance",
            severity=severity,
            explanation="Headroom concern",
            action="Monitor",
        )
        if due:
            workspace.analyst.validate(rid, checks=(True, True, True), notes="Reviewed exceptions.")
            sid = workspace.analyst.save_report(rid, text="Continue monitoring.", submit=True)
            workspace.manager.request_analysis(sid, kind="context", question="Explain.", due=due)
    cases = manager_cases(workspace, period, period)
    assert [c["borrower_id"] for c in cases] == ["SYN003", "SYN002", "SYN001"]
    assert cases[0]["submission"] is None


@pytest.mark.parametrize("failed_state", ["failed", "missing"])
def test_document_retry_targets_failed_supported_sources_only(
    app, workspace, monkeypatch, failed_state
):
    did = workspace.documents.register(
        company="Test issuer",
        title="HTML evidence",
        url="https://example.test/filing.html",
        document_type="10-Q",
        document_date=date(2025, 9, 30),
        borrower_ids=["SYN002"],
    )
    inventory = workspace.documents.inventory()
    for record in inventory:
        if record["document_id"] == did:
            record["status"] = failed_state
            record["error"] = "Previous download or extraction failed."
    monkeypatch.setattr(workspace.documents, "inventory", lambda: inventory)
    calls = []

    def process(kind, ids, **kwargs):
        calls.append((kind, ids, kwargs.get("force")))
        return [{"document_id": did, "status": "complete"}]

    monkeypatch.setattr(workspace.documents, "run_documents", process)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    open_borrower(app)
    click(app, "v3btn_docs")
    click(app, "v3btn_retry")
    assert calls == [("Process", [did], False)]
    assert app.session_state.v3_document_outcomes[0]["status"] == "complete"


def test_assistant_suggestions_retain_draft_and_recalculation_is_explicit(
    app, workspace, monkeypatch
):
    from credit_monitoring.domain.agent import AgentAnswer
    from credit_monitoring.web_v3 import assistant

    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    model = review_model()
    portfolio = workspace.analyst.portfolio
    portfolio.follow_up_service = FollowUpQuestionService(
        wiring.WORKING_DIR, FollowUpQuestionAgent(model)
    )
    open_borrower(app)
    assess(app)
    assessment = portfolio.repository.assessment_history("SYN002")[0][0]
    rid = assessment.assessment_run_id
    portfolio.follow_up_service.generate(assessment, None)
    conversations = []

    class Conversation:
        closed = False

        def __init__(self, agent):
            self.service = agent.assessment_service
            self.questions = []

        def prime_evidence(self, *args):
            pass

        def ask(self, question, **kwargs):
            self.questions.append(question)
            self.service.assess("SYN002", assessment.period_end, assessment.information_cutoff)
            return AgentAnswer(
                answer="Saved evidence is limited; inspect the source references.",
                confidence="medium",
            )

        def close(self):
            self.closed = True

    def start(agent, **kwargs):
        conversation = Conversation(agent)
        conversations.append(conversation)
        return conversation

    monkeypatch.setattr(assistant.CreditAssessmentAgent, "start_conversation", start)
    click(app, "v3btn_assistant")
    suggestion = f"v3btn_suggestion_{rid}_0"
    click(app, suggestion)
    assert "evidence gaps" in app.text_area(key=f"v3_chat_draft_{rid}").value
    app.text_area(key=f"v3_chat_draft_{rid}").set_value("My edited question.").run()
    click(app, suggestion)
    assert app.text_area(key=f"v3_chat_draft_{rid}").value == "My edited question."
    click(app, "v3btn_chat_send")
    assert conversations[0].questions == ["My edited question."]
    assert len(portfolio.repository.assessment_history("SYN002")) == 1
    app.text_area(key=f"v3_chat_draft_{rid}").set_value("Recalculate this version.")
    app.checkbox(key=f"v3_chat_recalc_{rid}").check().run()
    click(app, "v3btn_chat_send")
    assert app.session_state.v3_page == "Borrower"
    assert len(portfolio.repository.assessment_history("SYN002")) == 2
