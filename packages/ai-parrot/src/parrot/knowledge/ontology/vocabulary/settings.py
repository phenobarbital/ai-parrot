"""ONTOLOGY_* settings for the vocabulary store, resolved at call time (FEAT-824)."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

_VALID_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


class OntologyStoreSettings(BaseModel):
    """Resolved ONTOLOGY_* settings (spec section 2 settings table)."""

    backend: str = "postgres"
    dsn: str | None = None
    schema_name: str = "ontology_store"
    embedding_dim: int = 1024
    ann_index_kind: str = "hnsw"
    snapshot_dir: Path = Path("~/.parrot/ontology")
    snapshot_url: str | None = None
    default_lang: str = "es"


def resolve_ontology_settings(
    *,
    backend: str | None = None,
    dsn: str | None = None,
    schema: str | None = None,
) -> OntologyStoreSettings:
    """Resolve settings via explicit values, environment, navconfig, then defaults.

    Args:
        backend: Explicit backend override.
        dsn: Explicit PostgreSQL DSN override.
        schema: Explicit PostgreSQL schema override.

    Returns:
        The resolved and validated ontology-store settings.

    Raises:
        ValueError: When the schema name is not a plain SQL identifier, or the
            ANN index kind is not ``hnsw`` or ``ivfflat``.
    """
    from parrot.knowledge.wiki.project import resolve_setting

    schema_name = str(resolve_setting("ONTOLOGY_PG_SCHEMA", default="ontology_store", explicit=schema))
    if _VALID_SCHEMA_NAME.fullmatch(schema_name) is None:
        raise ValueError(f"Invalid ontology schema name: {schema_name!r}")

    ann_index_kind = str(resolve_setting("ONTOLOGY_ANN_INDEX_KIND", default="hnsw"))
    if ann_index_kind not in {"hnsw", "ivfflat"}:
        raise ValueError(f"Invalid ontology ANN index kind: {ann_index_kind!r}; expected hnsw or ivfflat")

    snapshot_dir = Path(resolve_setting("ONTOLOGY_SNAPSHOT_DIR", default="~/.parrot/ontology")).expanduser()
    return OntologyStoreSettings(
        backend=resolve_setting("ONTOLOGY_BACKEND", default="postgres", explicit=backend),
        dsn=resolve_setting("ONTOLOGY_PG_DSN", explicit=dsn),
        schema_name=schema_name,
        embedding_dim=int(resolve_setting("ONTOLOGY_EMBEDDING_DIM", default=1024)),
        ann_index_kind=ann_index_kind,
        snapshot_dir=snapshot_dir,
        snapshot_url=resolve_setting("ONTOLOGY_SNAPSHOT_URL"),
        default_lang=resolve_setting("ONTOLOGY_DEFAULT_LANG", default="es"),
    )
