"""Postgres schema, migration, and connection-pool base for GraphIndex (FEAT-520).

Module 1 of the GraphIndex Postgres backend. Owns the ``graphindex.*``
bitemporal schema (spec §2 "Schema DDL"), an idempotent versioned migration
in the house ``_MIGRATION_COLUMNS`` style (``wiki/store.py:166``,
``persist_sqlite.py:109``), asyncpg pool creation with pgvector codec
registration, and navconfig-backed settings.

``asyncpg`` is the only driver used anywhere in this backend — no other
ORM/SQL-toolkit imports (spec U4/D8).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import asyncpg
from navconfig import config
from pgvector.asyncpg import register_vector

from parrot.conf import default_dsn

logger = logging.getLogger(__name__)

#: Version of the ``graphindex.*`` Postgres schema. Bumped whenever
#: ``_MIGRATION_COLUMNS`` grows a new entry.
PG_SCHEMA_VERSION = "1"

# ---------------------------------------------------------------------------
# navconfig-backed settings
# ---------------------------------------------------------------------------

#: asyncpg DSN for the backend. Defaults to ``parrot.conf.default_dsn`` (the
#: local Postgres carrying the vector/btree_gist/pg_trgm extensions) —
#: exact pattern of ``CREW_RESULT_STORAGE_PG_DSN`` (``conf.py:302``).
#: ``None`` when neither an explicit override nor the default DB config is
#: present (``conf.py:76``) — live tests skip in that case.
GRAPHINDEX_PG_DSN: Optional[str] = config.get("GRAPHINDEX_PG_DSN", fallback=default_dsn)

#: Postgres schema name housing all GraphIndex tables.
GRAPHINDEX_PG_SCHEMA: str = config.get("GRAPHINDEX_PG_SCHEMA", fallback="graphindex")

#: pgvector embedding column dimension (deployment-fixed).
GRAPHINDEX_EMBEDDING_DIM: int = int(config.get("GRAPHINDEX_EMBEDDING_DIM", fallback=1536))

#: Namespace-prefix -> Postgres FTS regconfig map (D7). Declarative config,
#: never hardcoded in SQL strings. Longest-prefix match, default ``simple``.
GRAPHINDEX_FTS_REGCONFIG: dict[str, str] = {
    "legal:": "spanish",
    "sym:": "simple",
}

#: ANN index type for ``graphindex.embeddings``. Default ``"ivfflat"`` —
#: TASK-2770's OQ3 spike (``artifacts/logs/feat-520-oq3-spike.md``)
#: measured ivfflat beating hnsw on BOTH build time (~0.8s vs ~22.8s) and
#: query latency (~0.01s vs ~0.07s) at a 5k-row synthetic corpus on
#: pgvector 0.5.0, contradicting TASK-2769's provisional ``"hnsw"``
#: default. Config-overridable (``"hnsw"`` or ``"ivfflat"``); re-run the
#: spike before trusting this at a materially different corpus size,
#: dimension, or once the deployment target runs pgvector >=0.8 (iterative
#: scan changes hnsw's filtered-query economics).
GRAPHINDEX_ANN_INDEX_KIND: str = config.get("GRAPHINDEX_ANN_INDEX_KIND", fallback="ivfflat")


def validate_embedding_dim(vector: list[float], *, dim: Optional[int] = None) -> None:
    """Reject a vector whose length does not match the configured dimension.

    Args:
        vector: The embedding to validate.
        dim: Expected dimension; defaults to ``GRAPHINDEX_EMBEDDING_DIM``.

    Raises:
        ValueError: When ``len(vector) != dim``.
    """
    expected = dim if dim is not None else GRAPHINDEX_EMBEDDING_DIM
    if len(vector) != expected:
        raise ValueError(
            f"Embedding dimension mismatch: expected {expected}, got {len(vector)} "
            "(GRAPHINDEX_EMBEDDING_DIM configures the fixed column width)."
        )


def resolve_regconfig(namespace: str) -> str:
    """Resolve the FTS regconfig for a namespace via longest-prefix match.

    Args:
        namespace: A node/edge namespace such as ``"legal:core"`` or
            ``"sym:python"``.

    Returns:
        The configured regconfig name, or ``"simple"`` when no prefix in
        ``GRAPHINDEX_FTS_REGCONFIG`` matches.
    """
    best_match = ""
    best_regconfig = "simple"
    for prefix, regconfig in GRAPHINDEX_FTS_REGCONFIG.items():
        if namespace.startswith(prefix) and len(prefix) > len(best_match):
            best_match = prefix
            best_regconfig = regconfig
    return best_regconfig


# ---------------------------------------------------------------------------
# DDL (normative draft — spec §2 "Schema DDL")
# ---------------------------------------------------------------------------

#: Extensions required by the schema. Failure to create either surfaces a
#: clear, actionable error instead of a cryptic ``UndefinedObjectError``
#: deep inside a later ``CREATE TABLE``.
_REQUIRED_EXTENSIONS = ("vector", "btree_gist", "pg_trgm")


def _ddl(schema: str) -> str:
    """Build the full idempotent DDL for the ``graphindex`` schema.

    Args:
        schema: The Postgres schema name (operator-controlled navconfig
            setting, not user input — safe to interpolate).

    Returns:
        A multi-statement SQL string, safe to execute repeatedly.
    """
    return f"""
