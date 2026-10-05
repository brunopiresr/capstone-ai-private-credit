"""Adapt existing clients while validating raw responses before SDK tool dispatch."""

import asyncio
import inspect
from typing import Any

from openai import AsyncOpenAI, OpenAI
from openai.types.responses import Response


class AgentFailure(Exception):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


class ResponsesClientAdapter:
    """Async Responses surface used by OpenAIResponsesModel.

    The SDK reduces raw Responses to ModelResponse objects, losing status/error
    fields. Validate at the client boundary so partial output never runs tools.
    Existing synchronous extraction clients remain usable without global SDK setup.
    """

    def __init__(self, client: OpenAI | AsyncOpenAI) -> None:
        self.client = client
        self.responses = self

    def __getattr__(self, name: str) -> Any:
        return getattr(self.client, name)

    def with_options(self, **kwargs: Any) -> ResponsesClientAdapter:
        return ResponsesClientAdapter(self.client.with_options(**kwargs))

    async def create(self, **kwargs: Any) -> Response:
        create = self.client.responses.create
        if inspect.iscoroutinefunction(create):
            response = await create(**kwargs)
        else:
            response = await asyncio.to_thread(create, **kwargs)
        for item in response.output:
            if item.type == "message":
                for content in item.content:
                    if content.type == "refusal":
                        raise AgentFailure(f"Model refused: {content.refusal}", "model_refusal")
        if response.status != "completed" or response.error is not None:
            raise AgentFailure(
                f"Agent response did not complete: {response.status}; error={response.error}",
                "model_incomplete" if response.status == "incomplete" else "model_error",
            )
        return response
