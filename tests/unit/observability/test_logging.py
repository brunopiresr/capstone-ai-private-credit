"""Console setup and timing behavior without network or global logging changes."""

import logging
from types import SimpleNamespace

import pytest

from credit_monitoring.observability.logging import configure_logging, log_step


def test_console_logging_is_visible_and_idempotent(monkeypatch, capsys):
    logger = logging.Logger("credit_monitoring")
    monkeypatch.setattr(
        "credit_monitoring.observability.logging.logging",
        SimpleNamespace(
            getLogger=lambda _: logger,
            StreamHandler=logging.StreamHandler,
            Formatter=logging.Formatter,
        ),
    )
    configure_logging()
    configure_logging()
    assert len(logger.handlers) == 1
    assert not logger.propagate
    logger.info("Document started")
    output = capsys.readouterr().err
    assert output.count("INFO credit_monitoring: Document started") == 1
    assert logger.handlers[0].formatter._fmt.startswith("%(asctime)s")

    configure_logging("WARNING")
    logger.info("Hidden progress")
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("fails", [False, True])
def test_step_logs_before_work_and_measures_elapsed_time(fails, monkeypatch, caplog):
    clock = iter([10.0, 12.5])
    monkeypatch.setattr("credit_monitoring.observability.logging.perf_counter", lambda: next(clock))
    logger = logging.getLogger("credit_monitoring.test")
    caplog.set_level(logging.INFO, logger="credit_monitoring")

    def run():
        with log_step(logger, "Test step", document_id="SYN"):
            assert caplog.messages == ["Test step started document_id=SYN"]
            if fails:
                raise ValueError("Private input")

    if fails:
        with pytest.raises(ValueError, match="Private input"):
            run()
        assert caplog.messages[-1] == (
            "Test step failed document_id=SYN elapsed_s=2.50 error_type=ValueError"
        )
        assert caplog.records[-1].levelno == logging.ERROR
        assert "Private input" not in caplog.text
    else:
        run()
        assert caplog.messages[-1] == "Test step complete document_id=SYN elapsed_s=2.50"
