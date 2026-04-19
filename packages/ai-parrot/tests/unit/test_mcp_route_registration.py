"""Unit tests for MCP helper route registration (TASK-773)."""
from __future__ import annotations

import pytest


class TestMCPRouteRegistration:
    """Tests for setup_mcp_helper_routes and route registration."""

    def test_setup_mcp_helper_routes_importable(self) -> None:
        """Verify setup function can be imported from the correct module."""
        from parrot.handlers.mcp_helper import setup_mcp_helper_routes
        assert callable(setup_mcp_helper_routes)

    def test_routes_registered_in_app(self) -> None:
        """Verify routes are added to an aiohttp application."""
        from aiohttp import web
        from parrot.handlers.mcp_helper import setup_mcp_helper_routes

        app = web.Application()
        setup_mcp_helper_routes(app)

        routes = [r.resource.canonical for r in app.router.routes()
                  if hasattr(r, 'resource')]
        assert any("mcp-servers" in r for r in routes)

    def test_catalog_route_registered(self) -> None:
        """GET /mcp-servers base route is registered."""
        from aiohttp import web
        from parrot.handlers.mcp_helper import setup_mcp_helper_routes

        app = web.Application()
        setup_mcp_helper_routes(app)

        routes = [r.resource.canonical for r in app.router.routes()
                  if hasattr(r, 'resource')]
        # Base route: /api/v1/agents/chat/{agent_id}/mcp-servers
        assert any(
            "mcp-servers" in r and "active" not in r and "server_name" not in r
            for r in routes
        )

    def test_active_route_registered(self) -> None:
        """/mcp-servers/active route is registered."""
        from aiohttp import web
        from parrot.handlers.mcp_helper import setup_mcp_helper_routes

        app = web.Application()
        setup_mcp_helper_routes(app)

        routes = [r.resource.canonical for r in app.router.routes()
                  if hasattr(r, 'resource')]
        assert any("active" in r for r in routes)

    def test_delete_route_registered(self) -> None:
        """/mcp-servers/{server_name} delete route is registered."""
        from aiohttp import web
        from parrot.handlers.mcp_helper import setup_mcp_helper_routes

        app = web.Application()
        setup_mcp_helper_routes(app)

        routes = [r.resource.canonical for r in app.router.routes()
                  if hasattr(r, 'resource')]
        assert any("server_name" in r for r in routes)

    def test_four_routes_total(self) -> None:
        """Exactly four MCP helper routes are registered."""
        from aiohttp import web
        from parrot.handlers.mcp_helper import setup_mcp_helper_routes

        app = web.Application()
        setup_mcp_helper_routes(app)

        mcp_routes = [r for r in app.router.routes()
                      if hasattr(r, 'resource') and "mcp-servers" in r.resource.canonical]
        assert len(mcp_routes) == 4

    def test_setup_mcp_helper_routes_in_manager_import(self) -> None:
        """Verify setup_mcp_helper_routes is imported in manager.py."""
        import os

        manager_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..",
            "src", "parrot", "manager", "manager.py",
        )
        with open(os.path.abspath(manager_path)) as f:
            content = f.read()

        assert "setup_mcp_helper_routes" in content, (
            "setup_mcp_helper_routes not found in manager.py"
        )

    def test_setup_mcp_helper_routes_called_in_manager(self) -> None:
        """Verify setup_mcp_helper_routes(self.app) is called in manager.py."""
        import os

        manager_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..",
            "src", "parrot", "manager", "manager.py",
        )
        with open(os.path.abspath(manager_path)) as f:
            content = f.read()

        assert "setup_mcp_helper_routes(self.app)" in content, (
            "setup_mcp_helper_routes(self.app) call not found in manager.py"
        )

    def test_mcp_routes_registered_after_credentials(self) -> None:
        """setup_mcp_helper_routes is called after setup_credentials_routes in manager.py."""
        import os

        manager_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..",
            "src", "parrot", "manager", "manager.py",
        )
        with open(os.path.abspath(manager_path)) as f:
            content = f.read()

        cred_pos = content.find("setup_credentials_routes(self.app)")
        mcp_pos = content.find("setup_mcp_helper_routes(self.app)")
        assert cred_pos != -1 and mcp_pos != -1, "Both route setups must be present"
        assert mcp_pos > cred_pos, (
            "setup_mcp_helper_routes must appear after setup_credentials_routes"
        )
