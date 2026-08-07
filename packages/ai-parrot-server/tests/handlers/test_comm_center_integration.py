"""Cross-module integration tests for CommCenter (FEAT-417, spec §4).

Exercises ingestion (Module 4) + render/validation (Module 5) + fan-out
(Module 6) + the handler (Module 7) together, end-to-end, through
``CommCenterHandler``'s own methods — the same call-through-the-handler
style used across this feature's unit suites, since a live aiohttp
``TestClient`` + real auth backend + real Postgres/Redis is not available
in this environment (see individual task Completion Notes for the
documented, pre-existing sandbox gaps). Redis is faked via
``dispatch._get_notify_client``; Postgres is faked by monkeypatching
``NotificationBatchRecipient``'s persistence methods onto an in-memory
dict — every assertion is made on the *exact* captured payloads, which is
how spec §5's sender criteria are verified without a live NotifyWorker.
"""
import asyncio
import json

import parrot.handlers.comm_center as comm_center_module
import parrot.services.comm_center.dispatch as dispatch_module
import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from notify.models import Actor
from notify.server.wrapper import NotifyWrapper
from parrot.handlers.comm_center import CommCenterHandler
from parrot.handlers.models import NotificationBatchRecipient
from parrot.services.comm_center.models import RecipientIn
from parrot.services.comm_center.render import build_preview, build_wire_payload


def _make_json_request(method: str, path: str, json_body: dict) -> web.Request:
    request = make_mocked_request(
        method, path, headers={"Content-Type": "application/json"}
    )
    request["authenticated"] = True

    async def fake_json(**kwargs):
        return json_body

    request.json = fake_json
    return request


def _make_multipart_request(
    method: str, path: str, file_entries: dict, form: dict | None = None
) -> web.Request:
    """A mocked request pre-wired for the multipart transport.

    ``file_entries`` mirrors ``BaseHandler.handle_upload``'s return shape:
    ``{field_name: [{"file_path": ..., "file_name": ..., "mime_type": ...}]}``.
    """
    request = make_mocked_request(
        method, path, headers={"Content-Type": "multipart/form-data; boundary=x"}
    )
    request["authenticated"] = True
    return request


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
    calls: list = []

    class _Client:
        async def connect(self):
            pass

        async def close(self):
            pass

        async def stream(self, message, stream, use_wrapper=False):
            calls.append((message, stream, use_wrapper))
            return "1700000000000-0"

    monkeypatch.setattr(dispatch_module, "_get_notify_client", lambda: _Client())
    return calls


async def _wait_for_background_fanout():
    """Yield control so a ``launch_fan_out``-scheduled task actually runs."""
    await asyncio.sleep(0.05)


