"""Narrative RAG uses injected PydanticAI models and preserves its string contract."""

import ast
import asyncio
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from model_helpers import ScriptedModel
from pydantic_ai.messages import ModelResponse, TextPart

from credit_monitoring.agents.prompts.narrative import NARRATIVE_INSTRUCTIONS
from credit_monitoring.application.rag_service import rag, rag_async


def test_narrative_uses_centralized_evidence_only_instructions(synthetic_records):
    index = Mock()
    index.search.return_value = [synthetic_records["base"]]
    model = ScriptedModel(
        response=ModelResponse(parts=[TextPart("Synthetic cited narrative response.")])
    )
    answer = rag("Describe disclosed terms", model=model, index=index, document_count=1)
    assert answer == "Synthetic cited narrative response."
    request = model.respond.call_args.kwargs
    assert request["info"].instructions == NARRATIVE_INSTRUCTIONS.strip()
    assert (
        json.loads(request["messages"][0].parts[0].content)["retrieved_records"][0]["text"]
        == synthetic_records["base"]["content"]
    )


def test_narrative_empty_evidence_skips_model():
    model = ScriptedModel()
    assert (
        rag("Describe terms", model=model, index=None, document_count=0)
        == "No relevant evidence was retrieved."
    )
    model.respond.assert_not_called()


@pytest.mark.parametrize("prompt_number", [1, 2])
def test_notebook_prompts_run_in_existing_event_loop(synthetic_records, capsys, prompt_number):
    notebook_path = Path(__file__).resolve().parents[3] / "notebooks/02-rag.ipynb"
    cells = json.loads(notebook_path.read_text())["cells"]
    index = Mock()
    index.search.return_value = [synthetic_records["base"]]
    model = ScriptedModel(response=ModelResponse(parts=[TextPart("Synthetic cited narrative.")]))
    namespace = {"MODEL": model, "index": index, "documents": [synthetic_records["base"]]}
    exec("from functools import partial", namespace)
    for cell in cells:
        source = "".join(cell["source"])
        if cell["cell_type"] == "code" and (
            "from credit_monitoring.application.rag_service" in source
        ):
            exec(source, namespace)
    heading = next(
        i
        for i, cell in enumerate(cells)
        if "".join(cell["source"]).startswith(f"### Prompt {prompt_number}:")
    )
    code = compile(
        "".join(cells[heading + 1]["source"]),
        "notebook-prompt",
        "exec",
        flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
    )

    async def run_cell():
        await eval(code, namespace)

    asyncio.run(run_cell())
    assert capsys.readouterr().out == "Synthetic cited narrative.\n"
    request = model.respond.call_args.kwargs
    assert request["info"].instructions == NARRATIVE_INSTRUCTIONS.strip()
    assert (
        json.loads(request["messages"][0].parts[0].content)["retrieved_records"][0]["text"]
        == synthetic_records["base"]["content"]
    )


def test_async_narrative_empty_evidence_skips_model():
    model = ScriptedModel()
    answer = asyncio.run(rag_async("Describe terms", model=model, index=None, document_count=0))
    assert answer == "No relevant evidence was retrieved."
    model.respond.assert_not_called()
