"""Real extraction/cache concurrency with isolated models and caller-owned progress."""

import asyncio
import csv
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from model_helpers import ScriptedModel, model_response
from pydantic_ai.messages import ModelRequest, UserPromptPart

from credit_monitoring.domain import CovenantExtraction
from credit_monitoring.ingestion.converters.sec_markdown import CONVERSION_VERSION
from credit_monitoring.observability import session_scope
from credit_monitoring.observability.session import get_active_session


@pytest.fixture
def batch_service(document_service_factory):
    service = document_service_factory()
    base = service.catalog_record("SYN")
    records = [{**base, "document_id": f"DOC{i}"} for i in range(8)]
    with service.source_file.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(base))
        writer.writeheader()
        writer.writerows(records)
    for row in records:
        did = row["document_id"]
        (service.markdown_dir / f"{did}.md").write_text("Maximum leverage is 4.0x.")
        (service.markdown_dir / f".{did}.conversion-version").write_text(CONVERSION_VERSION)
    return service


def document_id(messages):
    payload = next(
        part.content
        for m in reversed(messages)
        if isinstance(m, ModelRequest)
        for part in m.parts
        if isinstance(part, UserPromptPart)
    )
    return json.loads(payload)["retrieved_records"][0]["document_id"]


def factory_for(respond, owned):
    class OwnedModel(ScriptedModel):
        async def __aenter__(self):
            self.owner = threading.get_ident()
            self.loop = asyncio.get_running_loop()
            self.closed = False
            return await super().__aenter__()

        async def __aexit__(self, *args):
            assert threading.get_ident() == self.owner
            assert asyncio.get_running_loop() is self.loop
            self.closed = True
            return await super().__aexit__(*args)

    def create():
        model = OwnedModel()
        model.respond.side_effect = respond
        owned.append(model)
        return model

    return create


def test_parallelism_is_bounded_ordered_and_context_is_preserved(batch_service):
    service = batch_service
    barrier = threading.Barrier(4)
    guard = threading.Lock()
    active, peak, sessions, owned = 0, 0, [], []
    caller = threading.get_ident()
    events = []

    def respond(messages, **kwargs):
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
            sessions.append(get_active_session().session_id)
        barrier.wait(timeout=10)
        with guard:
            active -= 1
        return model_response(extraction=CovenantExtraction())

    service.model_factory = factory_for(respond, owned)

    def report(event):
        assert threading.get_ident() == caller
        events.append(event)

    with session_scope() as session:
        results = service.process_documents([f"DOC{i}" for i in range(8)], progress=report)
    assert [r.document_id for r in results] == [f"DOC{i}" for i in range(8)]
    assert all(r.status == "complete" for r in results)
    assert peak == 4 and sessions == [session.session_id] * 8
    assert all(m.closed and m.loop.is_closed() and m.owner != caller for m in owned)
    assert all(a.total_fraction <= b.total_fraction for a, b in zip(events, events[1:]))
    assert events[-1].total_fraction == 1 and events[-1].completed_documents == 8
    assert service.repository.section_count("DOC0", results[0].cache_key) == 1
    count = len(owned)
    cached = service.process_all_documents()
    assert all(r.cache_hit for r in cached) and len(owned) == count
    # Force creates new isolated clients; no extra work occurs within a document.
    assert all(not r.cache_hit for r in service.process_all_documents(force=True))
    assert len(owned) == 16


def test_out_of_order_failures_and_successes_keep_input_order(batch_service):
    release_first = threading.Event()
    completed = []
    owned = []

    def respond(messages, **kwargs):
        did = document_id(messages)
        if did == "DOC0":
            assert release_first.wait(10)
        elif did == "DOC1":
            raise OSError("Expected per-document error")
        return model_response(extraction=CovenantExtraction())

    batch_service.model_factory = factory_for(respond, owned)

    def report(event):
        if event.outcome:
            completed.append(event.document_id)
            if event.document_id == "DOC1":
                release_first.set()

    results = batch_service.process_documents(["DOC0", "DOC1", "DOC2"], progress=report)
    assert [r.document_id for r in results] == ["DOC0", "DOC1", "DOC2"]
    assert [r.status for r in results] == ["complete", "failed", "complete"]
    assert completed[0] != "DOC0"
    assert "Expected per-document error" in results[1].error
    assert all(m.closed for m in owned)


def test_parallel_injected_resources_require_factories_and_invalid_workers_fail(batch_service):
    for workers in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match="positive integer"):
            batch_service.process_all_documents(max_workers=workers)
    with pytest.raises(ValueError, match="model_factory"):
        batch_service.process_all_documents()
    batch_service.model_factory = lambda: ScriptedModel()
    batch_service.converter = SimpleNamespace()
    with pytest.raises(ValueError, match="converter_factory"):
        batch_service.process_all_documents()
    batch_service.model.respond.assert_not_called()


def test_parallel_cache_hits_need_no_provider_credentials(batch_service, monkeypatch):
    batch_service.model.respond.return_value = model_response(extraction=CovenantExtraction())
    batch_service.process_all_documents(max_workers=1)
    batch_service.model_factory = lambda: pytest.fail("Cached batch constructed a model")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert all(r.cache_hit for r in batch_service.process_all_documents())


