"""Bounded Responses tool loop for evidence-backed analyst questions."""

import json
from typing import Any

from openai import APIError

from credit_monitoring.agents.prompts.monitoring import MONITORING_INSTRUCTIONS
from credit_monitoring.agents.tools.documents import DocumentTools, decode_arguments
from credit_monitoring.application.document_processing_service import DocumentProcessingService
from credit_monitoring.domain.agent import AgentAnswer, SourceReference, ToolExecution


class MonitoringAgent:
    def __init__(
        self,
        *,
        client: Any,
        service: DocumentProcessingService,
        model: str = "gpt-4o-mini",
        max_tool_rounds: int = 6,
    ) -> None:
        if max_tool_rounds <= 0:
            raise ValueError("max_tool_rounds must be positive.")
        self.client = client
        self.service = service
        self.model = model
        self.max_tool_rounds = max_tool_rounds

    def ask(self, question: str, ticker: str | None = None) -> AgentAnswer:
        if not question.strip():
            raise ValueError("Question must not be empty.")
        tools = DocumentTools(self.service, ticker=ticker)
        history = [
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question,
                        "ticker": ticker,
                    }
                ),
            }
        ]
        trace = []
        sources = {}

        def incomplete(message: str, error: str) -> AgentAnswer:
            return AgentAnswer(
                answer=message,
                complete=False,
                error=error,
                sources=list(sources.values()),
                tool_trace=trace,
            )

        # Up to six rounds of tool execution, then one chance to return an answer.
        for round_index in range(self.max_tool_rounds + 1):
            try:
                response = self.client.responses.create(
                    model=self.model,
                    instructions=MONITORING_INSTRUCTIONS,
                    tools=tools.definitions,
                    input=list(history),
                    parallel_tool_calls=False,
                )
            except APIError as exc:
                return incomplete(f"Agent model request failed: {exc}", "model_error")
            for item in response.output:
                if item.type == "message":
                    for content in item.content:
                        if content.type == "refusal":
                            return incomplete(f"Model refused: {content.refusal}", "model_refusal")
            if response.status != "completed" or response.error is not None:
                return incomplete(
                    f"Agent response did not complete: {response.status}; error={response.error}",
                    "model_incomplete" if response.status == "incomplete" else "model_error",
                )
            calls = [item for item in response.output if item.type == "function_call"]
            if not calls:
                if not response.output_text.strip():
                    return incomplete("Model returned no answer or tool calls.", "empty_response")
                return AgentAnswer(
                    answer=response.output_text,
                    sources=list(sources.values()),
                    tool_trace=trace,
                )
            if round_index == self.max_tool_rounds:
                return incomplete(
                    "Processing stopped at the tool-round limit. "
                    "The question is not fully answered; "
                    "available sources and executed tools are attached.",
                    "tool_round_limit",
                )
            # Preserve all SDK output items for continuation (including private
            # reasoning when applicable), but never put those items in the public trace.
            history.extend(item.model_dump(exclude_none=True) for item in response.output)
            for call in calls:
                arguments = decode_arguments(call.arguments)
                outcome = tools.execute(call.name, arguments)
                trace.append(
                    ToolExecution(
                        call_id=call.call_id,
                        name=call.name,
                        arguments=arguments,
                        outcome=outcome,
                    )
                )
                for source in outcome.get("sources", []):
                    reference = SourceReference(**source)
                    sources[(reference.document_id, reference.citation)] = reference
                history.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": json.dumps(outcome, ensure_ascii=False),
                    }
                )
        raise AssertionError("Unreachable loop termination")
