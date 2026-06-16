"""Unit tests for TASK-1583 — exclude-provider registration in setup_form_api.

Tests verify that:
- setup_form_api registers an exclude-provider when app["auth"] supports it.
- No error is raised when app["auth"] is absent or lacks add_exclude_provider.
- The registered provider yields paths for is_public=True forms only.
- The provider returns [] when no public forms exist.
- The provider catches list_forms() exceptions and returns [].
- The provider calls load_from_storage() when has_storage=True (startup-ordering
  safety: auth_startup may fire before FormRegistry.on_startup).
- The provider iterates all tenants (multi-tenant correctness).
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot_formdesigner.services.public_forms import public_form_paths


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app_with_auth(*, has_add_exclude_provider: bool = True):
    """Return an aiohttp Application with a mock auth handler."""
    from aiohttp import web

    app = web.Application()
    auth = MagicMock()
    auth.register_exclusions = MagicMock()
    if has_add_exclude_provider:
        auth.add_exclude_provider = MagicMock()
    else:
        # simulate old navigator-auth that lacks the method
        del auth.add_exclude_provider
    app["auth"] = auth
    return app, auth


def _make_registry(*, forms=None):
    """Return a mock FormRegistry."""
    registry = MagicMock()
    registry.list_forms = AsyncMock(return_value=forms or [])
    registry.set_public_toggle_callback = MagicMock()
    return registry


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestExcludeProviderRegistration:
    def test_provider_registered_when_auth_present(self):
        """setup_form_api registers a provider when app['auth'] has add_exclude_provider."""
        from parrot_formdesigner.api.routes import setup_form_api
        from parrot_formdesigner.services.registry import FormRegistry

        app, auth = _make_app_with_auth()
        registry = FormRegistry(require_tenant=False)

        setup_form_api(app, registry)

        auth.add_exclude_provider.assert_called_once()
        # The argument must be a callable (the provider function)
        provider = auth.add_exclude_provider.call_args[0][0]
        assert callable(provider)

    def test_no_error_when_auth_absent(self):
        """setup_form_api must not raise when app has no 'auth' key."""
        from aiohttp import web
        from parrot_formdesigner.api.routes import setup_form_api
        from parrot_formdesigner.services.registry import FormRegistry

        app = web.Application()
        registry = FormRegistry(require_tenant=False)

        setup_form_api(app, registry)  # must not raise

    def test_no_error_when_auth_lacks_add_exclude_provider(self):
        """setup_form_api degrades gracefully when auth lacks add_exclude_provider."""
        from parrot_formdesigner.api.routes import setup_form_api
        from parrot_formdesigner.services.registry import FormRegistry

        app, auth = _make_app_with_auth(has_add_exclude_provider=False)
        registry = FormRegistry(require_tenant=False)

        setup_form_api(app, registry)  # must not raise
        # add_exclude_provider was NOT called (because it doesn't exist)
        assert not hasattr(auth, "add_exclude_provider")


# ---------------------------------------------------------------------------
# Provider behaviour tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExcludeProviderBehavior:
    """Test the async provider function registered by setup_form_api."""

    async def _get_provider(self, forms):
        """Helper: call setup_form_api and extract the registered provider.

        Stubs out has_storage (False), list_tenants (["default"]) and
        list_forms so the provider exercises the tenant-iteration path
        without touching any real storage.
        """
        from parrot_formdesigner.api.routes import setup_form_api
        from parrot_formdesigner.services.registry import FormRegistry

        app, auth = _make_app_with_auth()
        registry = FormRegistry(require_tenant=False)
        # No storage → skip load_from_storage() call.
        # list_tenants returns one sentinel tenant so the loop fires.
        registry.list_tenants = AsyncMock(return_value=["default"])
        registry.list_forms = AsyncMock(return_value=forms)

        setup_form_api(app, registry)

        assert auth.add_exclude_provider.called
        provider = auth.add_exclude_provider.call_args[0][0]
        return provider

    async def test_provider_yields_public_form_paths(self):
        """Provider returns exactly the 5 patterns for each is_public=True form."""
        from parrot_formdesigner.core.schema import FormSchema

        forms = [
            FormSchema(form_id="pub", title="Public", sections=[], is_public=True),
            FormSchema(form_id="priv", title="Private", sections=[], is_public=False),
        ]
        provider = await self._get_provider(forms)

        paths = await provider()

        assert len(paths) == 5
        assert all("/forms/pub" in p for p in paths)
        assert not any("/forms/priv" in p for p in paths)

    async def test_provider_includes_expected_patterns(self):
        """Provider returns the five specific URL patterns defined by public_form_paths."""
        from parrot_formdesigner.core.schema import FormSchema

        forms = [
            FormSchema(form_id="contact", title="Contact", sections=[], is_public=True),
        ]
        provider = await self._get_provider(forms)

        paths = await provider()
        expected = public_form_paths("contact", base_path="/api/v1")

        assert set(paths) == set(expected)

    async def test_provider_empty_when_no_public_forms(self):
        """Provider returns [] when no forms have is_public=True."""
        from parrot_formdesigner.core.schema import FormSchema

        forms = [
            FormSchema(form_id="priv", title="Private", sections=[], is_public=False),
        ]
        provider = await self._get_provider(forms)

        paths = await provider()

        assert paths == []

    async def test_provider_empty_when_no_forms(self):
        """Provider returns [] when registry has no forms at all."""
        provider = await self._get_provider([])

        paths = await provider()

        assert paths == []

    async def test_provider_handles_list_forms_exception(self):
        """Provider returns [] when list_forms() raises — does not propagate."""
        from parrot_formdesigner.api.routes import setup_form_api
        from parrot_formdesigner.services.registry import FormRegistry

        app, auth = _make_app_with_auth()
        registry = FormRegistry(require_tenant=False)
        registry.list_tenants = AsyncMock(return_value=["default"])
        registry.list_forms = AsyncMock(side_effect=RuntimeError("DB down"))

        setup_form_api(app, registry)

        provider = auth.add_exclude_provider.call_args[0][0]

        # Must not raise — provider swallows the exception
        paths = await provider()
        assert paths == []

    async def test_provider_multiple_public_forms(self):
        """Provider yields paths for each is_public=True form."""
        from parrot_formdesigner.core.schema import FormSchema

        forms = [
            FormSchema(form_id="form-a", title="A", sections=[], is_public=True),
            FormSchema(form_id="form-b", title="B", sections=[], is_public=True),
            FormSchema(form_id="form-c", title="C", sections=[], is_public=False),
        ]
        provider = await self._get_provider(forms)

        paths = await provider()

        # 2 public forms × 5 paths each
        assert len(paths) == 10
        assert any("/forms/form-a" in p for p in paths)
        assert any("/forms/form-b" in p for p in paths)
        assert not any("/forms/form-c" in p for p in paths)


# ---------------------------------------------------------------------------
# Startup-ordering safety tests (issue #1 from code review)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExcludeProviderStartupOrdering:
    """Verify the provider handles startup-ordering races correctly.

    auth_startup (which calls providers) may fire before FormRegistry.on_startup
    (which loads forms from DB) because aiohttp on_startup hooks are called in
    FIFO registration order.  The provider must call load_from_storage() itself
    when a backend is configured so it returns the correct results even in that
    scenario.
    """

    async def test_provider_calls_load_from_storage_when_has_storage(self):
        """Provider calls registry.load_from_storage() when has_storage=True."""
        from parrot_formdesigner.api.routes import setup_form_api
        from parrot_formdesigner.services.registry import FormRegistry
        from parrot_formdesigner.core.schema import FormSchema

        app, auth = _make_app_with_auth()
        registry = FormRegistry(require_tenant=False)

        # Simulate a storage backend being configured (has_storage=True).
        mock_storage = MagicMock()
        registry._storage = mock_storage
        # load_from_storage is the async method that reads from DB.
        registry.load_from_storage = AsyncMock(return_value=0)
        # list_tenants and list_forms return the forms as if already loaded.
        forms = [
            FormSchema(form_id="pub", title="Public", sections=[], is_public=True),
        ]
        registry.list_tenants = AsyncMock(return_value=["navigator"])
        registry.list_forms = AsyncMock(return_value=forms)

        setup_form_api(app, registry)
        provider = auth.add_exclude_provider.call_args[0][0]

        paths = await provider()

        # load_from_storage must have been called to handle ordering race.
        registry.load_from_storage.assert_awaited_once()
        assert len(paths) == 5
        assert all("/forms/pub" in p for p in paths)

    async def test_provider_skips_load_when_no_storage(self):
        """Provider does NOT call load_from_storage when has_storage=False."""
        from parrot_formdesigner.api.routes import setup_form_api
        from parrot_formdesigner.services.registry import FormRegistry

        app, auth = _make_app_with_auth()
        registry = FormRegistry(require_tenant=False)
        # No storage backend: has_storage=False
        registry.load_from_storage = AsyncMock()
        registry.list_tenants = AsyncMock(return_value=[])
        registry.list_forms = AsyncMock(return_value=[])

        setup_form_api(app, registry)
        provider = auth.add_exclude_provider.call_args[0][0]

        paths = await provider()

        registry.load_from_storage.assert_not_awaited()
        assert paths == []

    async def test_provider_iterates_all_tenants(self):
        """Provider collects public forms from all tenants, not just default."""
        from parrot_formdesigner.api.routes import setup_form_api
        from parrot_formdesigner.services.registry import FormRegistry
        from parrot_formdesigner.core.schema import FormSchema

        app, auth = _make_app_with_auth()
        registry = FormRegistry(require_tenant=False)
        registry.load_from_storage = AsyncMock(return_value=0)
        registry._storage = MagicMock()  # has_storage=True

        tenant_forms = {
            "navigator": [
                FormSchema(form_id="nav-form", title="Nav", sections=[], is_public=True),
            ],
            "epson": [
                FormSchema(form_id="epson-form", title="Epson", sections=[], is_public=True),
            ],
        }
        registry.list_tenants = AsyncMock(return_value=list(tenant_forms.keys()))
        registry.list_forms = AsyncMock(
            side_effect=lambda tenant: tenant_forms.get(tenant, [])
        )

        setup_form_api(app, registry)
        provider = auth.add_exclude_provider.call_args[0][0]

        paths = await provider()

        # 2 tenants × 1 public form × 5 paths = 10
        assert len(paths) == 10
        assert any("/forms/nav-form" in p for p in paths)
        assert any("/forms/epson-form" in p for p in paths)
