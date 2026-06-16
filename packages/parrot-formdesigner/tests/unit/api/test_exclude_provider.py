"""Unit tests for TASK-1583 — exclude-provider registration in setup_form_api.

Tests verify that:
- setup_form_api registers an exclude-provider when app["auth"] supports it.
- No error is raised when app["auth"] is absent or lacks add_exclude_provider.
- The registered provider yields paths for is_public=True forms only.
- The provider returns [] when no public forms exist.
- The provider catches list_forms() exceptions and returns [].
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
        """Helper: call setup_form_api and extract the registered provider."""
        from parrot_formdesigner.api.routes import setup_form_api
        from parrot_formdesigner.services.registry import FormRegistry

        app, auth = _make_app_with_auth()
        registry = FormRegistry(require_tenant=False)
        # Patch list_forms to return our test forms
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