CREATE SCHEMA IF NOT EXISTS {schema};

CREATE TABLE IF NOT EXISTS {schema}.meta (
    key   text PRIMARY KEY,
    value text NOT NULL
);

CREATE TABLE IF NOT EXISTS {schema}.nodes (
    concept_id   text PRIMARY KEY,
    namespace    text NOT NULL DEFAULT '',
    category     text NOT NULL,
    node_id      text,
    lang         text NOT NULL DEFAULT 'simple',
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS {schema}.node_versions (
    version_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    concept_id   text NOT NULL REFERENCES {schema}.nodes ON DELETE CASCADE,
    validity     tstzrange NOT NULL DEFAULT tstzrange(now(), null),
    tx_from      timestamptz NOT NULL DEFAULT now(),
    title        text NOT NULL,
    summary      text NOT NULL DEFAULT '',
    body         text,
    body_ref     text,
    source_id    text,
    content_hash text,
    token_count  integer NOT NULL DEFAULT 0,
    fts          tsvector,
    provenance   text NOT NULL DEFAULT 'extracted',
    derived      boolean NOT NULL DEFAULT false,
    origin       text,
    asserted_by  text,
    updated_at   timestamptz,
    assertion    jsonb,
    domain_tags  jsonb,
    EXCLUDE USING gist (concept_id WITH =, validity WITH &&)
);
CREATE INDEX IF NOT EXISTS nv_current  ON {schema}.node_versions (concept_id) WHERE upper_inf(validity);
CREATE INDEX IF NOT EXISTS nv_validity ON {schema}.node_versions USING gist (validity);
CREATE INDEX IF NOT EXISTS nv_fts      ON {schema}.node_versions USING gin (fts);

CREATE TABLE IF NOT EXISTS {schema}.edges (
    edge_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    src          text NOT NULL,
    dst          text NOT NULL,
    rel          text NOT NULL,
    validity     tstzrange NOT NULL DEFAULT tstzrange(now(), null),
    tx_from      timestamptz NOT NULL DEFAULT now(),
    provenance   text NOT NULL DEFAULT 'extracted',
    derived      boolean NOT NULL DEFAULT false,
    confidence   real,
    assertion    jsonb,
    evidence_ref jsonb,
    source_id    text,
    CHECK ((provenance = 'inferred') = (confidence IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS e_src      ON {schema}.edges (src, rel) WHERE upper_inf(validity);
CREATE INDEX IF NOT EXISTS e_dst      ON {schema}.edges (dst, rel) WHERE upper_inf(validity);
CREATE INDEX IF NOT EXISTS e_validity ON {schema}.edges USING gist (validity);

CREATE TABLE IF NOT EXISTS {schema}.embeddings (
    concept_id   text NOT NULL,
    version_id   bigint NOT NULL REFERENCES {schema}.node_versions ON DELETE CASCADE,
    model        text NOT NULL DEFAULT '',
    embedding    vector({GRAPHINDEX_EMBEDDING_DIM}) NOT NULL,
    PRIMARY KEY (version_id, model)
);

CREATE TABLE IF NOT EXISTS {schema}.symbols (
    concept_id   text PRIMARY KEY,
    rel_path     text NOT NULL,
    language     text NOT NULL,
    kind         text NOT NULL,
    name         text NOT NULL,
    qualname     text NOT NULL,
    parent       text,
    signature    text NOT NULL DEFAULT '',
    doc          text NOT NULL DEFAULT '',
    exported     boolean NOT NULL DEFAULT false,
    is_async     boolean NOT NULL DEFAULT false,
    depth        integer NOT NULL DEFAULT 1,
    start_line   integer,
    end_line     integer,
    start_byte   integer,
    end_byte     integer,
    node_kind    text,
    content_hash text,
    source_id    text
);
CREATE INDEX IF NOT EXISTS idx_symbols_name   ON {schema}.symbols (name);
CREATE INDEX IF NOT EXISTS idx_symbols_path   ON {schema}.symbols (rel_path);
CREATE INDEX IF NOT EXISTS idx_symbols_source ON {schema}.symbols (source_id);

CREATE TABLE IF NOT EXISTS {schema}.files (
    source_uri text PRIMARY KEY,
    mtime      double precision NOT NULL,
    sha1       text NOT NULL,
    indexed_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS {schema}.commits (
    commit_id    text PRIMARY KEY,
    seq          bigint GENERATED ALWAYS AS IDENTITY,
    op           text NOT NULL,
    agent_id     text,
    run_id       text,
    asserted_by  text NOT NULL,
    reason       text,
    committed_at timestamptz NOT NULL DEFAULT now(),
    payload      jsonb NOT NULL,
    reverted_at  timestamptz
);

CREATE TABLE IF NOT EXISTS {schema}.commit_items (
    commit_id  text NOT NULL REFERENCES {schema}.commits,
    item_type  text NOT NULL,
    item_key   text NOT NULL,
    collection text,
    prior      jsonb,
    PRIMARY KEY (commit_id, item_type, item_key)
);
"""


#: Columns added after v1 shipped. ``CREATE TABLE IF NOT EXISTS`` silently
#: skips existing tables/columns, so ``ensure_schema`` ALTERs these in when
#: missing (idempotent, no data rewrite) — same shape as
#: ``wiki/store.py:166`` / ``persist_sqlite.py:109``. Module 8 (TASK-2772)
#: adds the symbol FTS column here — ``simple`` regconfig only, never
#: language-stemmed (D7: code/symbols never get stemming).
_MIGRATION_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "symbols": [("search_tsv", "tsvector")],
}


async def _ensure_extensions(conn: asyncpg.Connection) -> None:
    """Create the Postgres extensions this schema requires.

    Args:
        conn: An open asyncpg connection with sufficient privilege.

    Raises:
        RuntimeError: When an extension cannot be created (missing
            privilege or the extension is not available on the server),
            with a clear, actionable message.
    """
    for ext in _REQUIRED_EXTENSIONS:
        try:
            await conn.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
        except asyncpg.PostgresError as exc:
            raise RuntimeError(
                f"GraphIndex Postgres backend requires the '{ext}' extension, "
                f"but it could not be created ({exc}). Install/enable "
                f"'{ext}' on the target Postgres server (superuser or "
                f"CREATE privilege on extensions may be required)."
            ) from exc


async def _migrate(conn: asyncpg.Connection, schema: str) -> None:
    """Apply any missing columns from ``_MIGRATION_COLUMNS`` idempotently.

    Args:
        conn: An open asyncpg connection.
        schema: The target schema name.
    """
    for table, columns in _MIGRATION_COLUMNS.items():
        existing = {
            row["column_name"]
            for row in await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = $1 AND table_name = $2",
                schema,
                table,
            )
        }
        for column, ddl_type in columns:
            if column in existing:
                continue
            await conn.execute(
                f"ALTER TABLE {schema}.{table} ADD COLUMN IF NOT EXISTS {column} {ddl_type}"
            )


async def ensure_schema(pool: asyncpg.Pool, schema: str = GRAPHINDEX_PG_SCHEMA) -> None:
    """Idempotently create/migrate the ``graphindex.*`` schema.

    Safe to call on every store initialization: a second call against an
    already-migrated schema is a no-op beyond the version-stamp upsert.

    Args:
        pool: An asyncpg connection pool (see ``create_pg_pool``).
        schema: The target schema name.
    """
    async with pool.acquire() as conn:
        await _ensure_extensions(conn)
        async with conn.transaction():
            await conn.execute(_ddl(schema))
            await _migrate(conn, schema)
            # Post-migration indexes on migrated columns (search_tsv must
            # already exist — guaranteed by _migrate() above).
            await conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS symbols_search_tsv_idx ON {schema}.symbols USING gin (search_tsv);
                CREATE INDEX IF NOT EXISTS symbols_qualname_trgm_idx
                    ON {schema}.symbols USING gin (qualname gin_trgm_ops);
                CREATE INDEX IF NOT EXISTS symbols_name_trgm_idx
                    ON {schema}.symbols USING gin (name gin_trgm_ops);
                """
            )
            await conn.execute(
                f"""
                INSERT INTO {schema}.meta (key, value) VALUES ('schema_version', $1)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                PG_SCHEMA_VERSION,
            )
    logger.info("graphindex Postgres schema '%s' ensured at version %s", schema, PG_SCHEMA_VERSION)


async def ensure_ann_index(
    pool: asyncpg.Pool,
    *,
    schema: str = GRAPHINDEX_PG_SCHEMA,
    kind: str = GRAPHINDEX_ANN_INDEX_KIND,
) -> None:
    """Idempotently create the ANN index on ``graphindex.embeddings.embedding``.

    Config-driven, not called by :func:`ensure_schema` automatically —
    building an ANN index is a deliberate operational step (ivfflat in
    particular benefits from running after data is loaded). ``kind``
    defaults to ``"ivfflat"`` per TASK-2770's OQ3 spike measurements
    (``artifacts/logs/feat-520-oq3-spike.md``); ``"hnsw"`` remains
    available and config-selectable.

    Args:
        pool: An asyncpg connection pool.
        schema: The target schema name.
        kind: ``"hnsw"`` or ``"ivfflat"``.

    Raises:
        ValueError: For an unknown ``kind``.
    """
    index_name = f"embeddings_{kind}_idx"
    if kind == "hnsw":
        ddl = (
            f"CREATE INDEX IF NOT EXISTS {index_name} ON {schema}.embeddings "
            "USING hnsw (embedding vector_cosine_ops)"
        )
    elif kind == "ivfflat":
        ddl = (
            f"CREATE INDEX IF NOT EXISTS {index_name} ON {schema}.embeddings "
            "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )
    else:
        raise ValueError(f"Unknown ANN index kind {kind!r} — expected 'hnsw' or 'ivfflat'")

    async with pool.acquire() as conn:
        await conn.execute(ddl)
    logger.info("graphindex Postgres ANN index '%s' (%s) ensured on schema '%s'", index_name, kind, schema)


async def create_pg_pool(
    dsn: Optional[str] = None,
    *,
    schema: str = GRAPHINDEX_PG_SCHEMA,
    min_size: int = 1,
    max_size: int = 10,
    **kwargs: Any,
) -> asyncpg.Pool:
    """Create an asyncpg pool configured for the GraphIndex Postgres backend.

    Registers the pgvector codec and sets ``search_path`` on every new
    connection so callers can reference unqualified table names.

    Args:
        dsn: asyncpg-compatible DSN. Defaults to ``GRAPHINDEX_PG_DSN``
            (itself defaulting to ``parrot.conf.default_dsn``).
        schema: Schema to set as the connection's search_path.
        min_size: Minimum pool size.
        max_size: Maximum pool size.
        **kwargs: Extra kwargs forwarded to ``asyncpg.create_pool``.

    Returns:
        A ready-to-use ``asyncpg.Pool``.

    Raises:
        ValueError: When no DSN is resolved (no override and
            ``default_dsn`` is ``None``).
    """
    resolved_dsn = dsn or GRAPHINDEX_PG_DSN
    if not resolved_dsn:
        raise ValueError(
            "No Postgres DSN resolved for the GraphIndex backend. Set "
            "GRAPHINDEX_PG_DSN or configure the default database (DBUSER/"
            "DBHOST/DBNAME) so parrot.conf.default_dsn resolves."
        )

    async def _init(conn: asyncpg.Connection) -> None:
        await register_vector(conn)
        await conn.execute(f"SET search_path TO {schema}, public")

    return await asyncpg.create_pool(
        dsn=resolved_dsn,
        min_size=min_size,
        max_size=max_size,
        init=_init,
        **kwargs,
    )
