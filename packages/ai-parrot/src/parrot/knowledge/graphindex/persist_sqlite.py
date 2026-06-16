"""SQLite persistence backend for GraphIndex (FEAT-240).

Provides a per-tenant SQLite artefact as an alternative to ArangoDB.
Features WAL journal mode, a ``files`` table for incremental staleness
tracking, ``nodes``/``edges`` tables, and a ``nodes_fts`` FTS5/BM25
virtual table for lexical search.

Public API mirrors ``GraphIndexPersistence``:
- ``persist_graph(ctx, nodes, edges)`` — full persist with schema creation
- ``replace_document_slice(ctx, document_uri, nodes, edges)`` — atomic DELETE+INSERT
- ``is_stale(ctx, source_uri, mtime, sha1)`` — incremental staleness check
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import aiosqlite
import orjson

from parrot.knowledge.graphindex.schema import (
    UniversalEdge,
    UniversalNode,
)
from parrot.knowledge.ontology.schema import TenantContext

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS files (
    source_uri  TEXT PRIMARY KEY,
    mtime       REAL NOT NULL,
    sha1        TEXT NOT NULL,
    indexed_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nodes (
    node_id       TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    title         TEXT NOT NULL,
    source_uri    TEXT NOT NULL,
    parent_id     TEXT,
    summary       TEXT,
    content_ref   TEXT,
    embedding_ref TEXT,
    provenance    TEXT NOT NULL,
    domain_tags   TEXT
);
CREATE INDEX IF NOT EXISTS idx_nodes_source_uri ON nodes(source_uri);
CREATE INDEX IF NOT EXISTS idx_nodes_parent     ON nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_nodes_kind       ON nodes(kind);

CREATE TABLE IF NOT EXISTS edges (
    source_id   TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    kind        TEXT NOT NULL,
    provenance  TEXT NOT NULL,
    confidence  REAL,
    source_uri  TEXT,
    PRIMARY KEY (source_id, target_id, kind)
);
CREATE INDEX IF NOT EXISTS idx_edges_kind       ON edges(kind, source_id);
CREATE INDEX IF NOT EXISTS idx_edges_source_uri ON edges(source_uri);

CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    node_id UNINDEXED, title, summary, tokenize = 'unicode61'
);
"""


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _tags_json(node: UniversalNode) -> str:
    """Serialize a node's domain_tags to a JSON string via orjson."""
    return orjson.dumps(node.domain_tags).decode()


