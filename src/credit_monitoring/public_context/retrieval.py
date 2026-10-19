"""Injection boundary for future news sources, defaulting to explicit unavailability."""

from datetime import UTC, date
from typing import Protocol

from .events import PublicNewsContext


class PublicNewsProvider(Protocol):
    async def get_context(
        self, borrower_id: str, information_cutoff: date
    ) -> PublicNewsContext: ...


class UnavailableNewsProvider:
    async def get_context(self, borrower_id: str, information_cutoff: date) -> PublicNewsContext:
        return PublicNewsContext(
            borrower_id=borrower_id,
            information_cutoff=information_cutoff,
            status="unavailable",
            issues=("Public news is unavailable; no news search was performed.",),
        )


def filter_news(
    context: PublicNewsContext, borrower_id: str, information_cutoff: date
) -> PublicNewsContext:
    """UTC cutoff is inclusive through end of day; unknown times remain excluded."""
    context = PublicNewsContext.model_validate(context.model_dump())
    if context.borrower_id != borrower_id or context.information_cutoff != information_cutoff:
        raise ValueError("News context does not match the configured borrower and cutoff.")
    accepted, issues = [], list(context.issues)
    for item in context.items:
        if item.borrower_id != borrower_id:
            issues.append("Excluded a news item outside the configured borrower scope.")
        elif item.published_at is None:
            issues.append(f"Excluded news {item.news_id}: publication time is unknown.")
        elif item.published_at.astimezone(UTC).date() > information_cutoff:
            issues.append(f"Excluded news {item.news_id}: publication is after the cutoff.")
        else:
            accepted.append(item)
    status = context.status
    if status == "available" and not accepted:
        status = "empty"
    return PublicNewsContext(
        borrower_id=borrower_id,
        information_cutoff=information_cutoff,
        status=status,
        items=tuple(accepted),
        issues=tuple(issues),
    )
