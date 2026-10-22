"""parrot.bots.database — Unified database agent with multi-toolkit architecture.

Public API:
    - ``DatabaseAgent`` — main agent class
    - ``DatabaseToolkit``, ``SQLToolkit``, ``PostgresToolkit``, etc. — toolkits
    - ``CacheManager``, ``CachePartition``, ``CachePartitionConfig`` — caching
    - All models from ``models.py`` remain unchanged

Every name is resolved lazily on first access (PEP 562) so that importing a
leaf module such as ``parrot.bots.database.models`` — as ``wikitoolkit``'s
schema plane does — never loads ``DatabaseAgent``, the toolkits or the cache
layer (and, through them, the ai-parrot-tools satellite).
"""
from __future__ import annotations

from importlib import import_module

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
    # Structured output models
    "QueryDataset",
    "QueryResponse",
]

_LAZY_ATTRS = {
    # Agent
    "DatabaseAgent": ".agent",
    # Toolkits
    "BigQueryToolkit": ".toolkits",
    "DatabaseToolkit": ".toolkits",
    "DatabaseToolkitConfig": ".toolkits",
    "DocumentDBToolkit": ".toolkits",
    "ElasticToolkit": ".toolkits",
    "InfluxDBToolkit": ".toolkits",
    "PostgresToolkit": ".toolkits",
    "SQLToolkit": ".toolkits",
    # Cache
    "CacheManager": ".cache",
    "CachePartition": ".cache",
    "CachePartitionConfig": ".cache",
    "SchemaMetadataCache": ".cache",  # backward-compat alias
    # Response models
    "QueryDataset": ".models",
    "QueryResponse": ".models",
}


def __getattr__(name: str):
    """Resolve a public export on first attribute access.

    Args:
        name: Attribute being looked up on the ``parrot.bots.database`` package.

    Returns:
        The resolved attribute (cached in the module globals afterwards).

    Raises:
        AttributeError: If ``name`` is not a public export of this package.
    """
    module_name = _LAZY_ATTRS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    attr = getattr(import_module(module_name, __name__), name)
    globals()[name] = attr
    return attr


def __dir__() -> list[str]:
    """Return the public attribute names, including lazy exports."""
    return sorted(set(globals()) | set(__all__))
