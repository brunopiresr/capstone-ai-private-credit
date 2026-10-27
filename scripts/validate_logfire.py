"""Explicit SDK acceptance checks; offline by default, --live sends synthetic EU telemetry.

Run in a fresh process. Automated unit tests cover application helpers separately.
No live language model or SEC requests are made in either mode.
"""

import argparse
import asyncio
import csv
import json
import logging
import os
from contextlib import aclosing, nullcontext
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlsplit

import logfire
import requests
from dotenv import load_dotenv
from logfire.testing import SimpleSpanProcessor, TestExporter
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RequestUsage

from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.application.bootstrap import (
    create_assessment_service,
    create_credit_review_service,
    create_document_service,
)
from credit_monitoring.application.rag_service import llm, llm_async, rag, rag_async
from credit_monitoring.config.settings import AssessmentSettings
from credit_monitoring.covenants.extraction import extract_covenants
from credit_monitoring.covenants.structured import SyntheticCovenantReader
from credit_monitoring.financials.repositories import FinancialRepository
from credit_monitoring.ingestion.converters.sec_markdown import CONVERSION_VERSION
from credit_monitoring.ingestion.loaders.financials import load_financials
from credit_monitoring.observability import SessionContext, configure_observability, session_scope
from credit_monitoring.observability.configuration import span
from credit_monitoring.observability.logging import configure_logging
from credit_monitoring.observability.session import get_active_session
from credit_monitoring.retrieval.lexical.sec import build_index

ROOT = Path(__file__).resolve().parents[1]
PERIOD = date(2025, 9, 30)
CONTENT_MARKER = "synthetic-private-content-marker"


def conversation_model() -> FunctionModel:
    """Script the real conversation graph through thread-backed assessment tools."""

    def reply(messages, info):
        last_prompt = max(
            i
            for i, message in enumerate(messages)
            if isinstance(message, ModelRequest)
            and any(isinstance(part, UserPromptPart) for part in message.parts)
        )
        called = {
            part.tool_name
            for message in messages[last_prompt:]
            if isinstance(message, ModelResponse)
            for part in message.parts
            if isinstance(part, ToolCallPart)
        }
        tool = next(
            (name for name in ("get_financials", "assess_covenants") if name not in called), None
        )
        arguments = (
            {"period_end": PERIOD.isoformat(), "information_cutoff": PERIOD.isoformat()}
            if tool
            else {
                "answer": "Synthetic assessment completed.",
                "confidence": "medium",
                "confidence_explanation": "Synthetic inputs only.",
            }
        )
        return ModelResponse(parts=[ToolCallPart(tool or "final_result", arguments)])

    async def stream(messages, info):
        response = reply(messages, info)
        part = response.parts[0]
        yield {
            0: DeltaToolCall(
                name=part.tool_name, json_args=part.args_as_json_str(), tool_call_id="synthetic"
            )
        }

    return FunctionModel(reply, stream_function=stream, model_name="synthetic-conversation")


def assessment_service(directory: Path):
    database = directory / "financials.sqlite3"
    load_financials(ROOT / "data/app/synthetic/synthetic_quarterly_financials.csv", database)
    return create_assessment_service(
        financial_repository=FinancialRepository(database),
        covenant_reader=SyntheticCovenantReader(
            ROOT / "data/app/synthetic/synthetic_covenant_terms.csv"
        ),
        settings=AssessmentSettings(analytics_database=directory / "analytics.sqlite3"),
    )


def document_checks(directory: Path) -> None:
    """Exercise individual processing, batch reuse, and real local RAG retrieval."""
    markdown = directory / "markdown"
    markdown.mkdir()
    (markdown / "SYN.md").write_text("# Synthetic filing\nMaximum leverage ratio 4.0.\n")
    (markdown / ".SYN.conversion-version").write_text(CONVERSION_VERSION)
    record = {
        "document_id": "SYN",
        "company": "Synthetic issuer",
        "ticker": "SYN",
        "document_type": "Amendment",
        "document_date": "2025-09-30",
        "source_url": "https://example.invalid/synthetic",
    }
    catalog = directory / "catalog.csv"
    with catalog.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(record))
        writer.writeheader()
        writer.writerow(record)
    documents = create_document_service(
        source_file=catalog,
        html_dir=directory / "html",
        markdown_dir=markdown,
        database_path=directory / "documents.sqlite3",
        model=TestModel(custom_output_args={"gaps": ["Synthetic evidence only."]}),
    )
    assert documents.process_document("SYN").status == "complete"
    assert documents.process_all_documents()[0].cache_hit
    index = build_index(
        [
            {
                **record,
                "content": "Maximum leverage ratio 4.0.",
                "citation": "Synthetic",
                "role": "agreement",
                "notes": "",
                "period_end": "2025-09-30",
            }
        ]
    )
    assert rag("leverage", index=index, document_count=1, model=TestModel())
    assert asyncio.run(rag_async("leverage", index=index, document_count=1, model=TestModel()))


