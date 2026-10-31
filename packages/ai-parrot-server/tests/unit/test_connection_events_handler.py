"""Tests for the connection-events SSE handler and its wiring (FEAT-777 M1)."""

from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from collections.abc import AsyncIterator

import pytest
from aiohttp import web

from parrot.auth.oauth2.events import ConnectionEvent
from parrot.handlers.connection_events import ConnectionEventsHandler
from parrot.manager.manager import BotManager
from parrot.services.connection_push import CHANNEL_TEMPLATE, RedisConnectionPush

REDIS_TEST_URL = "redis://localhost:6379/15"


def _unwrap(method):
    """Remove authentication decorators for isolated handler tests."""
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


def _event(user_id: str) -> ConnectionEvent:
    """Build a connection event for one principal."""
    return ConnectionEvent(
        kind="connection.completed",
        user_id=user_id,
        provider="jira",
        channel="web",
        occurred_at=time.time(),
    )


async def _dispatch(request: web.Request) -> web.StreamResponse:
    """Invoke the undecorated handler through an aiohttp test route."""
    handler = ConnectionEventsHandler.__new__(ConnectionEventsHandler)
    handler._request = request
    return await _unwrap(ConnectionEventsHandler.get)(handler)


class _SingleEventPush:
    """Push double that records the subscribed principal and then ends."""

    def __init__(self) -> None:
        self.user_ids: list[str] = []

    async def subscribe(self, user_id: str) -> AsyncIterator[ConnectionEvent]:
        """Yield one event for the requested principal."""
        self.user_ids.append(user_id)
        yield _event(user_id)


