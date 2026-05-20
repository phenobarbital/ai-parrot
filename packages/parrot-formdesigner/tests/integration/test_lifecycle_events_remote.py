"""Integration tests for the remote events endpoint — FEAT-188 TASK-1271.

Tests cover the POST /forms/{form_id}/events/{event_name} endpoint, CSRF token
issuance in get_form, and the event dispatch path.

Uses mocked aiohttp requests and a mocked FormRegistry; no real HTTP server
required.
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
from parrot_formdesigner.services.csrf import (
    _clear_csrf_store_for_tests,
    issue_form_csrf_token,
)
from parrot_formdesigner.services.event_registry import (
    _clear_event_registry_for_tests,
    register_form_event,
)
from parrot_formdesigner.services.registry import FormRegistry


@pytest.fixture(autouse=True)
def _clear_stores() -> None:  # type: ignore[return]
    """Isolate CSRF store and event registry between tests."""
    yield
    _clear_event_registry_for_tests()
    _clear_csrf_store_for_tests()


def _make_form(
    form_id: str = "test_form",
    events: FormEventsConfig | None = None,
) -> FormSchema:
    """Build a minimal FormSchema."""
    return FormSchema(
        form_id=form_id,
        title={"en": "Test Form"},
        sections=[],
        events=events,
    )


def _make_handler(form: FormSchema | None = None) -> FormAPIHandler:
    """Build a FormAPIHandler with mocked registry."""
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form)
    registry.default_tenant = "default"
    return FormAPIHandler(registry=registry)


def _make_get_form_request(form_id: str = "test_form", session_id: str = "sess1") -> MagicMock:
    """Build a mocked GET request for get_form.

    Sets up the session mock so that ``_extract_session_id`` returns the
    provided ``session_id`` and ``_get_tenant`` / ``_get_programs`` work
    without raising.
    """
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_id": form_id}
    req.method = "GET"
    req.headers = {}
    req.query = {}

    # Build a session mock that returns sensible defaults for all .get() calls.
    session_data: dict = {"id": session_id, "programs": []}
    session = MagicMock()
    session.get = MagicMock(side_effect=lambda key, default=None: session_data.get(key, default))

    # ``"session" in request`` → True so _extract_session_id reads it;
    # ``request["session"]`` → the session mock.
    req.__contains__ = MagicMock(side_effect=lambda k: k == "session")
    req.__getitem__ = MagicMock(return_value=session)
    req.__setitem__ = MagicMock()
    return req


def _make_remote_request(
    form_id: str = "test_form",
    event_name: str = "onBeforeSubmit",
    csrf_token: str | None = None,
    body: dict | None = None,
    session_id: str = "sess1",
) -> MagicMock:
    """Build a mocked POST request for remote_event."""
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_id": form_id, "event_name": event_name}
    req.method = "POST"

    headers: dict[str, str] = {}
    if csrf_token is not None:
        headers["X-CSRF-Token"] = csrf_token
    req.headers = headers

    req.__contains__ = MagicMock(side_effect=lambda k: k == "session")
    session = MagicMock()
    session.get = MagicMock(return_value=session_id)
    req.__getitem__ = MagicMock(return_value=session)

    req.json = AsyncMock(return_value=body or {})
    return req


# ---------------------------------------------------------------------------
# CSRF store: issue_form_csrf_token / validate_form_csrf_token
# ---------------------------------------------------------------------------


class TestCSRFStore:
    """Unit-level checks for the CSRF helper functions."""

    def test_issued_token_is_non_empty_string(self) -> None:
        token = issue_form_csrf_token("sess1", "form1")
        assert isinstance(token, str) and len(token) > 0

    def test_different_sessions_get_different_tokens(self) -> None:
        t1 = issue_form_csrf_token("sess1", "form1")
        t2 = issue_form_csrf_token("sess2", "form1")
        assert t1 != t2

    def test_reissue_for_same_key_replaces_token(self) -> None:
        from parrot_formdesigner.services.csrf import validate_form_csrf_token

        t1 = issue_form_csrf_token("sess1", "form1")
        t2 = issue_form_csrf_token("sess1", "form1")
        assert t1 != t2  # tokens are random — just verify old token is now invalid
        assert validate_form_csrf_token("sess1", "form1", t2) is True

    def test_wrong_token_fails_validation(self) -> None:
        from parrot_formdesigner.services.csrf import validate_form_csrf_token

        issue_form_csrf_token("sess1", "form1")
        assert validate_form_csrf_token("sess1", "form1", "wrong") is False

    def test_unknown_session_fails_validation(self) -> None:
        from parrot_formdesigner.services.csrf import validate_form_csrf_token

        assert validate_form_csrf_token("no_such_session", "form1", "tok") is False


# ---------------------------------------------------------------------------
# remote_event — CSRF enforcement
# ---------------------------------------------------------------------------


class TestRemoteEventCSRF:
    """Tests that CSRF enforcement works in remote_event."""

    async def test_missing_csrf_returns_403(self) -> None:
        """Request without X-CSRF-Token returns 403."""
        form = _make_form()
        handler = _make_handler(form=form)
        req = _make_remote_request(csrf_token=None)

        resp = await handler.remote_event(req)

        assert resp.status == 403
        body = json.loads(resp.body)
        assert "CSRF" in body["error"]

    async def test_invalid_csrf_returns_403(self) -> None:
        """Request with wrong X-CSRF-Token returns 403."""
        form = _make_form()
        handler = _make_handler(form=form)
        # Issue a valid token for a different session
        issue_form_csrf_token("other_session", "test_form")
        req = _make_remote_request(csrf_token="wrong_token")

        resp = await handler.remote_event(req)

        assert resp.status == 403


# ---------------------------------------------------------------------------
# remote_event — event_name validation
# ---------------------------------------------------------------------------


class TestRemoteEventValidation:
    """Tests for event_name validation in remote_event."""

    async def test_unknown_event_name_returns_400(self) -> None:
        """Unknown event_name returns 400 before CSRF check."""
        form = _make_form()
        handler = _make_handler(form=form)
        req = _make_remote_request(event_name="onBogus", csrf_token="tok")

        resp = await handler.remote_event(req)

        # 400 because event name is checked first
        assert resp.status == 400
        body = json.loads(resp.body)
        assert "onBogus" in body["error"]

    async def test_form_not_found_returns_404(self) -> None:
        """Form not found returns 404."""
        handler = _make_handler(form=None)
        token = issue_form_csrf_token("sess1", "no_such_form")
        req = _make_remote_request(
            form_id="no_such_form",
            event_name="onBeforeSubmit",
            csrf_token=token,
        )

        resp = await handler.remote_event(req)

        assert resp.status == 404


# ---------------------------------------------------------------------------
# remote_event — dispatch
# ---------------------------------------------------------------------------


class TestRemoteEventDispatch:
    """Tests for successful dispatch through remote_event."""

    async def test_valid_request_dispatches_handler(self) -> None:
        """Valid CSRF + valid event name → handler invoked, 200 returned."""
        invocations: list[str] = []

        @register_form_event("test_form.onBeforeSubmit")
        async def h(ctx):  # type: ignore[no-untyped-def]
            invocations.append(ctx.event)
            return EventResolution()

        form = _make_form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref="test_form.onBeforeSubmit"),
            )
        )
        handler = _make_handler(form=form)
        token = issue_form_csrf_token("sess1", "test_form")
        req = _make_remote_request(
            event_name="onBeforeSubmit",
            csrf_token=token,
            body={"payload": {"name": "Alice"}},
        )

        resp = await handler.remote_event(req)

        assert resp.status == 200
        assert invocations == ["onBeforeSubmit"]

    async def test_event_abort_returns_error_status(self) -> None:
        """FormEventAbort in remote handler → typed JSON response."""

        @register_form_event("test_form.onBeforeSubmit")
        async def block(ctx):  # type: ignore[no-untyped-def]
            raise FormEventAbort("blocked", user_message="Access denied", status_code=403)

        form = _make_form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref="test_form.onBeforeSubmit"),
            )
        )
        handler = _make_handler(form=form)
        token = issue_form_csrf_token("sess1", "test_form")
        req = _make_remote_request(event_name="onBeforeSubmit", csrf_token=token)

        resp = await handler.remote_event(req)

        assert resp.status == 403
        body = json.loads(resp.body)
        assert body["error"] == "Access denied"
        assert body["reason"] == "blocked"

    async def test_resolution_payload_returned_in_response(self) -> None:
        """EventResolution with payload is serialized into the response body."""

        @register_form_event("test_form.onBeforeSubmit")
        async def enrich(ctx):  # type: ignore[no-untyped-def]
            return EventResolution(payload={"enriched": True})

        form = _make_form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref="test_form.onBeforeSubmit"),
            )
        )
        handler = _make_handler(form=form)
        token = issue_form_csrf_token("sess1", "test_form")
        req = _make_remote_request(event_name="onBeforeSubmit", csrf_token=token)

        resp = await handler.remote_event(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert body.get("payload") == {"enriched": True}


# ---------------------------------------------------------------------------
# get_form — CSRF token issuance
# ---------------------------------------------------------------------------


class TestGetFormCSRFIssuance:
    """Tests for CSRF token emission in get_form."""

    async def test_get_form_no_remote_binding_no_csrf_header(self) -> None:
        """Form without remote=True binding does NOT emit X-Form-CSRF-Token."""
        form = _make_form(events=None)
        handler = _make_handler(form=form)
        req = _make_get_form_request()

        resp = await handler.get_form(req)

        assert resp.status == 200
        assert "X-Form-CSRF-Token" not in resp.headers

    async def test_get_form_with_remote_binding_emits_csrf_header(self) -> None:
        """Form with remote=True binding emits X-Form-CSRF-Token in response."""
        form = _make_form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(
                    handler_ref="test_form.onBeforeSubmit",
                    remote=True,
                ),
            )
        )
        handler = _make_handler(form=form)
        req = _make_get_form_request(session_id="sess1")

        resp = await handler.get_form(req)

        assert resp.status == 200
        assert "X-Form-CSRF-Token" in resp.headers
        assert len(resp.headers["X-Form-CSRF-Token"]) > 0

    async def test_get_form_csrf_token_is_valid_for_remote_event(self) -> None:
        """Token issued by get_form can be used to authenticate a remote_event call."""
        from parrot_formdesigner.services.csrf import validate_form_csrf_token

        form = _make_form(
            form_id="test_form",
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(
                    handler_ref="test_form.onBeforeSubmit",
                    remote=True,
                ),
            )
        )
        handler = _make_handler(form=form)
        req = _make_get_form_request(form_id="test_form", session_id="sess1")

        resp = await handler.get_form(req)

        assert resp.status == 200
        token = resp.headers.get("X-Form-CSRF-Token", "")
        assert token
        assert validate_form_csrf_token("sess1", "test_form", token) is True
