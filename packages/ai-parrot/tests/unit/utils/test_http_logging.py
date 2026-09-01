"""Tests for ``parrot.utils.http_logging`` — quieting the HTTP transport logs.

The regression these guard: the OpenAI SDK depends on ``httpx2``/``httpcore2``
(the 2.x line ships under different top-level names), so the codebase's
long-standing ``getLogger("httpcore")`` suppressions never reached it and a
Bedrock Mantle call flooded the console with ``httpcore2.http11`` DEBUG lines.
"""

import logging

import pytest
from parrot.utils.http_logging import HTTP_LOGGER_NAMES, quiet_http_loggers
from parrot.utils.log_levels import resolve_log_level


@pytest.fixture(autouse=True)
def _restore_levels():
    """Restore whatever level each HTTP logger had before the test."""
    before = {n: logging.getLogger(n).level for n in HTTP_LOGGER_NAMES}
    yield
    for name, level in before.items():
        logging.getLogger(name).setLevel(level)


def test_both_stack_generations_are_covered():
    """The 2.x names are separate top-level packages, not children of the 1.x ones."""
    assert set(HTTP_LOGGER_NAMES) == {"httpx", "httpcore", "httpx2", "httpcore2"}
    # httpcore2 is NOT under the httpcore logger tree, so quieting "httpcore"
    # alone provably cannot silence it — the reason this module exists.
    assert not "httpcore2".startswith("httpcore.")


def test_quiet_raises_every_family_to_warning():
    for name in HTTP_LOGGER_NAMES:
        logging.getLogger(name).setLevel(logging.DEBUG)

    quiet_http_loggers()

    for name in HTTP_LOGGER_NAMES:
        assert logging.getLogger(name).level == logging.WARNING


def test_debug_records_are_filtered_after_quieting():
    """The level is what actually suppresses the record, not just an attribute."""
    logger = logging.getLogger("httpcore2.http11")
    logging.getLogger("httpcore2").setLevel(logging.DEBUG)
    assert logger.isEnabledFor(logging.DEBUG)

    quiet_http_loggers()

    assert not logger.isEnabledFor(logging.DEBUG)
    assert logger.isEnabledFor(logging.WARNING)


def test_env_var_restores_the_wire_trace(monkeypatch):
    monkeypatch.setenv("PARROT_HTTP_LOG_LEVEL", "DEBUG")
    quiet_http_loggers()
    assert logging.getLogger("httpcore2").level == logging.DEBUG


def test_explicit_level_wins_over_env(monkeypatch):
    monkeypatch.setenv("PARROT_HTTP_LOG_LEVEL", "DEBUG")
    quiet_http_loggers(logging.ERROR)
    assert logging.getLogger("httpx2").level == logging.ERROR

    quiet_http_loggers("INFO")
    assert logging.getLogger("httpx2").level == logging.INFO


def test_quiet_is_idempotent():
    quiet_http_loggers()
    first = logging.getLogger("httpcore2").level
    quiet_http_loggers()
    assert logging.getLogger("httpcore2").level == first


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, logging.WARNING),
        ("", logging.WARNING),
        ("   ", logging.WARNING),
        ("debug", logging.DEBUG),
        (" Info ", logging.INFO),
        ("10", 10),
        ("not-a-level", logging.WARNING),
    ],
)
def test_resolve_log_level(raw, expected):
    assert resolve_log_level(raw, logging.WARNING) == expected
