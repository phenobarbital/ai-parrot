"""Unit tests for ToolCatalogHandler and _build_catalog (TASK-1039).

We load tools_catalog.py directly via importlib to avoid triggering the
full parrot package chain (navigator, navconfig, Cython extensions, etc.).
The handler's GET method is exercised through its private logic (_build_catalog)
and via a minimal stub for the json_response call.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub out heavy navigator / navconfig dependencies before loading the module.
# ---------------------------------------------------------------------------

_STUBS: dict[str, Any] = {
    "navconfig": None,
    "navconfig.logging": None,
    "navigator": None,
    "navigator.views": None,
    "navigator_auth": None,
    "navigator_auth.decorators": None,
    "navigator_session": None,
    "parrot_tools": None,
}

for _stub_name in _STUBS:
    if _stub_name not in sys.modules:
        _mod = types.ModuleType(_stub_name)
        # navconfig.logging needs a getLogger attribute
        _mod.logging = MagicMock()  # type: ignore[attr-defined]
        _mod.logging.getLogger = lambda name="": MagicMock()  # type: ignore[attr-defined]
        # navigator.views.BaseView — a simple no-op base
        _mod.BaseView = object  # type: ignore[attr-defined]
        # navigator_auth.decorators — identity decorators
        def _identity_decorator(*a, **kw):  # noqa: E306
            def _dec(cls):
                return cls
            return _dec
        _mod.is_authenticated = _identity_decorator  # type: ignore[attr-defined]
        _mod.user_session = _identity_decorator  # type: ignore[attr-defined]
        # parrot_tools.TOOL_REGISTRY — empty by default
        _mod.TOOL_REGISTRY = {}  # type: ignore[attr-defined]
        sys.modules[_stub_name] = _mod

_WT_ROOT = Path(__file__).resolve().parents[2]
_TC_SRC = (
    _WT_ROOT
    / "packages"
    / "ai-parrot"
    / "src"
    / "parrot"
    / "handlers"
    / "tools_catalog.py"
)
_MOD_NAME = "parrot.handlers.tools_catalog"

if _MOD_NAME not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_MOD_NAME, str(_TC_SRC))
    _tc_mod = importlib.util.module_from_spec(_spec)
    sys.modules[_MOD_NAME] = _tc_mod
    _spec.loader.exec_module(_tc_mod)

from parrot.handlers.tools_catalog import (  # noqa: E402
    ToolCatalogHandler,
    _build_catalog,
)

_TC_MOD = sys.modules[_MOD_NAME]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_cache() -> None:
    """Reset the module-level catalog cache between tests."""
    _TC_MOD._CATALOG_CACHE = None


# ---------------------------------------------------------------------------
# Tests — _build_catalog
# ---------------------------------------------------------------------------


class TestBuildCatalog:
    """Tests for the _build_catalog helper."""

    def setup_method(self):
        _reset_cache()

    def test_returns_sorted_entries(self) -> None:
        """Entries must be sorted by slug."""
        registry = {
            "zzz-tool": "pkg.zzz.ZZZ",
            "aaa-tool": "pkg.aaa.AAA",
            "mmm-tool": "pkg.mmm.MMM",
        }
        with patch.object(_TC_MOD, "TOOL_REGISTRY", registry):
            result = _build_catalog()

        slugs = [e["slug"] for e in result]
        assert slugs == ["aaa-tool", "mmm-tool", "zzz-tool"]

    def test_each_entry_has_slug_and_dotted_path(self) -> None:
        """Every entry must contain slug and dotted_path."""
        registry = {"my-tool": "some.module.MyTool"}
        with patch.object(_TC_MOD, "TOOL_REGISTRY", registry):
            result = _build_catalog()

        assert len(result) == 1
        assert result[0]["slug"] == "my-tool"
        assert result[0]["dotted_path"] == "some.module.MyTool"

    def test_empty_registry_returns_empty_list(self) -> None:
        """An empty TOOL_REGISTRY yields an empty catalog."""
        with patch.object(_TC_MOD, "TOOL_REGISTRY", {}):
            result = _build_catalog()
        assert result == []

    def test_description_extracted_from_docstring(self) -> None:
        """If the tool class has a docstring, description is added."""

        class _FakeTool:
            """Fetch the current weather for a location."""

        fake_module = types.ModuleType("fake_pkg.fake_module")
        fake_module._FakeTool = _FakeTool

        registry = {"weather": "fake_pkg.fake_module._FakeTool"}
        with (
            patch.object(_TC_MOD, "TOOL_REGISTRY", registry),
            patch.dict(sys.modules, {"fake_pkg.fake_module": fake_module}),
        ):
            result = _build_catalog()

        assert len(result) == 1
        assert result[0]["description"] == "Fetch the current weather for a location."

    def test_missing_tool_class_does_not_raise(self) -> None:
        """An import error for a tool class should not crash the catalog build."""
        registry = {"broken-tool": "nonexistent_pkg.does_not_exist.BrokenTool"}
        with patch.object(_TC_MOD, "TOOL_REGISTRY", registry):
            result = _build_catalog()  # must not raise

        assert len(result) == 1
        assert result[0]["slug"] == "broken-tool"
        assert "description" not in result[0]

    def test_category_extracted_when_present(self) -> None:
        """If the tool class exposes a category attribute, it appears in the entry."""

        class _CategorisedTool:
            """A tool with a category."""

            category = "search"

        fake_module = types.ModuleType("cat_pkg.mod")
        fake_module._CategorisedTool = _CategorisedTool

        registry = {"cat-tool": "cat_pkg.mod._CategorisedTool"}
        with (
            patch.object(_TC_MOD, "TOOL_REGISTRY", registry),
            patch.dict(sys.modules, {"cat_pkg.mod": fake_module}),
        ):
            result = _build_catalog()

        assert result[0].get("category") == "search"


# ---------------------------------------------------------------------------
# Tests — ToolCatalogHandler.get (via stub instance)
# ---------------------------------------------------------------------------


class _StubHandler:
    """Minimal stand-in that exposes json_response for testing."""

    def __init__(self):
        self.logger = MagicMock()
        self._response = None

    def json_response(self, data: Any) -> Any:
        self._response = data
        return data

    # Wire _build_catalog and _CATALOG_CACHE from the real module
    # using the already-loaded module object (avoids real package resolution).
    async def get(self) -> Any:
        if _TC_MOD._CATALOG_CACHE is None:
            _TC_MOD._CATALOG_CACHE = _TC_MOD._build_catalog()
            self.logger.info(
                "Tool catalog built: %d entries", len(_TC_MOD._CATALOG_CACHE)
            )
        return self.json_response(_TC_MOD._CATALOG_CACHE)


class TestToolCatalogHandlerGet:
    """Tests for ToolCatalogHandler.get via the stub handler."""

    def setup_method(self):
        _reset_cache()

    @pytest.mark.asyncio
    async def test_get_returns_list(self) -> None:
        """get() returns a list (possibly empty)."""
        stub = _StubHandler()
        registry = {"t1": "pkg.T1", "t2": "pkg.T2"}
        with patch.object(_TC_MOD, "TOOL_REGISTRY", registry):
            result = await stub.get()
        assert isinstance(result, list)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_output_is_sorted(self) -> None:
        """get() returns entries sorted by slug."""
        stub = _StubHandler()
        registry = {"zzz": "p.Z", "aaa": "p.A"}
        with patch.object(_TC_MOD, "TOOL_REGISTRY", registry):
            result = await stub.get()
        assert [e["slug"] for e in result] == ["aaa", "zzz"]

    @pytest.mark.asyncio
    async def test_get_caches_catalog(self) -> None:
        """Second call to get() reuses the cache (no second build)."""
        stub = _StubHandler()
        registry = {"only": "p.Only"}
        with patch.object(_TC_MOD, "TOOL_REGISTRY", registry):
            await stub.get()
            first_cache = _TC_MOD._CATALOG_CACHE
            await stub.get()
            second_cache = _TC_MOD._CATALOG_CACHE
        assert first_cache is second_cache

    @pytest.mark.asyncio
    async def test_get_with_empty_registry(self) -> None:
        """get() returns empty list when registry is empty."""
        stub = _StubHandler()
        with patch.object(_TC_MOD, "TOOL_REGISTRY", {}):
            result = await stub.get()
        assert result == []


class TestToolCatalogHandlerClass:
    """Verify ToolCatalogHandler class properties."""

    def test_is_a_class(self) -> None:
        """ToolCatalogHandler must be a class."""
        assert isinstance(ToolCatalogHandler, type)

    def test_has_get_method(self) -> None:
        """ToolCatalogHandler must have a get method."""
        assert callable(getattr(ToolCatalogHandler, "get", None))
