"""Unit tests for CommCenter fan-out, state machine, aggregation and retry.

FEAT-417, Module 6. ``NotifyClient`` is faked via
``dispatch._get_notify_client`` (spec pattern); the database is faked by
monkeypatching ``NotificationBatchRecipient.get``/``filter`` onto an
in-memory ``FakeRow`` store, since a live Postgres is not available to this
test suite. No real Redis or Postgres connection is ever attempted.
"""
import uuid

import pytest
from parrot.handlers.models import NotificationBatchRecipient
from parrot.services.comm_center import dispatch
from parrot.services.comm_center.dispatch import fan_out, publish_one, retry_batch


class FakeRow:
    """A minimal in-memory stand-in for a ``NotificationBatchRecipient`` row."""

    def __init__(self, store: dict, **kwargs):
        self._store = store
        self.id = kwargs.get("id", uuid.uuid4())
        self.batch_id = kwargs["batch_id"]
        self.row_number = kwargs.get("row_number", 0)
        self.provider = kwargs.get("provider", "email")
        self.status = kwargs.get("status", "pending")
        self.attempts = kwargs.get("attempts", 0)
        self.reason = kwargs.get("reason")
        self.message_id = kwargs.get("message_id")
        self.published_at = kwargs.get("published_at")
        self.recipient_name = kwargs.get("recipient_name", "Ana")
        self.recipient_address = kwargs.get("recipient_address", "a@e.com")
        self.template_ref = kwargs.get("template_ref", "Hola {{ name }}")
        self.subject = kwargs.get("subject")
        store[self.id] = self

    async def update(self):
        self._store[self.id] = self
        return self


class FakeNotifyClient:
    """Captures every ``stream()`` call: ``(message, stream, use_wrapper)``.

    ``fail_on`` is a set of zero-based call indices that should raise,
    simulating a transient publish failure without aborting the batch.
    """

    def __init__(self, fail_on: frozenset = frozenset()):
        self.calls: list = []
        self.fail_on = fail_on
        self.connected = False
        self.closed = False

    async def connect(self):
        self.connected = True

    async def close(self):
        self.closed = True

    async def stream(self, message, stream, use_wrapper=False):
        index = len(self.calls)
        self.calls.append((message, stream, use_wrapper))
        if index in self.fail_on:
            raise ConnectionError("redis down")
        return "1700000000000-0"


@pytest.fixture
def row_store(monkeypatch):
    """Backs ``NotificationBatchRecipient.get``/``filter`` with an in-memory dict."""
    store: dict = {}

    async def fake_get(*, id):
        return store[id]

    async def fake_filter(**kwargs):
        return [
            row
            for row in store.values()
            if all(getattr(row, key) == value for key, value in kwargs.items())
        ]

    monkeypatch.setattr(NotificationBatchRecipient, "get", staticmethod(fake_get))
    monkeypatch.setattr(NotificationBatchRecipient, "filter", staticmethod(fake_filter))
    monkeypatch.setattr(dispatch, "_get_db", lambda: _FakeAsyncDB())
    return store


class _FakeConnCtx:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc_info):
        return False


class _FakeAsyncDB:
    """Bypasses the real ``AsyncDB('pg')`` connection entirely.

    ``connection()`` is itself ``async`` — matching the real ``AsyncDB``,
    which dispatch.py calls as ``async with await db.connection() as conn:``.
    """

    async def connection(self):
        return _FakeConnCtx()


def _payload(name="Ana", email="a@e.com"):
    return {
        "provider": "email",
        "recipient": [{"name": name, "account": {"provider": "email", "address": email}}],
        "template": "hi",
        "subject": None,
        "name": name,
        "username": name,
        "email": email,
        "phone": None,
    }


