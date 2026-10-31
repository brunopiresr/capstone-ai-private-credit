"""Explicit SEC downloads and catalog loading; no work occurs at import time."""

import csv
import logging
import re
import time
from collections.abc import Mapping
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import Any
from urllib.parse import urlparse

import requests

from credit_monitoring.ingestion.chunking.evidence import select_relevant_evidence
from credit_monitoring.observability.logging import log_step

logger = logging.getLogger(__name__)
_DOWNLOAD_LOCK = Lock()


def validate_document_id(document_id: str) -> None:
    """Reject directory components before any cache path is constructed."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", document_id):
        raise ValueError("Document IDs must be filenames without directory components.")


def load_sec_html(record: Mapping[str, Any], *, html_dir: Path, user_agent: str) -> Path:
    """Reuse the canonical HTML cache, publishing successful downloads atomically."""
    document_id = record["document_id"]
    validate_document_id(document_id)
    if urlparse(record["source_url"]).path.lower().endswith(".pdf"):
        raise ValueError("PDF downloads are unsupported by the HTML pipeline.")
    target = Path(html_dir) / f"{document_id}.html"
    if target.is_file() and target.read_text(encoding="utf-8").strip():
        logger.info("HTML cache hit document_id=%s", document_id)
        return target
    if not user_agent.strip():
        raise ValueError("Set SEC_USER_AGENT to your organization/name and contact email.")
    with log_step(logger, "Download SEC HTML", document_id=document_id):
        with _DOWNLOAD_LOCK:
            try:
                content = download_sec_filing(record["source_url"], user_agent=user_agent)
            finally:
                throttle_download()
        if not content.strip() or content.lstrip().startswith("%PDF-"):
            raise ValueError("SEC download returned empty or unsupported PDF content.")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=target.parent, suffix=".tmp", delete=False
            ) as file:
                temporary = Path(file.name)
                file.write(content)
            temporary.replace(target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return target


def download_sec_filing(url: str, *, user_agent: str, session: Any = None) -> str:
    """Download using a caller-supplied identifying User-Agent, never a hard-coded identity."""
    if not user_agent.strip():
        raise ValueError("Set SEC_USER_AGENT to your organization/name and contact email.")
    http = session if session is not None else requests
    response = http.get(
        url,
        headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
        timeout=30,
    )
    response.raise_for_status()
    return response.content.decode("utf-8", errors="ignore")


def load_catalog(source_file: Path) -> list[dict[str, str]]:
    with Path(source_file).open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def filing_citation(record: Mapping[str, Any]) -> str:
    """The same catalog citation used by retrieval and full-document processing."""
    label_date = record.get("document_date") or record.get("period_end") or "date not listed"
    return (
        f"{record['company']}, {record['document_type']} ({label_date}), "
        f"{record['document_id']} — {record['source_url']}"
    )


def full_document_record(
    record: Mapping[str, Any], markdown: str, *, markdown_dir: Path
) -> dict[str, Any]:
    """Keep every character and supply measured offsets in the original Markdown."""
    document_id = record["document_id"]
    validate_document_id(document_id)
    return {
        **record,
        "citation": filing_citation(record),
        "markdown_path": str(Path(markdown_dir).resolve() / f"{document_id}.md"),
        "content": markdown,
        "truncated": False,
        "source_start": 0,
        "source_end": len(markdown),
        "source_length": len(markdown),
        "offset_coordinate_system": "markdown",
    }


def build_company_catalog(records: list[Mapping[str, Any]]) -> dict[str, str]:
    """Retain exactly the supplied ticker/name associations; reject ambiguous catalog entries."""
    companies = {}
    for record in records:
        ticker, company = record.get("ticker"), record.get("company")
        if ticker and company:
            if ticker in companies and companies[ticker] != company:
                raise ValueError(f"Catalog has conflicting company names for ticker {ticker}.")
            companies[ticker] = company
    return dict(sorted(companies.items()))


def create_documents(
    source_file: Path,
    *,
    html_dir: Path,
    markdown_dir: Path,
    user_agent: str,
    converter: Any = None,
    max_chars: int = 3500,
) -> list[dict[str, Any]]:
    """Load catalog filings and select evidence, preserving the notebook citation format."""
    from credit_monitoring.ingestion.converters.sec_markdown import load_markdown

    documents = []
    for record in load_catalog(source_file):
        markdown = load_markdown(
            record,
            html_dir=html_dir,
            markdown_dir=markdown_dir,
            user_agent=user_agent,
            converter=converter,
        )
        selection = select_relevant_evidence(markdown, max_chars=max_chars)
        label_date = record.get("document_date") or record.get("period_end") or "date not listed"
        citation = (
            f"{record['company']}, {record['document_type']} ({label_date}), "
            f"{record['document_id']} — {record['source_url']}"
        )
        documents.append(
            {
                **record,
                "citation": citation,
                "markdown_path": str(Path(markdown_dir) / f"{record['document_id']}.md"),
                "content": selection.text,
                "truncated": selection.truncated,
                "source_length": len(selection.text),
                "offset_coordinate_system": "selected_excerpt",
            }
        )
    return documents


def throttle_download() -> None:
    """Preserve the notebook's delay between SEC requests."""
    time.sleep(0.15)
