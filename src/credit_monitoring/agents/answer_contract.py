"""Render model-authored answer data without judging its evidence or interpretation."""

import re
from html import escape

from markdown_it import MarkdownIt

from credit_monitoring.domain.agent import AnswerContent, AnswerDraft, AnswerTable, SourceReference

SCHEMA_VERSION = "agent-answer-v3"
_MARKDOWN = MarkdownIt("commonmark", {"html": False})

# Preserve code and autolinks while escaping HTML and math delimiters in prose.
_INLINE_MARKDOWN = re.compile(
    r"(?<![\\`])(?P<ticks>`+)(?!`)[^\n]*?(?<!`)(?P=ticks)(?!`)"
    r"|<(?:https?://|mailto:)[^<>\s]+>"
)


def _prose(text: str) -> str:
    def escape_prose(value: str) -> str:
        return re.sub(
            r"(\\*)\$",
            lambda match: match[1] + (r"\$" if len(match[1]) % 2 == 0 else "$"),
            value.replace("<", "&lt;"),
        )

    parts = []
    start = 0
    for match in _INLINE_MARKDOWN.finditer(text):
        parts.extend((escape_prose(text[start : match.start()]), match[0]))
        start = match.end()
    parts.append(escape_prose(text[start:]))
    return "".join(parts)


def _narrative(text: str) -> str:
    """Preserve Markdown code blocks; escape HTML and math delimiters only in prose."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.splitlines(keepends=True)
    parts = []
    start = 0
    for token in _MARKDOWN.parse(text):
        if token.type not in {"fence", "code_block"} or token.map is None:
            continue
        first, end = token.map
        parts.extend((_prose("".join(lines[start:first])), "".join(lines[first:end])))
        if token.type == "fence" and token.level == 0:
            closing = (
                r" {0,3}"
                + re.escape(token.markup[0])
                + "{"
                + str(len(token.markup))
                + r",}[ \t]*\n?"
            )
            if end - first == 1 or not re.fullmatch(closing, lines[end - 1]):
                # A partial fence must not swallow subsequent citations or sections.
                parts.append(("" if text.endswith("\n") else "\n") + token.markup + "\n")
        start = end
    parts.append(_prose("".join(lines[start:])))
    return "".join(parts)


def _list_item(marker: str, text: str) -> str:
    return marker + _narrative(text).replace("\n", "\n" + " " * len(marker))


def markdown_literal(text: str) -> str:
    """Display supplied text literally, including Markdown, HTML and currency."""
    text = re.sub(r"([\\`*_{}\[\]|$#!])", r"\\\1", escape(text, quote=False))
    return re.sub(
        r"(?m)^([ \t]*)([-+]|\d+[.)])(?=\s)",
        lambda match: (
            match[1]
            + match[2]
            .replace(".", r"\.")
            .replace(")", r"\)")
            .replace("-", r"\-")
            .replace("+", r"\+")
        ),
        text,
    )


def _cell(text: str) -> str:
    return markdown_literal(text).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def _sources(citations: list[SourceReference]) -> str:
    return "; ".join(
        markdown_literal(f"{source.document_id}: {source.citation}") for source in citations
    )


def _table(table: AnswerTable) -> str:
    # Tolerate incomplete streaming rows without losing supplied cells.
    width = max([len(table.columns), *(len(row.cells) for row in table.rows)], default=0)
    if not width:
        return ""
    columns = [
        table.columns[i] if i < len(table.columns) else f"Column {i + 1}" for i in range(width)
    ]
    cited = any(row.citations for row in table.rows)
    if cited:
        columns.append("Sources")
    lines = ["| " + " | ".join(_cell(column) for column in columns) + " |"]
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    citations: dict[tuple[str, str], str] = {}
    for row in table.rows:
        cells = [_cell(row.cells[i]) if i < len(row.cells) else "" for i in range(width)]
        if cited:
            keys = []
            for source in row.citations:
                key = (source.document_id, source.citation)
                keys.append(citations.setdefault(key, f"S{len(citations) + 1}"))
            cells.append(", ".join(dict.fromkeys(keys)))
        lines.append("| " + " | ".join(cells) + " |")
    if citations:
        lines.append(
            "\n"
            + "\n\n".join(
                f"**{label}:** " + markdown_literal(f"{document}: {citation}")
                for (document, citation), label in citations.items()
            )
        )
    heading = "### " + markdown_literal(table.title) + "\n\n" if table.title else ""
    return heading + "\n".join(lines)


def render_content(draft: AnswerDraft) -> AnswerContent:
    """The same projection serves provisional snapshots and completed answers."""
    paragraphs = [_narrative(draft.summary)] if draft.summary else []
    for finding in draft.findings:
        text = _narrative(finding.text)
        if finding.citations:
            text += "\n\nSource: " + _sources(finding.citations)
        paragraphs.append(text)
    paragraphs.extend(rendered for table in draft.tables if (rendered := _table(table)))
    if draft.gaps:
        paragraphs.append(
            "### Gaps and limitations\n\n" + "\n".join(_list_item("- ", gap) for gap in draft.gaps)
        )
    if draft.diligence_questions:
        paragraphs.append(
            "### Diligence questions\n\n"
            + "\n".join(
                _list_item(f"{i}. ", question)
                for i, question in enumerate(draft.diligence_questions, 1)
            )
        )
    return AnswerContent(
        **draft.model_dump(), answer="\n\n".join(paragraphs), schema_version=SCHEMA_VERSION
    )
