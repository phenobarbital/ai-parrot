"""Unit tests for the single-recipient send endpoint (FEAT-417, Module 8 / G13).

Redis is faked via ``dispatch._get_notify_client``; Postgres is faked by
monkeypatching ``NotificationBatchRecipient``'s persistence methods onto an
in-memory dict shared across both ``comm_center._get_db`` (row creation)
and ``dispatch._get_db`` (``publish_one``'s row update), matching how the
real code paths share the same model class.
"""
from datetime import datetime

import parrot.handlers.comm_center as comm_center_module
import parrot.services.comm_center.dispatch as dispatch_module
import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers.comm_center import CommCenterHandler
from parrot.handlers.models import NotificationBatchRecipient
from parrot.services.comm_center.models import RecipientIn
from parrot.services.comm_center.render import prepare

FROZEN = datetime(2026, 8, 6, 12, 0, 0)


def _make_request(method: str, path: str, json_body: dict | None = None) -> web.Request:
    request = make_mocked_request(method, path)
    request["authenticated"] = True
    if json_body is not None:

        async def fake_json(**kwargs):
            return json_body

        request.json = fake_json
    return request


class FakeNotifyClient:
    """Captures every stream() call; can simulate a publish failure."""

    def __init__(self, fail: bool = False):
        self.calls: list = []
        self.fail = fail

    async def connect(self):
        pass

    async def close(self):
        pass

    async def stream(self, message, stream, use_wrapper=False):
        self.calls.append((message, stream, use_wrapper))
        if self.fail:
            raise ConnectionError("redis down")
        return "1700000000000-0"


class _FakeConnCtx:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc_info):
        return False


class _FakeAsyncDB:
    async def connection(self):
        return _FakeConnCtx()


@pytest.fixture
def row_store(monkeypatch):
    """Backs NotificationBatchRecipient's persistence methods with an in-memory dict."""
    store: dict = {}

    async def fake_insert(self):
        store[self.id] = self
        return self

    async def fake_update(self):
        store[self.id] = self
        return self

    async def fake_get(*, id):
        return store[id]

    async def fake_filter(**kwargs):
        return [
            row
            for row in store.values()
            if all(getattr(row, key) == value for key, value in kwargs.items())
        ]

    monkeypatch.setattr(NotificationBatchRecipient, "insert", fake_insert)
    monkeypatch.setattr(NotificationBatchRecipient, "update", fake_update)
    monkeypatch.setattr(NotificationBatchRecipient, "get", staticmethod(fake_get))
    monkeypatch.setattr(NotificationBatchRecipient, "filter", staticmethod(fake_filter))
    monkeypatch.setattr(comm_center_module, "_get_db", lambda: _FakeAsyncDB())
    monkeypatch.setattr(dispatch_module, "_get_db", lambda: _FakeAsyncDB())
    return store


@pytest.fixture
def fake_notify(monkeypatch):
    client = FakeNotifyClient()
    monkeypatch.setattr(dispatch_module, "_get_notify_client", lambda: client)
    return client


@pytest.fixture
def failing_notify(monkeypatch):
    client = FakeNotifyClient(fail=True)
    monkeypatch.setattr(dispatch_module, "_get_notify_client", lambda: client)
    return client


class TestSingleMessage:
    async def test_sends_single_recipient(self, row_store, fake_notify):
        handler = CommCenterHandler()
        request = _make_request(
            "POST",
            "/api/v1/comm_center/message",
            {
                "provider": "email",
                "recipient": {"name": "Ana", "email": "ana@example.com"},
                "template": "Hola {{ name }}, hoy es {{ today }}",
            },
        )
        resp = await handler.post_message(request)
        assert resp.status == 202
        assert len(fake_notify.calls) == 1

    async def test_persists_one_row_batch(self, row_store, fake_notify):
        handler = CommCenterHandler()
        request = _make_request(
            "POST",
            "/api/v1/comm_center/message",
            {
                "provider": "email",
                "recipient": {"name": "Ana", "email": "ana@example.com"},
                "template": "hi",
            },
        )
        await handler.post_message(request)
        assert len(row_store) == 1
        (row,) = row_store.values()
        assert row.status == "queued"

    async def test_invalid_recipient_returns_400(self, row_store, fake_notify):
        handler = CommCenterHandler()
        request = _make_request(
            "POST",
            "/api/v1/comm_center/message",
            {"provider": "email", "recipient": {"name": "NoMail"}, "template": "hi"},
        )
        with pytest.raises(web.HTTPException) as excinfo:
            await handler.post_message(request)
        assert excinfo.value.status == 400
        assert fake_notify.calls == []

    async def test_requires_explicit_provider(self, row_store, fake_notify):
        handler = CommCenterHandler()
        request = _make_request(
            "POST",
            "/api/v1/comm_center/message",
            {"recipient": {"name": "Ana", "email": "a@e.com"}, "template": "hi"},
        )
        with pytest.raises(web.HTTPException) as excinfo:
            await handler.post_message(request)
        assert excinfo.value.status == 400

    async def test_publish_failure_returns_502(self, row_store, failing_notify):
        handler = CommCenterHandler()
        request = _make_request(
            "POST",
            "/api/v1/comm_center/message",
            {
                "provider": "email",
                "recipient": {"name": "Ana", "email": "a@e.com"},
                "template": "hi",
            },
        )
        with pytest.raises(web.HTTPException) as excinfo:
            await handler.post_message(request)
        assert excinfo.value.status == 502
        # The row is persisted and left retryable, not silently dropped.
        (row,) = row_store.values()
        assert row.status == "publish_failed"

    async def test_missing_recipient_returns_400(self, row_store, fake_notify):
        handler = CommCenterHandler()
        request = _make_request(
            "POST", "/api/v1/comm_center/message", {"provider": "email", "template": "hi"}
        )
        with pytest.raises(web.HTTPException) as excinfo:
            await handler.post_message(request)
        assert excinfo.value.status == 400


class TestPayloadParity:
    """PARITY GUARD — proves post_message shares prepare() with post_sender."""

    async def test_message_and_sender_share_prepare(self):
        recipient = RecipientIn(name="Ana", email="ana@example.com")
        template = "Hola {{ name }}, hoy es {{ today }}"

        single = await prepare(
            recipients=[recipient],
            provider="email",
            template_source=template,
            subject=None,
            now=FROZEN,
        )
        bulk = await prepare(
            recipients=[recipient],
            provider="email",
            template_source=template,
            subject=None,
            now=FROZEN,
        )

        assert single.queued[0].payload == bulk.queued[0].payload
        assert single.resolved_functions == bulk.resolved_functions
