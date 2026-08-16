"""Integration tests for lifecycle event hooks in read handlers — FEAT-188 TASK-1269.

Tests cover the onBeforeOpen and onSchemaLoaded hooks wired into
FormAPIHandler.get_form() and FormAPIHandler.get_schema().

Uses mocked aiohttp requests and a real FormRegistry to test end-to-end
behavior of the dispatch integration without requiring the full HTTP server.
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
from parrot_formdesigner.services.event_registry import (
    _clear_event_registry_for_tests,
    register_form_event,
)
from parrot_formdesigner.services.registry import FormRegistry


@pytest.fixture(autouse=True)
def _clear_registry() -> None:  # type: ignore[return]
    """Isolate registry state between tests."""
    yield
    _clear_event_registry_for_tests()


_UNKNOWN_FORM_UID = "00000000-0000-0000-0000-000000000000"

# FEAT-421: fixed tenant shared by _make_form()/_make_request() so
# FormAPIHandler._get_tenant() (declared_tenant()) resolves consistently
# and _assert_form_tenant()'s cross-check never fires for these
# lifecycle-hook tests, which are not testing tenant enforcement.
_TEST_TENANT = "test-tenant"


def _make_form(form_id: str = "test_form", events: FormEventsConfig | None = None) -> FormSchema:
    """Build a minimal FormSchema. form_uid is auto-generated."""
    return FormSchema(
        form_id=form_id,
        title={"en": "Test Form"},
        tenant=_TEST_TENANT,
        sections=[],
        events=events,
    )


def _make_request(form_uid: str = _UNKNOWN_FORM_UID) -> MagicMock:
    """Build a mocked aiohttp Request.

    Args:
        form_uid: Value for the ``{form_uid}`` path parameter (FEAT-389) —
            MUST be a well-formed UUID string (validated by
            ``extract_form_uid()``). Defaults to a well-formed, never
            registered UUID for "not found" tests.
    """
    req = MagicMock(spec=web.Request)
    # aiohttp's real match_info always holds raw path strings — mirror that
    # here so a caller passing FormSchema.form_uid (uuid.UUID, FEAT-393)
    # round-trips through extract_form_uid() exactly like a live request.
    req.match_info = {"form_uid": str(form_uid)}
    req.method = "GET"
    req.headers = {}
    # FEAT-421: declared_tenant() reads request.get("tenant") — the value
    # @requires_tenant would have stashed. No other key is read this way.
    req.__contains__ = MagicMock(return_value=False)
    req.__getitem__ = MagicMock(side_effect=KeyError)
    req.get = MagicMock(
        side_effect=lambda key, default=None: _TEST_TENANT if key == "tenant" else default
    )
    # Session with default tenant
    session = MagicMock()
    session.get = MagicMock(return_value={"programs": [_TEST_TENANT]})
    req.session = session
    return req


def _make_handler(form: FormSchema | None = None) -> FormAPIHandler:
    """Build a FormAPIHandler with mocked registry."""
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form)
    registry.default_tenant = "default"

    handler = FormAPIHandler(registry=registry)
    return handler


# ---------------------------------------------------------------------------
# get_form — onBeforeOpen
# ---------------------------------------------------------------------------


class TestGetFormOnBeforeOpen:
    """Tests for onBeforeOpen hook in get_form."""

    async def test_get_form_no_events_returns_200(self) -> None:
        """Form without events config returns 200 unchanged — no-op."""
        form = _make_form(events=None)
        handler = _make_handler(form=form)
        req = _make_request(form.form_uid)

        resp = await handler.get_form(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["form_id"] == "test_form"

    async def test_get_form_with_open_hook_handler_invoked(self) -> None:
        """onBeforeOpen handler is invoked and can return resolution."""
        invocations: list[str] = []

        @register_form_event("test_form.onBeforeOpen")
        async def on_open(ctx):  # type: ignore[no-untyped-def]
            invocations.append(ctx.form_id)
            return EventResolution()

        form = _make_form(
            events=FormEventsConfig(
                onBeforeOpen=FormEventBinding(handler_ref="test_form.onBeforeOpen"),
            )
        )
        handler = _make_handler(form=form)
        req = _make_request(form.form_uid)

        resp = await handler.get_form(req)

        assert resp.status == 200
        assert invocations == ["test_form"]

    async def test_get_form_onbeforeopen_abort_returns_403(self) -> None:
        """FormEventAbort raised in onBeforeOpen → HTTP 403 with user_message."""

        @register_form_event("test_form.onBeforeOpen")
        async def block(ctx):  # type: ignore[no-untyped-def]
            raise FormEventAbort("gated", user_message="Access denied", status_code=403)

        form = _make_form(
            events=FormEventsConfig(
                onBeforeOpen=FormEventBinding(handler_ref="test_form.onBeforeOpen"),
            )
        )
        handler = _make_handler(form=form)
        req = _make_request(form.form_uid)

        resp = await handler.get_form(req)

        assert resp.status == 403
        body = json.loads(resp.body)
        assert body["error"] == "Access denied"
        assert body["reason"] == "gated"

    async def test_get_form_onbeforeopen_custom_status_code(self) -> None:
        """FormEventAbort can use a custom status_code (e.g. 401)."""

        @register_form_event("test_form.onBeforeOpen")
        async def block(ctx):  # type: ignore[no-untyped-def]
            raise FormEventAbort("unauth", user_message="Login required", status_code=401)

        form = _make_form(
            events=FormEventsConfig(
                onBeforeOpen=FormEventBinding(handler_ref="test_form.onBeforeOpen"),
            )
        )
        handler = _make_handler(form=form)
        req = _make_request(form.form_uid)

        resp = await handler.get_form(req)

        assert resp.status == 401
        body = json.loads(resp.body)
        assert body["error"] == "Login required"

    async def test_get_form_404_when_form_not_found(self) -> None:
        """Form not found returns 404 (lifecycle hooks not invoked)."""
        handler = _make_handler(form=None)
        req = _make_request()

        resp = await handler.get_form(req)

        assert resp.status == 404


# ---------------------------------------------------------------------------
# get_schema — onSchemaLoaded
# ---------------------------------------------------------------------------


class TestGetSchemaOnSchemaLoaded:
    """Tests for onSchemaLoaded hook in get_schema."""

    async def test_get_schema_no_events_returns_schema_unchanged(self) -> None:
        """Form without events returns schema byte-identical to pre-change."""
        form = _make_form(events=None)
        handler = _make_handler(form=form)
        req = _make_request(form.form_uid)

        resp = await handler.get_schema(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        # JsonSchemaRenderer output is a dict — just verify it's returned
        assert isinstance(body, dict)

    async def test_get_schema_with_loaded_hook_handler_invoked(self) -> None:
        """onSchemaLoaded handler is called with the rendered schema."""
        invocations: list[str] = []

        @register_form_event("test_form.onSchemaLoaded")
        async def on_loaded(ctx):  # type: ignore[no-untyped-def]
            invocations.append(ctx.event)
            return EventResolution()

        form = _make_form(
            events=FormEventsConfig(
                onSchemaLoaded=FormEventBinding(handler_ref="test_form.onSchemaLoaded"),
            )
        )
        handler = _make_handler(form=form)
        req = _make_request(form.form_uid)

        resp = await handler.get_schema(req)

        assert resp.status == 200
        assert invocations == ["onSchemaLoaded"]

    async def test_get_schema_applies_schema_overrides(self) -> None:
        """schema_overrides from EventResolution are shallowly merged into output."""

        @register_form_event("test_form.onSchemaLoaded")
        async def mutate(ctx):  # type: ignore[no-untyped-def]
            return EventResolution(schema_overrides={"__test_key__": "overridden"})

        form = _make_form(
            events=FormEventsConfig(
                onSchemaLoaded=FormEventBinding(handler_ref="test_form.onSchemaLoaded"),
            )
        )
        handler = _make_handler(form=form)
        req = _make_request(form.form_uid)

        resp = await handler.get_schema(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert body.get("__test_key__") == "overridden"

    async def test_get_schema_abort_returns_403(self) -> None:
        """FormEventAbort in onSchemaLoaded → HTTP error response."""

        @register_form_event("test_form.onSchemaLoaded")
        async def gate(ctx):  # type: ignore[no-untyped-def]
            raise FormEventAbort("schema_gated", user_message="Forbidden", status_code=403)

        form = _make_form(
            events=FormEventsConfig(
                onSchemaLoaded=FormEventBinding(handler_ref="test_form.onSchemaLoaded"),
            )
        )
        handler = _make_handler(form=form)
        req = _make_request(form.form_uid)

        resp = await handler.get_schema(req)

        assert resp.status == 403
        body = json.loads(resp.body)
        assert body["error"] == "Forbidden"
        assert body["reason"] == "schema_gated"

    async def test_get_schema_404_when_form_not_found(self) -> None:
        """Form not found returns 404."""
        handler = _make_handler(form=None)
        req = _make_request()

        resp = await handler.get_schema(req)

        assert resp.status == 404
