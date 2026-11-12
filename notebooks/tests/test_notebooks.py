"""Exercise the actual notebook chat helper without credentials or notebook setup."""

import ast
import asyncio
import csv
import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import nbformat
import pytest
from model_helpers import ScriptedModel, model_response

from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.agents.events import AgentEventCallback
from credit_monitoring.domain import CovenantExtraction, RiskAssessment, ToolExecution, ToolFailure
from credit_monitoring.domain.agent import AgentAnswer
from credit_monitoring.paths import APP_SYNTHETIC_DIR, MODELS_DIR

NOTEBOOK = Path(__file__).resolve().parents[1] / "03-agents.ipynb"


@pytest.fixture
def notebook_cells():
    notebook = json.loads(NOTEBOOK.read_text())
    return {cell["id"]: "".join(cell["source"]) for cell in notebook["cells"]}


def test_notebook_passes_mapping_question_to_agent(notebook_cells):
    model = ScriptedModel(
        response=model_response(
            answer="No configured relationship links SYN002 to FMC.", answer_kind="scope"
        )
    )
    service = Mock()
    show_answer = Mock()
    namespace = {
        "document_agent": CreditAssessmentAgent(service=service, model=model),
        "AgentEventCallback": AgentEventCallback,
        "show_answer": show_answer,
    }
    code = compile(
        notebook_cells["test-issuer-mapping"],
        "test-issuer-mapping",
        "exec",
        flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
    )
    asyncio.run(eval(code, namespace))
    answer = namespace["issuer_mapping_answer"]
    assert answer.complete and answer.answer_kind == "scope"
    assert "SYN002" in answer.answer and "FMC" in answer.answer
    assert not answer.tool_trace and not answer.evidence
    show_answer.assert_called_once_with(answer)
    model.respond.assert_called_once()
    assert service.mock_calls == []


def test_notebook_assessment_passes_structured_dates(notebook_cells):
    agent = Mock()
    agent.ask_async = AsyncMock(return_value=AgentAnswer(answer="Assessment complete."))
    namespace = {
        "date": date,
        "BORROWER_ID": "SYN002",
        "PERIOD_END": "2025-09-30",
        "INFORMATION_CUTOFF": "2025-09-30",
        "assessment_agent": agent,
        "AgentEventCallback": AgentEventCallback,
        "show_answer": Mock(),
    }
    code = compile(
        notebook_cells["1a5c3405"],
        "assessment-question",
        "exec",
        flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
    )
    asyncio.run(eval(code, namespace))
    assert agent.ask_async.call_args.kwargs["selected_dates"] == (
        date(2025, 9, 30),
        date(2025, 9, 30),
    )


def test_notebook_opt_out_configures_a_working_stub(notebook_cells, tmp_path, monkeypatch):
    trained = Mock(side_effect=AssertionError("Default must not load numerical artifacts"))
    monkeypatch.setattr("credit_monitoring.ml.factory.LogisticRegressionRiskModel", trained)
    namespace = {
        "processed_dir": tmp_path,
        "APP_SYNTHETIC_DIR": APP_SYNTHETIC_DIR,
        "MODELS_DIR": MODELS_DIR,
    }
    exec(notebook_cells["select-risk-model"], namespace)
    namespace["USE_TRAINED_MODEL"] = False
    exec(notebook_cells["9cf32123"], namespace)
    service = namespace["assessment_service"]
    assert service.settings.risk_model.type == "stub"
    result = service.assess("SYN002", date(2025, 9, 30), date(2025, 9, 30), ml_enabled=True)
    assert result.results and result.prediction.breach_probability is None
    assert result.prediction.model_name == "stub"
    trained.assert_not_called()


def test_notebook_default_selects_the_bundled_model(notebook_cells, tmp_path, monkeypatch):
    create = Mock()
    monkeypatch.setattr("credit_monitoring.ml.factory.create_risk_model", create)
    namespace = {
        "processed_dir": tmp_path,
        "APP_SYNTHETIC_DIR": APP_SYNTHETIC_DIR,
        "MODELS_DIR": MODELS_DIR,
    }
    exec(notebook_cells["select-risk-model"], namespace)
    exec(notebook_cells["9cf32123"], namespace)
    service = namespace["assessment_service"]
    assert service.settings.risk_model.type == "logistic_regression"
    assert service.settings.risk_model.artifact_path == MODELS_DIR / "logistic_regression/v1"
    create.assert_called_once_with(service.settings.risk_model)


@pytest.mark.parametrize(
    "error", [FileNotFoundError("manifest missing"), ImportError("sklearn"), ValueError("checksum")]
)
def test_notebook_trained_model_fails_at_configuration(
    notebook_cells, tmp_path, monkeypatch, error
):
    monkeypatch.setattr("credit_monitoring.ml.factory.create_risk_model", Mock(side_effect=error))
    namespace = {
        "processed_dir": tmp_path,
        "APP_SYNTHETIC_DIR": APP_SYNTHETIC_DIR,
        "MODELS_DIR": MODELS_DIR,
        "USE_TRAINED_MODEL": True,
    }
    with pytest.raises(RuntimeError, match="uv sync --extra ml"):
        exec(notebook_cells["9cf32123"], namespace)
    assert "assessment_service" not in namespace
    assert not (tmp_path / "agent_analytics.sqlite3").exists()


