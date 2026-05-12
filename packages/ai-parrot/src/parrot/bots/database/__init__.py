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
    "SchemaMetadataCache",
]
