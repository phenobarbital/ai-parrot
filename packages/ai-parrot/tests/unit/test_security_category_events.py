"""FEAT-761 TASK-4829 — content-free security events."""

import inspect
import logging

import pytest

from parrot.security.prompt_injection import SecurityEventLogger, ThreatLevel


class _Conn:
    def __init__(self, calls, fail=False):
        self.calls = calls
        self.fail = fail

    async def execute(self, *args):
        if self.fail:
            raise RuntimeError("SECRET-SYSTEM-PROMPT")
        self.calls.append(args)


class _Ctx:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def acquire(self):
        return _Ctx(_Conn(self.calls, self.fail))


def test_signature_has_no_content_parameter():
    params = inspect.signature(SecurityEventLogger.log_security_category_event).parameters
    for name in params:
        assert name not in {"content", "text", "matched_text", "original_input", "sanitized_input"}
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for n, p in params.items() if n != "self")


@pytest.mark.asyncio
async def test_log_line_has_category_and_severity(caplog):
    ev = SecurityEventLogger()
    with caplog.at_level(logging.WARNING):
        await ev.log_security_category_event(
            category="jailbreak", severity=ThreatLevel.HIGH, score=0.9, counts={"n": 2}
        )
    text = caplog.text
    assert "jailbreak" in text and "HIGH" in text
    assert "anonymous" in text and "unknown" in text


@pytest.mark.asyncio
async def test_db_row_has_no_content_and_not_null_defaults():
    pool = _Pool()
    ev = SecurityEventLogger(db_pool=pool)
    await ev.log_security_category_event(
        category="prompt_leakage", severity=ThreatLevel.CRITICAL, score=0.5, counts={"matched_segments": 2}
    )
    assert len(pool.calls) == 1
    args = pool.calls[0]
    assert args[1] == "prompt_leakage"
    assert args[2] == "anonymous" and args[3] == "unknown"
    assert args[5] == "critical"
    assert args[6] == {"score": 0.5, "counts": {"matched_segments": 2}}
    assert args[7] is None and args[8] is None


@pytest.mark.asyncio
async def test_db_failure_logged_not_raised(caplog):
    ev = SecurityEventLogger(db_pool=_Pool(fail=True))
    with caplog.at_level(logging.ERROR):
        await ev.log_security_category_event(category="jailbreak", severity=ThreatLevel.LOW)
    assert "RuntimeError" in caplog.text
    assert "SECRET-SYSTEM-PROMPT" not in caplog.text
