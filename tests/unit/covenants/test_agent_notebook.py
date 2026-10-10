"""Exercise the actual notebook chat helper without credentials or notebook setup."""

import ast
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import nbformat
import pytest

from credit_monitoring.agents.events import AgentEventCallback
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


def test_notebook_schema_and_all_code_cell_syntax():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    nbformat.validate(notebook)
    for cell in notebook.cells:
        if cell.cell_type == "code":
            compile(cell.source, cell.id, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
