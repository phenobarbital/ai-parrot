"""Deprecated alias — use ``parrot.tools.databasequery`` instead.

This module exists for backwards compatibility only.  The ``DatabaseToolkit``
class was renamed to ``DatabaseQueryToolkit`` and moved to
``parrot.tools.databasequery`` in FEAT-105 (databasetoolkit-clash) to resolve
a name clash with ``parrot.bots.database.toolkits.base.DatabaseToolkit``.

Migration:

    # Before (deprecated):
    from parrot.tools.database import DatabaseToolkit

    # After:
    from parrot.tools.databasequery import DatabaseQueryToolkit

This shim will be removed in a future major release.
"""
from __future__ import annotations

import warnings

from parrot.tools.databasequery import (
    AbstractDatabaseSource,
    ColumnMeta,
    DatabaseQueryToolkit,
    MetadataResult,
    QueryResult,
    RowResult,
    TableMeta,
    ValidationResult,
)

#: Backwards-compatible alias — resolves to ``DatabaseQueryToolkit``.
DatabaseToolkit = DatabaseQueryToolkit

_warned = False
if not _warned:
    warnings.warn(
        "parrot.tools.database is deprecated; "
        "import from parrot.tools.databasequery (DatabaseQueryToolkit) instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    _warned = True

__all__ = [
    "DatabaseToolkit",
    "AbstractDatabaseSource",
    "ValidationResult",
    "ColumnMeta",
    "TableMeta",
    "MetadataResult",
    "QueryResult",
    "RowResult",
]
