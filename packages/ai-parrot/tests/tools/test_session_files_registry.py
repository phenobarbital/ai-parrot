"""SessionFileToolkit must be reachable through both tool registries (FEAT-643)."""

import importlib

from parrot.tools.session_files import SessionFileToolkit


def test_tool_registry_resolves_session_files():
    """AC10 — the TOOL_REGISTRY entry imports to the real class."""
    from parrot_tools import TOOL_REGISTRY

    dotted = TOOL_REGISTRY["session_files"]
    module_path, _, name = dotted.rpartition(".")
    resolved = getattr(importlib.import_module(module_path), name)

    assert resolved is SessionFileToolkit


def test_lazy_export_from_parrot_tools():
    """AC10 — `from parrot.tools import SessionFileToolkit` resolves lazily."""
    import parrot.tools as tools_package

    assert tools_package.SessionFileToolkit is SessionFileToolkit
    assert "SessionFileToolkit" in tools_package.__all__


def test_export_is_lazy_not_eager():
    """The entry lives in the lazy map, so importing parrot.tools stays cheap."""
    from parrot.tools import _LAZY_CORE_TOOLS

    assert _LAZY_CORE_TOOLS["SessionFileToolkit"] == ".session_files"
