"""Registry resolution test for the FEAT-379 clean-break migration.

Verifies the lazy `TOOL_REGISTRY` entry now points at
`MultiStoreSearchToolkit` (not the removed `MultiStoreSearchTool`), and
that the legacy tool is genuinely gone (no deprecation shim).
"""
import importlib

import pytest

import parrot_tools


def test_registry_entry_points_at_toolkit():
    """TOOL_REGISTRY resolves "multi_store_search_toolkit" to the new class."""
    dotted_path = parrot_tools.TOOL_REGISTRY["multi_store_search_toolkit"]
    assert dotted_path == "parrot_tools.multistoresearch.MultiStoreSearchToolkit"

    module_path, class_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    tk_cls = getattr(module, class_name)
    assert tk_cls.__name__ == "MultiStoreSearchToolkit"


def test_old_registry_key_removed():
    """The old "multi_store_search" key is gone (clean break, no alias)."""
    assert "multi_store_search" not in parrot_tools.TOOL_REGISTRY


def test_legacy_tool_gone():
    """MultiStoreSearchTool no longer exists anywhere in the package."""
    mod = importlib.import_module("parrot_tools.multistoresearch")
    assert not hasattr(mod, "MultiStoreSearchTool")
    assert not hasattr(mod, "MultiStoreSearchSchema")

    with pytest.raises(ImportError):
        from parrot_tools.multistoresearch import (  # noqa: F401
            MultiStoreSearchTool,
        )


def test_legacy_tool_module_file_removed():
    """The transitional _legacy_tool module is gone too."""
    with pytest.raises(ImportError):
        importlib.import_module("parrot_tools.multistoresearch._legacy_tool")
