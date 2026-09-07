"""Unit tests for FEAT-536 TASK-2943 — serve the locked LiveKit SDK to the
Voice demo (``examples/clients/voice/server.py``).

``examples/clients/voice/server.py`` is a standalone script, not part of
any installed package — imported here via ``importlib.util`` from its
file path, the only way to exercise it directly without turning
``examples/`` into an importable package (out of scope for this task).

The real ``livekit-client`` UMD asset is NOT installed in this sandboxed
environment (``packages/ai-parrot-server/ui``'s ``node_modules`` is
absent — a documented prerequisite, not something this test suite can
install). Tests therefore exercise BOTH the genuinely-missing case (the
sandbox's real state) and a monkeypatched "installed" case (a fixture
file standing in for the real 2.22.1 UMD artifact) so the "known fixture
SDK file serves successfully" acceptance criterion is covered without
requiring the actual frontend install step.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SERVER_PATH = _REPO_ROOT / "examples" / "clients" / "voice" / "server.py"


def _load_server_module():
    """Import examples/clients/voice/server.py by file path.

    A fresh module object per call (not cached in sys.modules under a
    fixed name across tests) so each test can safely monkeypatch its
    module-level state (e.g. ``NOVA_AVAILABLE``,
    ``_resolve_livekit_umd_path``) without leaking into other tests.
    """
    spec = importlib.util.spec_from_file_location("voice_demo_server_under_test", _SERVER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def server_module():
    module = _load_server_module()
    yield module
    sys.modules.pop("voice_demo_server_under_test", None)


def _extract_config(html: str) -> dict:
    """Parse the ``window.__CONFIG__ = {...};`` bootstrap out of the
    rendered page using a real JSON decoder (``raw_decode``) rather than
    a naive ``";"``-delimited slice — the config itself legitimately
    contains semicolons in nested string values (e.g. capability
    descriptors), which would otherwise truncate the parse early."""
    marker = "window.__CONFIG__ = "
    start = html.rindex(marker) + len(marker)
    cfg, _end_offset = json.JSONDecoder().raw_decode(html[start:])
    return cfg


@pytest.fixture
def fixture_umd_asset(tmp_path: Path) -> Path:
    """A stand-in for the real, locked livekit-client.umd.js artifact —
    NOT a real SDK, just a known, deterministic fixture file to prove the
    route serves whatever ``_resolve_livekit_umd_path()`` resolves to."""
    asset = tmp_path / "livekit-client.umd.js"
    asset.write_text("/* fixture livekit-client UMD stand-in for tests */\nvar LivekitClient = {};\n")
    return asset


# ── test_voice_demo_sdk_route_is_scoped ───────────────────────────────────


class TestVoiceDemoSdkRouteIsScoped:
    """A known fixture SDK file serves successfully; the route is a
    single EXACT path (no traversal surface); an absent file reports
    unavailable without breaking the page or provider routes."""

    @pytest.mark.asyncio
    async def test_known_fixture_sdk_file_serves_successfully(self, server_module, fixture_umd_asset, monkeypatch):
        monkeypatch.setattr(server_module, "_resolve_livekit_umd_path", lambda: fixture_umd_asset)
        app = server_module.build_app()

        async with TestClient(TestServer(app)) as client:
            resp = await client.get(server_module._LIVEKIT_UMD_ROUTE)
            assert resp.status == 200
            body = await resp.text()
            assert "LivekitClient" in body
            assert resp.content_type == "application/javascript"

    @pytest.mark.asyncio
    async def test_missing_fixture_returns_controlled_unavailable_response(self, server_module, monkeypatch):
        """This sandbox's REAL state: the package is not installed."""
        monkeypatch.setattr(server_module, "_resolve_livekit_umd_path", lambda: None)
        app = server_module.build_app()

        async with TestClient(TestServer(app)) as client:
            resp = await client.get(server_module._LIVEKIT_UMD_ROUTE)
            assert resp.status == 503
            body = await resp.text()
            assert "not installed" in body.lower()

    @pytest.mark.asyncio
    async def test_adjacent_traversal_like_urls_are_not_routed_here(self, server_module, fixture_umd_asset, monkeypatch):
        """The route has no path parameter — a traversal-shaped adjacent
        URL cannot dispatch to this handler at all (404, not the asset,
        not an arbitrary node_modules file)."""
        monkeypatch.setattr(server_module, "_resolve_livekit_umd_path", lambda: fixture_umd_asset)
        app = server_module.build_app()

        async with TestClient(TestServer(app)) as client:
            for suspicious in (
                "/voice-assets/../server.py",
                "/voice-assets/livekit-client.umd.js/../../server.py",
                "/voice-assets/",
                "/voice-assets/other-file.js",
                "/voice-assets/livekit-client.umd.js%2e%2e",
            ):
                resp = await client.get(suspicious)
                assert resp.status in (404, 400), f"{suspicious} unexpectedly routed (status={resp.status})"

    def test_resolve_path_rejects_escaped_symlink(self, server_module, tmp_path, monkeypatch):
        """Defense-in-depth: if a malformed/malicious symlink made the
        resolved real path escape the package directory,
        _resolve_livekit_umd_path() must refuse to return it (None), not
        serve whatever the symlink actually points to."""
        ui_dir = tmp_path / "ui"
        package_dir = ui_dir / "node_modules" / "livekit-client"
        package_dir.mkdir(parents=True)

        # "dist" is a symlink pointing OUTSIDE package_dir entirely, and
        # the outside location happens to contain a same-named file —
        # this must still be refused, not served.
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        (outside_dir / "livekit-client.umd.js").write_text("should never be served")
        (package_dir / "dist").symlink_to(outside_dir, target_is_directory=True)

        monkeypatch.setattr(server_module, "_UI_PACKAGE_DIR", ui_dir)

        assert server_module._resolve_livekit_umd_path() is None


