"""Reusable evidence-only narrative RAG with explicitly supplied dependencies."""

from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models import Model

from credit_monitoring.agents.models import DEFAULT_MODEL, check_response, resolve_model
from credit_monitoring.agents.prompts.assembly import build_prompt as build_prompt
from credit_monitoring.agents.prompts.narrative import NARRATIVE_INSTRUCTIONS
from credit_monitoring.retrieval.lexical.sec import search


def llm(
    user_prompt: str,
    *,
    instructions: str = NARRATIVE_INSTRUCTIONS,
    model: Model | str = DEFAULT_MODEL,
) -> str:
    result = Agent(resolve_model(model), instructions=instructions).run_sync(user_prompt)
    check_response(result.response)
    return result.output


async def llm_async(
    user_prompt: str,
    *,
    instructions: str = NARRATIVE_INSTRUCTIONS,
    model: Model | str = DEFAULT_MODEL,
) -> str:
    """Generate a narrative inside an existing event loop, including Jupyter."""
    result = await Agent(resolve_model(model), instructions=instructions).run(user_prompt)
    check_response(result.response)
    return result.output


def rag(
    query: str,
    *,
    index: Any,
    document_count: int,
    ticker: str | None = None,
    model: Model | str = DEFAULT_MODEL,
) -> str:
    results = search(query, index=index, document_count=document_count, ticker=ticker)
    if not results:
        return "No relevant evidence was retrieved."
    return llm(build_prompt(query, results), model=model)


async def rag_async(
    query: str,
    *,
    index: Any,
    document_count: int,
    ticker: str | None = None,
    model: Model | str = DEFAULT_MODEL,
) -> str:
    """Retrieve evidence and await a narrative without driving the caller's event loop."""
    results = search(query, index=index, document_count=document_count, ticker=ticker)
    if not results:
        return "No relevant evidence was retrieved."
    return await llm_async(build_prompt(query, results), model=model)
