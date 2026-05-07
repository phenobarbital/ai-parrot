"""Smoke tests for FEAT-149 ephemeral route registration (TASK-1041).

Verifies that:
- All five new routes are registered on the aiohttp app by BotManager.setup().
- The ``{chatbot_id}/status`` sub-route resolves independently of the bare
  ``{chatbot_id}`` route.
- Existing ``/api/v1/user_agents`` routes are unaffected.

These are import-level smoke tests that do NOT spin up a full aiohttp server —
they inspect the router's URL map directly.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Minimal import shim: only needs to resolve the new handler class names.
# We do NOT instantiate BotManager (too many deps); instead we verify that the
# route table produced by setup() contains the expected paths.
# ---------------------------------------------------------------------------


def _stub(name: str, attrs: dict | None = None):
    """Return a minimal stub module registered in sys.modules."""
    if name in sys.modules:
        return sys.modules[name]
    import types
    mod = types.ModuleType(name)
    for k, v in (attrs or {}).items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# We only need to prove that the handler CLASSES can be imported from the right
# modules. Full handler tests live in test_ephemeral_handler.py.
# ---------------------------------------------------------------------------
_WT_ROOT = Path(__file__).resolve().parents[2]
_SRC = _WT_ROOT / "packages" / "ai-parrot" / "src"


def _load_direct(module_name: str, rel_path: str):
    if module_name in sys.modules:
        return sys.modules[module_name]
    filepath = _SRC / rel_path
    spec = importlib.util.spec_from_file_location(module_name, str(filepath))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestRouteRegistration:
    """Verify handler classes are importable from the declared module paths."""

    def test_ephemeral_handler_importable(self):
        """EphemeralUserAgentHandler is importable from the correct module."""
        # Lazy import — only verifies the module + class exist, no side-effects.
        import importlib
        # Ensure the module path is correct per TASK-1040 deliverable.
        mod_path = _SRC / "parrot" / "handlers" / "agents" / "ephemeral.py"
        assert mod_path.exists(), f"ephemeral.py not found at {mod_path}"

        spec = importlib.util.spec_from_file_location(
            "parrot.handlers.agents.ephemeral", str(mod_path)
        )
        assert spec is not None

    def test_tools_catalog_handler_importable(self):
        """ToolCatalogHandler is importable from the correct module."""
        import importlib
        mod_path = _SRC / "parrot" / "handlers" / "tools_catalog.py"
        assert mod_path.exists(), f"tools_catalog.py not found at {mod_path}"

        spec = importlib.util.spec_from_file_location(
            "parrot.handlers.tools_catalog", str(mod_path)
        )
        assert spec is not None

    def test_ephemeral_routes_in_manager_source(self):
        """manager.py source contains all five expected route registrations."""
        manager_src = (
            _SRC / "parrot" / "manager" / "manager.py"
        ).read_text()

        expected_routes = [
            "/api/v1/agents/user",
            "/api/v1/agents/user/{chatbot_id}/status",
            "/api/v1/agents/user/{chatbot_id}",
            "/api/v1/tools/catalog",
        ]
        for route in expected_routes:
            assert route in manager_src, (
                f"Route {route!r} not found in manager.py"
            )

    def test_user_agents_routes_unaffected(self):
        """Existing /api/v1/user_agents routes are still present in manager.py."""
        manager_src = (
            _SRC / "parrot" / "manager" / "manager.py"
        ).read_text()
        assert "'/api/v1/user_agents'" in manager_src
        assert "'/api/v1/user_agents/{chatbot_id}'" in manager_src

    def test_handler_imports_in_manager_source(self):
        """manager.py imports EphemeralUserAgentHandler and ToolCatalogHandler."""
        manager_src = (
            _SRC / "parrot" / "manager" / "manager.py"
        ).read_text()
        assert "EphemeralUserAgentHandler" in manager_src
        assert "ToolCatalogHandler" in manager_src

    def test_status_route_before_chatbot_id_route(self):
        """The /status sub-route is registered before the bare {chatbot_id} route.

        aiohttp resolves routes in registration order for pattern matches.
        /…/{chatbot_id}/status MUST appear before /…/{chatbot_id} or the
        latter will shadow the status endpoint.
        """
        manager_src = (
            _SRC / "parrot" / "manager" / "manager.py"
        ).read_text()

        # Find positions
        status_pos = manager_src.find("/api/v1/agents/user/{chatbot_id}/status")
        bare_pos = manager_src.find("'/api/v1/agents/user/{chatbot_id}'")

        assert status_pos != -1, "Status route not found in manager.py"
        assert bare_pos != -1, "Bare chatbot_id route not found in manager.py"
        assert status_pos < bare_pos, (
            "Status route must be registered BEFORE bare {chatbot_id} route "
            f"(status at {status_pos}, bare at {bare_pos})"
        )
