"""Schema plane — SQL data-model knowledge as a wikitoolkit overlay plane (FEAT-600)."""

from __future__ import annotations

import importlib
from typing import Any

_EXPORTS: dict[str, str] = {
    "SchemaSourceConfig": "models",
    "SchemaPlaneConfig": "models",
    "ColumnRecord": "models",
    "TableRecord": "models",
    "LookupResult": "models",
    "SyncReport": "models",
    "KINDS": "ids",
    "source_concept_id": "ids",
    "schema_concept_id": "ids",
    "table_concept_id": "ids",
    "parse_table_id": "ids",
    "normalize_ref": "ids",
    "content_hash": "render",
    "render_ddl": "render",
    "render_page": "render",
    "render_source_page": "render",
    "render_schema_page": "render",
    "SchemaStore": "store",
    "SchemaPlaneService": "service",
    "SchemaPlaneReader": "service",
    "create_schema_tools": "tools",
    "SchemaPlaneToolkit": "toolkit",
}
__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve a public name from its submodule on first access."""
    try:
        module = importlib.import_module(f"{__name__}.{_EXPORTS[name]}")
    except KeyError as exc:
        raise AttributeError(name) from exc
    return getattr(module, name)
