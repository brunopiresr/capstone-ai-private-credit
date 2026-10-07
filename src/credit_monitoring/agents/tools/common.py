"""Shared validation and JSON outcomes for SDK function tools."""

import inspect
import json
import sqlite3
from collections.abc import Callable, Iterable
from typing import Annotated, Any

import requests
from agents import ModelBehaviorError, RunContextWrapper
from agents.tool_context import ToolContext
from pydantic import Field, StrictStr

from credit_monitoring.agents.run_state import AgentRunState, decode_arguments
from credit_monitoring.covenants.extraction import ExtractionError

NonEmptyString = Annotated[StrictStr, Field(min_length=1)]
ISODate = Annotated[StrictStr, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class InvalidToolArguments(ValueError):
    pass


def validate_call(ctx: ToolContext[AgentRunState], method: Callable[..., str]) -> None:
    """Reject unexpected raw fields that SDK argument parsing could otherwise ignore."""
    arguments = decode_arguments(ctx.tool_arguments)
    if arguments is None:
        raise InvalidToolArguments("Tool arguments must be a JSON object.")
    allowed = set(inspect.signature(method).parameters) - {"ctx"}
    unexpected = set(arguments) - allowed
    if unexpected:
        raise InvalidToolArguments(f"Unexpected arguments: {', '.join(sorted(unexpected))}")


def tool_result(data: Any, *, sources: Iterable[dict[str, str]] = ()) -> str:
    return json.dumps({"ok": True, "data": data, "sources": list(sources)}, ensure_ascii=False)


def tool_error(ctx: RunContextWrapper[AgentRunState], error: Exception) -> str:
    """Return expected failures to the model; let unexpected application errors propagate."""
    if isinstance(error, (ModelBehaviorError, InvalidToolArguments)):
        code = "invalid_arguments"
    elif isinstance(
        error,
        (ExtractionError, OSError, ValueError, sqlite3.Error, requests.RequestException),
    ):
        code = "service_error"
    else:
        raise error
    return json.dumps({"ok": False, "error": code, "message": str(error)}, ensure_ascii=False)
