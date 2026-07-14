"""Unit tests for the crew special-nodes catalog handler.

We load special_nodes.py directly via importlib (mirroring
test_tools_catalog.py) to avoid triggering the full parrot-server package
chain. Navigator/navconfig dependencies are stubbed when not installed.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub out heavy navigator / navconfig dependencies before loading the module.
# ---------------------------------------------------------------------------

_STUBS = (
    "navconfig",
    "navconfig.logging",
    "navigator",
    "navigator.views",
    "navigator_auth",
    "navigator_auth.decorators",
)

for _stub_name in _STUBS:
    if _stub_name not in sys.modules:
        _mod = types.ModuleType(_stub_name)
        _mod.logging = MagicMock()  # type: ignore[attr-defined]
        _mod.logging.getLogger = lambda name="": MagicMock()  # type: ignore[attr-defined]
        _mod.BaseView = object  # type: ignore[attr-defined]

        def _identity_decorator(*a, **kw):  # noqa: E306
            def _dec(cls):
                return cls
            return _dec

        _mod.is_authenticated = _identity_decorator  # type: ignore[attr-defined]
        _mod.user_session = _identity_decorator  # type: ignore[attr-defined]
        sys.modules[_stub_name] = _mod

_WT_ROOT = Path(__file__).resolve().parents[2]
_SN_SRC = (
    _WT_ROOT
    / "packages"
    / "ai-parrot-server"
    / "src"
    / "parrot"
    / "handlers"
    / "crew"
    / "special_nodes.py"
)
_MOD_NAME = "crew_special_nodes_under_test"

if _MOD_NAME not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_MOD_NAME, str(_SN_SRC))
    _sn_mod = importlib.util.module_from_spec(_spec)
    sys.modules[_MOD_NAME] = _sn_mod
    _spec.loader.exec_module(_sn_mod)

_SN_MOD = sys.modules[_MOD_NAME]
CREW_SPECIAL_NODE_CATALOG = _SN_MOD.CREW_SPECIAL_NODE_CATALOG
CrewSpecialNodeCatalogHandler = _SN_MOD.CrewSpecialNodeCatalogHandler


# ---------------------------------------------------------------------------
# Tests — catalog contents
# ---------------------------------------------------------------------------


class TestSpecialNodeCatalog:
    """Contract tests for the curated special-node catalog."""

    def test_catalog_is_nonempty_list(self) -> None:
        assert isinstance(CREW_SPECIAL_NODE_CATALOG, list)
        assert len(CREW_SPECIAL_NODE_CATALOG) >= 1

    def test_every_entry_has_required_fields(self) -> None:
        required = {
            "slug", "name", "display_name", "description",
            "category", "type", "config_schema",
        }
        for entry in CREW_SPECIAL_NODE_CATALOG:
            assert required.issubset(entry.keys()), entry.get("slug")
            assert entry["type"] == "special_node"

    def test_slugs_are_unique(self) -> None:
        slugs = [e["slug"] for e in CREW_SPECIAL_NODE_CATALOG]
        assert len(slugs) == len(set(slugs))

    def test_tool_node_entry_present(self) -> None:
        entry = next(
            e for e in CREW_SPECIAL_NODE_CATALOG if e["slug"] == "tool_node"
        )
        assert entry["name"] == "ToolNode"
        assert entry["category"] == "deterministic"
        schema = entry["config_schema"]
        assert set(schema.keys()) == {
            "node_id", "tool", "args", "kwargs", "description",
        }
        # The template syntax must be documented for the builder UI
        assert "{input}" in schema["kwargs"]["description"]
        assert "{nodes.<node_name>.output}" in schema["kwargs"]["description"]


# ---------------------------------------------------------------------------
# Tests — handler
# ---------------------------------------------------------------------------


class _StubHandler:
    """Minimal stand-in exposing json_response for testing get().

    Mirrors test_tools_catalog.py: the real handler class may be wrapped by
    navigator_auth decorators (session/auth plumbing), so the stub replays
    the handler's one-line get() body against the real catalog constant.
    """

    def __init__(self) -> None:
        self.logger = MagicMock()

    def json_response(self, data: Any) -> Any:
        return data

    async def get(self) -> Any:
        return self.json_response(_SN_MOD.CREW_SPECIAL_NODE_CATALOG)


class TestSpecialNodeCatalogHandler:
    """Tests for CrewSpecialNodeCatalogHandler.get."""

    def test_is_a_class_with_get(self) -> None:
        assert isinstance(CrewSpecialNodeCatalogHandler, type)
        assert callable(getattr(CrewSpecialNodeCatalogHandler, "get", None))

    @pytest.mark.asyncio
    async def test_get_returns_catalog(self) -> None:
        stub = _StubHandler()
        result = await stub.get()
        assert result is CREW_SPECIAL_NODE_CATALOG
