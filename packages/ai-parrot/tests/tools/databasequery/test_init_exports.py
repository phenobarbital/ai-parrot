"""Tests for parrot.tools.databasequery package exports.

Updated for FEAT-105: DatabaseQueryToolkit replaces DatabaseToolkit.
PgSchemaSearchTool and BQSchemaSearchTool were removed in FEAT-082;
these tests now verify the FEAT-105 public surface.

Part of FEAT-105 — databasetoolkit-clash / TASK-738.
"""
import pytest


def test_import_database_query_toolkit():
    """DatabaseQueryToolkit is importable from the package."""
    from parrot.tools.databasequery import DatabaseQueryToolkit
    assert DatabaseQueryToolkit is not None


def test_import_database_query_tool():
    """DatabaseQueryTool is importable from the package."""
    from parrot.tools.databasequery import DatabaseQueryTool
    assert DatabaseQueryTool is not None


def test_import_abstract_database_source():
    """AbstractDatabaseSource is importable from the package."""
    from parrot.tools.databasequery import AbstractDatabaseSource
    assert AbstractDatabaseSource is not None


def test_import_result_types():
    """All result types are importable from the package."""
    from parrot.tools.databasequery import (
        ValidationResult,
        ColumnMeta,
        TableMeta,
        MetadataResult,
        QueryResult,
        RowResult,
    )
    assert ValidationResult is not None
    assert ColumnMeta is not None
    assert TableMeta is not None
    assert MetadataResult is not None
    assert QueryResult is not None
    assert RowResult is not None


def test_all_exports():
    """__all__ contains expected names."""
    import parrot.tools.databasequery as dq_pkg
    expected = {
        "DatabaseQueryToolkit",
        "DatabaseQueryTool",
        "AbstractDatabaseSource",
        "ValidationResult",
        "ColumnMeta",
        "TableMeta",
        "MetadataResult",
        "QueryResult",
        "RowResult",
    }
    for name in expected:
        assert name in dq_pkg.__all__, f"'{name}' missing from __all__"


def test_database_toolkit_not_in_new_package_all():
    """DatabaseToolkit is NOT in parrot.tools.databasequery.__all__.

    The renamed class is DatabaseQueryToolkit; DatabaseToolkit is only available
    via the deprecated parrot.tools.database shim.
    """
    import parrot.tools.databasequery as dq_pkg
    assert "DatabaseToolkit" not in dq_pkg.__all__
