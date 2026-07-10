"""Unit tests for the ``visit.*`` namespace of the event dispatcher — FEAT-329.

Tests cover the dispatch_visit() coroutine added by TASK-337: registration
and dispatch of visit handlers through the shared FEAT-188 registry,
pre-hook FormEventAbort propagation, tenant → global fallback, post-hook
fire-and-forget semantics, and non-regression of the form-scoped dispatch().
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from parrot_formdesigner.core.events import (
    EventResolution,
    FormEventAbort,
    FormEventBinding,
    FormEventsConfig,
    VisitEventContext,
)
from parrot_formdesigner.services.event_dispatcher import (
    dispatch,
    dispatch_visit,
)
from parrot_formdesigner.services.event_registry import (
    _clear_event_registry_for_tests,
    register_form_event,
)


@pytest.fixture(autouse=True)
def _clear_registry() -> None:  # type: ignore[return]
    """Isolate registry state between tests."""
    yield
    _clear_event_registry_for_tests()


@pytest.fixture()
def auth_context() -> None:
    """Minimal auth context (None is valid — auth_context typed Any)."""
    return None


class TestDispatchVisit:
    """Tests for the dispatch_visit() coroutine."""

    async def test_visit_handler_registration_and_dispatch(
        self, auth_context: None
    ) -> None:
        """A handler registered under the visit event name runs and its
        EventResolution is returned; the context carries the visit fields."""
        seen: list[VisitEventContext] = []
        expected = EventResolution(metadata={"checked_in": True})

        @register_form_event("visit.onCheckout")
        async def h(ctx: VisitEventContext) -> EventResolution | None:
            seen.append(ctx)
            return expected

        result = await dispatch_visit(
            "visit.onCheckout",
            tenant="acme",
            auth_context=auth_context,
            event_id="ev-1",
            shift_id="sh-1",
            visit_id="v-1",
            staff_id="st-1",
            payload={"lat": 1.0, "lng": 2.0},
        )
        assert result is expected
        assert len(seen) == 1
        ctx = seen[0]
        assert ctx.event == "visit.onCheckout"
        assert ctx.tenant == "acme"
        assert ctx.event_id == "ev-1"
        assert ctx.shift_id == "sh-1"
        assert ctx.visit_id == "v-1"
        assert ctx.staff_id == "st-1"
        assert ctx.payload == {"lat": 1.0, "lng": 2.0}

    async def test_visit_prehook_abort_propagates_status_and_message(
        self, auth_context: None
    ) -> None:
        """FormEventAbort raised by the visit.onArrival pre-hook is re-raised
        intact with user_message and status_code."""

        @register_form_event("visit.onArrival")
        async def h(ctx: VisitEventContext) -> EventResolution | None:
            raise FormEventAbort(
                "outside geofence",
                user_message="You are too far from the store.",
                status_code=422,
            )

        with pytest.raises(FormEventAbort, match="outside geofence") as exc_info:
            await dispatch_visit(
                "visit.onArrival",
                tenant=None,
                auth_context=auth_context,
                visit_id="v-1",
            )
        assert exc_info.value.user_message == "You are too far from the store."
        assert exc_info.value.status_code == 422

    async def test_tenant_fallback_to_global_handler(
        self, auth_context: None
    ) -> None:
        """A tenant with no specific registration falls back to the global
        handler; a tenant-specific registration shadows it."""
        calls: list[str] = []

        @register_form_event("visit.onAssignmentCreated")
        async def global_h(ctx: VisitEventContext) -> EventResolution | None:
            calls.append("global")
            return None

        @register_form_event("visit.onAssignmentCreated", tenant="acme")
        async def acme_h(ctx: VisitEventContext) -> EventResolution | None:
            calls.append("acme")
            return None

        await dispatch_visit(
            "visit.onAssignmentCreated",
            tenant="globex",  # no globex-specific handler → global fallback
            auth_context=auth_context,
        )
        await dispatch_visit(
            "visit.onAssignmentCreated",
            tenant="acme",  # tenant-specific shadows global
            auth_context=auth_context,
        )
        assert calls == ["global", "acme"]

    async def test_missing_handler_is_noop(self, auth_context: None) -> None:
        """No registered handler for the visit event returns an empty
        EventResolution (no-op)."""
        result = await dispatch_visit(
            "visit.onArtifactAttached",
            tenant="acme",
            auth_context=auth_context,
        )
        assert result == EventResolution()

    async def test_handler_returns_none_is_empty_resolution(
        self, auth_context: None
    ) -> None:
        """Handler returning None is normalised to empty EventResolution."""

        @register_form_event("visit.onGeofenceExit")
        async def h(ctx: VisitEventContext) -> EventResolution | None:
            return None

        result = await dispatch_visit(
            "visit.onGeofenceExit",
            tenant=None,
            auth_context=auth_context,
        )
        assert result == EventResolution()

    async def test_posthook_exception_is_swallowed(
        self, auth_context: None
    ) -> None:
        """A post-hook handler failure is fire-and-forget: logged, swallowed,
        and an empty EventResolution is returned."""

        @register_form_event("visit.onArtifactAttached")
        async def h(ctx: VisitEventContext) -> EventResolution | None:
            raise ValueError("observer blew up")

        result = await dispatch_visit(
            "visit.onArtifactAttached",
            tenant=None,
            auth_context=auth_context,
        )
        assert result == EventResolution()

    async def test_posthook_abort_is_ignored(self, auth_context: None) -> None:
        """FormEventAbort raised by a post-hook is ignored (aborts are only
        meaningful for pre-hooks)."""

        @register_form_event("visit.onCheckout")
        async def h(ctx: VisitEventContext) -> EventResolution | None:
            raise FormEventAbort("late abort", user_message="Nope")

        result = await dispatch_visit(
            "visit.onCheckout",
            tenant=None,
            auth_context=auth_context,
        )
        assert result == EventResolution()

    async def test_prehook_other_exceptions_propagate(
        self, auth_context: None
    ) -> None:
        """Non-abort exceptions from the pre-hook propagate unchanged
        (mirror of the form-scoped before* semantics)."""

        @register_form_event("visit.onArrival")
        async def h(ctx: VisitEventContext) -> EventResolution | None:
            raise ValueError("unexpected problem")

        with pytest.raises(ValueError, match="unexpected problem"):
            await dispatch_visit(
                "visit.onArrival",
                tenant=None,
                auth_context=auth_context,
            )

    async def test_explicit_handler_ref_overrides_event_name(
        self, auth_context: None
    ) -> None:
        """A custom handler_ref is used for the registry lookup instead of
        the event name."""
        calls: list[str] = []

        @register_form_event("visit.custom.arrival_check")
        async def h(ctx: VisitEventContext) -> EventResolution | None:
            calls.append(ctx.event)
            return None

        await dispatch_visit(
            "visit.onArrival",
            tenant=None,
            auth_context=auth_context,
            handler_ref="visit.custom.arrival_check",
        )
        assert calls == ["visit.onArrival"]


class TestFormDispatchUnaffected:
    """Non-regression: form-scoped dispatch() behaviour is unchanged."""

    async def test_form_dispatch_unaffected(self, auth_context: None) -> None:
        """dispatch() still resolves form bindings from the shared registry
        while visit handlers coexist under the visit.* namespace."""
        from parrot_formdesigner.core.schema import FormSchema

        calls: list[str] = []

        @register_form_event("visit.onArrival")
        async def visit_h(ctx: VisitEventContext) -> EventResolution | None:
            calls.append("visit")
            return None

        expected = EventResolution(payload={"email": "a@b.com"})

        @register_form_event("f1.onBeforeSubmit")
        async def form_h(ctx):  # type: ignore[no-untyped-def]
            calls.append("form")
            return expected

        form = FormSchema(
            form_id="f1",
            title={"en": "Test Form"},
            sections=[],
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref="f1.onBeforeSubmit"),
            ),
        )
        result = await dispatch(
            "onBeforeSubmit",
            form=form,
            request=MagicMock(),
            tenant=None,
            auth_context=auth_context,
            payload={"email": "A@B.COM"},
        )
        assert result is expected
        assert calls == ["form"]  # visit handler was never invoked
