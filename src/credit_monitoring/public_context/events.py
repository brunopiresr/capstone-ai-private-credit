"""Immutable news inputs with source identity and publication-time provenance."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import AnyHttpUrl, AwareDatetime, ConfigDict, Field, model_validator

from credit_monitoring.domain.analytics_base import AssessmentModel

type NewsText = Annotated[str, Field(min_length=1)]


class PublicNewsItem(AssessmentModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    news_id: NewsText
    borrower_id: NewsText
    title: NewsText
    publisher: NewsText
    url: AnyHttpUrl
    published_at: AwareDatetime | None
    excerpt: NewsText


class PublicNewsContext(AssessmentModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    borrower_id: NewsText
    information_cutoff: date
    status: Literal["unavailable", "failed", "empty", "available"]
    items: tuple[PublicNewsItem, ...] = ()
    issues: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if (self.status == "available") != bool(self.items):
            raise ValueError(
                "Only available news may contain items, and must contain at least one."
            )
        identifiers = [item.news_id for item in self.items]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("News identifiers must be unique within a context.")
        return self
