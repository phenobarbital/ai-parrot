"""Unit tests for parrot_formdesigner.services.callback_registry."""

from __future__ import annotations

import pytest

from parrot_formdesigner.services.callback_registry import (
    _CALLBACK_REGISTRY,
    get_form_callback,
    list_form_callbacks,
    register_form_callback,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_registry():
    """Ensure a clean registry for every test."""
    _CALLBACK_REGISTRY.clear()
    yield
    _CALLBACK_REGISTRY.clear()


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


def test_register_global():
    """@register_form_callback without tenant registers a global entry."""

    @register_form_callback("compute")
    async def fn(payload, auth_context):
        return None

    assert get_form_callback("compute") is fn


def test_register_tenant_specific():
    """@register_form_callback with tenant registers a tenant entry."""

    @register_form_callback("compute", tenant="acme")
    async def fn(payload, auth_context):
        return None

    assert (("acme", "compute") in _CALLBACK_REGISTRY)


def test_register_global_and_tenant():
    """Both global and tenant entries can coexist for the same name."""

    @register_form_callback("compute")
    async def global_fn(payload, auth_context):
        return None

    @register_form_callback("compute", tenant="acme")
    async def tenant_fn(payload, auth_context):
        return None

    assert (None, "compute") in _CALLBACK_REGISTRY
    assert ("acme", "compute") in _CALLBACK_REGISTRY


def test_duplicate_global_raises():
    """Re-registering the same global name raises ValueError."""

    @register_form_callback("x")
    async def fn(payload, auth_context):
        return None

    with pytest.raises(ValueError, match="already registered"):
        register_form_callback("x")(fn)


def test_duplicate_tenant_raises():
    """Re-registering the same (tenant, name) raises ValueError."""

    @register_form_callback("x", tenant="acme")
    async def fn(payload, auth_context):
        return None

    with pytest.raises(ValueError, match="already registered"):
        register_form_callback("x", tenant="acme")(fn)


def test_tenant_named_none_string_rejected():
    """tenant='None' (string) is rejected — collides with the global sentinel."""
    with pytest.raises(ValueError, match="collides"):
        register_form_callback("x", tenant="None")


# ---------------------------------------------------------------------------
# Lookup tests
# ---------------------------------------------------------------------------


def test_get_returns_tenant_entry():
    """get_form_callback returns the tenant-specific entry when it exists."""

    @register_form_callback("compute")
    async def global_fn(payload, auth_context):
        return None

    @register_form_callback("compute", tenant="acme")
    async def tenant_fn(payload, auth_context):
        return None

    assert get_form_callback("compute", tenant="acme") is tenant_fn


def test_get_falls_back_to_global():
    """get_form_callback falls back to the global entry for unknown tenants."""

    @register_form_callback("compute")
    async def global_fn(payload, auth_context):
        return None

    # tenant "other" has no entry — falls back to global
    assert get_form_callback("compute", tenant="other") is global_fn


def test_get_missing_callback_raises_keyerror():
    """get_form_callback raises KeyError when no entry is found."""
    with pytest.raises(KeyError):
        get_form_callback("missing")


def test_get_missing_tenant_and_global_raises_keyerror():
    """KeyError when neither tenant-specific nor global entry exists."""
    # Only a different-name global exists
    @register_form_callback("something_else")
    async def fn(p, a):
        return None

    with pytest.raises(KeyError):
        get_form_callback("missing", tenant="acme")


def test_get_without_tenant_returns_global():
    """get_form_callback without tenant returns the global entry."""

    @register_form_callback("compute")
    async def fn(payload, auth_context):
        return None

    assert get_form_callback("compute") is fn


# ---------------------------------------------------------------------------
# List tests
# ---------------------------------------------------------------------------


def test_list_without_tenant_returns_only_globals():
    """list_form_callbacks() returns only global entries when tenant=None."""

    @register_form_callback("a")
    async def g(p, a):
        return None

    @register_form_callback("b", tenant="acme")
    async def t(p, a):
        return None

    listed = list_form_callbacks()
    assert (None, "a") in listed
    assert ("acme", "b") not in listed


def test_list_with_tenant_includes_both():
    """list_form_callbacks(tenant=...) returns tenant + global entries."""

    @register_form_callback("a")
    async def g(p, a):
        return None

    @register_form_callback("b", tenant="acme")
    async def t(p, a):
        return None

    listed = list_form_callbacks(tenant="acme")
    assert (None, "a") in listed
    assert ("acme", "b") in listed


def test_list_empty_registry():
    """list_form_callbacks returns empty list on empty registry."""
    assert list_form_callbacks() == []
    assert list_form_callbacks(tenant="acme") == []


# ---------------------------------------------------------------------------
# Decorator return value
# ---------------------------------------------------------------------------


def test_decorator_returns_function_unchanged():
    """The decorator returns the original function (transparent wrapping)."""

    async def my_fn(p, a):
        return None

    result = register_form_callback("unchanged")(my_fn)
    assert result is my_fn
