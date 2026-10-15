"""Exercise the actual notebook chat helper without credentials or notebook setup."""

import ast
import asyncio
import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import nbformat
import pytest

from credit_monitoring.agents.events import AgentEventCallback
from credit_monitoring.domain import CovenantExtraction, RiskAssessment, ToolExecution, ToolFailure
from credit_monitoring.domain.agent import AgentAnswer

NOTEBOOK = Path(__file__).resolve().parents[3] / "notebooks/03-agents.ipynb"


@pytest.fixture
def notebook_cells():
    notebook = json.loads(NOTEBOOK.read_text())
    return {cell["id"]: "".join(cell["source"]) for cell in notebook["cells"]}


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
    service.model.respond.return_value = generation_response(CovenantExtraction())
    notebook = json.loads((NOTEBOOK.parent / "02-rag.ipynb").read_text())
    cells = {cell["id"]: "".join(cell["source"]) for cell in notebook["cells"]}
    # Use the local synthetic filing in place of the public FMC document.
    source = cells[cell_id].replace('"DOC_FMC_AMD3_2025"', '"SYN"')
    if cell_id == "process-catalog-helper":
        source += '\noutcomes = await process_catalog(ticker="SYN")\n'
    code = compile(source, cell_id, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
    namespace = {"asyncio": asyncio, "processing_service": service}

    async def run_cell():
        await eval(code, namespace)

    asyncio.run(run_cell())
    outcome = service.get_document_extraction("SYN")
    assert outcome.status == "complete" and outcome.result is not None
    service.model.respond.assert_called_once()
    # Repeating the actual notebook cell reuses the persistent result.
    asyncio.run(run_cell())
    service.model.respond.assert_called_once()
    if cell_id == "process-complete-fmc-document":
        assert namespace["fmc_document"].cache_hit
    else:
        outcomes = namespace["documents" if cell_id == "ac7bc8f7" else "outcomes"]
        assert len(outcomes) == 1 and outcomes[0].cache_hit
