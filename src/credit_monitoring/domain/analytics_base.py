"""Shared validation and identifiers for assessment records."""

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

type ComparisonOperator = Literal["<", "<=", ">", ">=", "="]
type CalculationFormula = Literal[
    "net_leverage",
    "total_leverage",
    "pro_forma_leverage",
    "interest_coverage",
    "fixed_charge_coverage",
]
type ComplianceStatus = Literal[
    "compliant",
    "breach",
    "waived",
    "not_tested",
    "incomplete",
    "unresolved",
    "unsupported",
]
type TestingStatus = Literal["active", "waived", "suspended", "inactive", "unresolved"]


def new_identifier() -> str:
    """Create an application-owned identifier for an append-only record."""
    return str(uuid4())


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class AssessmentModel(BaseModel):
    """Reject unknown fields and nonfinite numbers at assessment boundaries."""

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        revalidate_instances="always",
    )
