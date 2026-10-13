"""Model configuration and response checks shared by generation entry points."""

from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import Model, infer_model

DEFAULT_MODEL = "openai-responses:gpt-4o-mini"


class ModelFailure(RuntimeError):
    """A rejected model response, with an application-facing failure code."""

    def __init__(self, message: str, code: str, response_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.response_id = response_id


def resolve_model(model: Model | str) -> Model:
    """Resolve provider configuration without coupling services to client SDKs."""
    return infer_model(model)


def model_identity(model: Model | str) -> str:
    if isinstance(model, str):
        return model
    return f"{model.system}:{model.model_name}"


def check_response(response: ModelResponse) -> None:
    """Reject partial/refused responses before tools or final output are accepted."""
    details = response.provider_details or {}
    response_id = response.provider_response_id
    if response.finish_reason == "content_filter" or details.get("refusal"):
        raise ModelFailure(
            f"Model refused: {details.get('refusal', 'content filter')}",
            "model_refusal",
            response_id,
        )
    if response.finish_reason == "error" or details.get("finish_reason") in {
        "failed",
        "cancelled",
        "in_progress",
        "queued",
    }:
        raise ModelFailure("Model response failed to complete.", "model_error", response_id)
    if (
        response.state != "complete"
        # The Responses adapter can exhaust a stream without a terminal event.
        # Such a response has no finish reason even if its state became complete.
        or (response.provider_name == "openai" and response.finish_reason is None)
        or response.finish_reason == "length"
        or details.get("finish_reason") in {"incomplete", "max_output_tokens"}
    ):
        raise ModelFailure("Model response is incomplete.", "model_incomplete", response_id)
    if not response.tool_calls and not (response.text or "").strip() and not response.images:
        raise ModelFailure("Model returned no answer or tool calls.", "empty_response", response_id)
