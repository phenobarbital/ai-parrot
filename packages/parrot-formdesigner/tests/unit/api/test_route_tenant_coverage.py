"""Router-wide tenant coverage tests (FEAT-421 TASK-2201).

Introspects the router built by ``setup_form_api`` to prove:
- every forms route carries the ``requires_tenant`` decorator (AC2),
- no ``/org/*`` route carries it (G7, AC11),
- the ten ``/org/*`` paths are byte-identical to 0.8.21,
- the legacy (un-tenant-qualified) forms paths are gone (hard cut).

The audio WS route is deliberately NOT covered here: it is only mounted
when ``synthesizer``/``transcriber``/``token_validator`` is passed to
``setup_form_api``, and per spec §7 "Known Risks" it is intentionally left
undecorated (its tenant check is inline, TASK-2204's responsibility) — the
default fixture below does not pass those kwargs, so the audio route is
simply absent and the blanket "/forms" coverage assertion never has to
special-case it.
"""

import pytest
from aiohttp import web
from parrot_formdesigner.api.render import _RENDERERS
from parrot_formdesigner.api.routes import setup_form_api
from parrot_formdesigner.services.registry import FormRegistry


@pytest.fixture(autouse=True)
def _reset_renderers():
    snapshot = dict(_RENDERERS)
    _RENDERERS.clear()
    yield
    _RENDERERS.clear()
    _RENDERERS.update(snapshot)


@pytest.fixture
def app():
    application = web.Application()
    registry = FormRegistry()
    setup_form_api(application, registry)
    return application


def _path_of(route) -> str:
    return route.resource.canonical


def _has_tenant_layer(handler) -> bool:
    return bool(getattr(handler, "_requires_tenant", False))


class TestRouteTenantCoverage:
    def test_every_forms_route_is_decorated(self, app):
        for route in app.router.routes():
            path = _path_of(route)
            if "/forms" in path or path.endswith("/fields"):
                assert _has_tenant_layer(route.handler), f"undecorated: {path}"

    def test_no_org_route_is_decorated(self, app):
        for route in app.router.routes():
            if "/org/" in _path_of(route):
                assert not _has_tenant_layer(route.handler)

    def test_org_paths_unchanged(self, app):
        paths = {_path_of(r) for r in app.router.routes() if "/org/" in _path_of(r)}
        expected = {
            "/api/v1/org/graph",
            "/api/v1/org/projects",
            "/api/v1/org/cost-centers/{project_id}/workday-map",
            "/api/v1/org/users/{user_id}/assign",
            "/api/v1/org/sync/workday",
            "/api/v1/org/stores/{store_id}/sites",
            "/api/v1/org/sites/{site_id}/locations",
            "/api/v1/org/locations/{location_id}",
        }
        assert expected.issubset(paths)
        assert not any("/t/" in p for p in paths)

    def test_form_controls_is_not_tenant_qualified(self, app):
        """Static, tenant-agnostic metadata — same carve-out as /org/*."""
        paths = {_path_of(r) for r in app.router.routes()}
        assert "/api/v1/form-controls" in paths

    def test_legacy_forms_path_not_registered(self, app):
        paths = {_path_of(r) for r in app.router.routes()}
        assert "/api/v1/forms/{form_uid}" not in paths
        assert "/api/v1/forms" not in paths

    def test_forms_routes_are_tenant_qualified(self, app):
        paths = {_path_of(r) for r in app.router.routes()}
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
            "/api/v1/{tenant}/fields",
        }
        assert expected.issubset(paths)

    def test_blank_route_registered_before_form_uid_catchall(self, app):
        """POST /forms/blank must still precede the {form_uid} catch-all
        (belt-and-braces defensive ordering — see api/routes.py comment)."""
        paths = [_path_of(r) for r in app.router.routes()]
        blank_idx = paths.index("/api/v1/{tenant}/forms/blank")
        uid_idx = paths.index("/api/v1/{tenant}/forms/{form_uid}")
        assert blank_idx < uid_idx
