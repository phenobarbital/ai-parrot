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
try:
    from .abstract import AbstractDBAgent
    from .sql import SQLAgent
except ImportError:
    AbstractDBAgent = None  # type: ignore[assignment,misc]
    SQLAgent = None  # type: ignore[assignment,misc]


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
