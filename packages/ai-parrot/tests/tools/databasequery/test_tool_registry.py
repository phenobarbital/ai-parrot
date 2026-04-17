"""Tests for TOOL_REGISTRY['database_query'] resolution.

Verifies that the registry entry points at the new canonical location
and that the lazy import resolves to the correct class.

Part of FEAT-105 — databasetoolkit-clash / TASK-738.
"""
import importlib

import pytest


def _import_from_dotted_path(dotted_path: str):
    """Utility: import a class from a dotted path like 'module.ClassName'."""
    module_path, class_name = dotted_path.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


def test_tool_registry_database_query_path():
    """TOOL_REGISTRY['database_query'] points to the new canonical path."""
    from parrot_tools import TOOL_REGISTRY
    value = TOOL_REGISTRY["database_query"]
    assert value == "parrot.tools.databasequery.DatabaseQueryTool", (
        f"Expected new canonical path, got: {value!r}"
    )


def test_tool_registry_resolves_to_database_query_tool():
    """The registry path resolves to DatabaseQueryTool class."""
    from parrot_tools import TOOL_REGISTRY
    dotted_path = TOOL_REGISTRY["database_query"]
    cls = _import_from_dotted_path(dotted_path)
    assert cls.__name__ == "DatabaseQueryTool"
    assert cls.__module__.startswith("parrot.tools.databasequery"), (
        f"Expected module under parrot.tools.databasequery, got: {cls.__module__}"
    )


def test_tool_registry_entry_not_parrot_tools():
    """TOOL_REGISTRY['database_query'] does NOT reference the old parrot_tools path."""
    from parrot_tools import TOOL_REGISTRY
    value = TOOL_REGISTRY["database_query"]
    assert not value.startswith("parrot_tools."), (
        f"Registry still points at old parrot_tools path: {value!r}"
    )


def test_tool_registry_class_has_correct_tool_name():
    """The resolved class has tool name 'database_query'."""
    from parrot_tools import TOOL_REGISTRY
    dotted_path = TOOL_REGISTRY["database_query"]
    cls = _import_from_dotted_path(dotted_path)
    assert cls.name == "database_query"
