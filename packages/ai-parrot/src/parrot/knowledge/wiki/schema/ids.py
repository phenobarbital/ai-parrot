"""Kind-first id grammar for the schema plane (FEAT-600 M1)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parrot.knowledge.wiki.schema.models import SchemaSourceConfig

KINDS: tuple[str, ...] = ("source", "schema", "table")
_TABLE_RE = re.compile(r"^table:(?P<origin>[^/]+)/(?P<schema>[^.]+)\.(?P<table>.+)$")
_BARE_RE = re.compile(r"^(?P<origin>[A-Za-z0-9_-]+):(?P<schema>[^.]+)\.(?P<table>.+)$")
_SCHEMA_TABLE_RE = re.compile(r"^(?P<schema>[^.:/]+)\.(?P<table>[^.:/]+)$")


def source_concept_id(origin: str) -> str:
    """Return ``source:<origin>``."""
    return f"source:{origin}"


def schema_concept_id(origin: str, schema: str) -> str:
    """Return ``schema:<origin>/<schema>``."""
    return f"schema:{origin}/{schema}"


def table_concept_id(origin: str, schema: str, table: str) -> str:
    """Return a table concept id, preserving dialect case."""
    return f"table:{origin}/{schema}.{table}"


def parse_table_id(concept_id: str) -> tuple[str, str, str]:
    """Return ``(origin, schema, table)`` for a valid table concept id.

    Raises:
        ValueError: If the id is malformed or has another kind.
    """
    match = _TABLE_RE.match(concept_id)
    if match is None:
        raise ValueError(f"not a table id: {concept_id!r}")
    return match["origin"], match["schema"], match["table"]


def normalize_ref(ref: str, *, sources: dict[str, SchemaSourceConfig] | None = None) -> str | list[str]:
    """Normalize a table reference without guessing an ambiguous origin."""
    if _TABLE_RE.match(ref):
        return ref
    bare = _BARE_RE.match(ref)
    if bare and not ref.startswith(tuple(kind + ":" for kind in KINDS)):
        return table_concept_id(bare["origin"], bare["schema"], bare["table"])
    schema_table = _SCHEMA_TABLE_RE.match(ref)
    if schema_table is None:
        raise ValueError(f"unrecognised table reference: {ref!r}")
    candidates = [
        table_concept_id(alias, schema_table["schema"], schema_table["table"])
        for alias, config in (sources or {}).items()
        if schema_table["schema"] in config.allowed_schemas
    ]
    return candidates[0] if len(candidates) == 1 else candidates
