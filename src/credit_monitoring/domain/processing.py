"""Application-level document processing outcomes, separate from LLM fact schemas."""

from typing import Literal

from pydantic import Field

from .base import ExtractionModel
from .validation import ExtractionResult


class DocumentExtraction(ExtractionModel):
    document_id: str = Field(description="Catalog source document ID.")
    citation: str = Field(description="Supplied catalog citation.")
    ticker: str | None = Field(default=None, description="Catalog ticker, when supplied.")
    status: Literal["missing", "stale", "processing", "failed", "complete", "unavailable"] = Field(
        description="Current source/configuration state; complete requires every section."
    )
    cache_key: str | None = Field(default=None, description="Content/configuration fingerprint.")
    cache_hit: bool = Field(
        default=False, description="True if a complete stored result was reused."
    )
    completed_sections: int = Field(default=0, description="Successfully stored section count.")
    total_sections: int = Field(
        default=0, description="Planned section count, zero before processing."
    )
    result: ExtractionResult | None = Field(
        default=None, description="Complete extraction only; null for missing/stale/failed sources."
    )
    error: str | None = Field(
        default=None, description="Processing error or source availability gap."
    )
