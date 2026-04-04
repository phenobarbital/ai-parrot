"""Database toolkits — per-database-type tool collections.

Each toolkit inherits ``DatabaseToolkit`` (which itself inherits
``AbstractToolkit``) and exposes database-specific operations as
LLM-callable tools.
"""
from __future__ import annotations

from .base import DatabaseToolkit, DatabaseToolkitConfig
from .sql import SQLToolkit

__all__ = [
    "DatabaseToolkit",
    "DatabaseToolkitConfig",
    "SQLToolkit",
]
