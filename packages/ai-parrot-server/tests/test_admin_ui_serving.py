"""Unit tests for the embedded Admin UI serving module (FEAT-468, TASK-2523).

Covers ``setup_admin_ui()``: absent-dist graceful degradation, SPA
index-fallback deep links, hashed-asset static mount, no shadowing of
``/api/*`` routes, and navigator-auth exclude-list registration (with and
without an installed ``AuthHandler``).
"""
from __future__ import annotations

import logging

import pytest
from aiohttp import web
from parrot.server.ui import serving, setup_admin_ui


@pytest.fixture
def fake_dist(tmp_path, monkeypatch):
    """Minimal fake ``dist/``: index.html + a hashed asset."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>admin</html>")
    (dist / "assets" / "app-abc123.js").write_text("//js")
    monkeypatch.setattr(serving, "_dist_dir", lambda: dist)
    return dist


class TestAbsentDist:
    async def test_absent_dist_returns_false_and_registers_no_spa_routes(
        self, tmp_path, monkeypatch, caplog
    ):
        """No dist -> no SPA mount, but the status JSON endpoint is
        UI-agnostic and still registers (TASK-2524)."""
        missing = tmp_path / "no-dist-here"
        monkeypatch.setattr(serving, "_dist_dir", lambda: missing)
        monkeypatch.setattr(serving, "_warned_missing_dist", False)

        app = web.Application()
        with caplog.at_level(logging.WARNING, logger=serving.__name__):
            result = setup_admin_ui(app)

        assert result is False
        paths = {r.resource.canonical for r in app.router.routes()}
        assert paths == {"/api/v1/admin/status"}
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1


class TestMountedDist:
    async def test_index_fallback_serves_deep_links(self, fake_dist, aiohttp_client):
        app = web.Application()
        assert setup_admin_ui(app) is True

        client = await aiohttp_client(app)

        resp = await client.get("/admin")
        assert resp.status == 200
        assert "admin" in (await resp.text())
        assert resp.headers.get("Cache-Control") == "no-cache"

        resp = await client.get("/admin/agents")
        assert resp.status == 200
        assert "admin" in (await resp.text())

    async def test_assets_served_with_long_cache_headers(self, fake_dist, aiohttp_client):
        app = web.Application()
        assert setup_admin_ui(app) is True

        client = await aiohttp_client(app)
        resp = await client.get("/admin/assets/app-abc123.js")
        assert resp.status == 200
        assert "js" in (await resp.text())
        assert resp.headers.get("Cache-Control") == "public, max-age=31536000, immutable"

    async def test_api_routes_not_shadowed(self, fake_dist, aiohttp_client):
        app = web.Application()

        async def _api_handler(request):
            return web.json_response({"ok": True})

        app.router.add_get("/api/v1/anything", _api_handler)
        assert setup_admin_ui(app) is True

        client = await aiohttp_client(app)
        resp = await client.get("/api/v1/anything")
        assert resp.status == 200
        assert (await resp.json()) == {"ok": True}

    async def test_prefix_does_not_shadow_lookalike_route(self, fake_dist, aiohttp_client):
        """A future route whose path merely starts with the same
        characters as the prefix (e.g. /administer) must NOT be swallowed
        by the SPA catch-all, which is anchored on a path-segment boundary."""
        app = web.Application()

        async def _administer_handler(request):
            return web.json_response({"ok": True})

        app.router.add_get("/administer", _administer_handler)
        assert setup_admin_ui(app) is True

        client = await aiohttp_client(app)
        resp = await client.get("/administer")
        assert resp.status == 200
        assert (await resp.json()) == {"ok": True}

    async def test_exclude_list_registered_when_auth_present(self, fake_dist):
        from navigator_auth.conf import AUTH_EXCLUDE_LIST_KEY

        app = web.Application()
        app[AUTH_EXCLUDE_LIST_KEY] = []
        assert setup_admin_ui(app) is True
        assert "/admin" in app[AUTH_EXCLUDE_LIST_KEY]
        assert "/admin/*" in app[AUTH_EXCLUDE_LIST_KEY]
        # Segment-boundary patterns must not accidentally match lookalikes.
        import fnmatch

        assert not any(
            fnmatch.fnmatch("/administer", p) for p in app[AUTH_EXCLUDE_LIST_KEY]
        )

    async def test_no_crash_without_auth_handler(self, fake_dist):
        app = web.Application()
        # No AUTH_EXCLUDE_LIST_KEY set on the app — must not raise.
        assert setup_admin_ui(app) is True
