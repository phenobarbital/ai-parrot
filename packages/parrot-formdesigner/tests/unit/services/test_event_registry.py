"""Unit tests for parrot_formdesigner.services.event_registry — FEAT-188.

Tests cover all public functions of the tenant-scoped event registry
created by TASK-1266: registration, lookup with fallback, listing, and
the test-helper clear function.
"""

import pytest

from parrot_formdesigner.core.events import EventResolution
from parrot_formdesigner.services.event_registry import (
    _clear_event_registry_for_tests,
    get_form_event,
    list_form_events,
    register_form_event,
)


@pytest.fixture(autouse=True)
def _clear_registry() -> None:  # type: ignore[return]
    """Isolate registry state between tests."""
    yield
    _clear_event_registry_for_tests()


class TestRegisterFormEvent:
    """Tests for register_form_event decorator."""

    async def test_global_registration_and_lookup(self) -> None:
        """A globally-registered handler is retrievable by handler_ref."""

        @register_form_event("survey_v1.onBeforeSubmit")
        async def h(ctx):  # type: ignore[no-untyped-def]
            return EventResolution()

        assert get_form_event("survey_v1.onBeforeSubmit") is h

    async def test_tenant_specific_registration(self) -> None:
        """A tenant-specific handler is retrievable by (tenant, handler_ref)."""

        @register_form_event("a.b", tenant="acme")
        async def acme_h(ctx):  # type: ignore[no-untyped-def]
            return EventResolution()

        assert get_form_event("a.b", tenant="acme") is acme_h

    async def test_tenant_overrides_global(self) -> None:
        """Tenant-specific registration shadows the global entry for that tenant."""

        @register_form_event("a.b")
        async def global_h(ctx):  # type: ignore[no-untyped-def]
            return EventResolution()

        @register_form_event("a.b", tenant="acme")
        async def acme_h(ctx):  # type: ignore[no-untyped-def]
            return EventResolution()

        assert get_form_event("a.b", tenant="acme") is acme_h
        assert get_form_event("a.b", tenant="other") is global_h
        assert get_form_event("a.b") is global_h

    def test_duplicate_raises_value_error(self) -> None:
        """Registering the same (tenant, handler_ref) twice raises ValueError."""

        @register_form_event("a.b")
        async def first(ctx):  # type: ignore[no-untyped-def]
            return EventResolution()

        with pytest.raises(ValueError, match="already registered"):

            @register_form_event("a.b")
            async def second(ctx):  # type: ignore[no-untyped-def]
                return EventResolution()

    def test_sync_handler_rejected(self) -> None:
        """Synchronous handlers are rejected with TypeError."""
        with pytest.raises(TypeError, match="async"):

            @register_form_event("a.b")
            def sync_h(ctx):  # type: ignore[no-untyped-def]
                return None

    def test_tenant_string_none_rejected(self) -> None:
        """Literal string 'None' as tenant is rejected (collision with sentinel)."""
        with pytest.raises(ValueError, match="None"):

            @register_form_event("a.b", tenant="None")
            async def h(ctx):  # type: ignore[no-untyped-def]
                return None

    def test_returns_original_function(self) -> None:
        """The decorator returns the original function unchanged."""

        @register_form_event("x.y")
        async def handler(ctx):  # type: ignore[no-untyped-def]
            return None

        # Should still be callable and the same object
        assert callable(handler)
        assert handler.__name__ == "handler"


class TestGetFormEvent:
    """Tests for get_form_event lookup function."""

    def test_missing_handler_raises_key_error(self) -> None:
        """Looking up an unregistered handler_ref raises KeyError."""
        with pytest.raises(KeyError):
            get_form_event("does.not.exist")

    async def test_global_lookup_without_tenant(self) -> None:
        """get_form_event with no tenant returns the global handler."""

        @register_form_event("form.event")
        async def h(ctx):  # type: ignore[no-untyped-def]
            return None

        assert get_form_event("form.event", tenant=None) is h

    async def test_tenant_fallback_to_global(self) -> None:
        """When no tenant-specific handler exists, falls back to global."""

        @register_form_event("f.g")
        async def global_h(ctx):  # type: ignore[no-untyped-def]
            return EventResolution()

        assert get_form_event("f.g", tenant="acme") is global_h

    async def test_tenant_specific_shadow(self) -> None:
        """Tenant-specific handler takes precedence over global."""

        @register_form_event("f.g")
        async def global_h(ctx):  # type: ignore[no-untyped-def]
            return EventResolution()

        @register_form_event("f.g", tenant="acme")
        async def acme_h(ctx):  # type: ignore[no-untyped-def]
            return EventResolution()

        result = get_form_event("f.g", tenant="acme")
        assert result is acme_h
        assert result is not global_h


class TestListFormEvents:
    """Tests for list_form_events introspection helper."""

    async def test_returns_global_entries_only_when_no_tenant(self) -> None:
        """With no tenant, only global entries are listed."""

        @register_form_event("g.h")
        async def h(ctx):  # type: ignore[no-untyped-def]
            return None

        @register_form_event("i.j", tenant="acme")
        async def acme_h(ctx):  # type: ignore[no-untyped-def]
            return None

        entries = list_form_events()
        assert (None, "g.h") in entries
        assert ("acme", "i.j") not in entries

    async def test_returns_global_and_tenant_entries(self) -> None:
        """With a tenant, both global and tenant-specific entries are listed."""

        @register_form_event("g.h")
        async def global_h(ctx):  # type: ignore[no-untyped-def]
            return None

        @register_form_event("i.j", tenant="acme")
        async def acme_h(ctx):  # type: ignore[no-untyped-def]
            return None

        entries = list_form_events(tenant="acme")
        assert (None, "g.h") in entries
        assert ("acme", "i.j") in entries

    async def test_excludes_other_tenants_entries(self) -> None:
        """Other tenants' entries are not returned."""

        @register_form_event("f.g", tenant="other")
        async def other_h(ctx):  # type: ignore[no-untyped-def]
            return None

        entries = list_form_events(tenant="acme")
        assert ("other", "f.g") not in entries

    def test_empty_when_nothing_registered(self) -> None:
        """Returns empty list when registry is empty."""
        assert list_form_events() == []


class TestClearEventRegistryForTests:
    """Tests for _clear_event_registry_for_tests helper."""

    async def test_clears_all_entries(self) -> None:
        """After clear, all previously registered entries are gone."""

        @register_form_event("x.y")
        async def h(ctx):  # type: ignore[no-untyped-def]
            return None

        _clear_event_registry_for_tests()
        with pytest.raises(KeyError):
            get_form_event("x.y")