@pytest.mark.asyncio
async def test_sse_handler_requires_session_and_ignores_query_user(
    aiohttp_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A query user cannot authenticate or replace the request-managed principal."""
    class _Request(dict):
        def __init__(self, *, user_id: str | None, push: object | None = None) -> None:
            super().__init__()
            if user_id is not None:
                self["user_id"] = user_id
            self.app = {} if push is None else {"connection_push": push}
            self.query = {"user_id": "attacker"}

    unauthenticated_handler = ConnectionEventsHandler.__new__(ConnectionEventsHandler)
    unauthenticated_handler._request = _Request(user_id=None)
    denied = await _unwrap(ConnectionEventsHandler.get)(unauthenticated_handler)

    assert denied.status == 401

    unavailable_handler = ConnectionEventsHandler.__new__(ConnectionEventsHandler)
    unavailable_handler._request = _Request(user_id="session-user")
    unavailable = await _unwrap(ConnectionEventsHandler.get)(unavailable_handler)

    assert unavailable.status == 503

    push = _SingleEventPush()

    class _Response:
        def __init__(self, *, status: int, headers: dict[str, str]) -> None:
            self.status = status
            self.headers = headers
            self.frames: list[bytes] = []

        async def prepare(self, request: object) -> None:
            return None

        async def write(self, data: bytes) -> None:
            self.frames.append(data)

    monkeypatch.setattr("parrot.handlers.connection_events.web.StreamResponse", _Response)
    authenticated_handler = ConnectionEventsHandler.__new__(ConnectionEventsHandler)
    authenticated_handler._request = _Request(user_id="session-user", push=push)
    response = await _unwrap(ConnectionEventsHandler.get)(authenticated_handler)
    body = b"".join(response.frames).decode()

    assert response.status == 200
    assert push.user_ids == ["session-user"]
    assert '"user_id":"session-user"' in body
    assert "attacker" not in body


@pytest.mark.asyncio
async def test_sse_frames_and_keepalive(monkeypatch: pytest.MonkeyPatch) -> None:
    """The handler writes keep-alives and frames, then unsubscribes on disconnect."""
    unsubscribed = asyncio.Event()
    event = _event("session-user")

    class _Push:
        async def subscribe(self, user_id: str) -> AsyncIterator[ConnectionEvent]:
            assert user_id == "session-user"
            try:
                await asyncio.sleep(0.02)
                yield event
                await asyncio.Event().wait()
            finally:
                unsubscribed.set()

    class _Response:
        def __init__(self, *, status: int, headers: dict[str, str]) -> None:
            self.status = status
            self.headers = headers
            self.frames: list[bytes] = []

        async def prepare(self, request: object) -> None:
            return None

        async def write(self, data: bytes) -> None:
            self.frames.append(data)
            if data.startswith(b"event: connection"):
                raise ConnectionResetError

    class _Request(dict):
        def __init__(self) -> None:
            super().__init__(user_id="session-user")
            self.app = {"connection_push": _Push()}

    monkeypatch.setattr("parrot.handlers.connection_events.KEEPALIVE_SECONDS", 0.005)
    monkeypatch.setattr("parrot.handlers.connection_events.web.StreamResponse", _Response)
    handler = ConnectionEventsHandler.__new__(ConnectionEventsHandler)
    handler._request = _Request()

    response = await _unwrap(ConnectionEventsHandler.get)(handler)

    assert response.headers["Content-Type"] == "text/event-stream"
    assert "Access-Control-Allow-Origin" not in response.headers
    assert b": keep-alive\n\n" in response.frames
    assert f"event: connection\ndata: {event.model_dump_json()}\n\n".encode() in response.frames
    assert unsubscribed.is_set()


async def _wait_for_numsub(push: RedisConnectionPush, channel: str, expected: int) -> None:
    """Wait until Redis reports the expected subscriber count."""
    deadline = asyncio.get_running_loop().time() + 2
    while True:
        subscriptions = await push._redis.pubsub_numsub(channel)
        if subscriptions[0][1] == expected:
            return
        if asyncio.get_running_loop().time() >= deadline:
            pytest.fail(f"Expected {expected} subscribers on {channel}, got {subscriptions!r}")
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_sse_cross_worker_delivery(aiohttp_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """A push from one Redis client reaches another client's principal-scoped SSE stream."""
    publisher_push = RedisConnectionPush(REDIS_TEST_URL)
    subscriber_push = RedisConnectionPush(REDIS_TEST_URL)
    await publisher_push.start()
    await subscriber_push.start()
    try:
        await publisher_push._redis.ping()
    except Exception as exc:  # noqa: BLE001
        await publisher_push.close()
        await subscriber_push.close()
        pytest.skip(f"Redis unreachable: {exc}")

    user_id = f"connection-events-{uuid.uuid4()}"
    other_user_id = f"connection-events-{uuid.uuid4()}"
    target_channel = CHANNEL_TEMPLATE.format(user_id=user_id)
    other_channel = CHANNEL_TEMPLATE.format(user_id=other_user_id)
    other_subscription = subscriber_push.subscribe(other_user_id)
    other_receive = asyncio.create_task(anext(other_subscription))

    async def _session_dispatch(request: web.Request) -> web.StreamResponse:
        request["user_id"] = user_id
        return await _dispatch(request)

    monkeypatch.setattr("parrot.handlers.connection_events.KEEPALIVE_SECONDS", 0.01)
    app = web.Application()
    app["connection_push"] = subscriber_push
    app.router.add_get("/events", _session_dispatch)
    client = await aiohttp_client(app)
    response = await client.get("/events")

    try:
        await _wait_for_numsub(subscriber_push, target_channel, 1)
        await _wait_for_numsub(subscriber_push, other_channel, 1)
        event = _event(user_id)
        await publisher_push.deliver(event)

        frame = await asyncio.wait_for(response.content.readuntil(b"\n\n"), timeout=2)
        while frame.startswith(b": keep-alive"):
            frame = await asyncio.wait_for(response.content.readuntil(b"\n\n"), timeout=2)

        assert frame == f"event: connection\ndata: {event.model_dump_json()}\n\n".encode()
        assert not other_receive.done()
    finally:
        response.close()
        other_receive.cancel()
        with pytest.raises(asyncio.CancelledError):
            await other_receive
        await other_subscription.aclose()
        await publisher_push.close()
        await subscriber_push.close()


def test_events_route_precedes_provider_route() -> None:
    """The concrete manager registers the literal events route before the provider route."""
    source = inspect.getsource(BotManager.setup)
    events_route = 'router.add_view("/api/v1/connections/events", ConnectionEventsHandler)'
    provider_route = 'router.add_view("/api/v1/connections/{provider}", ConnectionsHandler)'

    assert source.index(events_route) < source.index(provider_route)