class SQLitePersistence:
    """Per-tenant SQLite persistence backend for GraphIndex.

    Creates one ``<tenant_id>.db`` file per tenant inside ``db_dir``.
    The schema is initialised automatically on first access.

    The public API matches ``GraphIndexPersistence`` so the builder can
    use either backend via dependency injection.  Additionally exposes
    ``is_stale()`` for incremental build support.

    Args:
        db_dir: Directory where tenant ``.db`` files are stored.  Will
            be created if it does not exist.
    """

    def __init__(self, db_dir: Path) -> None:
        self._db_dir = Path(db_dir)
        self._db_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _db_path(self, ctx: TenantContext) -> Path:
        """Return the path to the tenant's SQLite database file.

        Args:
            ctx: Tenant context containing the ``tenant_id``.

        Returns:
            Absolute path to the ``.db`` file.
        """
        return self._db_dir / f"{ctx.tenant_id}.db"

    @asynccontextmanager
    async def _connect(self, ctx: TenantContext) -> AsyncIterator[aiosqlite.Connection]:
        """Open (or create) the tenant's database and initialise the schema.

        Yields an ``aiosqlite.Connection`` with WAL mode and the full schema
        applied.  The caller is responsible for committing before exiting.

        Args:
            ctx: Tenant context.

        Yields:
            An open aiosqlite.Connection.
        """
        async with aiosqlite.connect(str(self._db_path(ctx))) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA_SQL)
            await conn.commit()
            yield conn

    async def _upsert_files(
        self,
        conn: aiosqlite.Connection,
        nodes: list[UniversalNode],
    ) -> None:
        """Insert or replace file-level mtime/sha1 tracking rows.

        Only processes nodes whose ``domain_tags`` contain ``"mtime"`` and
        ``"sha1"`` (i.e. module nodes written by ``CodeExtractor``). Canonical
        nodes with synthetic ``source_uri`` values (e.g. ``odoo-model://``) are
        intentionally skipped.

        Args:
            conn: Open database connection (within a transaction).
            nodes: All nodes from the current batch.
        """
        indexed_at = _now_iso()
        for n in nodes:
            tags = n.domain_tags
            mtime = tags.get("mtime")
            sha1 = tags.get("sha1")
            if mtime is None or sha1 is None:
                continue
            if n.source_uri.startswith("odoo-model://"):
                continue
            await conn.execute(
                "INSERT OR REPLACE INTO files (source_uri, mtime, sha1, indexed_at)"
                " VALUES (?, ?, ?, ?)",
                (n.source_uri, mtime, sha1, indexed_at),
            )

    async def _insert_nodes_fts(
        self,
        conn: aiosqlite.Connection,
        nodes: list[UniversalNode],
    ) -> None:
        """Populate the FTS5 index for the given nodes.

        Args:
            conn: Open database connection.
            nodes: Nodes to index.
        """
        await conn.executemany(
            "INSERT OR REPLACE INTO nodes_fts(node_id, title, summary)"
            " VALUES (?, ?, ?)",
            [(n.node_id, n.title, n.summary or "") for n in nodes],
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def persist_graph(
        self,
        ctx: TenantContext,
        nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> dict[str, Any]:
        """Persist all nodes and edges for a tenant graph.

        Applies an ``INSERT OR REPLACE`` strategy so repeated calls are
        idempotent.  The FTS5 index and ``files`` table are also updated.

        Args:
            ctx: Tenant context.
            nodes: All graph nodes to persist.
            edges: All graph edges to persist.

        Returns:
            ``{"nodes_persisted": N, "edges_persisted": M}``
        """
        async with self._connect(ctx) as conn:
            await self._upsert_files(conn, nodes)

            await conn.executemany(
                "INSERT OR REPLACE INTO nodes"
                " (node_id, kind, title, source_uri, parent_id, summary,"
                "  content_ref, embedding_ref, provenance, domain_tags)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        n.node_id,
                        n.kind.value,
                        n.title,
                        n.source_uri,
                        n.parent_id,
                        n.summary,
                        n.content_ref,
                        n.embedding_ref,
                        n.provenance.value,
                        _tags_json(n),
                    )
                    for n in nodes
                ],
            )

            await conn.executemany(
                "INSERT OR REPLACE INTO edges"
                " (source_id, target_id, kind, provenance, confidence, source_uri)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        e.source_id,
                        e.target_id,
                        e.kind.value,
                        e.provenance.value,
                        e.confidence,
                        None,
                    )
                    for e in edges
                ],
            )

            # Populate FTS5 index
            await conn.execute("DELETE FROM nodes_fts")
            await self._insert_nodes_fts(conn, nodes)

            await conn.commit()

            logger.info(
                "SQLitePersistence.persist_graph: %d nodes, %d edges → %s",
                len(nodes),
                len(edges),
                self._db_path(ctx),
            )
            return {"nodes_persisted": len(nodes), "edges_persisted": len(edges)}

    async def replace_document_slice(
        self,
        ctx: TenantContext,
        document_uri: str,
        nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> dict[str, Any]:
        """Atomically replace all nodes/edges for a single document.

        Deletes existing nodes and edges whose ``source_uri`` matches
        ``document_uri``, then inserts the new ones.  Canonical nodes
        (``source_uri`` starting with ``odoo-model://``) are NEVER deleted
        even if their ``source_uri`` is passed as ``document_uri``.

        The entire operation is wrapped in a single transaction for
        atomicity.

        Args:
            ctx: Tenant context.
            document_uri: URI of the document to replace.
            nodes: Replacement nodes (may include canonical nodes).
            edges: Replacement edges.

        Returns:
            ``{"nodes_replaced": N, "edges_replaced": M}``
        """
        async with self._connect(ctx) as conn:
            # Count what we're replacing
            async with conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE source_uri = ?"
                " AND source_uri NOT LIKE 'odoo-model://%'",
                (document_uri,),
            ) as cur:
                row = await cur.fetchone()
                old_node_count = row[0] if row else 0

            # Delete nodes (preserve canonical nodes)
            await conn.execute(
                "DELETE FROM nodes WHERE source_uri = ?"
                " AND source_uri NOT LIKE 'odoo-model://%'",
                (document_uri,),
            )
            # Delete edges stamped with the document_uri
            await conn.execute(
                "DELETE FROM edges WHERE source_uri = ?",
                (document_uri,),
            )
            # Also remove edges whose source/target nodes no longer exist
            # (orphan cleanup from deleted nodes)
            await conn.execute(
                "DELETE FROM edges WHERE source_id NOT IN (SELECT node_id FROM nodes)"
                " OR target_id NOT IN (SELECT node_id FROM nodes)"
            )

            await self._upsert_files(conn, nodes)

            await conn.executemany(
                "INSERT OR REPLACE INTO nodes"
                " (node_id, kind, title, source_uri, parent_id, summary,"
                "  content_ref, embedding_ref, provenance, domain_tags)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        n.node_id,
                        n.kind.value,
                        n.title,
                        n.source_uri,
                        n.parent_id,
                        n.summary,
                        n.content_ref,
                        n.embedding_ref,
                        n.provenance.value,
                        _tags_json(n),
                    )
                    for n in nodes
                ],
            )

            # Stamp edges with the source_uri of their source node
            edge_rows = []
            node_uri_by_id = {n.node_id: n.source_uri for n in nodes}
            for e in edges:
                src_uri = node_uri_by_id.get(e.source_id)
                edge_rows.append((
                    e.source_id,
                    e.target_id,
                    e.kind.value,
                    e.provenance.value,
                    e.confidence,
                    src_uri,
                ))

            await conn.executemany(
                "INSERT OR REPLACE INTO edges"
                " (source_id, target_id, kind, provenance, confidence, source_uri)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                edge_rows,
            )

            # Update FTS5 for the replaced nodes
            await conn.execute(
                "DELETE FROM nodes_fts WHERE node_id IN"
                " (SELECT node_id FROM nodes WHERE source_uri = ?)",
                (document_uri,),
            )
            await self._insert_nodes_fts(conn, nodes)

            await conn.commit()

            logger.info(
                "SQLitePersistence.replace_document_slice: %s → %d nodes, %d edges",
                document_uri,
                len(nodes),
                len(edges),
            )
            return {
                "nodes_replaced": old_node_count,
                "edges_replaced": len(edges),
            }

    async def is_stale(
        self,
        ctx: TenantContext,
        source_uri: str,
        mtime: float,
        sha1: str,
    ) -> bool:
        """Check whether a source file needs re-extraction.

        Returns ``False`` (not stale) when the stored ``mtime`` matches
        and the stored ``sha1`` matches the supplied values.  Returns
        ``True`` (stale) when the file has not been indexed before, the
        ``mtime`` has changed, or the ``sha1`` differs.

        Args:
            ctx: Tenant context.
            source_uri: The file's source URI as stored in the ``files``
                table.
            mtime: Current filesystem modification time.
            sha1: SHA-1 hex digest of the current file content.

        Returns:
            ``True`` if the file should be re-extracted; ``False`` if the
            stored snapshot is still valid.
        """
        db = self._db_path(ctx)
        if not db.exists():
            return True

        async with aiosqlite.connect(str(db)) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT mtime, sha1 FROM files WHERE source_uri = ?",
                (source_uri,),
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                return True
            if row["sha1"] != sha1:
                return True
            if row["mtime"] != mtime:
                return True
            return False
