"""Reusable evidence-only narrative RAG with explicitly supplied dependencies."""

from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models import Model

from credit_monitoring.agents.models import DEFAULT_MODEL, check_response, resolve_model
from credit_monitoring.agents.prompts.assembly import build_prompt as build_prompt
from credit_monitoring.agents.prompts.narrative import NARRATIVE_INSTRUCTIONS
from credit_monitoring.observability import session_scope
from credit_monitoring.observability.configuration import span
from credit_monitoring.retrieval.lexical.sec import search


def llm(
    user_prompt: str,
    *,
    instructions: str = NARRATIVE_INSTRUCTIONS,
    model: Model | str = DEFAULT_MODEL,
) -> str:
    with session_scope() as session:
        result = Agent(
            resolve_model(model), name="Assessment narrative", instructions=instructions
        ).run_sync(user_prompt, conversation_id=session.session_id)
        check_response(result.response)
        return result.output


async def llm_async(
    user_prompt: str,
    *,
    instructions: str = NARRATIVE_INSTRUCTIONS,
    model: Model | str = DEFAULT_MODEL,
) -> str:
    """Generate a narrative inside an existing event loop, including Jupyter."""
    with session_scope() as session:
        result = await Agent(
            resolve_model(model), name="Assessment narrative", instructions=instructions
        ).run(user_prompt, conversation_id=session.session_id)
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
    with session_scope(), span("rag"):
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
    with session_scope(), span("rag"):
        results = search(query, index=index, document_count=document_count, ticker=ticker)
        if not results:
            return "No relevant evidence was retrieved."
        return await llm_async(build_prompt(query, results), model=model)