def parent_id(record: dict) -> int | None:
    return (record.get("parent") or {}).get("span_id")


def assert_descendant(record: dict, ancestor: dict, records: list[dict]) -> None:
    by_id = {item["context"]["span_id"]: item for item in records}
    current = record
    while parent_id(current) is not None:
        if parent_id(current) == ancestor["context"]["span_id"]:
            assert record["context"]["trace_id"] == ancestor["context"]["trace_id"]
            return
        current = by_id[parent_id(current)]
    raise AssertionError(f"{record['name']} is not beneath {ancestor['name']}")


async def async_checks(conversation, session, service):
    original = logfire.get_context()
    # Scope cleanup must occur in this consuming task for interrupted streams.
    async with aclosing(conversation.stream_async(CONTENT_MARKER)) as stream:
        await anext(stream)
    assert get_active_session() is None and logfire.get_context() == original

    async def broken_callback(event):
        raise ValueError("synthetic callback failure")

    try:
        await conversation.ask_async(CONTENT_MARKER, event_stream_handler=broken_callback)
    except ValueError:
        pass
    else:
        raise AssertionError("Callback error must propagate")
    assert get_active_session() is None and logfire.get_context() == original

    started = asyncio.Event()

    async def block_callback(event):
        started.set()
        await asyncio.Event().wait()

    cleanup = []

    async def consume():
        try:
            await conversation.ask_async(CONTENT_MARKER, event_stream_handler=block_callback)
        finally:
            cleanup.append((get_active_session(), logfire.get_context()))

    task = asyncio.create_task(consume())
    await started.wait()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert cleanup == [(None, original)]
    assert get_active_session() is None and logfire.get_context() == original

    # Retain native sibling runs beneath full review, including thread dispatch.
    perspective = {
        "thesis": "Synthetic evidence is limited.",
        "arguments": [],
        "gaps": ["Synthetic smoke has no supported credit arguments."],
        "confidence": "low",
        "confidence_explanation": "Synthetic smoke only.",
    }
    recommendation = {
        "action": "defer",
        "rationale": "Synthetic smoke only.",
        "argument_judgments": [],
        "confidence": "low",
        "confidence_explanation": "Synthetic smoke only.",
    }
    review = create_credit_review_service(
        assessment_service=service,
        bullish_model=TestModel(custom_output_args=perspective),
        bearish_model=TestModel(custom_output_args=perspective),
        recommendation_model=TestModel(custom_output_args=recommendation),
    )
    with session_scope(session):
        result = await review.review_async("SYN002", PERIOD, PERIOD)
        assert result.status == "complete"
        await review.review_assessment_async(service.assess("SYN002", PERIOD, PERIOD))
        await llm_async(CONTENT_MARKER, model=TestModel())
        assert (
            await rag_async("empty", index=None, document_count=0)
            == "No relevant evidence was retrieved."
        )

    # Provider-reported usage on each request includes an output-validation retry.
    attempts = 0

    def respond(messages, info):
        return ModelResponse(
            parts=[TextPart("synthetic retry")],
            usage=RequestUsage(input_tokens=11, output_tokens=3),
        )

    retry_agent = Agent(FunctionModel(respond), name="Synthetic retry", retries=1)

    @retry_agent.output_validator
    def retry_once(output):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ModelRetry("Synthetic retry requested")
        return output

    with session_scope(session):
        await retry_agent.run(CONTENT_MARKER, conversation_id=conversation.session_id)
        await Agent(FunctionModel(respond), name="Synthetic usage peer").run(
            CONTENT_MARKER, conversation_id=conversation.session_id
        )
    assert attempts == 2


