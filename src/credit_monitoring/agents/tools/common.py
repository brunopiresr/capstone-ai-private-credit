"""Strict argument types and expected service-error conversion for function tools."""

import asyncio
import sqlite3
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Annotated

import requests
from pydantic import Field, RootModel, StrictStr
from pydantic_ai import Tool

from credit_monitoring.covenants.extraction import ExtractionError
from credit_monitoring.domain.documents import RetrievedRecord
from credit_monitoring.domain.processing import DocumentSummary
from credit_monitoring.domain.tool_results import ToolFailure, ToolOutcome

NonEmptyString = Annotated[StrictStr, Field(min_length=1)]
ISODate = Annotated[StrictStr, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class InvalidToolArguments(ValueError):
    pass


class ToolCollection(RootModel[list[DocumentSummary] | list[RetrievedRecord]]):
    """Serialize lists, including [], as data rather than multimodal content sequences."""


def tool_outcome(value: ToolOutcome | ToolCollection) -> ToolOutcome:
    """Unwrap the framework's collection representation at the application boundary."""
    return value.root if isinstance(value, ToolCollection) else value


def domain_tool[**P, T](function: Callable[P, T]) -> Tool:
    """Keep public methods native; adapt collection serialization only for the framework."""
    protected = service_errors(function)

    @wraps(function)
    async def call(*args: P.args, **kwargs: P.kwargs) -> T | ToolFailure | ToolCollection:
        result = await protected(*args, **kwargs)
        if isinstance(result, list):
            return ToolCollection(root=result)
        return result

    return Tool(call, strict=True, sequential=True)


def service_errors[**P, T](function: Callable[P, T]) -> Callable[P, Awaitable[T | ToolFailure]]:
    """Keep recoverable service errors as tool data; unexpected exceptions propagate."""

    @wraps(function)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T | ToolFailure:
        try:
            return await asyncio.to_thread(function, *args, **kwargs)
        except (
            OSError,
            ValueError,
            sqlite3.Error,
            requests.RequestException,
            ExtractionError,
        ) as exc:
            return ToolFailure(
                code="invalid_arguments"
                if isinstance(exc, InvalidToolArguments)
                else "service_error",
                message=str(exc),
            )

    return wrapped