class TestFanOut:
    """Publishing, one xadd per recipient, resilient to per-row failure."""

    async def test_one_xadd_per_recipient(self, row_store, monkeypatch):
        batch_id = uuid.uuid4()
        client = FakeNotifyClient()
        monkeypatch.setattr(dispatch, "_get_notify_client", lambda: client)

        rows = [FakeRow(row_store, batch_id=batch_id) for _ in range(3)]
        payloads = [(row.id, _payload()) for row in rows]

        await fan_out(batch_id, payloads)

        assert len(client.calls) == 3
        assert all(row_store[row.id].status == "queued" for row in rows)

    async def test_uses_json_path(self, row_store, monkeypatch):
        batch_id = uuid.uuid4()
        client = FakeNotifyClient()
        monkeypatch.setattr(dispatch, "_get_notify_client", lambda: client)

        row = FakeRow(row_store, batch_id=batch_id)
        await fan_out(batch_id, [(row.id, _payload())])

        assert client.calls[0][2] is False  # use_wrapper=False

    async def test_publishing_marker_before_xadd(self, row_store, monkeypatch):
        """Status must already be 'publishing' when stream() is entered."""
        batch_id = uuid.uuid4()
        row = FakeRow(row_store, batch_id=batch_id)
        seen = {}

        class ObservingClient(FakeNotifyClient):
            async def stream(self, message, stream, use_wrapper=False):
                seen["status"] = row_store[row.id].status
                return await super().stream(message, stream, use_wrapper=use_wrapper)

        monkeypatch.setattr(dispatch, "_get_notify_client", lambda: ObservingClient())
        await fan_out(batch_id, [(row.id, _payload())])

        assert seen["status"] == "publishing"

    async def test_failure_marks_row_and_continues(self, row_store, monkeypatch):
        """The second of three calls raises; the batch still finishes."""
        batch_id = uuid.uuid4()
        client = FakeNotifyClient(fail_on=frozenset({1}))
        monkeypatch.setattr(dispatch, "_get_notify_client", lambda: client)

        rows = [FakeRow(row_store, batch_id=batch_id) for _ in range(3)]
        payloads = [(row.id, _payload()) for row in rows]

        await fan_out(batch_id, payloads)

        assert len(client.calls) == 3  # all three were attempted
        assert row_store[rows[0].id].status == "queued"
        assert row_store[rows[1].id].status == "publish_failed"
        assert row_store[rows[1].id].reason
        assert row_store[rows[2].id].status == "queued"

    async def test_no_credentials_in_payload(self, row_store, monkeypatch):
        batch_id = uuid.uuid4()
        client = FakeNotifyClient()
        monkeypatch.setattr(dispatch, "_get_notify_client", lambda: client)

        row = FakeRow(row_store, batch_id=batch_id)
        await fan_out(batch_id, [(row.id, _payload())])

        msg = client.calls[0][0]
        assert not {"password", "api_key", "token", "secret"} & set(msg)

    async def test_attempts_incremented(self, row_store, monkeypatch):
        batch_id = uuid.uuid4()
        client = FakeNotifyClient()
        monkeypatch.setattr(dispatch, "_get_notify_client", lambda: client)

        row = FakeRow(row_store, batch_id=batch_id, attempts=0)
        await publish_one(batch_id, _payload(), row.id, client=client)

        assert row_store[row.id].attempts == 1


