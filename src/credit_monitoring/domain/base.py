"""Shared configuration for evidence extraction contracts."""

from pydantic import BaseModel, ConfigDict


class ExtractionModel(BaseModel):
    """Reject unknown fields rather than silently dropping old or invented facts."""

    model_config = ConfigDict(extra="forbid")
