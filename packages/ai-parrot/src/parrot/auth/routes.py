"""Compatibility route registration for Jira OAuth callbacks."""

from __future__ import annotations

from aiohttp import web


def setup_jira_oauth_routes(app: web.Application) -> None:
    """Mount the generic OAuth2 callback at Jira's registered redirect URI (alias, AC-14)."""
    callback_path = "/api/auth/jira/callback"
    for route in app.router.routes():
        if route.method == "GET" and route.get_info().get("path") == callback_path:
            return

    from parrot.auth.oauth2_routes import setup_oauth2_routes

    setup_oauth2_routes(app, "jira", callback_path)
