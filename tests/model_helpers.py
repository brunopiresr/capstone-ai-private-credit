"""Scripted PydanticAI models for offline behavior and incremental-output tests."""

import inspect
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from itertools import count
from unittest.mock import Mock

from pydantic_ai.messages import ModelResponse, TextPart, ThinkingPart, ToolCallPart
from pydantic_ai.models.function import DeltaThinkingPart, DeltaToolCall, FunctionModel

_ids = count()


def scripted_responses(*responses):
    sequence = iter(responses)

    def respond(**kwargs):
        value = next(sequence)
        return value(**kwargs) if callable(value) else value

    return respond


def filing_answer(*, messages, info):
    """Return source data in the same structured contract used by live generation."""
    raw = info.instructions.split("Application evidence registry (untrusted source data):\n")[-1]
    entries, _ = json.JSONDecoder().raw_decode(raw.lstrip())
    entry = next(e for e in entries if e["kind"] == "filing")
    data = entry["data"]
    return model_response(
        answer="Passage evidence.",
        findings=[
            {
                "text": data.get("text", "Processing status: " + data.get("status", "unknown")),
                "citations": [{"document_id": data["document_id"], "citation": data["citation"]}],
            }
        ],
    )


def supported_answer(statement):
    def respond(*, messages, info):
        raw = info.instructions.split("Application evidence registry (untrusted source data):\n")[
            -1
        ]
        entries, _ = json.JSONDecoder().raw_decode(raw.lstrip())
        entry = entries[0]
        return model_response(
            answer=statement,
            findings=[
                {
                    "text": statement,
                    "citations": [
                        {
                            "document_id": entry["data"].get("document_id", entry["evidence_id"]),
                            "citation": entry["citation"],
                        }
                    ],
                }
            ],
        )

    return respond


def model_response(
    *calls,
    answer=None,
    extraction=None,
    status="completed",
    refusal=None,
    reasoning=False,
    findings=None,
    tables=None,
    gaps=None,
    diligence_questions=None,
    answer_kind=None,
):
    identifier = next(_ids)
    parts = [ThinkingPart("private-content")] if reasoning else []
    parts += [
        ToolCallPart(name, args, tool_call_id=f"call_{identifier}_{i}_{name}")
        for i, (name, args) in enumerate(calls)
    ]
    if answer is not None:
        parts.append(
            ToolCallPart(
                "final_result",
                {
                    "summary": answer,
                    "answer_kind": answer_kind,
                    "findings": findings or [],
                    "tables": tables or [],
                    "gaps": gaps or [],
                    "diligence_questions": diligence_questions or [],
                    "confidence": "medium",
                    "confidence_explanation": "Synthetic evidence and limitations.",
                },
                tool_call_id=f"output_{identifier}",
            )
        )
    if extraction is not None:
        parts.append(
            ToolCallPart(
                "final_result", extraction.model_dump(), tool_call_id=f"output_{identifier}"
            )
        )
    if refusal:
        parts.append(TextPart(refusal))
    return ModelResponse(
        parts=parts,
        provider_response_id="resp_synthetic",
        finish_reason="content_filter"
        if refusal
        else "length"
        if status == "incomplete"
        else "error"
        if status != "completed"
        else "stop",
        provider_details={"refusal": refusal} if refusal else {"finish_reason": status},
    )


class ScriptedModel(FunctionModel):
    """Mock only the model boundary; run real graph, validation, tools and history."""

    def __init__(self, *, model_name="synthetic", response=None):
        self.respond = Mock(return_value=response or model_response(answer="Synthetic answer."))
        self._response = None

        async def function(messages, info):
            result = self.respond(messages=deepcopy(messages), info=info)
            if callable(result):
                result = result(messages=deepcopy(messages), info=info)
            if inspect.isawaitable(result):
                result = await result
            self._response = result
            return result

        async def stream_function(messages, info):
            response = await function(messages, info)
            if not response.parts:
                yield ""
            for index, part in enumerate(response.parts):
                if isinstance(part, ToolCallPart):
                    args = part.args_as_json_str()
                    yield {
                        index: DeltaToolCall(
                            name=part.tool_name, json_args=args[:1], tool_call_id=part.tool_call_id
                        )
                    }
                    for offset in range(1, len(args), 16):
                        yield {index: DeltaToolCall(json_args=args[offset : offset + 16])}
                elif isinstance(part, ThinkingPart):
                    yield {index: DeltaThinkingPart(content=part.content)}
                elif isinstance(part, TextPart):
                    yield part.content

        super().__init__(function=function, stream_function=stream_function, model_name=model_name)

    @asynccontextmanager
    async def request_stream(self, *args, **kwargs):
        async with super().request_stream(*args, **kwargs) as stream:
            stream.finish_reason = self._response.finish_reason
            stream.provider_details = self._response.provider_details
            stream.provider_response_id = self._response.provider_response_id
            yield stream