@pytest.fixture
def chat_helper(notebook_cells, monkeypatch):
    def build(inputs):
        conversation = Mock(closed=False)
        conversation.ask_async = AsyncMock()
        conversation.close.side_effect = lambda: setattr(conversation, "closed", True)
        agent = Mock()
        agent.name = "Notebook test agent"
        agent.start_conversation.return_value = conversation
        show_answer = Mock()
        monkeypatch.setattr("builtins.input", Mock(side_effect=inputs))
        namespace = {"show_answer": show_answer, "AgentEventCallback": AgentEventCallback}
        exec(notebook_cells["interactive-chat-helper"], namespace)
        return namespace["chat_with_agent"], agent, conversation, show_answer

    return build


def test_notebook_chat_skips_blanks_displays_failures_and_continues(chat_helper, capsys):
    chat, agent, conversation, show_answer = chat_helper(
        ["  ", "Find evidence", "Explain that result", "done"]
    )
    incomplete = AgentAnswer(answer="Model request failed.", complete=False, error="model_error")
    complete = AgentAnswer(answer="Recovered answer.")
    conversation.ask_async.side_effect = [incomplete, complete, None]
    asyncio.run(chat(agent, ticker="SYN"))
    agent.start_conversation.assert_called_once_with(ticker="SYN", borrower_id=None)
    assert [call.args[0] for call in conversation.ask_async.call_args_list] == [
        "Find evidence",
        "Explain that result",
        "done",
    ]
    assert all(
        isinstance(call.kwargs["event_stream_handler"], AgentEventCallback)
        for call in conversation.ask_async.call_args_list
    )
    assert [call.args[0] for call in show_answer.call_args_list] == [incomplete, complete]
    assert conversation.closed
    assert capsys.readouterr().out.count("Conversation closed.") == 1


@pytest.mark.parametrize("interruption", [EOFError(), KeyboardInterrupt()])
def test_notebook_chat_input_interruption_closes_cleanly(chat_helper, interruption, capsys):
    chat, agent, conversation, show_answer = chat_helper([interruption])
    asyncio.run(chat(agent, borrower_id="SYN002"))
    conversation.ask_async.assert_not_called()
    show_answer.assert_not_called()
    assert conversation.closed
    assert "Conversation closed." in capsys.readouterr().out


