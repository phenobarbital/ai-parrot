"""Linked-surface descriptors (FEAT-598)."""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import Any

from parrot.outputs.a2ui.linked.models import (
    Derive,
    DeriveBinary,
    Filter,
    GroupBy,
    Join,
    JoinKey,
    Limit,
    LinkedDataSource,
    LinkedSources,
    ParamSpec,
    Pivot,
    RefreshPolicy,
    Rename,
    Select,
    Sort,
    SortKey,
    SourceRequest,
    TransformOp,
    TransformRef,
    TransformSpec,
)
from parrot.outputs.a2ui.linked.models import Union_ as UnionOp

DATA_SOURCES_EXTENSION = "parrot_data_sources"

_LAZY: dict[str, str] = {
    "derive_conditions": "conditions",
    "export_json_schema": "schema",
    "apply_transform": "dsl",
    "TransformError": "dsl",
    "execute_sources": "executor",
    "map_query_error": "executor",
    "SourceOutcome": "executor",
    "ExecutionOutcome": "executor",
    "LinkedSurfaceService": "service",
    "LinkedGuardRequired": "service",
    "TransformManifest": "manifest",
    "load_manifest": "manifest",
    "resolve_ref": "manifest",
}


def __getattr__(name: str) -> Any:
    """Resolve execution-side names on first access (PEP 562)."""
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(f"{__name__}.{module}"), name)


def has_data_sources(envelope: Any) -> bool:
    """Return whether an envelope carries a non-empty data-source extension."""
    if isinstance(envelope, Mapping):
        payload = envelope.get("createSurface", envelope)
        if not isinstance(payload, Mapping):
            return False
        metadata = payload.get("metadata")
        extensions = metadata.get("extensions") if isinstance(metadata, Mapping) else None
    else:
        metadata = getattr(envelope, "metadata", None)
        extensions = getattr(metadata, "extensions", None)
        extensions = getattr(extensions, "root", extensions)
    if not isinstance(extensions, Mapping):
        return False
    sources = extensions.get(DATA_SOURCES_EXTENSION)
    return isinstance(sources, Mapping) and bool(sources)


__all__ = [
    "DATA_SOURCES_EXTENSION",
    "Derive",
    "DeriveBinary",
    "Filter",
    "GroupBy",
    "Join",
    "JoinKey",
    "Limit",
    "LinkedDataSource",
    "LinkedSources",
    "ParamSpec",
    "Pivot",
    "RefreshPolicy",
    "Rename",
    "Select",
    "Sort",
    "SortKey",
    "SourceRequest",
    "TransformOp",
    "TransformRef",
    "TransformSpec",
    "UnionOp",
    "has_data_sources",
    *_LAZY,
]
