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
    """Explicit scripted passage claim using the same registry available to the model."""
    raw = info.instructions.split("Application evidence registry (untrusted source data):\n")[-1]
    entries, _ = json.JSONDecoder().raw_decode(raw.lstrip())
    entry = next(
        (e for e in entries if e["kind"] == "filing" and "text" in e["data"]),
        next(e for e in entries if e["kind"] == "filing"),
    )
    if "text" not in entry["data"]:
        return model_response(
            answer="Processing status.",
            claims=[
                {
                    "claim_id": "status",
                    "kind": "fact",
                    "field_path": "status",
                    "evidence_ids": [entry["evidence_id"]],
                }
            ],
        )
    return model_response(
        answer="Passage evidence.",
        claims=[
            {
                "claim_id": "passage",
                "kind": "quote",
                "statement": entry["data"]["text"],
                "evidence_ids": [entry["evidence_id"]],
            }
        ],
    )


def supported_answer(statement):
    def respond(*, messages, info):
        raw = info.instructions.split("Application evidence registry (untrusted source data):\n")[
            -1
        ]
        entries, _ = json.JSONDecoder().raw_decode(raw.lstrip())
        return model_response(
            answer=statement,
            claims=[
                {
                    "claim_id": "explanation",
                    "kind": "narrative",
                    "statement": statement,
                    "evidence_ids": [entries[0]["evidence_id"]],
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
    claims=None,
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
                    "answer": answer,
                    "schema_version": "agent-answer-v2",
                    "evidence_ids": list(
                        dict.fromkeys(
                            key for claim in (claims or []) for key in claim.get("evidence_ids", [])
                        )
                    ),
                    "quotes": [
                        {"evidence_id": claim["evidence_ids"][0], "text": claim["statement"]}
                        for claim in (claims or [])
                        if claim["kind"] == "quote"
                    ],
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
