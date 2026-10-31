"""Cached SEC HTML → cleaned HTML → Markdown conversion."""

import logging
from collections.abc import Mapping
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from credit_monitoring.ingestion.cleaners.sec_html import clean_html
from credit_monitoring.ingestion.loaders.sec import load_sec_html, validate_document_id
from credit_monitoring.observability.logging import log_step

CONVERSION_VERSION = "beautifulsoup-clean-v2"
logger = logging.getLogger(__name__)


def _atomic_text(path: Path, content: str) -> None:
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_markdown(
    record: Mapping[str, Any],
    *,
    html_dir: Path,
    markdown_dir: Path,
    user_agent: str,
    converter: Any = None,
) -> str:
    """Reuse the existing cache and conversion marker; download only when HTML is absent."""
    document_id = record["document_id"]
    validate_document_id(document_id)
    html_dir, markdown_dir = Path(html_dir), Path(markdown_dir)
    markdown_path = markdown_dir / f"{document_id}.md"
    marker_path = markdown_dir / f".{document_id}.conversion-version"
    if (
        markdown_path.exists()
        and markdown_path.stat().st_size > 0
        and marker_path.exists()
        and marker_path.read_text(encoding="utf-8") == CONVERSION_VERSION
    ):
        logger.info("Markdown cache hit document_id=%s", document_id)
        return markdown_path.read_text(encoding="utf-8")
    markdown_dir.mkdir(parents=True, exist_ok=True)
    html_path = load_sec_html(record, html_dir=html_dir, user_agent=user_agent)
    cleaned_html_path = html_dir / f"{document_id}.cleaned.html"
    with log_step(logger, "Clean SEC HTML", document_id=document_id):
        _atomic_text(cleaned_html_path, clean_html(html_path.read_text(encoding="utf-8")))
    with log_step(logger, "Convert HTML to Markdown", document_id=document_id):
        if converter is None:
            from markitdown import MarkItDown

            converter = MarkItDown(enable_plugins=False)
        markdown = converter.convert_local(str(cleaned_html_path)).markdown
        if not markdown.strip():
            raise ValueError(
                f"MarkItDown returned empty text for {document_id}: {record['source_url']}"
            )
    with log_step(logger, "Save Markdown cache", document_id=document_id):
        _atomic_text(markdown_path, markdown)
        _atomic_text(marker_path, CONVERSION_VERSION)
    return markdown
