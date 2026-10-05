"""Portable JSON contracts for snapshots and judgments, independent of the app."""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

JudgeKind = Literal["extraction", "retrieval", "answer"]
JudgeLabel = Literal["pass", "fail", "insufficient_evidence"]


class SourcePassage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    citation: str = Field(min_length=1)
    text: str = Field(min_length=1)
    ticker: str | None = None
    source_start: int | None = Field(default=None, ge=0)
    source_end: int | None = Field(default=None, ge=0)

    @field_validator("document_id", "citation", "text")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Source identity, citation and text must not be blank.")
        return value


class JudgeCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    judge: JudgeKind
    question: str = Field(min_length=1)
    output: str | None = None
    context: list[SourcePassage] = Field(default_factory=list)
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    reference: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    expected_label: JudgeLabel | None = None

    @field_validator("case_id", "question")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Case ID and question must not be blank.")
        return value


class JudgeResult(BaseModel):
    case_id: str
    judge: JudgeKind
    status: Literal["evaluated", "skipped", "error"]
    label: JudgeLabel | None = None
    reason: str
    expected_label: JudgeLabel | None = None


def load_cases(path: Path) -> list[JudgeCase]:
    """Validate the entire file before incurring any model cost."""
    cases = []
    seen = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            case = JudgeCase.model_validate(json.loads(line))
        except ValueError as error:
            raise ValueError(f"{path}:{line_number}: {error}") from error
        key = (case.case_id, case.judge)
        if key in seen:
            raise ValueError(f"{path}:{line_number}: duplicate case/judge {key}")
        seen.add(key)
        cases.append(case)
    if not cases:
        raise ValueError(f"{path}: no evaluation cases")
    return cases
