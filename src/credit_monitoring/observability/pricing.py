"""Versioned, application-owned USD prices per million tokens."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

PRICING_VERSION = "2026-10-25.1"
PRICING_SOURCE = "https://developers.openai.com/api/docs/models/gpt-4o-mini"
PRICING_VERIFIED_AT = date(2026, 10, 25)


@dataclass(frozen=True)
class ModelPrice:
    provider: str
    model: str
    effective_from: date
    input_rate: Decimal
    cached_input_rate: Decimal
    output_rate: Decimal


# Initial baseline: these models have used these rates since their release.
MODEL_PRICES = tuple(
    ModelPrice(
        "openai", model, date(2024, 7, 18), Decimal("0.15"), Decimal("0.075"), Decimal("0.60")
    )
    for model in ("gpt-4o-mini", "gpt-4o-mini-2024-07-18")
)


def find_price(provider: str, model: str, requested_at: date) -> ModelPrice | None:
    matches = [
        price
        for price in MODEL_PRICES
        if (price.provider, price.model) == (provider, model)
        and price.effective_from <= requested_at
    ]
    return max(matches, key=lambda price: price.effective_from, default=None)
