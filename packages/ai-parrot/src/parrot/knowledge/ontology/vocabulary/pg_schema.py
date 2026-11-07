"""PostgreSQL schema of the ontology vocabulary store (FEAT-824).

Idempotent DDL in a dedicated schema (default ``ontology_store``). Does not import
``parrot.knowledge.graphindex``.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import asyncpg

from parrot.knowledge.ontology.vocabulary.settings import resolve_ontology_settings

logger = logging.getLogger("parrot.knowledge.ontology.vocabulary.pg_schema")

ONTOLOGY_PG_SCHEMA_VERSION = "1"
_REQUIRED_EXTENSIONS = ("vector", "pg_trgm")
_VALID_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


def validate_schema_name(schema: str) -> None:
    """Raise ValueError unless ``schema`` is a plain, unquoted SQL identifier."""
    if not _VALID_SCHEMA_NAME.match(schema):
        raise ValueError(f"Invalid ontology schema name {schema!r} — expected ^[a-z_][a-z0-9_]*$")


def _ddl(schema: str, embedding_dim: int) -> str:
    """Return idempotent DDL for the vocabulary tables and non-ANN indexes."""
    s, dim = schema, int(embedding_dim)
    return f"""
CREATE SCHEMA IF NOT EXISTS {s};
CREATE TABLE IF NOT EXISTS {s}.ontology (
  ontology_id text PRIMARY KEY, base_iri text NOT NULL, title text,
  current_version int NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS {s}.version (
  ontology_id text NOT NULL REFERENCES {s}.ontology, version int NOT NULL,
  released_at timestamptz NOT NULL DEFAULT now(), checksum text NOT NULL,
  turtle_canonical text NOT NULL, turtle_uri text, notes text,
  PRIMARY KEY (ontology_id, version));
CREATE TABLE IF NOT EXISTS {s}.concept_identity (
  ontology_id text NOT NULL REFERENCES {s}.ontology, iri text NOT NULL,
  PRIMARY KEY (ontology_id, iri));
CREATE TABLE IF NOT EXISTS {s}.concept (
  ontology_id text NOT NULL, iri text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('class','object_property','datatype_property',
                                     'individual','concept_scheme','skos_concept')),
  pref_label text, definition text, deprecated boolean NOT NULL DEFAULT false, replaced_by text,
  since_version int NOT NULL, until_version int,
  embedding vector({dim}), extra jsonb NOT NULL DEFAULT '{{}}',
  PRIMARY KEY (ontology_id, iri, since_version),
  FOREIGN KEY (ontology_id, iri) REFERENCES {s}.concept_identity,
  FOREIGN KEY (ontology_id, since_version) REFERENCES {s}.version,
  FOREIGN KEY (ontology_id, until_version) REFERENCES {s}.version,
  CHECK (until_version IS NULL OR until_version > since_version));
CREATE TABLE IF NOT EXISTS {s}.label (
  ontology_id text NOT NULL, iri text NOT NULL, lang text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('pref','alt','hidden')), text text NOT NULL,
  since_version int NOT NULL, until_version int,
  PRIMARY KEY (ontology_id, iri, lang, kind, text, since_version),
  FOREIGN KEY (ontology_id, iri) REFERENCES {s}.concept_identity,
  FOREIGN KEY (ontology_id, since_version) REFERENCES {s}.version,
  FOREIGN KEY (ontology_id, until_version) REFERENCES {s}.version,
  CHECK (until_version IS NULL OR until_version > since_version));
CREATE TABLE IF NOT EXISTS {s}.relation (
  ontology_id text NOT NULL, subject_iri text NOT NULL, predicate text NOT NULL,
  object_iri text NOT NULL, inferred boolean NOT NULL DEFAULT false,
  since_version int NOT NULL, until_version int,
  PRIMARY KEY (ontology_id, subject_iri, predicate, object_iri, since_version),
  FOREIGN KEY (ontology_id, since_version) REFERENCES {s}.version,
  FOREIGN KEY (ontology_id, until_version) REFERENCES {s}.version,
  CHECK (until_version IS NULL OR until_version > since_version));
CREATE TABLE IF NOT EXISTS {s}.statement (
  ontology_id text NOT NULL, subject_iri text NOT NULL, predicate text NOT NULL,
  object jsonb NOT NULL, object_hash text NOT NULL,
  since_version int NOT NULL, until_version int,
  PRIMARY KEY (ontology_id, subject_iri, predicate, object_hash, since_version),
  FOREIGN KEY (ontology_id, since_version) REFERENCES {s}.version,
  FOREIGN KEY (ontology_id, until_version) REFERENCES {s}.version,
  CHECK (until_version IS NULL OR until_version > since_version));
CREATE TABLE IF NOT EXISTS {s}.closure (
  ontology_id text NOT NULL, version int NOT NULL,
  family text NOT NULL CHECK (family IN ('subclass','subproperty','broader','partof')),
  ancestor_iri text NOT NULL, descendant_iri text NOT NULL, depth int NOT NULL,
  PRIMARY KEY (ontology_id, version, family, descendant_iri, ancestor_iri),
  FOREIGN KEY (ontology_id, version) REFERENCES {s}.version);
