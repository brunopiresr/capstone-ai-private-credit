"""Console setup and timing behavior without network or global logging changes."""

import asyncio
import json
import logging
from contextlib import contextmanager
from datetime import date

import pytest

from credit_monitoring.calculations.leverage import CalculationInputError, divide
from credit_monitoring.observability.logging import (
    StructuredConsoleFormatter,
    _update_logger_threshold,
    configure_logging,
    log_event,
    log_step,
    logging_context,
)


def _use_package_logger(monkeypatch, logger):
    get_logger = logging.getLogger
    monkeypatch.setattr(
        logging,
        "getLogger",
        lambda name=None: logger if name == "credit_monitoring" else get_logger(name),
    )


def test_console_logging_is_visible_and_idempotent(monkeypatch, capsys):
    logger = logging.Logger("credit_monitoring")
    _use_package_logger(monkeypatch, logger)
    configure_logging()
    configure_logging()
    assert len(logger.handlers) == 1
    assert not logger.propagate
    logger.info("Document started")
    output = capsys.readouterr().err
    assert output.count("INFO credit_monitoring: Document started") == 1

    configure_logging("WARNING")
    logger.info("Hidden progress")
    assert capsys.readouterr().err == ""


def test_console_configuration_preserves_external_handlers(monkeypatch):
    logger = logging.Logger("credit_monitoring")
    external = logging.NullHandler()
    external.set_name("future_logfire_handler")
    external.setLevel(logging.DEBUG)
    logger.addHandler(external)
    _use_package_logger(monkeypatch, logger)
    configure_logging()
    configure_logging("WARNING")
    assert logger.handlers[0] is external
    assert external.level == logging.DEBUG
    assert len(logger.handlers) == 2
    assert logger.handlers[1].level == logging.WARNING
    assert logger.level == logging.DEBUG


@pytest.mark.parametrize("external_level", [logging.DEBUG, logging.NOTSET])
def test_console_warning_keeps_debug_enabled_for_other_handlers(monkeypatch, external_level):
    logger = logging.Logger("credit_monitoring")
    records = []

    class RecordingHandler(logging.Handler):
        def emit(self, record):
            records.append(record)

    external = RecordingHandler(external_level)
    logger.addHandler(external)
    _use_package_logger(monkeypatch, logger)
    configure_logging(logging.WARNING)
    logger.debug("Detailed calculation")
    assert logger.level == logging.DEBUG
    assert [record.getMessage() for record in records] == ["Detailed calculation"]
    assert logger.handlers[1].level == logging.WARNING


@pytest.mark.parametrize(
    "levels, expected",
    [
        ([], logging.INFO),
        ([logging.WARNING], logging.WARNING),
        ([logging.WARNING, logging.INFO], logging.INFO),
        ([logging.NOTSET, logging.ERROR], logging.DEBUG),
    ],
)
def test_logger_threshold_uses_attached_handlers(levels, expected):
    logger = logging.Logger("credit_monitoring")
    for level in levels:
        logger.addHandler(logging.NullHandler(level))
    _update_logger_threshold(logger)
    assert logger.level == expected
    assert not logger.propagate


def test_log_step_projects_context_without_mutating_inputs(monkeypatch):
    captured = []

    @contextmanager
    def span(name, **attributes):
        captured.append((name, attributes))
        yield

    monkeypatch.setattr("credit_monitoring.observability.logging.span", span)
    payload = {"period_end": date(2025, 9, 30), "values": [1, 2]}
    logger = logging.Logger("credit_monitoring")
    with logging_context(borrower_id="parent", agreement_id="agreement"):
        with log_step(logger, "assessment", borrower_id="child", inputs=payload):
            payload["values"].append(3)
    assert captured == [
        (
            "assessment",
            {
                "borrower_id": "child",
                "agreement_id": "agreement",
                "inputs": {"period_end": "2025-09-30", "values": [1, 2]},
            },
        )
    ]
    assert payload["period_end"] == date(2025, 9, 30)


def test_structured_console_output_preserves_handler_attributes(caplog):
    caplog.set_level(logging.INFO, logger="credit_monitoring")
    logger = logging.getLogger("credit_monitoring.test")
    with logging_context(borrower_id="TEST", assessment_run_id="run"):
        log_event(
            logger,
            "adjustment",
            inputs={"before": 20, "cap": 10},
            outputs={"after": 10},
        )
    record = caplog.records[0]
    formatted = StructuredConsoleFormatter("%(message)s").format(record)
    assert formatted.startswith("adjustment complete ")
    fields = json.loads(formatted.removeprefix("adjustment complete "))
    assert fields["borrower_id"] == "TEST"
    assert fields["inputs"] == record.inputs == {"before": 20, "cap": 10}
    assert fields["outputs"] == record.outputs == {"after": 10}


def test_context_isolated_between_async_runs_and_thread_work(caplog):
    caplog.set_level(logging.INFO, logger="credit_monitoring")
    logger = logging.getLogger("credit_monitoring.test")

    async def run(borrower):
        with logging_context(borrower_id=borrower, assessment_run_id=f"run-{borrower}"):
            await asyncio.sleep(0)
            try:
                with logging_context(covenant_id=f"covenant-{borrower}"):
                    await asyncio.to_thread(log_event, logger, "scoped_work")
                    await asyncio.to_thread(divide, 1, 0)
            except CalculationInputError:
                pass
            await asyncio.to_thread(log_event, logger, "after_failure")

    async def main():
        await asyncio.gather(run("A"), run("B"))

    asyncio.run(main())
    for record in caplog.records:
        assert record.assessment_run_id == f"run-{record.borrower_id}"
        if record.operation == "scoped_work":
            assert record.covenant_id == f"covenant-{record.borrower_id}"
        else:
            assert not hasattr(record, "covenant_id")
    assert {r.borrower_id for r in caplog.records} == {"A", "B"}
    log_event(logger, "outside")
    assert not hasattr(caplog.records[-1], "borrower_id")
    assert not hasattr(caplog.records[-1], "assessment_run_id")


@pytest.mark.parametrize("fails", [False, True])
def test_step_logs_before_work_and_measures_elapsed_time(fails, monkeypatch, caplog):
    clock = iter([10.0, 12.5])
    monkeypatch.setattr("credit_monitoring.observability.logging.perf_counter", lambda: next(clock))
    logger = logging.getLogger("credit_monitoring.test")
    caplog.set_level(logging.INFO, logger="credit_monitoring")

    def run():
        with log_step(logger, "Test step", document_id="SYN"):
            assert "Test step" in caplog.messages[-1]
            assert "started" in caplog.messages[-1] and "document_id=SYN" in caplog.messages[-1]
            if fails:
                raise ValueError("Private input")

    if fails:
        with pytest.raises(ValueError, match="Private input"):
            run()
        assert all(
            item in caplog.messages[-1]
            for item in ("Test step", "failed", "elapsed_s=2.50", "error_type=ValueError")
        )
        assert caplog.records[-1].levelno == logging.ERROR
        assert "Private input" not in caplog.text
    else:
        run()
        assert all(
            item in caplog.messages[-1] for item in ("Test step", "complete", "elapsed_s=2.50")
        )
