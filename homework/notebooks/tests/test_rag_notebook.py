"""Execute the actual RAG notebook prompt cells with a controlled model."""

import ast
import asyncio
import json
from unittest.mock import Mock

import pytest
from model_helpers import ScriptedModel
from pydantic_ai.messages import ModelResponse, TextPart

from credit_monitoring.agents.prompts.narrative import NARRATIVE_INSTRUCTIONS
from credit_monitoring.paths import ROOT


@pytest.mark.parametrize("prompt_number", [1, 2])
def test_notebook_prompts_run_in_existing_event_loop(synthetic_records, capsys, prompt_number):
    notebook_path = ROOT / "homework/notebooks/02-rag.ipynb"
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