# ── test_voice_demo_missing_sdk_keeps_voice_routes ────────────────────────


class TestVoiceDemoMissingSdkKeepsVoiceRoutes:
    """Missing SDK disables only the avatar asset — both voice-provider
    WebSocket/health routes and the index page keep working."""

    @pytest.mark.asyncio
    async def test_health_routes_still_work_without_sdk(self, server_module, monkeypatch):
        monkeypatch.setattr(server_module, "_resolve_livekit_umd_path", lambda: None)
        app = server_module.build_app()

        async with TestClient(TestServer(app)) as client:
            gemini_health = await client.get("/health/gemini")
            assert gemini_health.status == 200

    @pytest.mark.asyncio
    async def test_index_page_still_serves_without_sdk(self, server_module, monkeypatch):
        monkeypatch.setattr(server_module, "_resolve_livekit_umd_path", lambda: None)
        app = server_module.build_app()

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/")
            assert resp.status == 200
            assert resp.content_type == "text/html"

    @pytest.mark.asyncio
    async def test_ws_routes_remain_mounted_without_sdk(self, server_module, monkeypatch):
        """The WebSocket routes are registered regardless of avatar SDK
        availability — asserted via the router, not a live WS handshake
        (out of scope here; TASK-2946/2947 cover real dual-output/E2E)."""
        monkeypatch.setattr(server_module, "_resolve_livekit_umd_path", lambda: None)
        app = server_module.build_app()

        route_paths = {resource.canonical for resource in app.router.resources()}
        assert "/ws/gemini" in route_paths
        assert "/ws/nova" in route_paths


# ── test_voice_demo_config_bootstrap ──────────────────────────────────────


class TestVoiceDemoConfigBootstrap:
    """The rendered window.__CONFIG__ bootstrap is valid JSON, exposes
    only the asset URL and its availability, and carries no credentials."""

    @pytest.mark.asyncio
    async def test_config_bootstrap_is_valid_json_with_avatar_section(self, server_module, fixture_umd_asset, monkeypatch):
        monkeypatch.setattr(server_module, "_resolve_livekit_umd_path", lambda: fixture_umd_asset)
        app = server_module.build_app()

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/")
            html = await resp.text()

        cfg = _extract_config(html)

        assert cfg["avatar"]["sdkUrl"] == server_module._LIVEKIT_UMD_ROUTE
        assert cfg["avatar"]["available"] is True

    @pytest.mark.asyncio
    async def test_config_bootstrap_reflects_unavailable_sdk(self, server_module, monkeypatch):
        monkeypatch.setattr(server_module, "_resolve_livekit_umd_path", lambda: None)
        app = server_module.build_app()

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/")
            html = await resp.text()

        cfg = _extract_config(html)

        assert cfg["avatar"]["available"] is False

    @pytest.mark.asyncio
    async def test_config_bootstrap_contains_no_credentials(self, server_module, fixture_umd_asset, monkeypatch):
        monkeypatch.setattr(server_module, "_resolve_livekit_umd_path", lambda: fixture_umd_asset)
        app = server_module.build_app()

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/")
            html = await resp.text()

        cfg = _extract_config(html)
        cfg_json = json.dumps(cfg)

        # Only asset URL/availability — never a token/secret/key.
        for forbidden in ("client_token", "api_key", "apiKey", "secret", "livekit_url", "AKIA"):
            assert forbidden not in cfg_json, f"unexpected credential-shaped key {forbidden!r} in bootstrap config"

    def test_only_single_anchored_replacement_occurs(self, server_module):
        """Code-review-guarded regression: the templating must remain a
        single, anchored str.replace(..., count=1) — never a bare
        token-wide replace that would also corrupt the page's other
        `window.__CONFIG__.providers`/`.capabilities` property accesses."""
        import inspect

        src = inspect.getsource(server_module.index_handler)
        assert src.count(".read_text().replace(") == 1
        assert '"window.__CONFIG__ = __CONFIG__;"' in src  # the exact anchor
        assert ",\n        1,\n    )" in src  # explicit count=1 positional arg
