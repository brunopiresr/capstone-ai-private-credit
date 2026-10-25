"""Application configuration policy with SDK calls stubbed; never export telemetry."""

import logging
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

import credit_monitoring.observability.configuration as configuration


@pytest.fixture
def configuration_stubs(monkeypatch):
    monkeypatch.setenv("LOGFIRE_SEND_TO_LOGFIRE", "false")
    monkeypatch.delenv("LOGFIRE_CAPTURE_CONTENT", raising=False)
    monkeypatch.delenv("LOGFIRE_SERVICE_NAME", raising=False)
    monkeypatch.setattr(configuration, "_configured", False)
    monkeypatch.setattr(configuration, "_capture_content", False)
    configure = Mock()
    instrument = Mock()
    monkeypatch.setattr(configuration.logfire, "configure", configure)
    monkeypatch.setattr(configuration.logfire, "instrument_pydantic_ai", instrument)
    handler_fallbacks = []

    def handler_factory(*, level, fallback):
        handler_fallbacks.append(fallback)
        return logging.NullHandler(level)

    monkeypatch.setattr(configuration.logfire, "LogfireLoggingHandler", handler_factory)
    logger = logging.Logger("credit_monitoring")
    get_logger = logging.getLogger
    monkeypatch.setattr(
        logging,
        "getLogger",
        lambda name=None: logger if name == "credit_monitoring" else get_logger(name),
    )
    return configure, instrument, logger, handler_fallbacks


@pytest.mark.parametrize(
    "value, expected", [("true", True), (" TRUE \n", True), ("false", False), ("\tFalse ", False)]
)
def test_content_policy_accepts_only_normalized_booleans(value, expected):
    assert configuration._parse_capture_content(value) is expected


@pytest.mark.parametrize("value", ["", "yes", "no", "1", "0", "none", "true,false"])
def test_content_policy_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="LOGFIRE_CAPTURE_CONTENT.*true.*false"):
        configuration._parse_capture_content(value)


def test_configuration_is_idempotent_and_preserves_external_handlers(configuration_stubs):
    configure, instrument, logger, fallbacks = configuration_stubs
    console = logging.NullHandler(logging.WARNING)
    console.set_name("credit_monitoring_console")
    external = logging.NullHandler(logging.ERROR)
    logger.addHandler(console)
    logger.addHandler(external)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: configuration.configure_observability(), range(8)))
    configure.assert_called_once_with(
        send_to_logfire=None, service_name="credit-monitoring", console=False
    )
    instrument.assert_called_once_with(include_content=False, include_binary_content=False)
    assert configuration.is_observability_configured()
    assert not configuration.capture_content_enabled()
    assert len(logger.handlers) == 3
    assert logger.handlers[:2] == [console, external]
    assert logger.handlers[-1].name == "credit_monitoring_logfire"
    assert logger.handlers[-1].level == logger.level == logging.DEBUG
    assert len(fallbacks) == 1 and isinstance(fallbacks[0], logging.NullHandler)
    assert not logger.propagate


def test_content_policy_is_resolved_once(configuration_stubs, monkeypatch):
    _, instrument, _, _ = configuration_stubs
    monkeypatch.setenv("LOGFIRE_CAPTURE_CONTENT", " TrUe ")
    configuration.configure_observability()
    monkeypatch.setenv("LOGFIRE_CAPTURE_CONTENT", "invalid-after-setup")
    configuration.configure_observability()
    assert configuration.capture_content_enabled()
    instrument.assert_called_once_with(include_content=True, include_binary_content=False)


def test_invalid_policy_does_not_begin_setup_and_can_be_corrected(configuration_stubs, monkeypatch):
    configure, instrument, logger, _ = configuration_stubs
    monkeypatch.setenv("LOGFIRE_CAPTURE_CONTENT", "yes")
    with pytest.raises(ValueError, match="LOGFIRE_CAPTURE_CONTENT"):
        configuration.configure_observability()
    configure.assert_not_called()
    instrument.assert_not_called()
    assert not configuration.is_observability_configured()
    assert logger.handlers == []
    monkeypatch.setenv("LOGFIRE_CAPTURE_CONTENT", "false")
    configuration.configure_observability()
    assert configuration.is_observability_configured()


def test_failed_setup_is_retryable(configuration_stubs):
    configure, instrument, logger, _ = configuration_stubs
    instrument.side_effect = RuntimeError("Setup failed")
    with pytest.raises(RuntimeError, match="Setup failed"):
        configuration.configure_observability()
    assert not configuration.is_observability_configured()
    assert not configuration.capture_content_enabled()
    assert logger.handlers == []
    instrument.side_effect = None
    configuration.configure_observability()
    assert configuration.is_observability_configured()
    assert configure.call_count == instrument.call_count == 2
    assert len(logger.handlers) == 1


def test_unconfigured_span_is_quiet_and_keeps_application_exceptions(
    configuration_stubs, monkeypatch
):
    span = Mock(side_effect=AssertionError("SDK must remain unused"))
    monkeypatch.setattr(configuration.logfire, "span", span)
    with pytest.raises(ValueError, match="Work failed"):
        with configuration.span("assessment", borrower_id="SYN"):
            raise ValueError("Work failed")
    span.assert_not_called()
