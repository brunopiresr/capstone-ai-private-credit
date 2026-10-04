"""Verbatim evidence supporting one source-backed extraction object."""

from pydantic import Field

from .base import ExtractionModel


class SourceEvidence(ExtractionModel):
    evidence_quote: str = Field(
        description=(
            "Short verbatim passage in the matching record directly supporting the parent fact."
        )
    )
    citation: str = Field(
        description="Exact citation from the same retrieved record; never synthesize."
    )
    document_id: str = Field(description="Exact document ID from the same retrieved record.")
    markdown_path: str | None = Field(
        default=None,
        description="Copy the matching record's Markdown path when supplied; else null.",
    )
    source_start: int | None = Field(
        default=None,
        description="Copy the supplied source start offset in its original coordinates; else null. "
        "Never estimate or treat excerpt offsets as Markdown-file offsets.",
    )
    source_end: int | None = Field(
        default=None,
        description="Copy the supplied source end offset in its original coordinates; else null. "
        "Never calculate or estimate a missing offset.",
    )
