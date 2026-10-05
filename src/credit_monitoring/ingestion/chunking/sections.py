"""Lossless extraction sections; tables and their introducing clauses stay together."""

import re
from dataclasses import dataclass
from typing import Any

SEGMENTATION_VERSION = "markdown-sections-v1"
DEFAULT_MAX_CHARS = 60_000
_HEADING = re.compile(r"(?m)^(?:#{1,6}\s+.+|(?:SECTION|ARTICLE)\s+[^\n]+)\r?$")


class SectionTooLargeError(ValueError):
    """An indivisible paragraph/table plus context exceeds the configured budget."""


@dataclass(frozen=True)
class DocumentSection:
    start: int
    end: int
    context: tuple[tuple[int, int], ...] = ()

    def records(self, document: dict[str, Any]) -> list[dict[str, Any]]:
        text = document["content"]
        return [
            {**document, "content": text[a:b], "source_start": a, "source_end": b}
            for a, b in (*self.context, (self.start, self.end))
        ]


def _blocks(text: str) -> list[tuple[int, int]]:
    starts = [0, *[m.end() for m in re.finditer(r"\r?\n[ \t]*\r?\n", text)]]
    spans = [(a, b) for a, b in zip(starts, [*starts[1:], len(text)], strict=True) if a < b]

    def table(i: int) -> bool:
        return bool(re.search(r"(?m)^\s*\|", text[spans[i][0] : spans[i][1]]))

    def decoration(i: int) -> bool:
        return all(
            not line.strip() or re.fullmatch(r"(?:\d+|[-_*]{3,})", line.strip())
            for line in text[spans[i][0] : spans[i][1]].splitlines()
        )

    # Mark protected boundaries between a table, its introducing paragraph, and
    # continued tables separated only by blank lines/page numbers/rules.
    protected = set()
    for i in range(len(spans)):
        if not table(i):
            continue
        previous = i - 1
        while previous >= 0 and decoration(previous):
            previous -= 1
        if previous >= 0:
            protected.update(range(previous + 1, i + 1))
    blocks = []
    start = 0
    for i in range(1, len(spans)):
        if i not in protected:
            blocks.append((start, spans[i][0]))
            start = spans[i][0]
    if start < len(text):
        blocks.append((start, len(text)))
    return blocks


def split_document(text: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> list[DocumentSection]:
    """Cover the entire source once, adding separately attributed heading context."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive.")
    if not text.strip():
        raise ValueError("Cannot process an empty document.")
    if len(text) <= max_chars:
        return [DocumentSection(0, len(text))]
    headings = [(m.start(), m.end()) for m in _HEADING.finditer(text)]
    blocks = _blocks(text)
    sections = []
    index = 0
    while index < len(blocks):
        start = blocks[index][0]
        preceding = [span for span in headings if span[1] <= start]
        context = (preceding[-1],) if preceding else ()
        context_length = sum(b - a for a, b in context)
        end = start
        while index < len(blocks) and blocks[index][1] - start + context_length <= max_chars:
            end = blocks[index][1]
            index += 1
        if end == start:
            raise SectionTooLargeError(
                f"Source block at {start}:{blocks[index][1]} plus heading context exceeds "
                f"{max_chars} characters. Increase max_chars; no text was truncated."
            )
        sections.append(DocumentSection(start, end, context))
    return sections
