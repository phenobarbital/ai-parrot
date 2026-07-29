"""Unit tests for WebhookSubscriber.

FEAT-176 — Lifecycle Events System (TASK-1192).

Tests use an in-process aiohttp stub server (via pytest-aiohttp) to verify
POST body, HMAC signature, retry on 5xx, and give-up on 4xx.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import pytest
from aiohttp import web

from parrot.core.events.lifecycle.events import AfterInvokeEvent
from navigator_eventbus.lifecycle.provider import EventProvider
from navigator_eventbus.lifecycle.registry import EventRegistry
from navigator_eventbus.lifecycle.subscribers.webhook import WebhookSubscriber
from navigator_eventbus.lifecycle.trace import TraceContext


# ---------------------------------------------------------------------------
# Stub server fixture
# ---------------------------------------------------------------------------

@pytest.fixture
async def stub_server(aiohttp_server: pytest.FixtureRequest):
    """In-process aiohttp server that records every POST and returns 200."""
    received: list[dict] = []

    async def handler(request: web.Request) -> web.Response:
        body = await request.read()
        received.append({
            "body": body,
            "signature": request.headers.get("X-Parrot-Signature"),
        })
        return web.Response(status=200)

    app = web.Application()
    app.router.add_post("/hook", handler)
    server = await aiohttp_server(app)
    yield server, received


@pytest.fixture
async def retry_server(aiohttp_server: pytest.FixtureRequest):
    """Server that returns 500 twice then 200, recording request count."""
    call_count: list[int] = [0]

    async def handler(request: web.Request) -> web.Response:
        call_count[0] += 1
        if call_count[0] < 3:
            return web.Response(status=500)
        return web.Response(status=200)

    app = web.Application()
    app.router.add_post("/hook", handler)
    server = await aiohttp_server(app)
    yield server, call_count


@pytest.fixture
async def server_404(aiohttp_server: pytest.FixtureRequest):
    """Server that always returns 404 — should not be retried."""
    call_count: list[int] = [0]

    async def handler(request: web.Request) -> web.Response:
        call_count[0] += 1
        return web.Response(status=404)

    app = web.Application()
    app.router.add_post("/hook", handler)
    server = await aiohttp_server(app)
    yield server, call_count


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestWebhookSubscriber:
    def test_protocol_conformance(self) -> None:
        """WebhookSubscriber conforms to EventProvider."""
        assert isinstance(WebhookSubscriber(url="http://example.com"), EventProvider)

    @pytest.mark.asyncio
    async def test_posts_event_body(self, stub_server: tuple) -> None:
        """POST body matches json.dumps(event.to_dict())."""
        server, received = stub_server
        sub = WebhookSubscriber(url=str(server.make_url("/hook")))
        reg = EventRegistry(forward_to_global=False)
        reg.add_provider(sub)
        await reg.emit(AfterInvokeEvent(trace_context=TraceContext.new_root()))
        await sub.aclose()
        assert len(received) == 1
        payload = json.loads(received[0]["body"])
        assert payload["event_class"] == "AfterInvokeEvent"

    @pytest.mark.asyncio
    async def test_hmac_signature(self, stub_server: tuple) -> None:
        """When secret is set, X-Parrot-Signature is sha256=<hmac> of the body."""
        server, received = stub_server
        secret = "topsecret"
        sub = WebhookSubscriber(url=str(server.make_url("/hook")), secret=secret)
        reg = EventRegistry(forward_to_global=False)
        reg.add_provider(sub)
        await reg.emit(AfterInvokeEvent(trace_context=TraceContext.new_root()))
        await sub.aclose()
        body = received[0]["body"]
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert received[0]["signature"] == expected

    @pytest.mark.asyncio
    async def test_no_signature_without_secret(self, stub_server: tuple) -> None:
        """Without a secret, X-Parrot-Signature header is absent."""
        server, received = stub_server
        sub = WebhookSubscriber(url=str(server.make_url("/hook")))
        reg = EventRegistry(forward_to_global=False)
        reg.add_provider(sub)
        await reg.emit(AfterInvokeEvent(trace_context=TraceContext.new_root()))
        await sub.aclose()
        assert received[0]["signature"] is None

    @pytest.mark.asyncio
    async def test_retry_on_5xx(self, retry_server: tuple) -> None:
        """POST is retried on 5xx until success within max_attempts."""
        server, call_count = retry_server
        sub = WebhookSubscriber(
            url=str(server.make_url("/hook")),
            max_attempts=3,
            timeout_seconds=2.0,
        )
        reg = EventRegistry(forward_to_global=False)
        reg.add_provider(sub)

        # Patch asyncio.sleep to speed up the test (don't actually wait).
        import unittest.mock
        with unittest.mock.patch("navigator_eventbus.lifecycle.subscribers.webhook.asyncio.sleep"):
            await reg.emit(AfterInvokeEvent(trace_context=TraceContext.new_root()))

        await sub.aclose()
        # 2 failures + 1 success = 3 attempts total
        assert call_count[0] == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_4xx(self, server_404: tuple) -> None:
        """4xx responses are NOT retried — exactly one attempt."""
        server, call_count = server_404
        sub = WebhookSubscriber(
            url=str(server.make_url("/hook")),
            max_attempts=3,
        )
        reg = EventRegistry(forward_to_global=False)
        reg.add_provider(sub)
        await reg.emit(AfterInvokeEvent(trace_context=TraceContext.new_root()))
        await sub.aclose()
        assert call_count[0] == 1

    @pytest.mark.asyncio
    async def test_aclose_closes_session(self) -> None:
        """aclose() closes the underlying aiohttp.ClientSession."""
        sub = WebhookSubscriber(url="http://127.0.0.1:9999/never")
        # Force session creation.
        await sub._ensure_session()
        assert sub._session is not None
        assert not sub._session.closed
        await sub.aclose()
        assert sub._session.closed

    @pytest.mark.asyncio
    async def test_event_classes_filter(self, stub_server: tuple) -> None:
        """event_classes restricts which events trigger a POST."""
        from parrot.core.events.lifecycle.events import BeforeInvokeEvent
        server, received = stub_server
        # Only subscribe to BeforeInvokeEvent.
        sub = WebhookSubscriber(
            url=str(server.make_url("/hook")),
            event_classes=[BeforeInvokeEvent],
        )
        reg = EventRegistry(forward_to_global=False)
        reg.add_provider(sub)
        trace = TraceContext.new_root()
        await reg.emit(AfterInvokeEvent(trace_context=trace))   # should NOT POST
        await reg.emit(BeforeInvokeEvent(trace_context=trace))  # should POST
        await sub.aclose()
        assert len(received) == 1
        payload = json.loads(received[0]["body"])
        assert payload["event_class"] == "BeforeInvokeEvent"
