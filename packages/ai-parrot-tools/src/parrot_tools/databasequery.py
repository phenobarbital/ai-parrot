"""Compat shim — use parrot.tools.databasequery instead.

This module re-exports the database query tools from their canonical location
at ``parrot.tools.databasequery``. It exists solely for backwards compatibility.
"""
from __future__ import annotations

from parrot.tools.databasequery.tool import (
    DatabaseQueryTool,
    DriverInfo,
    DatabaseQueryArgs,
)
from parrot.security import QueryLanguage, QueryValidator

__all__ = [
    "DatabaseQueryTool",
    "DriverInfo",
    "DatabaseQueryArgs",
    "QueryLanguage",
    "QueryValidator",
]
