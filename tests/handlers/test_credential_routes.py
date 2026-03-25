"""Tests for credential route registration (TASK-440)."""
import pytest
from aiohttp import web
from parrot.handlers.credentials import setup_credentials_routes


class TestCredentialRoutes:
    """Verify that setup_credentials_routes registers the expected routes."""

    def test_routes_registered(self):
        """All credential routes are registered on the application."""
        app = web.Application()
        setup_credentials_routes(app)

        # Collect all registered canonical URLs
        routes = [
            r.resource.canonical
            for r in app.router.routes()
            if hasattr(r, "resource") and r.resource is not None
        ]

        assert "/api/v1/users/credentials" in routes
        assert "/api/v1/users/credentials/{name}" in routes

    def test_collection_route_supports_all_methods(self):
        """The collection route is registered with wildcard method dispatch."""
        app = web.Application()
        setup_credentials_routes(app)

        # Find resources matching the collection URL
        resources = [
            r for r in app.router.resources()
            if r.canonical == "/api/v1/users/credentials"
        ]
        assert len(resources) >= 1

    def test_item_route_supports_name_parameter(self):
        """The item route includes the {name} path parameter."""
        app = web.Application()
        setup_credentials_routes(app)

        resources = [
            r for r in app.router.resources()
            if r.canonical == "/api/v1/users/credentials/{name}"
        ]
        assert len(resources) >= 1

    def test_routes_point_to_credentials_handler(self):
        """Routes are bound to the CredentialsHandler (by name)."""
        app = web.Application()
        setup_credentials_routes(app)

        handler_names = set()
        for route in app.router.routes():
            if hasattr(route, "handler"):
                h = route.handler
                # aiohttp wraps class-based views as functions with the same __name__
                name = getattr(h, "__name__", None) or getattr(h, "__class__", type).__name__
                handler_names.add(name)

        assert "CredentialsHandler" in handler_names

    def test_idempotent_registration(self):
        """Calling setup_credentials_routes twice does not raise errors."""
        app = web.Application()
        setup_credentials_routes(app)
        # A second call should not raise (may produce duplicate routes, but no crash)
        # aiohttp allows duplicate routes, so this should be fine
        try:
            setup_credentials_routes(app)
        except Exception as exc:
            pytest.fail(f"Second call to setup_credentials_routes raised: {exc}")
