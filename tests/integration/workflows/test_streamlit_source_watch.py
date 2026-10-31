"""Regression for new web code importing stale shared contracts after a source edit."""

import os
from pathlib import Path

from streamlit.watcher.local_sources_watcher import LocalSourcesWatcher

from credit_monitoring.web.source_watch import watch_application_sources


def test_streamlit_watches_shared_contracts_and_their_importers(monkeypatch):
    source_root = Path(__file__).resolve().parents[3] / "src"
    web = source_root / "credit_monitoring" / "web"
    monkeypatch.delenv("PYTHONPATH", raising=False)
    watcher = LocalSourcesWatcher.__new__(LocalSourcesWatcher)
    watcher._script_folder = str(web)
    watcher._watched_modules = {}
    shared_paths = [
        source_root / "credit_monitoring/domain/credit_review.py",
        source_root / "credit_monitoring/application/manager_workflow.py",
        source_root / "credit_monitoring/application/credit_review_service.py",
        source_root / "credit_monitoring/persistence/workflow_repository.py",
    ]
    assert watcher._file_should_be_watched(str(web / "preview.py"))
    assert all(not watcher._file_should_be_watched(str(path)) for path in shared_paths)
    watch_application_sources()
    assert all(watcher._file_should_be_watched(str(path)) for path in shared_paths)


def test_existing_watch_paths_are_preserved_across_repeated_app_reruns(monkeypatch, tmp_path):
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    watch_application_sources()
    first = os.environ["PYTHONPATH"]
    watch_application_sources()
    assert os.environ["PYTHONPATH"] == first
    assert first.split(os.pathsep)[-1] == str(tmp_path)