@pytest.mark.parametrize("cell_id", ["interactive-document-chat", "interactive-assessment-chat"])
def test_notebook_interactive_cells_do_not_prompt_during_run_all(notebook_cells, cell_id):
    namespace = {"chat_with_agent": AsyncMock()}
    code = compile(notebook_cells[cell_id], cell_id, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
    asyncio.run(eval(code, namespace))
    namespace["chat_with_agent"].assert_not_called()


@pytest.mark.parametrize("name", ["01-setup.ipynb", "02-rag.ipynb", "03-agents.ipynb"])
def test_notebook_schema_and_all_code_cell_syntax(name):
    notebook = nbformat.read(NOTEBOOK.parent / name, as_version=4)
    nbformat.validate(notebook)
    for cell in notebook.cells:
        if cell.cell_type == "code":
            compile(cell.source, cell.id, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)


def test_streaming_demo_is_opt_in(notebook_cells):
    namespace = {}
    code = compile(
        notebook_cells["streaming-demo"],
        "streaming-demo",
        "exec",
        flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
    )
    asyncio.run(eval(code, namespace))
    assert namespace["RUN_STREAMING_DEMO"] is False
    assert callable(namespace["show_stream"])


@pytest.mark.parametrize("failed", [False, True])
def test_notebook_trace_and_assessment_display_native_results(notebook_cells, capsys, failed):
    outcome = (
        ToolFailure(code="service_error", message="Source unavailable")
        if failed
        else RiskAssessment(
            assessment_run_id="run_synthetic",
            borrower_id="SYN",
            period_end=date(2025, 9, 30),
            information_cutoff=date(2025, 9, 30),
            results=[],
        )
    )
    answer = AgentAnswer(
        answer="Synthetic answer",
        tool_trace=[
            ToolExecution(call_id="call", name="predict_risk", arguments={}, outcome=outcome)
        ],
    )
    pandas = Mock()
    namespace = {
        "pd": pandas,
        "display": Mock(),
        "Markdown": Mock(),
        "document_answer": answer,
        "assessment_answer": answer,
    }
    exec(notebook_cells["6b5ed3e0"], namespace)
    row = pandas.DataFrame.call_args.args[0][0]
    assert row["ok"] is not failed
    assert row["error"] == ("service_error" if failed else None)
    exec(notebook_cells["7d484565"], namespace)
    output = capsys.readouterr().out
    assert ("Source unavailable" if failed else "Assessment run: run_synthetic") in output


@pytest.mark.parametrize(
    "cell_id", ["process-complete-fmc-document", "ac7bc8f7", "process-catalog-helper"]
)
def test_rag_notebook_document_processing_in_running_loop(
    cell_id, document_service_factory, generation_response
):
    service = document_service_factory()
    # Multiple records exercise the batch resource guard, which a single filing bypasses.
    original = service.catalog_record("SYN")
    with service.source_file.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(original))
        writer.writeheader()
        writer.writerows([original, {**original, "document_id": "SECOND"}])
    for suffix in (".md", ".conversion-version"):
        prefix = "." if suffix == ".conversion-version" else ""
        source_path = service.markdown_dir / f"{prefix}SYN{suffix}"
        (service.markdown_dir / f"{prefix}SECOND{suffix}").write_text(source_path.read_text())
    service.model.respond.return_value = generation_response(CovenantExtraction())
    notebook = json.loads((NOTEBOOK.parent / "02-rag.ipynb").read_text())
    cells = {cell["id"]: "".join(cell["source"]) for cell in notebook["cells"]}
    namespace = {
        "MODEL": service.model,
        "source_file": service.source_file,
        "html_dir": service.html_dir,
        "markdown_dir": service.markdown_dir,
        "RUNTIME_DIR": service.markdown_dir.parent,
        "sec_user_agent": "",
        "converter": Mock(),
        "MarkItDown": Mock(side_effect=Mock),
    }
    exec(cells["configure-document-service"], namespace)
    service = namespace["processing_service"]
    # Inject fresh offline models as the service does for the notebook's model string.
    respond = service.model.respond

    def model_factory():
        model = ScriptedModel()
        model.respond = respond
        return model

    service.model_factory = model_factory
    # Use the local synthetic filing in place of the public FMC document.
    source = cells[cell_id].replace('"DOC_FMC_AMD3_2025"', '"SYN"')
    if cell_id == "process-catalog-helper":
        source += '\noutcomes = await process_catalog(ticker="SYN")\n'
    code = compile(source, cell_id, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)

    async def run_cell():
        await eval(code, namespace)

    asyncio.run(run_cell())
    outcome = service.get_document_extraction("SYN")
    assert outcome.status == "complete" and outcome.result is not None
    expected_calls = 1 if cell_id == "process-complete-fmc-document" else 2
    assert service.model.respond.call_count == expected_calls
    # Repeating the actual notebook cell reuses the persistent result.
    asyncio.run(run_cell())
    assert service.model.respond.call_count == expected_calls
    if cell_id == "process-complete-fmc-document":
        assert namespace["fmc_document"].cache_hit
    else:
        outcomes = namespace["documents" if cell_id == "ac7bc8f7" else "outcomes"]
        assert [item.document_id for item in outcomes] == ["SYN", "SECOND"]
        assert all(item.cache_hit for item in outcomes)


@pytest.mark.parametrize("show_details", [False, True])
def test_notebook_answer_keeps_diagnostics_optional(notebook_cells, show_details):
    source = next(code for code in notebook_cells.values() if "def show_answer(" in code)
    definition = source.split("# Opt into diagnostics")[0]
    answer = AgentAnswer(answer="### Evidence matrix\n\nReadable result.", confidence="medium")
    pandas = Mock()
    display = Mock()
    namespace = {"pd": pandas, "display": display, "Markdown": lambda text: text}
    exec(definition, namespace)
    namespace["show_answer"](answer, show_details=show_details)
    assert display.call_args_list[0].args[0] == answer.answer
    assert pandas.DataFrame.call_count == int(show_details)


@pytest.mark.parametrize(
    "cell_id,agent_name,scope,kind",
    [
        ("88d244e0", "document_agent", {"ticker": "FMC"}, "evidence"),
        ("2e9c25c9", "assessment_agent", {"borrower_id": None}, "clarification"),
        ("24b132ef", "assessment_agent", {"borrower_id": "SYN006"}, "evidence"),
    ],
)
def test_notebook_question_context_reaches_model_without_policy_gates(
    notebook_cells, cell_id, agent_name, scope, kind
):
    """Check notebook wiring; live regressions check the model's interpretation."""
    model = ScriptedModel(
        response=model_response(answer="Model-selected response.", answer_kind=kind)
    )
    documents, assessments = Mock(), Mock()
    agent = CreditAssessmentAgent(service=documents, assessment_service=assessments, model=model)
    show_answer = Mock()
    namespace = {
        agent_name: agent,
        "TICKER": "FMC",
        "AgentEventCallback": AgentEventCallback,
        "show_answer": show_answer,
    }
    code = compile(notebook_cells[cell_id], cell_id, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
    asyncio.run(eval(code, namespace))
    model.respond.assert_called_once()
    call = model.respond.call_args.kwargs
    payload = json.loads(call["messages"][0].parts[0].content)
    assert all(payload[key] == value for key, value in scope.items())
    assert payload["selected_dates"] is None
    names = {tool.name for tool in call["info"].function_tools}
    assert ("assess_covenants" in names) == bool(scope.get("borrower_id"))
    answer = namespace[
        "document_answer" if agent_name == "document_agent" else "covenant_assessment_answer"
    ]
    assert answer.complete and answer.answer_kind == kind
    assert documents.mock_calls == assessments.mock_calls == []
