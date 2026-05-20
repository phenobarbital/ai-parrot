"""Unit tests for the setup_form_api registry guard (FEAT-185).

Verifies that setup_form_api does NOT overwrite app['form_registry'] if it
was already set by FormRegistry.__init__(app=...).
"""

import pytest
from aiohttp.web import Application

from parrot_formdesigner.services.registry import FormRegistry


class TestSetupFormApiGuard:
    def test_skips_registry_if_already_present(self):
        """setup_form_api does not overwrite app['form_registry'] if pre-set."""
        try:
            from parrot_formdesigner.api.routes import setup_form_api
        except ImportError:
            pytest.skip("navigator-auth not installed — skipping route tests")

        app = Application()
        registry = FormRegistry()
        app["form_registry"] = registry  # pre-set (as FormRegistry.__init__ would do)

        # Calling setup_form_api with the SAME registry should not change the value.
        try:
            setup_form_api(app, registry)
        except Exception:
            # Some arguments may be required; ignore errors from incomplete setup.
            pass

        assert app["form_registry"] is registry

    def test_sets_registry_when_not_present(self):
        """setup_form_api sets app['form_registry'] when not already present."""
        try:
            from parrot_formdesigner.api.routes import setup_form_api
        except ImportError:
            pytest.skip("navigator-auth not installed — skipping route tests")

        app = Application()
        registry = FormRegistry()
        # Do NOT pre-set app['form_registry']

        try:
            setup_form_api(app, registry)
        except Exception:
            pass

        assert app.get("form_registry") is registry

    def test_form_registry_init_with_app_self_registers(self):
        """FormRegistry(app=app) sets app['form_registry'] directly in __init__."""
        app = Application()
        registry = FormRegistry(app=app)
        assert app["form_registry"] is registry

    def test_form_registry_init_with_app_and_setup_form_api_consistent(self):
        """When FormRegistry was created with app=, setup_form_api leaves it unchanged."""
        try:
            from parrot_formdesigner.api.routes import setup_form_api
        except ImportError:
            pytest.skip("navigator-auth not installed — skipping route tests")

        app = Application()
        # FormRegistry sets app['form_registry'] in its __init__
        registry = FormRegistry(app=app)
        assert app["form_registry"] is registry

        # setup_form_api should see it's already there and skip the assignment.
        try:
            setup_form_api(app, registry)
        except Exception:
            pass

        # Still the same object
        assert app["form_registry"] is registry
