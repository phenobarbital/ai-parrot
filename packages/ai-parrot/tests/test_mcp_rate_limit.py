"""Tests for -32429 rate-limit handling in the MCP client.

Covers the three layers of the feature:
  * ``parse_retry_after`` normalizing the various retryAfter encodings,
  * ``raise_for_jsonrpc_error`` mapping JSON-RPC errors to the right type,
  * ``MCPClient.call_tool`` backing off and retrying (or failing fast).
"""
import asyncio
import logging

import pytest

from parrot.mcp.client import (
    MCPClientConfig,
    MCPConnectionError,
    MCPRateLimitError,
    parse_retry_after,
    raise_for_jsonrpc_error,
)
from parrot.mcp.integration import MCPClient


# --- parse_retry_after ------------------------------------------------------

def test_parse_retry_after_epoch_millis():
    # Fireflies-style absolute epoch milliseconds (realistic 2023+ timestamp).
    now = 1_700_000_000.0
    # 30s in the future, expressed as ms epoch.
    value = (now + 30) * 1000
    assert parse_retry_after(value, now=now) == pytest.approx(30.0)


def test_parse_retry_after_epoch_seconds():
    now = 2_000_000_000.0
    assert parse_retry_after(now + 12, now=now) == pytest.approx(12.0)


def test_parse_retry_after_plain_delay():
    assert parse_retry_after(5, now=1_000_000.0) == pytest.approx(5.0)
    assert parse_retry_after(2.5, now=1_000_000.0) == pytest.approx(2.5)


def test_parse_retry_after_past_clamps_to_zero():
    now = 2_000_000_000.0
    assert parse_retry_after((now - 100) * 1000, now=now) == 0.0


@pytest.mark.parametrize("value", [None, "nonsense", -1, object()])
def test_parse_retry_after_invalid(value):
    assert parse_retry_after(value, now=1_000_000.0) is None


# --- raise_for_jsonrpc_error ------------------------------------------------

def test_raise_for_rate_limit_by_code():
    err = {
        "code": -32429,
        "message": "Too many requests",
        "data": {"retryAfter": 5, "type": "rate_limit_exceeded"},
    }
    with pytest.raises(MCPRateLimitError) as ei:
        raise_for_jsonrpc_error(err)
    assert ei.value.retry_after == pytest.approx(5.0)
    assert ei.value.code == -32429
    assert ei.value.raw_error is err


def test_raise_for_rate_limit_by_data_type():
    # Some servers use a different code but tag the data type.
    err = {"code": -32000, "data": {"type": "rate_limit_exceeded"}}
    with pytest.raises(MCPRateLimitError):
        raise_for_jsonrpc_error(err)


def test_raise_for_generic_error_is_connection_error():
    err = {"code": -32603, "message": "boom"}
    with pytest.raises(MCPConnectionError) as ei:
        raise_for_jsonrpc_error(err)
    assert not isinstance(ei.value, MCPRateLimitError)


# --- MCPClient.call_tool backoff -------------------------------------------

class _FakeSession:
    """Raises a rate-limit error a fixed number of times, then succeeds."""

    def __init__(self, fail_times: int, retry_after: float):
        self.fail_times = fail_times
        self.retry_after = retry_after
        self.calls = 0

    async def call_tool(self, tool_name, arguments):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise MCPRateLimitError("rate limited", retry_after=self.retry_after)
        return {"ok": True, "calls": self.calls}


def _make_client(session, **cfg_kwargs) -> MCPClient:
    config = MCPClientConfig(name="fake", command="noop", **cfg_kwargs)
    client = MCPClient(config)
    client._session = session
    client._connected = True
    return client


@pytest.fixture
def no_sleep(monkeypatch):
    """Make asyncio.sleep instant but record the requested delays."""
    slept: list[float] = []

    async def fake_sleep(delay):
        slept.append(delay)

    monkeypatch.setattr("parrot.mcp.integration.asyncio.sleep", fake_sleep)
    return slept


@pytest.mark.asyncio
async def test_call_tool_retries_then_succeeds(no_sleep):
    session = _FakeSession(fail_times=2, retry_after=3.0)
    client = _make_client(session, rate_limit_max_retries=3, rate_limit_max_wait=60.0)

    result = await client.call_tool("get_transcripts", {})

    assert result == {"ok": True, "calls": 3}
    assert session.calls == 3
    assert no_sleep == [3.0, 3.0]  # waited the suggested retry_after each time


@pytest.mark.asyncio
async def test_call_tool_fails_fast_when_wait_exceeds_cap(no_sleep):
    # retry_after far above the cap -> no sleeping, error surfaced immediately.
    session = _FakeSession(fail_times=1, retry_after=3600.0)
    client = _make_client(session, rate_limit_max_retries=3, rate_limit_max_wait=60.0)

    with pytest.raises(MCPRateLimitError):
        await client.call_tool("get_user_contacts", {})

    assert session.calls == 1
    assert no_sleep == []  # never backed off


@pytest.mark.asyncio
async def test_call_tool_gives_up_after_max_retries(no_sleep):
    session = _FakeSession(fail_times=99, retry_after=1.0)
    client = _make_client(session, rate_limit_max_retries=2, rate_limit_max_wait=60.0)

    with pytest.raises(MCPRateLimitError):
        await client.call_tool("search", {})

    # initial attempt + 2 retries == 3 calls
    assert session.calls == 3
    assert no_sleep == [1.0, 1.0]
