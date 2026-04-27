"""Regression tests for AnthropicClient against anthropic SDK >=0.97.0.

This test suite was introduced as part of FEAT-124 (claude-sdk-migration) to
validate that the bump from `anthropic[aiohttp]==0.61.0` to
`anthropic[aiohttp]>=0.97.0,<1.0.0` does not break `AnthropicClient`. The
upgrade spans 36 minor versions, so we explicitly re-verify:

* the SDK exception types and message types still import,
* the ``betas`` parameter for the 1M context beta header is still accepted,
* ``AnthropicClient._is_capacity_error`` still classifies the modern SDK
  exception shapes correctly.

Live integration is covered by the ``test_anthropic_live_smoke`` test, which
is gated on ``ANTHROPIC_API_KEY`` and the ``@pytest.mark.live`` marker.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — build SDK exceptions without their full network-bound __init__
# ---------------------------------------------------------------------------

def _make_api_status_error(status_code: int):
    """Construct an APIStatusError without invoking its real constructor."""
    from anthropic import APIStatusError

    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.headers = {}
    mock_response.text = f"{status_code} Error"
    mock_response.json.return_value = {
        "error": {"message": f"{status_code} Error"}
    }
    error = APIStatusError.__new__(APIStatusError)
    error.status_code = status_code
    error.response = mock_response
    error.body = None
    error.message = f"{status_code} Error"
    return error


def _make_rate_limit_error():
    """Construct a RateLimitError without invoking its real constructor."""
    from anthropic import RateLimitError

    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.headers = {}
    mock_response.text = "429 Too Many Requests"
    mock_response.json.return_value = {
        "error": {"message": "rate limit exceeded"}
    }
    error = RateLimitError.__new__(RateLimitError)
    error.status_code = 429
    error.response = mock_response
    error.body = None
    error.message = "rate limit exceeded"
    return error


def _make_anthropic_client():
    """Bypass __init__ to obtain an AnthropicClient with the attributes the
    methods under test actually touch.

    We avoid a real ``__init__`` so we don't need to mock the AbstractClient
    base machinery (logger, conversation memory, …) just to assert pure
    branching logic on exceptions or payload shaping.
    """
    from parrot.clients.claude import AnthropicClient

    client = AnthropicClient.__new__(AnthropicClient)
    client._fallback_model = "claude-sonnet-4.5"
    return client


# ---------------------------------------------------------------------------
# Test 1 — SDK imports survive the 0.61 → 0.97 upgrade
# ---------------------------------------------------------------------------

def test_anthropic_imports_097():
    """Verify critical SDK imports survive the 0.61 → 0.97 upgrade.

    The ai-parrot codebase depends on these specific names being importable
    from the published ``anthropic`` package; a regression here would surface
    as ``ImportError`` at module load time of ``parrot.clients.claude``.
    """
    from anthropic import (  # noqa: F401
        APIStatusError,
        AsyncAnthropic,
        RateLimitError,
    )
    from anthropic.types import Message, MessageStreamEvent  # noqa: F401

    assert AsyncAnthropic is not None
    assert RateLimitError is not None
    assert APIStatusError is not None
    assert Message is not None
    assert MessageStreamEvent is not None


def test_anthropic_version_at_least_097():
    """Sanity check — the installed SDK is on the new pin range."""
    import anthropic

    parts = anthropic.__version__.split(".")
    major, minor = int(parts[0]), int(parts[1])
    assert (major, minor) >= (0, 97), (
        f"anthropic SDK is {anthropic.__version__}, expected >=0.97.0"
    )


# ---------------------------------------------------------------------------
# Test 2 — ``_is_capacity_error`` still detects modern SDK exception shapes
# ---------------------------------------------------------------------------

class TestCapacityErrorDetection097:
    """Re-verify capacity-error classification under SDK 0.97."""

    def test_rate_limit_error_detected(self):
        client = _make_anthropic_client()
        assert client._is_capacity_error(_make_rate_limit_error()) is True

    def test_api_status_error_429_detected(self):
        client = _make_anthropic_client()
        assert client._is_capacity_error(_make_api_status_error(429)) is True

    def test_api_status_error_503_detected(self):
        client = _make_anthropic_client()
        assert client._is_capacity_error(_make_api_status_error(503)) is True

    def test_api_status_error_529_detected(self):
        client = _make_anthropic_client()
        assert client._is_capacity_error(_make_api_status_error(529)) is True

    def test_non_capacity_error_400_rejected(self):
        client = _make_anthropic_client()
        assert client._is_capacity_error(_make_api_status_error(400)) is False


# ---------------------------------------------------------------------------
# Test 3 — ``betas=["context-1m-2025-08-07"]`` is forwarded to messages.create
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_anthropic_betas_param_passthrough():
    """`context_1m=True` should add ``betas=['context-1m-2025-08-07']`` to
    the kwargs sent to ``client.messages.create``.

    The test is fully mocked so it neither talks to the network nor depends on
    a configured ANTHROPIC_API_KEY.
    """
    from parrot.clients.claude import AnthropicClient

    # Mock the response object the SDK returns.
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="ok", type="text")]
    mock_response.stop_reason = "end_turn"
    mock_response.usage = MagicMock(input_tokens=1, output_tokens=1)
    mock_response.model = "claude-sonnet-4-5"
    mock_response.id = "msg_123"

    fake_async_client = MagicMock()
    fake_async_client.messages = MagicMock()
    fake_async_client.messages.create = AsyncMock(return_value=mock_response)

    # Build a real AnthropicClient but inject the fake SDK client via the
    # base class' per-loop cache.
    client = AnthropicClient(api_key="test-key")

    with patch.object(
        AnthropicClient, "get_client", new=AsyncMock(return_value=fake_async_client)
    ):
        try:
            await client.ask(
                "Hello, world!",
                model="claude-sonnet-4-5",
                context_1m=True,
            )
        except Exception:
            # We don't care if downstream parsing later barfs — we only want to
            # assert that the SDK call carried the betas header.
            pass

    assert fake_async_client.messages.create.await_count >= 1
    call_kwargs = fake_async_client.messages.create.await_args.kwargs
    assert "betas" in call_kwargs, (
        "context_1m=True must forward `betas` to messages.create; "
        f"observed kwargs: {sorted(call_kwargs)}"
    )
    assert call_kwargs["betas"] == ["context-1m-2025-08-07"]


@pytest.mark.asyncio
async def test_anthropic_betas_param_omitted_by_default():
    """Without ``context_1m=True`` the betas header must NOT be forwarded."""
    from parrot.clients.claude import AnthropicClient

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="ok", type="text")]
    mock_response.stop_reason = "end_turn"
    mock_response.usage = MagicMock(input_tokens=1, output_tokens=1)
    mock_response.model = "claude-sonnet-4-5"
    mock_response.id = "msg_123"

    fake_async_client = MagicMock()
    fake_async_client.messages = MagicMock()
    fake_async_client.messages.create = AsyncMock(return_value=mock_response)

    client = AnthropicClient(api_key="test-key")

    with patch.object(
        AnthropicClient, "get_client", new=AsyncMock(return_value=fake_async_client)
    ):
        try:
            await client.ask(
                "Hello, world!",
                model="claude-sonnet-4-5",
            )
        except Exception:
            pass

    assert fake_async_client.messages.create.await_count >= 1
    call_kwargs = fake_async_client.messages.create.await_args.kwargs
    assert "betas" not in call_kwargs, (
        "betas should not be present unless context_1m=True; "
        f"observed kwargs: {sorted(call_kwargs)}"
    )


# ---------------------------------------------------------------------------
# Test 4 — Live smoke test (skipped without ANTHROPIC_API_KEY)
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.asyncio
async def test_anthropic_live_smoke():
    """End-to-end smoke test against the real Anthropic API on SDK 0.97.

    Skipped when ``ANTHROPIC_API_KEY`` is not set so the suite remains green
    in environments without a key (CI defaults, contributor laptops).
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set; live test skipped.")

    from parrot.clients.claude import AnthropicClient

    client = AnthropicClient()
    result = await client.ask("ping")
    assert result is not None
    assert getattr(result, "output", None), (
        "Live AnthropicClient.ask did not produce an output."
    )
