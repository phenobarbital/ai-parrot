"""Lazy compatibility exports for the moved schema plane tools (FEAT-540 M3)."""

from typing import Any

_TARGET = "parrot_tools.wiki.schema"
_NAMES: frozenset[str] = frozenset(
    {
        "AbstractTool",
        "BaseWikiStore",
        "Optional",
        "Path",
        "SchemaLookupInput",
        "SchemaNeighborsInput",
        "SchemaPlaneService",
        "SchemaSearchInput",
        "SchemaSourcesInput",
        "ToolResult",
        "WikiProjectConfig",
        "WikiSchemaLookupTool",
        "WikiSchemaNeighborsTool",
        "WikiSchemaSearchTool",
        "WikiSchemaSourcesTool",
        "_SchemaTool",
        "create_schema_tools",
        "op_schema_lookup",
        "op_schema_neighbors",
        "op_schema_search",
        "op_schema_sources",
    }
)

__all__ = sorted(n for n in _NAMES if not n.startswith("_"))


def __getattr__(name: str) -> Any:
    """Resolve a moved name from ``parrot_tools.wiki`` only when requested."""
    if name not in _NAMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(_TARGET), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """List the moved names."""
    return sorted(_NAMES)