class TestIntegration:
    async def test_end_to_end_json_recipients_mocked_worker(self, row_store, fake_notify):
        handler = CommCenterHandler()
        request = _make_json_request(
            "POST",
            "/api/v1/comm_center/sender",
            {
                "provider": "email",
                "recipients": [
                    {"name": "Ana", "email": "ana@example.com"},
                    {"name": "Luis", "email": "luis@example.com"},
                ],
                "template": "Hola {{ name }}, hoy es {{ today }}",
            },
        )
        resp = await handler.post_sender(request)
        assert resp.status == 202
        await _wait_for_background_fanout()

        assert len(fake_notify) == 2
        for message, stream, use_wrapper in fake_notify:
            assert use_wrapper is False
            assert "recipient" in message and "recipients" not in message
            assert isinstance(NotifyWrapper(**message).recipients[0], Actor)
            assert message["username"]  # never absent (Trap 1 guard)

    async def test_end_to_end_multipart_xlsx_mocked_worker(
        self, row_store, fake_notify, recipients_xlsx, monkeypatch
    ):
        handler = CommCenterHandler()

        async def fake_handle_upload(request=None, form_key=None, ext=".csv", preserve_filenames=True):
            return (
                {"file": [{"file_path": recipients_xlsx, "file_name": "recipients.xlsx"}]},
                {"provider": "email", "template": "Hola {{ name }}, hoy es {{ today }}"},
            )

        monkeypatch.setattr(handler, "handle_upload", fake_handle_upload)

        request = _make_multipart_request("POST", "/api/v1/comm_center/sender", {})
        resp = await handler.post_sender(request)
        assert resp.status == 202
        await _wait_for_background_fanout()

        assert len(fake_notify) == 2
        names = {msg["name"] for msg, _stream, _wrapper in fake_notify}
        assert names == {"Ana Gomez", "Luis Perez"}

    async def test_end_to_end_stored_template_partial_render(self, row_store, fake_notify):
        """The batch-level (pass 1) render resolves computed functions while
        record placeholders survive literally for the worker's second pass.

        (Template *lookup* by id/name is TASK-2160's DB-backed
        ``_resolve_template_source`` path; here we assert the render
        contract itself using the inline-template transport, which is the
        same code path once the body is resolved.)
        """
        handler = CommCenterHandler()
        request = _make_json_request(
            "POST",
            "/api/v1/comm_center/sender",
            {
                "provider": "email",
                "recipients": [{"name": "Ana", "email": "ana@example.com"}],
                "template": "Hola {{ name }}, hoy es {{ today }}",
            },
        )
        await handler.post_sender(request)
        await _wait_for_background_fanout()

        message = fake_notify[0][0]
        # {{today}} was resolved in pass 1 -- no longer a bare placeholder.
        assert "{{ today }}" not in message["template"] and "{{today}}" not in message["template"]
        # {{ name }} is a per-recipient field -- preserved literally in the
        # partially-rendered template for the worker's pass 2.
        assert "{{ name }}" in message["template"]
        # ...and forwarded separately as a top-level pass-2 render kwarg.
        assert message["name"] == "Ana"

    async def test_smoke_template_file_path_real_notify(self):
        """The TEMPLATE_DIR filename path — works on async-notify 1.5.5 today."""
        from notify.conf import TEMPLATE_DIR

        assert TEMPLATE_DIR.exists()
        candidates = [
            p for p in TEMPLATE_DIR.iterdir() if p.is_file() and p.suffix in (".html", ".txt")
        ]
        assert candidates, f"no usable template file found under {TEMPLATE_DIR}"
        template_file = candidates[0].name

        recipient = RecipientIn(name="Ana", email="ana@example.com")
        payload = build_wire_payload(recipient, "email", template_file, "Test subject")
        wrapper = NotifyWrapper(**payload)
        assert isinstance(wrapper.recipients[0], Actor)
        assert wrapper.recipients[0].account.address == "ana@example.com"

    async def test_mixed_valid_invalid_rows_partial_send(self, row_store, fake_notify):
        handler = CommCenterHandler()
        request = _make_json_request(
            "POST",
            "/api/v1/comm_center/sender",
            {
                "provider": "email",
                "recipients": [
                    {"name": "Ana", "email": "ana@example.com"},
                    {"name": "NoMail"},
                ],
                "template": "Hola {{ name }}",
            },
        )
        resp = await handler.post_sender(request)
        payload = json.loads(resp.body)
        assert payload["queued"] == 1
        assert payload["skipped"] == 1
        await _wait_for_background_fanout()
        assert len(fake_notify) == 1

    async def test_end_to_end_single_message_mocked_worker(self, row_store, fake_notify):
        handler = CommCenterHandler()
        request = _make_json_request(
            "POST",
            "/api/v1/comm_center/message",
            {
                "provider": "email",
                "recipient": {"name": "Ana", "email": "ana@example.com"},
                "template": "Hola {{ name }}",
            },
        )
        resp = await handler.post_message(request)
        assert resp.status == 202
        assert len(fake_notify) == 1
        message = fake_notify[0][0]
        wrapper = NotifyWrapper(**message)
        assert isinstance(wrapper.recipients[0], Actor)

    async def test_dry_run_then_real_send_produce_same_payload(self, row_store, fake_notify):
        """Preview fidelity, exercised end-to-end (spec §4 / §5)."""
        handler = CommCenterHandler()
        recipient_body = {"name": "Ana", "email": "ana@example.com"}
        template = "Hola {{ name }}, hoy es {{ today }}"

        dry_request = _make_json_request(
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

        real_request = _make_json_request(
            "POST",
            "/api/v1/comm_center/sender",
            {"provider": "email", "recipients": [recipient_body], "template": template},
        )
        await handler.post_sender(real_request)
        await _wait_for_background_fanout()

        assert len(fake_notify) == 1
        published = fake_notify[0][0]
        assert dry_payload["preview"] == build_preview(published)


class TestPackaging:
    def test_comm_center_extra_declared(self):
        import pathlib
        import tomllib

        # Anchored to this file, not the process CWD — see the same note in
        # test_comm_center_models.py.
        pyproject = tomllib.loads(
            (pathlib.Path(__file__).parents[2] / "pyproject.toml").read_text()
        )
        extras = pyproject["project"]["optional-dependencies"]
        assert "comm-center" in extras
        assert any("comm-center" in a for a in extras["all"])
        assert not any(
            "async-notify" in dep for dep in pyproject["project"]["dependencies"]
        )

    def test_handler_imports_without_async_notify(self, monkeypatch):
        """Importing parrot.handlers.comm_center must never require async-notify."""
        import builtins
        import importlib
        import sys

        real_import = builtins.__import__

        def blocking_import(name, *args, **kwargs):
            if name == "notify" or name.startswith("notify."):
                raise ImportError("simulated: async-notify not installed")
            return real_import(name, *args, **kwargs)

        for mod_name in list(sys.modules):
            if mod_name == "parrot.handlers.comm_center" or mod_name.startswith(
                "parrot.services.comm_center"
            ):
                monkeypatch.delitem(sys.modules, mod_name, raising=False)

        monkeypatch.setattr(builtins, "__import__", blocking_import)
        importlib.import_module("parrot.handlers.comm_center")
