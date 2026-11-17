"""Unit tests for ``parrot_formdesigner.api.setup_form_api``."""

from __future__ import annotations

import pytest
from aiohttp import web
from parrot_formdesigner.api import setup_form_api
from parrot_formdesigner.api.render import _RENDERERS
from parrot_formdesigner.services.registry import FormRegistry


@pytest.fixture(autouse=True)
def _reset_renderers():
    snapshot = dict(_RENDERERS)
    _RENDERERS.clear()
    yield
    _RENDERERS.clear()
    _RENDERERS.update(snapshot)


def test_setup_mounts_routes_and_registers_form_registry():
    app = web.Application()
    registry = FormRegistry()
    setup_form_api(app, registry)
    assert app["form_registry"] is registry

    paths = {r.resource.canonical for r in app.router.routes()}
    expected = {
        "/api/v1/{tenant}/forms",
        "/api/v1/{tenant}/forms/from-db",
        "/api/v1/{tenant}/forms/blank",
        "/api/v1/{tenant}/forms/{form_uid}",
        "/api/v1/{tenant}/forms/{form_uid}/schema",
        "/api/v1/{tenant}/forms/{form_uid}/style",
        "/api/v1/{tenant}/forms/{form_uid}/render/{format}",
        "/api/v1/{tenant}/forms/{form_uid}/validate",
        "/api/v1/{tenant}/forms/{form_uid}/data",
        "/api/v1/{tenant}/forms/{form_uid}/operations",
        "/api/v1/form-controls",
    }
    assert expected.issubset(paths)


def test_setup_seeds_default_renderers():
    app = web.Application()
    registry = FormRegistry()
    setup_form_api(app, registry)
    assert "html" in _RENDERERS
    assert "adaptive" in _RENDERERS


def test_setup_with_custom_base_path():
    app = web.Application()
    registry = FormRegistry()
    setup_form_api(app, registry, base_path="/custom/v2")
    paths = {r.resource.canonical for r in app.router.routes()}
    assert "/custom/v2/{tenant}/forms" in paths
    assert "/custom/v2/form-controls" in paths


class TestTeamsSigningSecret:
    """FEAT-733 — the producing side must be able to sign through the documented entry point."""

    def test_setup_form_api_forwards_signing_secret(self, monkeypatch):
        """setup_form_api(teams_signing_secret=...) -> the registered renderer carries it."""
        monkeypatch.setenv("FORMDESIGNER_TEAMS_SIGNING_SECRET", "from-env")
        app = web.Application()
        registry = FormRegistry()
        setup_form_api(
            app,
            registry,
            public_base_url="https://forms.test",
            teams_signing_secret="s3cret",
        )

        assert _RENDERERS["teams"].signing_secret == "s3cret"

    def test_setup_form_api_signing_secret_from_env(self, monkeypatch):
        """FORMDESIGNER_TEAMS_SIGNING_SECRET is used when the argument is omitted."""
        monkeypatch.setenv("FORMDESIGNER_TEAMS_SIGNING_SECRET", "from-env")
        app = web.Application()
        registry = FormRegistry()
        setup_form_api(app, registry, public_base_url="https://forms.test")

        assert _RENDERERS["teams"].signing_secret == "from-env"

    def test_setup_form_api_explicit_renderer_still_wins(self):
        """An explicit teams_renderer= is registered as-is; the secret argument does not replace it."""
        sentinel_renderer = object()
        app = web.Application()
        registry = FormRegistry()
        setup_form_api(
            app,
            registry,
            teams_renderer=sentinel_renderer,
            teams_signing_secret="ignored",
        )

        assert _RENDERERS["teams"] is sentinel_renderer
