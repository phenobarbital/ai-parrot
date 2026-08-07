"""Unit tests for dry-run mode on both send endpoints (FEAT-417, Module 9 / G14).

Redis is faked via ``dispatch._get_notify_client``; Postgres is faked by
monkeypatching ``NotificationBatchRecipient``'s persistence methods onto an
in-memory dict, shared across ``comm_center._get_db`` and
``dispatch._get_db``. A dry run must never touch either fake — that is
exactly what these tests assert.
"""

import asyncio
import json

import parrot.handlers.comm_center as comm_center_module
import parrot.services.comm_center.dispatch as dispatch_module
import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers.comm_center import CommCenterHandler
from parrot.handlers.models import NotificationBatchRecipient
from parrot.services.comm_center.dispatch import fan_out
from parrot.services.comm_center.models import RecipientIn
from parrot.services.comm_center.render import build_preview, prepare


def _make_request(method: str, path: str, json_body: dict | None = None) -> web.Request:
    # ``post_sender`` dispatches on `request.content_type` (JSON vs.
    # multipart) -- make_mocked_request defaults to
    # "application/octet-stream", which _ingest_from_request correctly
    # rejects as unsupported. Set it explicitly for a JSON-body request.
    headers = {"Content-Type": "application/json"} if json_body is not None else None
    request = make_mocked_request(method, path, headers=headers)
    request["authenticated"] = True
    if json_body is not None:

        async def fake_json(**kwargs):
            return json_body

        request.json = fake_json
    return request


class FakeNotifyClient:
    """A NotifyClient that must never be called during a dry run."""

    def __init__(self):
        self.calls: list = []
        self.connect_called = False

    async def connect(self):
        self.connect_called = True

    async def close(self):
        pass

    async def stream(self, message, stream, use_wrapper=False):
        self.calls.append((message, stream, use_wrapper))
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


class TestDryRunBulk:
    async def test_publishes_nothing(self, row_store, fake_notify):
        handler = CommCenterHandler()
        request = _make_request(
            "POST",
            "/api/v1/comm_center/sender",
            {
                "provider": "email",
                "dry_run": True,
                "recipients": [{"name": "Ana", "email": "ana@example.com"}],
                "template": "Hola {{ name }}, hoy es {{ today }}",
            },
        )
        resp = await handler.post_sender(request)
        assert resp.status == 200
        assert fake_notify.calls == []
        assert fake_notify.connect_called is False

    async def test_writes_no_tracking_rows(self, row_store, fake_notify):
        handler = CommCenterHandler()
        request = _make_request(
            "POST",
            "/api/v1/comm_center/sender",
            {
                "provider": "email",
                "dry_run": True,
                "recipients": [{"name": "Ana", "email": "ana@example.com"}],
                "template": "hi",
            },
        )
        await handler.post_sender(request)
        assert len(row_store) == 0

    async def test_returns_preview_and_validation(self, row_store, fake_notify):
        handler = CommCenterHandler()
        request = _make_request(
            "POST",
            "/api/v1/comm_center/sender",
            {
                "provider": "email",
                "dry_run": True,
                "recipients": [
                    {"name": "Ana", "email": "a@e.com"},
                    {"name": "NoMail"},
                ],
                "template": "Hola {{ name }}, hoy es {{ today }}",
            },
        )
        resp = await handler.post_sender(request)
        assert resp.status == 200

        payload = json.loads(resp.body)
        assert payload["status"] == "dry_run"
        assert payload["batch_id"] is None
        assert "Ana" in payload["preview"]
        assert "{{" not in payload["preview"]
        assert len(payload["skipped_details"]) == 1

    async def test_preview_none_when_nothing_queued(self, row_store, fake_notify):
        handler = CommCenterHandler()
        request = _make_request(
            "POST",
            "/api/v1/comm_center/sender",
            {
                "provider": "email",
                "dry_run": True,
                "recipients": [{"name": "NoMail"}],
                "template": "hi",
            },
        )
        resp = await handler.post_sender(request)

        payload = json.loads(resp.body)
        assert payload["preview"] is None


class TestDryRunSingle:
    async def test_message_endpoint_dry_run(self, row_store, fake_notify):
        handler = CommCenterHandler()
        request = _make_request(
            "POST",
            "/api/v1/comm_center/message",
            {
                "provider": "email",
                "dry_run": True,
                "recipient": {"name": "Ana", "email": "a@e.com"},
                "template": "Hola {{ name }}",
            },
        )
        resp = await handler.post_message(request)
        assert resp.status == 200

        payload = json.loads(resp.body)
        assert payload["batch_id"] is None and payload["message_id"] is None
        assert payload["status"] == "dry_run"
        assert fake_notify.calls == []
        assert len(row_store) == 0


class TestEnforcement:
    """Guard is not handler-only (spec §5)."""

    async def test_service_layer_refuses_to_publish(self):
        recipient = RecipientIn(name="Ana", email="a@e.com")
        prepared = await prepare(
            recipients=[recipient],
            provider="email",
            template_source="hi",
            subject=None,
            dry_run=True,
        )
        with pytest.raises(RuntimeError, match="dry-run"):
            await fan_out(None, prepared)

    async def test_no_redis_connection_opened(self, row_store, fake_notify):
        handler = CommCenterHandler()
        request = _make_request(
            "POST",
            "/api/v1/comm_center/message",
            {
                "provider": "email",
                "dry_run": True,
                "recipient": {"name": "Ana", "email": "a@e.com"},
                "template": "hi",
            },
        )
        await handler.post_message(request)
        assert fake_notify.connect_called is False


class TestFidelity:
    """The preview must be trustworthy (spec §5 preview-fidelity criterion)."""

    async def test_dry_run_then_real_send_same_payload(self, row_store, fake_notify):
        recipient_body = {"name": "Ana", "email": "ana@example.com"}
        template = "Hola {{ name }}, hoy es {{ today }}"

        handler = CommCenterHandler()
        dry_request = _make_request(
            "POST",
            "/api/v1/comm_center/sender",
            {
                "provider": "email",
                "dry_run": True,
                "recipients": [recipient_body],
                "template": template,
            },
        )
        dry_resp = await handler.post_sender(dry_request)

        dry_payload = json.loads(dry_resp.body)

        real_request = _make_request(
            "POST",
            "/api/v1/comm_center/sender",
            {"provider": "email", "recipients": [recipient_body], "template": template},
        )
        await handler.post_sender(real_request)
        # launch_fan_out() schedules fan_out() as a background asyncio.Task
        # -- post_sender() does not await it (spec: "the request does not
        # await it"). Yield control so the scheduled task actually runs
        # before asserting on what it published.

        await asyncio.sleep(0.05)

        assert len(fake_notify.calls) == 1
        published_message = fake_notify.calls[0][0]
        assert dry_payload["preview"] == build_preview(published_message)
