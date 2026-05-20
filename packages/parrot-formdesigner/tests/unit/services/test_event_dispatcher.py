"""Unit tests for parrot_formdesigner.services.event_dispatcher — FEAT-188.

Tests cover the dispatch() coroutine and apply_schema_overrides() helper
created by TASK-1267.

Note: These tests require TASK-1268 (FormSchema.events field) to be complete,
since _form() constructs a FormSchema with an events kwarg.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from parrot_formdesigner.core.events import (
    EventResolution,
    FormEventAbort,
    FormEventBinding,
    FormEventsConfig,
)
from parrot_formdesigner.services.event_dispatcher import (
    apply_schema_overrides,
    dispatch,
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
def mock_request() -> MagicMock:
    """Minimal aiohttp Request mock."""
    return MagicMock()


@pytest.fixture()
def auth_context() -> None:
    """Minimal auth context (None is valid — auth_context typed Any)."""
    return None


def _form(form_id: str = "f1", events: FormEventsConfig | None = None):  # type: ignore[no-untyped-def]
    """Build a minimal FormSchema with optional events config.

    Requires TASK-1268 (FormSchema.events field) to be complete.
    """
    from parrot_formdesigner.core.schema import FormSchema

    return FormSchema(
        form_id=form_id,
        title={"en": "Test Form"},
        sections=[],
        events=events,
    )


class TestDispatch:
    """Tests for the dispatch() coroutine."""

    async def test_no_binding_is_noop(
        self, mock_request: MagicMock, auth_context: None
    ) -> None:
        """Form without events config returns empty EventResolution (no-op)."""
        form = _form(events=None)
        result = await dispatch(
            "onBeforeSubmit",
            form=form,
            request=mock_request,
            tenant="acme",
            auth_context=auth_context,
            payload={"x": 1},
        )
        assert result == EventResolution()

    async def test_event_not_declared_in_config_is_noop(
        self, mock_request: MagicMock, auth_context: None
    ) -> None:
        """FormEventsConfig with no binding for the event returns empty resolution."""
        form = _form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref="f1.onBeforeSubmit"),
                # onAfterSubmit is NOT declared
            )
        )
        result = await dispatch(
            "onAfterSubmit",
            form=form,
            request=mock_request,
            tenant=None,
            auth_context=auth_context,
        )
        assert result == EventResolution()

    async def test_handler_returns_none_is_empty_resolution(
        self, mock_request: MagicMock, auth_context: None
    ) -> None:
        """Handler returning None is normalised to empty EventResolution."""

        @register_form_event("f1.onBeforeSubmit")
        async def h(ctx):  # type: ignore[no-untyped-def]
            return None

        form = _form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref="f1.onBeforeSubmit"),
            )
        )
        result = await dispatch(
            "onBeforeSubmit",
            form=form,
            request=mock_request,
            tenant=None,
            auth_context=auth_context,
            payload={"x": 1},
        )
        assert result == EventResolution()

    async def test_handler_returns_resolution(
        self, mock_request: MagicMock, auth_context: None
    ) -> None:
        """Handler returning EventResolution passes it through."""
        expected = EventResolution(payload={"email": "a@b.com"})

        @register_form_event("f1.onBeforeSubmit")
        async def h(ctx):  # type: ignore[no-untyped-def]
            return expected

        form = _form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref="f1.onBeforeSubmit"),
            )
        )
        result = await dispatch(
            "onBeforeSubmit",
            form=form,
            request=mock_request,
            tenant=None,
            auth_context=auth_context,
            payload={"email": "A@B.COM"},
        )
        assert result is expected

    async def test_required_missing_handler_raises_runtime_error(
        self, mock_request: MagicMock, auth_context: None
    ) -> None:
        """required=True binding with no handler registered raises RuntimeError."""
        form = _form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(
                    handler_ref="f1.notRegistered", required=True
                ),
            )
        )
        with pytest.raises(RuntimeError, match="not registered"):
            await dispatch(
                "onBeforeSubmit",
                form=form,
                request=mock_request,
                tenant=None,
                auth_context=auth_context,
                payload={},
            )

    async def test_optional_missing_handler_returns_empty_resolution(
        self, mock_request: MagicMock, auth_context: None
    ) -> None:
        """required=False binding with no handler registered returns empty EventResolution."""
        form = _form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(
                    handler_ref="f1.notRegistered", required=False
                ),
            )
        )
        result = await dispatch(
            "onBeforeSubmit",
            form=form,
            request=mock_request,
            tenant=None,
            auth_context=auth_context,
            payload={},
        )
        assert result == EventResolution()

    async def test_form_event_abort_propagates(
        self, mock_request: MagicMock, auth_context: None
    ) -> None:
        """FormEventAbort raised by handler propagates intact."""

        @register_form_event("f1.onBeforeSubmit")
        async def h(ctx):  # type: ignore[no-untyped-def]
            raise FormEventAbort("blocked", user_message="Access denied")

        form = _form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref="f1.onBeforeSubmit"),
            )
        )
        with pytest.raises(FormEventAbort, match="blocked"):
            await dispatch(
                "onBeforeSubmit",
                form=form,
                request=mock_request,
                tenant=None,
                auth_context=auth_context,
                payload={},
            )

    async def test_other_exceptions_propagate(
        self, mock_request: MagicMock, auth_context: None
    ) -> None:
        """Non-FormEventAbort exceptions from handler propagate unchanged."""

        @register_form_event("f1.onBeforeSubmit")
        async def h(ctx):  # type: ignore[no-untyped-def]
            raise ValueError("unexpected problem")

        form = _form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref="f1.onBeforeSubmit"),
            )
        )
        with pytest.raises(ValueError, match="unexpected problem"):
            await dispatch(
                "onBeforeSubmit",
                form=form,
                request=mock_request,
                tenant=None,
                auth_context=auth_context,
                payload={},
            )

    async def test_tenant_fallback_used_in_dispatch(
        self, mock_request: MagicMock, auth_context: None
    ) -> None:
        """dispatch uses tenant for registry lookup with global fallback."""
        calls: list[str] = []

        @register_form_event("f1.onBeforeSubmit")
        async def global_h(ctx):  # type: ignore[no-untyped-def]
            calls.append("global")
            return EventResolution()

        form = _form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref="f1.onBeforeSubmit"),
            )
        )
        await dispatch(
            "onBeforeSubmit",
            form=form,
            request=mock_request,
            tenant="acme",  # no acme-specific handler → falls back to global
            auth_context=auth_context,
            payload={},
        )
        assert calls == ["global"]

    async def test_payload_replacement_returned(
        self, mock_request: MagicMock, auth_context: None
    ) -> None:
        """Handler returning payload override is returned in EventResolution."""
        new_payload = {"email": "normalised@example.com"}

        @register_form_event("f1.onBeforeSubmit")
        async def h(ctx):  # type: ignore[no-untyped-def]
            return EventResolution(payload=new_payload)

        form = _form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref="f1.onBeforeSubmit"),
            )
        )
        result = await dispatch(
            "onBeforeSubmit",
            form=form,
            request=mock_request,
            tenant=None,
            auth_context=auth_context,
            payload={"email": "RAW@EXAMPLE.COM"},
        )
        assert result.payload == new_payload


class TestApplySchemaOverrides:
    """Tests for apply_schema_overrides() helper."""

    def test_shallow_merge_replaces_top_level_key(self) -> None:
        """A top-level key in overrides replaces the same key in base."""
        base = {"a": 1, "b": {"x": 1}}
        result = apply_schema_overrides(base, {"b": {"y": 2}})
        assert result == {"a": 1, "b": {"y": 2}}

    def test_shallow_merge_drops_nested_original(self) -> None:
        """Shallow merge intentionally drops nested keys not in overrides."""
        base = {"title": {"en": "Old", "es": "Viejo"}, "form_id": "f1"}
        result = apply_schema_overrides(base, {"title": {"en": "New"}})
        # "es" is dropped because shallow merge replaces the whole "title" value
        assert result == {"title": {"en": "New"}, "form_id": "f1"}

    def test_does_not_mutate_base(self) -> None:
        """base dict is not modified in-place."""
        base = {"a": 1}
        original_base = dict(base)
        apply_schema_overrides(base, {"a": 2})
        assert base == original_base

    def test_adds_new_keys(self) -> None:
        """Keys present in overrides but not in base are added."""
        base = {"a": 1}
        result = apply_schema_overrides(base, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_empty_overrides_returns_copy_of_base(self) -> None:
        """Empty overrides returns a copy of base unchanged."""
        base = {"a": 1}
        result = apply_schema_overrides(base, {})
        assert result == base
        assert result is not base