def scenario(exporter: TestExporter) -> dict:
    # SDK gate: anchor has ended before either native run begins (separate loops).
    gate = SessionContext()
    for index in range(2):
        with session_scope(gate), span("validation.turn"):
            Agent(TestModel(), name=f"Carrier proof {index}").run_sync(
                CONTENT_MARKER, conversation_id=gate.session_id
            )
    records = exporter.exported_spans_as_dict()
    anchor = next(record for record in records if record["name"] == "agent.session")
    assert anchor["attributes"]["logfire.msg"] == "Credit assessment"
    for turn in (record for record in records if record["name"] == "validation.turn"):
        assert parent_id(turn) == anchor["context"]["span_id"]
        assert turn["context"]["trace_id"] == anchor["context"]["trace_id"]
        assert turn["start_time"] >= anchor["end_time"]
        assert any(
            parent_id(record) == turn["context"]["span_id"]
            and record["name"].startswith("invoke_agent")
            for record in records
        )

    with TemporaryDirectory(prefix="credit-logfire-") as directory:
        service = assessment_service(Path(directory))
        agent = CreditAssessmentAgent(assessment_service=service, model=conversation_model())
        session = SessionContext(name="Quarterly review — SYN002")
        conversation = agent.start_conversation(borrower_id="SYN002", session=session)
        start = len(exporter.exported_spans_as_dict())
        for _ in range(5):
            assert conversation.ask(CONTENT_MARKER).complete
            assert get_active_session() is None
        five_turns = exporter.exported_spans_as_dict()[start:]
        turns = [record for record in five_turns if record["name"] == "agent.turn"]
        assert len(turns) == 5
        session_anchor = next(record for record in five_turns if record["name"] == "agent.session")
        assert session_anchor["attributes"]["logfire.msg"] == "Quarterly review — SYN002"
        for turn in turns:
            assert turn["attributes"]["logfire.msg"] == (
                f"Agent turn: {agent.name} — {session.name} [chat {session.session_id}]"
            )
            assert turn["attributes"]["agent_name"] == agent.name
            assert turn["attributes"]["chat_name"] == session.name
            assert turn["attributes"]["chat_id"] == session.session_id
            assert parent_id(turn) == session_anchor["context"]["span_id"]
            assert any(
                record["name"].startswith("invoke_agent")
                and parent_id(record) == turn["context"]["span_id"]
                for record in five_turns
            )
        assert len({record["context"]["trace_id"] for record in five_turns}) == 1
        assert all(
            record["attributes"].get("gen_ai.conversation.id") == conversation.session_id
            for record in five_turns
        )
        for operation in (record for record in five_turns if record["name"] == "credit.assessment"):
            assert any(
                parent_id(operation) == record["context"]["span_id"]
                for record in five_turns
                if record["name"].startswith("execute_tool")
            )
        asyncio.run(async_checks(conversation, session, service))
        with session_scope(session):
            llm(CONTENT_MARKER, model=TestModel())
            extract_covenants(
                "Extract synthetic terms",
                [
                    {
                        "document_id": "SYN",
                        "citation": "Synthetic",
                        "content": "Synthetic terms only.",
                    }
                ],
                model=TestModel(custom_output_args={"gaps": ["Synthetic smoke only."]}),
            )
            document_checks(Path(directory))
        conversation.close()
        conversation.close()

    # Preserve nested parents; independent sessions created under a trace stay isolated.
    with span("validation.outer"):
        outer = logfire.get_context()
        with session_scope(gate):
            with span("validation.parent"):
                with session_scope() as nested:
                    assert nested is gate
                    with span("validation.child"):
                        pass
                fresh = SessionContext()
                with session_scope(fresh), span("validation.independent"):
                    pass
        assert logfire.get_context() == outer
    assert get_active_session() is None
    try:
        with session_scope(gate), span("validation.failure"):
            raise ValueError("Synthetic expected failure")
    except ValueError:
        pass
    assert get_active_session() is None

    records = exporter.exported_spans_as_dict()

    def find(name):
        return next(record for record in records if record["name"] == name)

    assert parent_id(find("validation.child")) == find("validation.parent")["context"]["span_id"]
    failure = find("validation.failure")
    assert any(
        event["name"] == "exception" and event["attributes"].get("exception.type") == "ValueError"
        for event in failure.get("events", [])
    )
    assert any(
        record["name"] == "agent.turn"
        and any(
            event["attributes"].get("exception.message") == "synthetic callback failure"
            for event in record.get("events", [])
        )
        for record in records
    )
    assert (
        find("validation.independent")["context"]["trace_id"]
        != find("validation.parent")["context"]["trace_id"]
    )
    assert (
        find("validation.outer")["context"]["trace_id"]
        != find("validation.independent")["context"]["trace_id"]
    )
    anchor = next(record for record in five_turns if record["name"] == "agent.session")
    assert (
        sum(
            record["name"] == "agent.session"
            and record["context"]["trace_id"] == anchor["context"]["trace_id"]
            for record in records
        )
        == 1
    )
    descendants = [
        record
        for record in records
        if record["context"]["trace_id"] == anchor["context"]["trace_id"] and record is not anchor
    ]
    for record in descendants:
        if record["context"]["span_id"] != anchor["context"]["span_id"]:
            assert_descendant(record, anchor, records)
    reviews = [record for record in records if record["name"] == "credit.review"]
    assert len(reviews) == 2
    for review in reviews:
        roles = [
            record
            for record in records
            if record["name"].startswith("invoke_agent Credit review:")
            and parent_id(record) == review["context"]["span_id"]
        ]
        assert len(roles) == 3
    retry = find("invoke_agent Synthetic retry")
    requests = [
        record
        for record in records
        if parent_id(record) == retry["context"]["span_id"]
        and "gen_ai.usage.input_tokens" in record["attributes"]
    ]
    assert len(requests) == 2
    assert sum(record["attributes"]["gen_ai.usage.input_tokens"] for record in requests) == 22
    assert sum(record["attributes"]["gen_ai.usage.output_tokens"] for record in requests) == 6
    usage_agents = {
        retry["context"]["span_id"],
        find("invoke_agent Synthetic usage peer")["context"]["span_id"],
    }
    usage_requests = [
        record
        for record in records
        if parent_id(record) in usage_agents and record["name"].startswith("chat ")
    ]
    assert len(usage_requests) == 3
    assert sum(record["attributes"]["gen_ai.usage.input_tokens"] for record in usage_requests) == 33
    assert sum(record["attributes"]["gen_ai.usage.output_tokens"] for record in usage_requests) == 9
    process = find("Process document")
    extraction_span = next(
        record
        for record in records
        if record["name"] == "invoke_agent Document extraction"
        and parent_id(record) == find("Extract section")["context"]["span_id"]
    )
    assert_descendant(extraction_span, process, records)
    assert_descendant(process, anchor, records)
    batch = find("Process all documents")
    assert any(
        record["name"] == "Process document" and parent_id(record) == batch["context"]["span_id"]
        for record in records
    )
    assert len([record for record in records if record["name"] == "rag"]) == 3
    for review in reviews:
        if any(
            record["name"] == "credit.assessment"
            and parent_id(record) == review["context"]["span_id"]
            for record in records
        ):
            break
    else:
        raise AssertionError("Full review must parent the thread-backed assessment")
    assert CONTENT_MARKER not in json.dumps(records)
    return {
        "mode": "offline",
        "spans": len(records),
        "questions": len(turns),
        "session_id": conversation.session_id,
        "trace_id": f"{anchor['context']['trace_id']:032x}",
        "request_input_tokens": sum(
            record["attributes"].get("gen_ai.usage.input_tokens", 0)
            for record in descendants
            if record["name"].startswith("chat ")
        ),
        "request_output_tokens": sum(
            record["attributes"].get("gen_ai.usage.output_tokens", 0)
            for record in descendants
            if record["name"].startswith("chat ")
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Send only synthetic telemetry using local EU credentials.",
    )
    args = parser.parse_args()
    os.environ["PYDANTIC_AI_NO_BANNER"] = "1"
    if args.live:
        load_dotenv(ROOT / ".env", override=False)
        if not os.getenv("LOGFIRE_TOKEN", "").strip():
            parser.error("Configure LOGFIRE_TOKEN locally before the live smoke run.")
        if os.getenv("LOGFIRE_BASE_URL") != "https://logfire-eu.pydantic.dev":
            parser.error(
                "The live smoke run requires LOGFIRE_BASE_URL=https://logfire-eu.pydantic.dev."
            )
    os.environ["LOGFIRE_SEND_TO_LOGFIRE"] = "true" if args.live else "false"
    os.environ["LOGFIRE_CAPTURE_CONTENT"] = "false"
    os.environ["LOGFIRE_MIN_LEVEL"] = "debug"
    exporter = TestExporter()
    configure_sdk = logfire.configure

    def configure_with_capture(**kwargs):
        return configure_sdk(**kwargs, additional_span_processors=[SimpleSpanProcessor(exporter)])

    accepted_batches = []
    send_request = requests.Session.send

    def observe_send(session, request, **kwargs):
        response = send_request(session, request, **kwargs)
        destination = urlsplit(request.url)
        if destination.hostname == "logfire-eu.pydantic.dev" and destination.path.endswith(
            "/v1/traces"
        ):
            accepted_batches.append(response.status_code)
        return response

    network_guard = (
        nullcontext()
        if args.live
        else patch(
            "socket.socket.connect",
            side_effect=AssertionError("Offline validation attempted a network connection"),
        )
    )
    # A new process owns configuration. The offline network guard includes setup.
    # Observing HTTP statuses in live mode verifies transport acceptance, not UI ingestion.
    with network_guard as connections, patch.object(requests.Session, "send", observe_send):
        with patch.object(logfire, "configure", side_effect=configure_with_capture):
            configure_observability()
            configure_observability()
        logger = logging.getLogger("credit_monitoring")
        assert sum(handler.name == "credit_monitoring_logfire" for handler in logger.handlers) == 1
        configure_logging(logging.WARNING)
        assert logger.level == logging.DEBUG
        result = scenario(exporter)
        assert logfire.force_flush(timeout_millis=3000), "Telemetry flush did not complete"
        if args.live:
            assert accepted_batches and all(200 <= code < 300 for code in accepted_batches), (
                "EU trace transport did not confirm acceptance"
            )
            result["accepted_trace_batches"] = len(accepted_batches)
        else:
            connections.assert_not_called()
    result["mode"] = "live" if args.live else "offline"
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
