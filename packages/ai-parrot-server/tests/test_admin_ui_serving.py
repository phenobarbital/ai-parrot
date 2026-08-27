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

    async def test_exclude_list_registered_when_auth_present(
        self, fake_dist, aiohttp_client
    ):
        """Registration happens on ``on_startup``, not eagerly in
        ``setup_admin_ui()`` — see ``_register_auth_exclusions_on_startup``'s
        docstring. In production both real entrypoints call
        ``BotManager.setup(app)`` (which calls ``setup_admin_ui``) BEFORE
        ``AuthHandler().setup(app)``, and ``AuthHandler.setup()``
        unconditionally overwrites ``app[AUTH_EXCLUDE_LIST_KEY]`` — an
        eager registration would either be a no-op (key unset yet) or get
        silently discarded by that overwrite. Simulate that exact ordering
        here: pre-populate the key (mimicking AuthHandler already having
        run its own ``setup()`` by the time ``on_startup`` fires), THEN
        start the app (which fires ``on_startup``) before asserting.
        """
        from navigator_auth.conf import AUTH_EXCLUDE_LIST_KEY

        app = web.Application()
        app[AUTH_EXCLUDE_LIST_KEY] = []
        assert setup_admin_ui(app) is True
        # Not yet registered — deferred until on_startup fires.
        assert app[AUTH_EXCLUDE_LIST_KEY] == []

        await aiohttp_client(app)  # starts the app -> fires on_startup

        assert "/admin" in app[AUTH_EXCLUDE_LIST_KEY]
        assert "/admin/*" in app[AUTH_EXCLUDE_LIST_KEY]
        # Segment-boundary patterns must not accidentally match lookalikes.
        import fnmatch

        assert not any(
            fnmatch.fnmatch("/administer", p) for p in app[AUTH_EXCLUDE_LIST_KEY]
        )

    async def test_no_crash_without_auth_handler(self, fake_dist, aiohttp_client):
        app = web.Application()
        # No AUTH_EXCLUDE_LIST_KEY set on the app — must not raise, even
        # once on_startup actually fires the deferred registration.
        assert setup_admin_ui(app) is True
        await aiohttp_client(app)  # starts the app -> fires on_startup; no raise

    async def test_survives_real_entrypoint_ordering(self, fake_dist, aiohttp_client):
        """Regression test for the real ``app.py``/``appauto.py`` ordering:
        ``BotManager.setup(app)`` (-> ``setup_admin_ui``) runs BEFORE
        ``AuthHandler().setup(app)``. ``AuthHandler.setup()`` unconditionally
        OVERWRITES ``app[AUTH_EXCLUDE_LIST_KEY]`` with a fresh list
        (``navigator_auth/auth.py``), which would silently discard an eager
        registration made before it ran. Reproduce that exact sequence:
        ``setup_admin_ui()`` first (no key set yet, like the real
        entrypoints), THEN simulate ``AuthHandler.setup()``'s overwrite,
        THEN start the app (fires the deferred ``on_startup`` registration)
        and assert the patterns still end up in the final list navigator-auth's
        ABAC middleware actually reads at request time.
        """
        from navigator_auth.conf import AUTH_EXCLUDE_LIST_KEY

        app = web.Application()
        # 1. setup_admin_ui() runs first — no AUTH_EXCLUDE_LIST_KEY yet.
        assert AUTH_EXCLUDE_LIST_KEY not in app
        assert setup_admin_ui(app) is True

        # 2. AuthHandler().setup(app) runs later, overwriting the key with
        #    a fresh list (mirrors navigator_auth/auth.py's own behavior).
        app[AUTH_EXCLUDE_LIST_KEY] = ["/some/other/excluded/path"]

        # 3. The app actually starts serving -> on_startup fires.
        await aiohttp_client(app)

        assert "/admin" in app[AUTH_EXCLUDE_LIST_KEY]
        assert "/admin/*" in app[AUTH_EXCLUDE_LIST_KEY]
        assert "/some/other/excluded/path" in app[AUTH_EXCLUDE_LIST_KEY]
