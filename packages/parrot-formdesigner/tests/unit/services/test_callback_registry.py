"""Unit tests for the tenant-scoped callback registry."""

from __future__ import annotations

import pytest

from parrot_formdesigner.services.callback_registry import (
    _CALLBACK_REGISTRY,
    get_form_callback,
    list_form_callbacks,
    register_form_callback,
)


@pytest.fixture(autouse=True)
def clean_registry():
    _CALLBACK_REGISTRY.clear()
    yield
    _CALLBACK_REGISTRY.clear()


def test_register_global():
    @register_form_callback("compute")
    async def fn(payload):
        return None

    assert get_form_callback("compute") is fn


def test_register_tenant_and_fallback():
    @register_form_callback("compute")
    async def global_fn(payload):
        return None

    @register_form_callback("compute", tenant="acme")
    async def tenant_fn(payload):
        return None

    assert get_form_callback("compute", tenant="acme") is tenant_fn
    assert get_form_callback("compute", tenant="other") is global_fn


def test_duplicate_raises():
    @register_form_callback("x")
    async def fn(payload):
        return None

    with pytest.raises(ValueError, match="already registered"):
        register_form_callback("x")(fn)


def test_tenant_named_None_string_rejected():
    with pytest.raises(ValueError, match="collides"):
        register_form_callback("x", tenant="None")


def test_missing_callback_raises_keyerror():
    with pytest.raises(KeyError):
        get_form_callback("missing")


def test_list_includes_tenant_and_global():
    @register_form_callback("a")
    async def g(p):
        return None

    @register_form_callback("b", tenant="acme")
    async def t(p):
        return None

    listed = list_form_callbacks(tenant="acme")
    assert (None, "a") in listed and ("acme", "b") in listed


def test_list_global_only_when_no_tenant():
    @register_form_callback("a")
    async def g(p):
        return None

    @register_form_callback("b", tenant="acme")
    async def t(p):
        return None

    listed = list_form_callbacks()
    assert (None, "a") in listed
    assert ("acme", "b") not in listed


def test_tenant_override_does_not_affect_global_slot():
    @register_form_callback("fn")
    async def global_fn(p):
        return "global"

    @register_form_callback("fn", tenant="acme")
    async def tenant_fn(p):
        return "tenant"

    assert get_form_callback("fn") is global_fn
    assert get_form_callback("fn", tenant="acme") is tenant_fn


def test_decorator_returns_original_function():
    async def my_fn(p):
        return None

    result = register_form_callback("ret_test")(my_fn)
    assert result is my_fn
