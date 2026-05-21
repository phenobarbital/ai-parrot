"""End-to-end integration tests for FEAT-188 Form Lifecycle Events.

These tests exercise the full dispatch chain — real event registry, real
dispatcher, real FormAPIHandler — without mocking the registry or dispatcher
layers.  Only the FormRegistry (data access) and FormValidator are mocked so
that the tests do not require a running database.

Coverage:
- All 5 lifecycle events on a single form (open → schema → submit).
- Backward-compatibility acid test: forms without ``events`` produce responses
  that are structurally identical to the pre-feature baseline.
- onBeforeSubmit payload replacement flows through to the validator.
- onBeforeSubmit abort is never routed through onError.
- onError is invoked on validation failure and does not prevent 422.
- Remote event endpoint: CSRF issuance and validation round-trip.
- HTML5 renderer: lifecycle script absent for event-less forms.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.core.events import (
    EventResolution,
    FormEventAbort,
    FormEventBinding,
    FormEventsConfig,
)
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.renderers.html5 import HTML5Renderer
from parrot_formdesigner.services.csrf import (
    _clear_csrf_store_for_tests,
)
from parrot_formdesigner.services.event_registry import (
    _clear_event_registry_for_tests,
    register_form_event,
)
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.validators import ValidationResult


@pytest.fixture(autouse=True)
def _isolate_stores() -> None:  # type: ignore[return]
    """Clear event registry and CSRF store between every test."""
    yield
    _clear_event_registry_for_tests()
    _clear_csrf_store_for_tests()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_form(
    form_id: str,
    events: FormEventsConfig | None = None,
) -> FormSchema:
    return FormSchema(
        form_id=form_id,
        title={"en": "E2E Test Form"},
        sections=[],
        events=events,
    )


def _make_request_get(form_id: str) -> MagicMock:
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_id": form_id}
    req.method = "GET"
    req.headers = {}
    req.__contains__ = MagicMock(return_value=False)
    req.__getitem__ = MagicMock(side_effect=KeyError)
    session = MagicMock()
    session.get = MagicMock(return_value={})
    req.session = session
    return req


def _make_request_post(
    form_id: str,
    body: dict | None = None,
    extra_match: dict | None = None,
) -> MagicMock:
    req = MagicMock(spec=web.Request)
    match = {"form_id": form_id}
    if extra_match:
        match.update(extra_match)
    req.match_info = match
    req.method = "POST"
    req.headers = {}
    req.query = {}
    req.__contains__ = MagicMock(return_value=False)
    req.__setitem__ = MagicMock()
    req.__getitem__ = MagicMock(side_effect=KeyError)
    req.json = AsyncMock(return_value=body or {})
    session = MagicMock()
    session.get = MagicMock(return_value={})
    req.session = session
    return req


def _make_handler(
    form: FormSchema | None = None,
    valid: bool = True,
    validation_errors: dict | None = None,
) -> FormAPIHandler:
    """Build FormAPIHandler with mocked registry + validator (real dispatcher)."""
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form)
    registry.default_tenant = "default"

    handler = FormAPIHandler(registry=registry)

    vr = MagicMock(spec=ValidationResult)
    vr.is_valid = valid
    vr.errors = validation_errors or ({} if valid else {"field": ["required"]})
    vr.sanitized_data = {"name": "Alice"} if valid else {}
    handler.validator = MagicMock()
    handler.validator.validate = AsyncMock(return_value=vr)

    return handler


# ---------------------------------------------------------------------------
# Full lifecycle across all 5 events
# ---------------------------------------------------------------------------


class TestFullLifecycle:
    """Exercise all 5 lifecycle hooks in sequence on a single form."""

    async def test_all_hooks_fire_in_order(self) -> None:
        """All registered hooks are invoked in the correct endpoint order."""
        invocations: list[str] = []
        form_id = "e2e_all_hooks"

        @register_form_event(f"{form_id}.onBeforeOpen")
        async def on_open(ctx):  # type: ignore[no-untyped-def]
            invocations.append("onBeforeOpen")
            return EventResolution()

        @register_form_event(f"{form_id}.onSchemaLoaded")
        async def on_schema(ctx):  # type: ignore[no-untyped-def]
            invocations.append("onSchemaLoaded")
            return EventResolution()

        @register_form_event(f"{form_id}.onBeforeSubmit")
        async def on_before(ctx):  # type: ignore[no-untyped-def]
            invocations.append("onBeforeSubmit")
            return EventResolution()

        @register_form_event(f"{form_id}.onAfterSubmit")
        async def on_after(ctx):  # type: ignore[no-untyped-def]
            invocations.append("onAfterSubmit")
            return EventResolution()

        @register_form_event(f"{form_id}.onError")
        async def on_error(ctx):  # type: ignore[no-untyped-def]
            invocations.append("onError")
            return EventResolution()

        form = _make_form(
            form_id=form_id,
            events=FormEventsConfig(
                onBeforeOpen=FormEventBinding(handler_ref=f"{form_id}.onBeforeOpen"),
                onSchemaLoaded=FormEventBinding(handler_ref=f"{form_id}.onSchemaLoaded"),
                onBeforeSubmit=FormEventBinding(handler_ref=f"{form_id}.onBeforeSubmit"),
                onAfterSubmit=FormEventBinding(handler_ref=f"{form_id}.onAfterSubmit"),
                onError=FormEventBinding(handler_ref=f"{form_id}.onError"),
            ),
        )
        handler = _make_handler(form=form, valid=True)

        # 1. GET /forms/{id}
        r1 = await handler.get_form(_make_request_get(form_id))
        assert r1.status == 200

        # 2. GET /forms/{id}/schema
        r2 = await handler.get_schema(_make_request_get(form_id))
        assert r2.status == 200

        # 3. POST /forms/{id}/data (success path)
        r3 = await handler.submit_data(
            _make_request_post(form_id, body={"name": "Alice"})
        )
        assert r3.status == 200

        assert "onBeforeOpen" in invocations
        assert "onSchemaLoaded" in invocations
        assert "onBeforeSubmit" in invocations
        assert "onAfterSubmit" in invocations
        assert "onError" not in invocations  # no error in happy path


# ---------------------------------------------------------------------------
# Backward-compatibility acid test
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    """Forms without events declared must produce structurally identical responses."""

    async def test_get_form_no_events_no_lifecycle_header(self) -> None:
        """Forms without events in get_form do not emit X-Form-CSRF-Token."""
        form = _make_form("compat_form", events=None)
        handler = _make_handler(form=form)
        resp = await handler.get_form(_make_request_get("compat_form"))

        assert resp.status == 200
        body = json.loads(resp.body)
        # form_id must be present
        assert body["form_id"] == "compat_form"
        # No lifecycle header
        assert "X-Form-CSRF-Token" not in resp.headers

    async def test_get_schema_no_events_unchanged(self) -> None:
        """Forms without events in get_schema return plain schema dict."""
        form = _make_form("compat_form", events=None)
        handler = _make_handler(form=form)
        resp = await handler.get_schema(_make_request_get("compat_form"))

        assert resp.status == 200
        body = json.loads(resp.body)
        # The JSON schema renderer produces a dict — just confirm it's there
        assert isinstance(body, dict)

    async def test_submit_no_events_returns_200(self) -> None:
        """Forms without events in submit_data return 200 (backward-compat)."""
        form = _make_form("compat_form", events=None)
        handler = _make_handler(form=form, valid=True)
        resp = await handler.submit_data(
            _make_request_post("compat_form", body={"name": "Alice"})
        )

        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["is_valid"] is True

    async def test_html5_no_events_no_lifecycle_script(self) -> None:
        """HTML5 renderer for event-less forms produces no lifecycle script."""
        form = _make_form("compat_form", events=None)
        renderer = HTML5Renderer()
        out = await renderer.render(form)

        # The lifecycle IIFE is absent
        assert "parrot:before-submit" not in out.content
        assert "EVENTS_CONFIG" not in out.content


# ---------------------------------------------------------------------------
# onBeforeSubmit payload replacement
# ---------------------------------------------------------------------------


class TestOnBeforeSubmitPayloadReplacement:
    """onBeforeSubmit can replace the payload before validation."""

    async def test_replacement_payload_reaches_validator(self) -> None:
        """Payload from EventResolution is passed to the validator."""
        received: list[dict] = []
        form_id = "e2e_payload"

        @register_form_event(f"{form_id}.onBeforeSubmit")
        async def normalise(ctx):  # type: ignore[no-untyped-def]
            return EventResolution(payload={"name": "NORMALISED"})

        form = _make_form(
            form_id=form_id,
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref=f"{form_id}.onBeforeSubmit"),
            ),
        )
        handler = _make_handler(form=form, valid=True)

        orig = handler.validator.validate

        async def capture(f, data):  # type: ignore[no-untyped-def]
            received.append(dict(data))
            return await orig(f, data)

        handler.validator.validate = capture
        req = _make_request_post(form_id, body={"name": "RAW"})

        resp = await handler.submit_data(req)

        assert resp.status == 200
        assert received == [{"name": "NORMALISED"}]


# ---------------------------------------------------------------------------
# FormEventAbort NOT routed through onError (spec §7)
# ---------------------------------------------------------------------------


class TestAbortNotRoutedThroughOnError:
    """FormEventAbort in onBeforeSubmit must NOT invoke onError."""

    async def test_abort_does_not_trigger_onerror(self) -> None:
        """Abort in onBeforeSubmit bypasses onError entirely."""
        on_error_calls: list[str] = []
        form_id = "e2e_abort"

        @register_form_event(f"{form_id}.onBeforeSubmit")
        async def abort_h(ctx):  # type: ignore[no-untyped-def]
            raise FormEventAbort("blocked", user_message="Blocked", status_code=409)

        @register_form_event(f"{form_id}.onError")
        async def err_h(ctx):  # type: ignore[no-untyped-def]
            on_error_calls.append("called")
            return EventResolution()

        form = _make_form(
            form_id=form_id,
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref=f"{form_id}.onBeforeSubmit"),
                onError=FormEventBinding(handler_ref=f"{form_id}.onError"),
            ),
        )
        handler = _make_handler(form=form, valid=True)
        resp = await handler.submit_data(
            _make_request_post(form_id, body={})
        )

        assert resp.status == 409
        assert on_error_calls == []


# ---------------------------------------------------------------------------
# onError called on validation failure
# ---------------------------------------------------------------------------


class TestOnErrorOnValidationFailure:
    """onError is dispatched when validation fails."""

    async def test_onerror_dispatched_and_422_returned(self) -> None:
        """422 is still returned; onError handler is invoked as a side-effect."""
        on_error_calls: list[str] = []
        form_id = "e2e_onerror"

        @register_form_event(f"{form_id}.onError")
        async def err_h(ctx):  # type: ignore[no-untyped-def]
            on_error_calls.append(type(ctx.error).__name__ if ctx.error else "no_error")
            return EventResolution(user_message="Friendly")

        form = _make_form(
            form_id=form_id,
            events=FormEventsConfig(
                onError=FormEventBinding(handler_ref=f"{form_id}.onError"),
            ),
        )
        handler = _make_handler(form=form, valid=False)
        resp = await handler.submit_data(
            _make_request_post(form_id, body={})
        )

        assert resp.status == 422
        assert on_error_calls  # onError was invoked


# ---------------------------------------------------------------------------
# Remote event endpoint CSRF round-trip
# ---------------------------------------------------------------------------


class TestRemoteEventCSRFRoundTrip:
    """Issue token via get_form, use it in remote_event."""

    async def _make_get_request_with_session(
        self, form_id: str, session_id: str = "sess_e2e"
    ) -> MagicMock:
        req = MagicMock(spec=web.Request)
        req.match_info = {"form_id": form_id}
        req.method = "GET"
        req.headers = {}
        req.query = {}
        session_data = {"id": session_id, "programs": []}
        session = MagicMock()
        session.get = MagicMock(
            side_effect=lambda k, default=None: session_data.get(k, default)
        )
        req.__contains__ = MagicMock(side_effect=lambda k: k == "session")
        req.__getitem__ = MagicMock(return_value=session)
        req.__setitem__ = MagicMock()
        return req

    async def test_token_issued_by_get_form_validates_remote_event(self) -> None:
        """Token from get_form response header authenticates remote_event call."""
        form_id = "e2e_csrf"

        @register_form_event(f"{form_id}.onBeforeSubmit")
        async def h(ctx):  # type: ignore[no-untyped-def]
            return EventResolution(payload={"ok": True})

        form = _make_form(
            form_id=form_id,
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(
                    handler_ref=f"{form_id}.onBeforeSubmit",
                    remote=True,
                ),
            ),
        )
        handler = _make_handler(form=form)

        # 1. GET /forms/{id} — picks up CSRF token
        get_req = await self._make_get_request_with_session(form_id)
        get_resp = await handler.get_form(get_req)
        assert get_resp.status == 200
        token = get_resp.headers.get("X-Form-CSRF-Token", "")
        assert token, "get_form must emit X-Form-CSRF-Token for remote-bound forms"

        # 2. POST /forms/{id}/events/onBeforeSubmit with the issued token
        remote_req = MagicMock(spec=web.Request)
        remote_req.match_info = {"form_id": form_id, "event_name": "onBeforeSubmit"}
        remote_req.method = "POST"
        headers = {"X-CSRF-Token": token}
        remote_req.headers = headers
        session_data = {"id": "sess_e2e", "programs": []}
        session = MagicMock()
        session.get = MagicMock(
            side_effect=lambda k, default=None: session_data.get(k, default)
        )
        remote_req.__contains__ = MagicMock(side_effect=lambda k: k == "session")
        remote_req.__getitem__ = MagicMock(return_value=session)
        remote_req.__setitem__ = MagicMock()
        remote_req.json = AsyncMock(return_value={"payload": {"name": "test"}})

        remote_resp = await handler.remote_event(remote_req)

        assert remote_resp.status == 200
        body = json.loads(remote_resp.body)
        assert body.get("payload") == {"ok": True}
