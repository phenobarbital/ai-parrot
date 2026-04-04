"""parrot.bots.database — Unified database agent with multi-toolkit architecture.

Public API:
    - ``DatabaseAgent`` — main agent class
    - ``DatabaseToolkit``, ``SQLToolkit``, ``PostgresToolkit``, etc. — toolkits
    - ``CacheManager``, ``CachePartition``, ``CachePartitionConfig`` — caching
    - All models from ``models.py`` remain unchanged
"""
from __future__ import annotations

# Agent
from .agent import DatabaseAgent

# Toolkits
from .toolkits import (
    BigQueryToolkit,
    DatabaseToolkit,
    DatabaseToolkitConfig,
    DocumentDBToolkit,
    ElasticToolkit,
    InfluxDBToolkit,
    PostgresToolkit,
    SQLToolkit,
)

# Cache
from .cache import (
    CacheManager,
    CachePartition,
    CachePartitionConfig,
    SchemaMetadataCache,  # backward-compat alias
)

# Backward compatibility aliases (deprecated — use DatabaseAgent instead)
import warnings as _warnings


class AbstractDBAgent(DatabaseAgent):
    """Deprecated: use ``DatabaseAgent`` instead."""

    def __init__(self, *args, **kwargs):
        _warnings.warn(
            "AbstractDBAgent is deprecated, use DatabaseAgent instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(*args, **kwargs)


class SQLAgent(DatabaseAgent):
    """Deprecated: use ``DatabaseAgent`` with ``PostgresToolkit`` instead."""

    def __init__(self, *args, **kwargs):
        _warnings.warn(
            "SQLAgent is deprecated, use DatabaseAgent with PostgresToolkit instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(*args, **kwargs)


__all__ = [
    # New public API
    "DatabaseAgent",
    "DatabaseToolkit",
    "DatabaseToolkitConfig",
    "SQLToolkit",
    "PostgresToolkit",
    "BigQueryToolkit",
    "InfluxDBToolkit",
    "ElasticToolkit",
    "DocumentDBToolkit",
    "CacheManager",
    "CachePartition",
    "CachePartitionConfig",
    # Backward compat (deprecated)
    "SchemaMetadataCache",
    "AbstractDBAgent",
    "SQLAgent",
]
