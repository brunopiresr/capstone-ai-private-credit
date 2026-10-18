"""The CLI warms the service cache without live SEC requests."""

import csv
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from credit_monitoring.ingestion.converters.sec_markdown import load_markdown
from credit_monitoring.ingestion.loaders.sec import load_sec_html

SCRIPT = Path(__file__).parents[3] / "data/download_sec_documents.py"
RECORD = {"document_id": "SYN", "source_url": "https://example.invalid/filing.htm"}


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    monkeypatch.setattr("credit_monitoring.ingestion.loaders.sec.throttle_download", lambda: None)
    spec = importlib.util.spec_from_file_location("sec_download_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def catalog(tmp_path, records):
    source = tmp_path / "catalog.csv"
    with source.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=RECORD.keys())
        writer.writeheader()
        writer.writerows(records)
    return source


def test_import_and_help_do_not_read_catalog_or_download(cli, monkeypatch, tmp_path):
    forbidden = Mock(side_effect=AssertionError("No I/O expected"))
    monkeypatch.setattr("credit_monitoring.ingestion.loaders.sec.load_catalog", forbidden)
    monkeypatch.setattr("credit_monitoring.ingestion.loaders.sec.load_sec_html", forbidden)
    monkeypatch.chdir(tmp_path)
    spec = importlib.util.spec_from_file_location("fresh_sec_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(SystemExit) as exit_info:
        module.main(["--help"])
    assert exit_info.value.code == 0
    forbidden.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_cli_cache_is_reused_by_conversion_and_cached_cli_needs_no_identity(
    cli, monkeypatch, tmp_path
):
    download = Mock(return_value="<p>Covenant threshold 4.00</p>")
    monkeypatch.setattr("credit_monitoring.ingestion.loaders.sec.download_sec_filing", download)
    monkeypatch.setenv("SEC_USER_AGENT", "Fixture fixture@example.invalid")
    args = ["--source-file", str(catalog(tmp_path, [RECORD])), "--html-dir", str(tmp_path / "html")]
    assert cli.main([*args, "--document-id", "SYN"]) == 0
    assert (tmp_path / "html/SYN.html").read_text() == download.return_value
    monkeypatch.delenv("SEC_USER_AGENT")
    assert cli.main(args) == 0
    converter = Mock()
    converter.convert_local.return_value = SimpleNamespace(markdown="Covenant threshold 4.00")
    assert (
        load_markdown(
            RECORD,
            html_dir=tmp_path / "html",
            markdown_dir=tmp_path / "markdown",
            user_agent="",
            converter=converter,
        )
        == "Covenant threshold 4.00"
    )
    download.assert_called_once()


@pytest.mark.parametrize("failure", ["identity", "empty", "http", "write", "pdf"])
def test_failed_downloads_do_not_publish_cache(cli, monkeypatch, tmp_path, failure):
    record = dict(RECORD)
    if failure == "pdf":
        record["source_url"] += ".pdf"
    download = Mock(return_value="" if failure == "empty" else "<p>source</p>")
    if failure == "http":
        download.side_effect = requests.HTTPError("Unavailable")
    if failure == "write":
        monkeypatch.setattr(Path, "replace", Mock(side_effect=OSError("Interrupted write")))
    monkeypatch.setattr("credit_monitoring.ingestion.loaders.sec.download_sec_filing", download)
    if failure != "identity":
        monkeypatch.setenv("SEC_USER_AGENT", "Fixture fixture@example.invalid")
    directory = tmp_path / "html"
    args = ["--source-file", str(catalog(tmp_path, [record])), "--html-dir", str(directory)]
    assert cli.main(args) == 1
    assert not (directory / "SYN.html").exists()
    assert not directory.exists() or not list(directory.iterdir())
    if failure in {"identity", "pdf"}:
        download.assert_not_called()


def test_cli_reports_failure_and_continues_other_documents(cli, monkeypatch, tmp_path):
    monkeypatch.setenv("SEC_USER_AGENT", "Fixture fixture@example.invalid")
    download = Mock(side_effect=[requests.HTTPError("Unavailable"), "<p>source</p>"])
    monkeypatch.setattr("credit_monitoring.ingestion.loaders.sec.download_sec_filing", download)
    source = catalog(tmp_path, [RECORD, {**RECORD, "document_id": "OTHER"}])
    assert cli.main(["--source-file", str(source), "--html-dir", str(tmp_path / "html")]) == 1
    assert (tmp_path / "html/OTHER.html").is_file()


@pytest.mark.parametrize("document_id", ["../escape", "a/b", "", "/absolute"])
def test_invalid_document_id_is_rejected_before_io(tmp_path, document_id):
    with pytest.raises(ValueError, match="filenames"):
        load_sec_html({**RECORD, "document_id": document_id}, html_dir=tmp_path, user_agent="")
    assert not list(tmp_path.iterdir())


def test_unknown_selection_fails_without_loading_html(cli, tmp_path, monkeypatch):
    load = Mock(side_effect=AssertionError("No download expected"))
    monkeypatch.setattr(cli, "load_sec_html", load)
    assert (
        cli.main(["--source-file", str(catalog(tmp_path, [RECORD])), "--document-id", "UNKNOWN"])
        == 1
    )
    load.assert_not_called()
