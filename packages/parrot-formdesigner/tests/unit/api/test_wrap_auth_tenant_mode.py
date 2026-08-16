"""Tests for the tenant mode on _wrap_auth / _page_wrap (FEAT-421 TASK-2200)."""

import pytest
from parrot_formdesigner.api.routes import _wrap_auth
from parrot_formdesigner.ui.routes import _page_wrap


async def _handler(request):
    return "ok"


def _has_tenant_layer(wrapped) -> bool:
    """Read the marker attribute set by _wrap_auth / _page_wrap.

    Prefer this explicit attribute over trying to walk ``__wrapped__``
    chains through navigator-auth's decorators, which are not guaranteed
    to preserve wrapper identity.
    """
    return bool(getattr(wrapped, "_requires_tenant", False))


class TestWrapAuthTenantMode:
    def test_defaults_to_required(self):
        """Silence must protect, not expose."""
        wrapped = _wrap_auth(_handler)
        assert _has_tenant_layer(wrapped) is True

    def test_public_mode_applies_layer(self):
        assert _has_tenant_layer(_wrap_auth(_handler, tenant="public")) is True

    def test_none_mode_skips_layer(self):
        assert _has_tenant_layer(_wrap_auth(_handler, tenant="none")) is False

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="tenant must be one of"):
            _wrap_auth(_handler, tenant="bogus")


class TestPageWrapTenantMode:
    def test_unprotected_page_still_gets_tenant_layer(self):
        """fieldsync runs protect_pages=False — the early return must not
        skip tenant validation (ui/routes.py:47-48)."""
        wrapped = _page_wrap(_handler, protect=False, tenant="required")
        assert _has_tenant_layer(wrapped) is True

    def test_protected_page_gets_tenant_layer(self):
        wrapped = _page_wrap(_handler, protect=True, tenant="required")
        assert _has_tenant_layer(wrapped) is True

    def test_none_mode_skips_layer_even_unprotected(self):
        wrapped = _page_wrap(_handler, protect=False, tenant="none")
        assert _has_tenant_layer(wrapped) is False

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="tenant must be one of"):
            _page_wrap(_handler, protect=False, tenant="bogus")
