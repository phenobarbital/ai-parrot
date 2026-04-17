"""Tests for backwards-compatibility shims.

Verifies that:
- ``from parrot.tools.database import DatabaseToolkit`` works and emits DeprecationWarning.
- ``from parrot_tools.databasequery import DatabaseQueryTool, DriverInfo, DatabaseQueryArgs, ...`` still works.

Part of FEAT-105 — databasetoolkit-clash / TASK-738.
"""
import importlib
import sys
import warnings

import pytest


def test_database_deprecation_alias_emits_warning():
    """Importing from parrot.tools.database emits DeprecationWarning."""
    # Remove cached module so the warning fires fresh
    sys.modules.pop("parrot.tools.database", None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        from parrot.tools.database import DatabaseToolkit  # noqa: F401

    our_warnings = [
        w for w in caught
        if issubclass(w.category, DeprecationWarning)
        and "parrot.tools.databasequery" in str(w.message)
    ]
    assert our_warnings, (
        "Expected a DeprecationWarning mentioning 'parrot.tools.databasequery' "
        f"but got: {[str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)]}"
    )


def test_database_alias_resolves_to_query_toolkit():
    """DatabaseToolkit from the shim IS DatabaseQueryToolkit."""
    sys.modules.pop("parrot.tools.database", None)
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        from parrot.tools.database import DatabaseToolkit

    from parrot.tools.databasequery import DatabaseQueryToolkit
    assert DatabaseToolkit is DatabaseQueryToolkit, (
        "DatabaseToolkit alias must resolve to DatabaseQueryToolkit"
    )


def test_new_package_does_not_emit_deprecation_warning():
    """Importing from parrot.tools.databasequery does NOT emit DeprecationWarning."""
    # Remove to force reimport
    for key in list(sys.modules.keys()):
        if "parrot.tools.databasequery" in key:
            sys.modules.pop(key, None)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        from parrot.tools.databasequery import DatabaseQueryToolkit  # noqa: F401

    our_warnings = [
        w for w in caught
        if issubclass(w.category, DeprecationWarning)
        and "parrot.tools.databasequery" in str(w.message)
    ]
    assert not our_warnings, (
        "parrot.tools.databasequery should NOT emit DeprecationWarning; "
        f"got: {[str(w.message) for w in our_warnings]}"
    )


def test_databasequery_shim_preserves_tool():
    """from parrot_tools.databasequery import DatabaseQueryTool still works."""
    from parrot_tools.databasequery import DatabaseQueryTool
    assert DatabaseQueryTool.__name__ == "DatabaseQueryTool"
    assert hasattr(DatabaseQueryTool, "name")
    assert DatabaseQueryTool.name == "database_query"


def test_databasequery_shim_preserves_driver_info():
    """DriverInfo is importable from the parrot_tools.databasequery shim."""
    from parrot_tools.databasequery import DriverInfo
    assert DriverInfo is not None
    assert hasattr(DriverInfo, "get_query_language")


def test_databasequery_shim_preserves_args():
    """DatabaseQueryArgs is importable from the parrot_tools.databasequery shim."""
    from parrot_tools.databasequery import DatabaseQueryArgs
    assert DatabaseQueryArgs is not None


def test_databasequery_shim_preserves_security_exports():
    """QueryLanguage and QueryValidator are importable from the shim."""
    from parrot_tools.databasequery import QueryLanguage, QueryValidator
    assert QueryLanguage is not None
    assert QueryValidator is not None