CREATE TABLE IF NOT EXISTS {s}.publication_outbox (
  id bigserial PRIMARY KEY, ontology_id text NOT NULL, version int NOT NULL,
  diff jsonb NOT NULL, enqueued_at timestamptz NOT NULL DEFAULT now(), processed_at timestamptz,
  attempts int NOT NULL DEFAULT 0, last_error text,
  FOREIGN KEY (ontology_id, version) REFERENCES {s}.version);

CREATE UNIQUE INDEX IF NOT EXISTS concept_current   ON {s}.concept (ontology_id, iri) WHERE until_version IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS label_current     ON {s}.label (ontology_id, iri, lang, kind, text) WHERE until_version IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS relation_current  ON {s}.relation (ontology_id, subject_iri, predicate, object_iri) WHERE until_version IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS statement_current ON {s}.statement (ontology_id, subject_iri, predicate, object_hash) WHERE until_version IS NULL;
CREATE INDEX IF NOT EXISTS label_text_trgm     ON {s}.label USING gin (text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS concept_label_trgm  ON {s}.concept USING gin (pref_label gin_trgm_ops);
CREATE INDEX IF NOT EXISTS relation_by_subject ON {s}.relation (ontology_id, predicate, subject_iri);
CREATE INDEX IF NOT EXISTS relation_by_object  ON {s}.relation (ontology_id, predicate, object_iri);
CREATE INDEX IF NOT EXISTS closure_by_ancestor ON {s}.closure (ontology_id, version, family, ancestor_iri);
"""


async def _ensure_extensions(conn: asyncpg.Connection) -> None:
    """Create the extensions required by the vocabulary schema.

    Args:
        conn: An open asyncpg connection with sufficient privilege.

    Raises:
        RuntimeError: When an extension cannot be created.
    """
    for extension in _REQUIRED_EXTENSIONS:
        try:
            await conn.execute(f"CREATE EXTENSION IF NOT EXISTS {extension}")
        except asyncpg.PostgresError as exc:
            raise RuntimeError(
                f"Ontology vocabulary Postgres backend requires the '{extension}' extension, "
                f"but it could not be created ({exc}). Install/enable '{extension}' on the target "
                "Postgres server (superuser or CREATE privilege on extensions may be required)."
            ) from exc


async def ensure_schema(
    pool: asyncpg.Pool,
    schema: str | None = None,
    *,
    embedding_dim: int | None = None,
    ann_index_kind: str | None = None,
) -> None:
    """Create extensions, schema, tables and indexes if missing.

    Raises:
        ValueError: Unsafe schema name or unknown ANN kind.
        RuntimeError: An extension cannot be created.
    """
    settings = resolve_ontology_settings(schema=schema)
    schema = settings.schema_name
    validate_schema_name(schema)
    dim = settings.embedding_dim if embedding_dim is None else int(embedding_dim)
    kind = settings.ann_index_kind if ann_index_kind is None else ann_index_kind
    if kind not in {"hnsw", "ivfflat"}:
        raise ValueError(f"Unknown ontology ANN index kind {kind!r} — expected 'hnsw' or 'ivfflat'")

    ann_options = "" if kind == "hnsw" else " WITH (lists = 100)"
    async with pool.acquire() as conn:
        await _ensure_extensions(conn)
        async with conn.transaction():
            await conn.execute(_ddl(schema, dim))
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS concept_embedding_ann ON {schema}.concept "
                f"USING {kind} (embedding vector_cosine_ops){ann_options} WHERE until_version IS NULL"
            )
    logger.info("ontology vocabulary Postgres schema '%s' ensured at version %s", schema, ONTOLOGY_PG_SCHEMA_VERSION)


async def create_ontology_pg_pool(
    dsn: str | None = None,
    *,
    schema: str | None = None,
    min_size: int = 1,
    max_size: int = 10,
    **kwargs: Any,
) -> asyncpg.Pool:
    """Create an asyncpg pool with a pgvector codec on every connection.

    Raises:
        ValueError: When no DSN is given and ONTOLOGY_PG_DSN is unset.
    """
    from pgvector.asyncpg import register_vector

    settings = resolve_ontology_settings(dsn=dsn, schema=schema)
    if not settings.dsn:
        raise ValueError(
            "No Postgres DSN resolved for the ontology vocabulary backend. Set "
            "ONTOLOGY_PG_DSN (environment or navconfig), or pass dsn= explicitly."
        )

    bootstrap_conn = await asyncpg.connect(dsn=settings.dsn)
    try:
        await _ensure_extensions(bootstrap_conn)
    finally:
        await bootstrap_conn.close()

    async def _init(conn: asyncpg.Connection) -> None:
        await register_vector(conn)

    return await asyncpg.create_pool(
        dsn=settings.dsn,
        min_size=min_size,
        max_size=max_size,
        init=_init,
        **kwargs,
    )