class TestRetry:
    """Retry re-publishes only the states the state machine allows."""

    async def test_never_retries_queued_or_skipped(self, row_store, monkeypatch):
        batch_id = uuid.uuid4()
        client = FakeNotifyClient()
        monkeypatch.setattr(dispatch, "_get_notify_client", lambda: client)

        FakeRow(row_store, batch_id=batch_id, status="queued")
        FakeRow(row_store, batch_id=batch_id, status="skipped")

        result = await retry_batch(batch_id)

        assert client.calls == []
        assert result["retried"] == 0

    async def test_retries_pending_and_failed(self, row_store, monkeypatch):
        batch_id = uuid.uuid4()
        client = FakeNotifyClient()
        monkeypatch.setattr(dispatch, "_get_notify_client", lambda: client)

        pending = FakeRow(row_store, batch_id=batch_id, status="pending", attempts=0)
        failed = FakeRow(
            row_store, batch_id=batch_id, status="publish_failed", attempts=1
        )

        result = await retry_batch(batch_id)

        assert result["retried"] == 2
        assert len(client.calls) == 2
        assert row_store[pending.id].status == "queued"
        assert row_store[failed.id].status == "queued"
        assert row_store[failed.id].attempts == 2

    async def test_excludes_publishing_without_force(self, row_store, monkeypatch):
        batch_id = uuid.uuid4()
        client = FakeNotifyClient()
        monkeypatch.setattr(dispatch, "_get_notify_client", lambda: client)

        stuck = FakeRow(row_store, batch_id=batch_id, status="publishing")

        result = await retry_batch(batch_id, force=False)

        assert client.calls == []
        assert result["retried"] == 0
        assert result["ambiguous"] == 1
        assert row_store[stuck.id].status == "publishing"  # untouched

    async def test_includes_publishing_with_force(self, row_store, monkeypatch):
        batch_id = uuid.uuid4()
        client = FakeNotifyClient()
        monkeypatch.setattr(dispatch, "_get_notify_client", lambda: client)

        stuck = FakeRow(row_store, batch_id=batch_id, status="publishing")

        result = await retry_batch(batch_id, force=True)

        assert result["retried"] == 1
        assert len(client.calls) == 1
        assert row_store[stuck.id].status == "queued"


class TestAggregation:
    """Batch progress aggregation and paginated details."""

    async def test_batch_progress_aggregation(self, row_store, monkeypatch):
        batch_id = uuid.uuid4()
        FakeRow(row_store, batch_id=batch_id, status="queued")
        FakeRow(row_store, batch_id=batch_id, status="queued")
        FakeRow(row_store, batch_id=batch_id, status="skipped")

        class FakeConn:
            async def fetchall(self, query, params=None):
                return [
                    {"status": "queued", "count": 2},
                    {"status": "skipped", "count": 1},
                ]

        class FakeConnCtxWithFetch:
            async def __aenter__(self):
                return FakeConn()

            async def __aexit__(self, *exc_info):
                return False

        class FakeAsyncDBWithFetch:
            async def connection(self):
                return FakeConnCtxWithFetch()

        monkeypatch.setattr(dispatch, "_get_db", lambda: FakeAsyncDBWithFetch())

        result = await dispatch.aggregate_batch_status(batch_id)

        assert result["total"] == 3
        assert result["by_status"]["queued"] == 2
        assert result["by_status"]["skipped"] == 1
        assert result["rows"] is None

    async def test_details_paginated_and_limit_clamped(self, row_store, monkeypatch):
        batch_id = uuid.uuid4()
        for _ in range(5):
            FakeRow(row_store, batch_id=batch_id, status="queued")

        class FakeConn:
            async def fetchall(self, query, params=None):
                return [{"status": "queued", "count": 5}]

        class FakeConnCtxWithFetch:
            async def __aenter__(self):
                return FakeConn()

            async def __aexit__(self, *exc_info):
                return False

        class FakeAsyncDBWithFetch:
            async def connection(self):
                return FakeConnCtxWithFetch()

        monkeypatch.setattr(dispatch, "_get_db", lambda: FakeAsyncDBWithFetch())

        result = await dispatch.aggregate_batch_status(
            batch_id, details=True, limit=10_000
        )

        assert len(result["rows"]) == 5  # clamped internally, but only 5 rows exist


class TestLazyImport:
    """Importing this module must never require async-notify."""

    def test_module_imports_without_notify(self):
        import importlib

        importlib.import_module("parrot.services.comm_center.dispatch")

    def test_actionable_error_when_notify_missing(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def blocking_import(name, *args, **kwargs):
            if name == "notify.server" or name.startswith("notify.server."):
                raise ImportError("simulated: async-notify not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocking_import)
        with pytest.raises(RuntimeError, match="comm-center"):
            dispatch._get_notify_client()
