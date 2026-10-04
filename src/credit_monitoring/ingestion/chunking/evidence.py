"""Existing keyword/neighbor evidence selection and gitsource chunk preparation."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

EVIDENCE_PATTERN = re.compile(
    r"net leverage|leverage ratio|total leverage|secured leverage|adjusted EBITDA|\bEBITDA\b|"
    r"net debt|covenant|compliance|non-compliance|waiver|default|relief period|testing period|"
    r"fixed charge|interest coverage|springing",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EvidenceSelection:
    text: str
    truncated: bool


def select_relevant_evidence(text: str, max_chars: int = 3500) -> EvidenceSelection:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive.")
    lines = text.splitlines()
    selected, seen = [], set()
    for i, line in enumerate(lines):
        if EVIDENCE_PATTERN.search(line):
            for j in range(max(0, i - 1), min(len(lines), i + 2)):
                candidate = lines[j].strip()
                if candidate and candidate not in seen:
                    selected.append(candidate)
                    seen.add(candidate)
    joined = "\n".join(selected)
    return EvidenceSelection(text=joined[:max_chars], truncated=len(joined) > max_chars)


def extract_relevant_evidence(text: str, max_chars: int = 3500) -> str:
    """Text-only convenience API; pipelines use select_relevant_evidence for diagnostics."""
    return select_relevant_evidence(text, max_chars=max_chars).text


def prepare_documents(chunks: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    documents = []
    for chunk in chunks:
        record = dict(chunk)
        # gitsource supplies start in the selected content's coordinates. Do not
        # estimate end or default absent starts to zero.
        record["source_start"] = chunk.get("source_start", chunk.get("start"))
        record["source_end"] = chunk.get("source_end")
        record["markdown_path"] = chunk.get("markdown_path")
        for name in ("role", "company", "ticker", "document_type", "period_end", "notes"):
            record[name] = chunk.get(name) or ""
        documents.append(record)
    return documents


def chunk_evidence_documents(
    documents: list[dict[str, Any]],
    *,
    size: int = 3500,
    step: int = 500,
) -> list[dict[str, Any]]:
    from gitsource import chunk_documents

    return prepare_documents(chunk_documents(documents=documents, size=size, step=step))