def test_document_lock_prevents_duplicate_concurrent_extraction(batch_service):
    started = threading.Event()
    release = threading.Event()
    owned = []

    def respond(**kwargs):
        started.set()
        assert release.wait(10)
        return model_response(extraction=CovenantExtraction())

    batch_service.model_factory = factory_for(respond, owned)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(batch_service.process_documents, ["DOC0"])
        assert started.wait(10)
        second = executor.submit(batch_service.process_documents, ["DOC0"])
        release.set()
        outcomes = [first.result(10)[0], second.result(10)[0]]
    assert len(owned) == 1
    assert sorted(r.cache_hit for r in outcomes) == [False, True]


def test_global_sec_download_lock_preserves_request_and_delay_pairing(tmp_path, monkeypatch):
    from credit_monitoring.ingestion.loaders import sec

    active = threading.Event()
    events = []

    def download(url, **kwargs):
        assert not active.is_set()
        active.set()
        events.append("request")
        return "<p>Filing</p>"

    def delay():
        assert active.is_set()
        events.append("delay")
        active.clear()

    monkeypatch.setattr(sec, "download_sec_filing", download)
    monkeypatch.setattr(sec, "throttle_download", delay)
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(
                sec.load_sec_html,
                {"document_id": f"D{i}", "source_url": f"https://example.invalid/{i}.html"},
                html_dir=tmp_path,
                user_agent="test test@example.invalid",
            )
            for i in range(8)
        ]
        assert all(f.result().is_file() for f in futures)
    assert events == ["request", "delay"] * 8


def test_converter_instances_are_isolated_closed_and_publish_complete_cache(batch_service):
    owned, converters = [], []
    barrier = threading.Barrier(2)
    service = batch_service
    service.html_dir.mkdir()
    for did in ("DOC0", "DOC1"):
        (service.markdown_dir / f"{did}.md").unlink()
        (service.markdown_dir / f".{did}.conversion-version").unlink()
        (service.html_dir / f"{did}.html").write_text("<p>Maximum leverage is 4.0x.</p>")

    class Converter:
        def __init__(self):
            self.owner = threading.get_ident()
            self.closed = False
            converters.append(self)

        def convert_local(self, path):
            assert threading.get_ident() == self.owner
            barrier.wait(10)
            return SimpleNamespace(markdown="Maximum leverage is 4.0x.")

        def close(self):
            assert threading.get_ident() == self.owner
            self.closed = True

    service.model_factory = factory_for(
        lambda **kwargs: model_response(extraction=CovenantExtraction()), owned
    )
    service.converter_factory = Converter
    results = service.process_documents(["DOC0", "DOC1"])
    assert all(r.status == "complete" for r in results)
    assert len(converters) == 2 and all(c.closed for c in converters)
    assert service.converter is None and all(m.closed for m in owned)
    assert all(
        (service.markdown_dir / f".{did}.conversion-version").read_text() == CONVERSION_VERSION
        for did in ("DOC0", "DOC1")
    )


def test_converter_factory_failure_still_closes_owned_model(batch_service):
    owned = []
    batch_service.model_factory = factory_for(lambda **kwargs: pytest.fail("Model called"), owned)

    def fail():
        raise ValueError("Expected converter setup failure")

    batch_service.converter_factory = fail
    outcomes = batch_service.process_documents(["DOC0", "DOC1"])
    assert all(o.status == "failed" for o in outcomes)
    assert all("converter setup failure" in o.error for o in outcomes)
    assert len(owned) == 2 and all(m.closed and m.loop.is_closed() for m in owned)


def test_parallel_failed_document_resumes_only_missing_sections(batch_service):
    from credit_monitoring.ingestion.chunking.sections import split_document

    service = batch_service
    text = "# Source\n\n" + "\n\n".join("Paragraph " + str(i) + " x" * 20 for i in range(8))
    (service.markdown_dir / "DOC0.md").write_text(text)
    service.max_chars = 150
    count = len(split_document(text, max_chars=150))
    calls, owned = {}, []
    guard = threading.Lock()

    def respond(messages, **kwargs):
        did = document_id(messages)
        with guard:
            calls[did] = calls.get(did, 0) + 1
            index = calls[did]
        if did == "DOC0" and index == 2:
            return model_response(status="incomplete")
        return model_response(
            extraction=CovenantExtraction(
                gaps=["Preserved first section"] if did == "DOC0" and index == 1 else []
            )
        )

    service.model_factory = factory_for(respond, owned)
    first = service.process_documents(["DOC0", "DOC1"])
    assert [r.status for r in first] == ["failed", "complete"]
    assert service.get_document_extraction("DOC0").completed_sections == 1
    second = service.process_documents(["DOC0", "DOC1"])
    assert all(r.status == "complete" for r in second)
    assert second[1].cache_hit and calls["DOC1"] == 1
    assert calls["DOC0"] == count + 1
    assert second[0].result.extraction.gaps == ["Preserved first section"]
    assert all(m.closed for m in owned)
