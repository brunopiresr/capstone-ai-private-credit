"""Reusable evidence-only narrative RAG with explicitly supplied dependencies."""

from typing import Any

from credit_monitoring.agents.prompts.assembly import build_prompt as build_prompt
from credit_monitoring.agents.prompts.narrative import NARRATIVE_INSTRUCTIONS
from credit_monitoring.retrieval.lexical.sec import search


def llm(
    user_prompt: str,
    *,
    client: Any,
    instructions: str = NARRATIVE_INSTRUCTIONS,
    model: str = "gpt-4o-mini",
) -> str:
    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=user_prompt,
    )
    if response.status != "completed":
        raise ValueError(f"Narrative response was not completed: {response.status}")
    return response.output_text


def rag(
    query: str,
    *,
    client: Any,
    index: Any,
    document_count: int,
    ticker: str | None = None,
    model: str = "gpt-4o-mini",
) -> str:
    results = search(query, index=index, document_count=document_count, ticker=ticker)
    if not results:
        return "No relevant evidence was retrieved."
    return llm(build_prompt(query, results), client=client, model=model)
