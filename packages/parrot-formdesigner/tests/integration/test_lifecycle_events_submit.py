"""Integration tests for lifecycle event hooks in submit handler — FEAT-188 TASK-1270.

Tests cover onBeforeSubmit, onAfterSubmit and onError hooks wired into
FormAPIHandler.submit_data().

Uses mocked aiohttp requests and a mocked FormRegistry/validator to test
end-to-end behavior without requiring a real database.
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
from parrot_formdesigner.services.validators import ValidationResult


@pytest.fixture(autouse=True)
def _clear_registry() -> None:  # type: ignore[return]
    """Isolate registry state between tests."""
    yield
    _clear_event_registry_for_tests()


def _make_form(form_id: str = "survey_v1", events: FormEventsConfig | None = None) -> FormSchema:
    """Build a minimal FormSchema."""
    return FormSchema(
        form_id=form_id,
        title={"en": "Survey"},
        sections=[],
        events=events,
    )


def _make_request(
    form_id: str = "survey_v1",
    body: dict | None = None,
) -> MagicMock:
    """Build a mocked aiohttp Request for submit."""
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_id": form_id}
    req.method = "POST"
    req.headers = {}
    req.query = {}
    # No auth context set
    req.__contains__ = MagicMock(return_value=False)
    req.__setitem__ = MagicMock()
    req.__getitem__ = MagicMock(side_effect=KeyError)
    req.json = AsyncMock(return_value=body or {})
    # Session for tenant resolution
    session = MagicMock()
    session.get = MagicMock(return_value={})
    req.session = session
    return req


def _make_handler(
    form: FormSchema | None = None,
    valid: bool = True,
) -> FormAPIHandler:
    """Build a FormAPIHandler with mocked registry and validator."""
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form)
    registry.default_tenant = "default"

    handler = FormAPIHandler(registry=registry)

    # Mock the validator
    validation_result = MagicMock(spec=ValidationResult)
    validation_result.is_valid = valid
    validation_result.errors = {} if valid else {"field": ["required"]}
    validation_result.sanitized_data = {"name": "Alice"} if valid else {}
    handler.validator = MagicMock()
    handler.validator.validate = AsyncMock(return_value=validation_result)

    return handler


# ---------------------------------------------------------------------------
# onBeforeSubmit
# ---------------------------------------------------------------------------


class TestOnBeforeSubmit:
    """Tests for onBeforeSubmit hook."""

    async def test_submit_without_events_returns_200(self) -> None:
        """Form without events returns 200 — no-op, backward compatible."""
        form = _make_form(events=None)
        handler = _make_handler(form=form, valid=True)
        req = _make_request(body={"name": "Alice"})

        resp = await handler.submit_data(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["is_valid"] is True

    async def test_onbeforesubmit_handler_invoked(self) -> None:
        """onBeforeSubmit handler is called before validation."""
        invocations: list[str] = []

        @register_form_event("survey_v1.onBeforeSubmit")
        async def h(ctx):  # type: ignore[no-untyped-def]
            invocations.append(ctx.event)
            return EventResolution()

        form = _make_form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref="survey_v1.onBeforeSubmit"),
            )
        )
        handler = _make_handler(form=form, valid=True)
        req = _make_request(body={"name": "Alice"})

        resp = await handler.submit_data(req)

        assert resp.status == 200
        assert invocations == ["onBeforeSubmit"]

    async def test_onbeforesubmit_payload_replacement(self) -> None:
        """Payload returned by onBeforeSubmit replaces the submitted data."""
        received_payloads: list[dict] = []

        @register_form_event("survey_v1.onBeforeSubmit")
        async def normalise(ctx):  # type: ignore[no-untyped-def]
            return EventResolution(payload={"name": "normalised"})

        form = _make_form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref="survey_v1.onBeforeSubmit"),
            )
        )
        handler = _make_handler(form=form, valid=True)
        # Capture what the validator receives
        original_validate = handler.validator.validate

        async def capturing_validate(form, data):  # type: ignore[no-untyped-def]
            received_payloads.append(dict(data))
            return await original_validate(form, data)

        handler.validator.validate = capturing_validate
        req = _make_request(body={"name": "RAW"})

        await handler.submit_data(req)

        assert received_payloads == [{"name": "normalised"}]

    async def test_onbeforesubmit_abort_returns_status(self) -> None:
        """FormEventAbort in onBeforeSubmit → HTTP error; validator NOT called."""

        @register_form_event("survey_v1.onBeforeSubmit")
        async def block(ctx):  # type: ignore[no-untyped-def]
            raise FormEventAbort("nope", user_message="Blocked", status_code=409)

        form = _make_form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref="survey_v1.onBeforeSubmit"),
            )
        )
        handler = _make_handler(form=form, valid=True)
        req = _make_request(body={})

        resp = await handler.submit_data(req)

        assert resp.status == 409
        body = json.loads(resp.body)
        assert body["error"] == "Blocked"
        assert body["reason"] == "nope"
        # Validator must NOT have been called
        handler.validator.validate.assert_not_called()

    async def test_onbeforesubmit_abort_not_routed_to_onerror(self) -> None:
        """FormEventAbort must NOT trigger onError (spec §7)."""
        on_error_invocations: list[str] = []

        @register_form_event("survey_v1.onBeforeSubmit")
        async def abort_h(ctx):  # type: ignore[no-untyped-def]
            raise FormEventAbort("abort", user_message="No", status_code=403)

        @register_form_event("survey_v1.onError")
        async def err_h(ctx):  # type: ignore[no-untyped-def]
            on_error_invocations.append("called")
            return EventResolution()

        form = _make_form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref="survey_v1.onBeforeSubmit"),
                onError=FormEventBinding(handler_ref="survey_v1.onError"),
            )
        )
        handler = _make_handler(form=form, valid=True)
        req = _make_request(body={})

        resp = await handler.submit_data(req)

        assert resp.status == 403
        assert on_error_invocations == []  # onError NOT called for abort


# ---------------------------------------------------------------------------
# onAfterSubmit
# ---------------------------------------------------------------------------


class TestOnAfterSubmit:
    """Tests for onAfterSubmit hook."""

    async def test_onaftersubmit_invoked_after_store(self) -> None:
        """onAfterSubmit is called after storage and forward."""
        invocations: list[str] = []

        @register_form_event("survey_v1.onAfterSubmit")
        async def after_h(ctx):  # type: ignore[no-untyped-def]
            invocations.append(ctx.event)
            return EventResolution()

        form = _make_form(
            events=FormEventsConfig(
                onAfterSubmit=FormEventBinding(handler_ref="survey_v1.onAfterSubmit"),
            )
        )
        handler = _make_handler(form=form, valid=True)
        req = _make_request(body={"name": "Alice"})

        resp = await handler.submit_data(req)

        assert resp.status == 200
        assert invocations == ["onAfterSubmit"]

    async def test_onaftersubmit_not_called_on_invalid(self) -> None:
        """onAfterSubmit is NOT called when validation fails."""
        invocations: list[str] = []

        @register_form_event("survey_v1.onAfterSubmit")
        async def after_h(ctx):  # type: ignore[no-untyped-def]
            invocations.append(ctx.event)
            return EventResolution()

        form = _make_form(
            events=FormEventsConfig(
                onAfterSubmit=FormEventBinding(handler_ref="survey_v1.onAfterSubmit"),
            )
        )
        handler = _make_handler(form=form, valid=False)
        req = _make_request(body={"name": ""})

        resp = await handler.submit_data(req)

        assert resp.status == 422
        assert invocations == []


# ---------------------------------------------------------------------------
# onError
# ---------------------------------------------------------------------------


class TestOnError:
    """Tests for onError hook."""

    async def test_onerror_called_on_validation_failure(self) -> None:
        """onError is dispatched when validation fails (422); 422 still returned."""
        called: list[str] = []

        @register_form_event("survey_v1.onError")
        async def err_h(ctx):  # type: ignore[no-untyped-def]
            called.append(type(ctx.error).__name__)
            return EventResolution(user_message="Friendly error")

        form = _make_form(
            events=FormEventsConfig(
                onError=FormEventBinding(handler_ref="survey_v1.onError"),
            )
        )
        handler = _make_handler(form=form, valid=False)
        req = _make_request(body={})

        resp = await handler.submit_data(req)

        assert resp.status == 422
        assert called  # onError was invoked

    async def test_onerror_itself_raising_does_not_mask_422(self) -> None:
        """onError handler that raises does not prevent the 422 from being returned."""

        @register_form_event("survey_v1.onError")
        async def broken_err_h(ctx):  # type: ignore[no-untyped-def]
            raise RuntimeError("broken handler")

        form = _make_form(
            events=FormEventsConfig(
                onError=FormEventBinding(handler_ref="survey_v1.onError"),
            )
        )
        handler = _make_handler(form=form, valid=False)
        req = _make_request(body={})

        # 422 must still be returned even when onError handler itself raises
        resp = await handler.submit_data(req)

        assert resp.status == 422
