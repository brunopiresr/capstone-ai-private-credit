"""Cached SEC HTML → cleaned HTML → Markdown conversion."""

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from credit_monitoring.ingestion.cleaners.sec_html import clean_html
from credit_monitoring.ingestion.loaders.sec import download_sec_filing, throttle_download
from credit_monitoring.observability.logging import log_step

CONVERSION_VERSION = "beautifulsoup-clean-v1"
logger = logging.getLogger(__name__)


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
    html_dir, markdown_dir = Path(html_dir), Path(markdown_dir)
    html_path = html_dir / f"{document_id}.html"
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
    html_dir.mkdir(parents=True, exist_ok=True)
    markdown_dir.mkdir(parents=True, exist_ok=True)
    if not html_path.exists():
        with log_step(logger, "Download SEC HTML", document_id=document_id):
            html_content = download_sec_filing(record["source_url"], user_agent=user_agent)
            html_path.write_text(html_content, encoding="utf-8")
            throttle_download()
    else:
        logger.info("HTML cache hit document_id=%s", document_id)
    cleaned_html_path = html_dir / f"{document_id}.cleaned.html"
    with log_step(logger, "Clean SEC HTML", document_id=document_id):
        cleaned_html_path.write_text(
            clean_html(html_path.read_text(encoding="utf-8")), encoding="utf-8"
        )
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
        markdown_path.write_text(markdown, encoding="utf-8")
        marker_path.write_text(CONVERSION_VERSION, encoding="utf-8")
    return markdown
