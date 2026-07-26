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
from typing import Any, AsyncIterator, Optional

import uuid

import aiosqlite
import orjson

from parrot.knowledge.graphindex.schema import (
    AssertionMeta,
    CommitReceipt,
    GraphUpdate,
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
    domain_tags   TEXT,
    assertion     TEXT
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
    assertion   TEXT,
    PRIMARY KEY (source_id, target_id, kind)
);
CREATE INDEX IF NOT EXISTS idx_edges_kind       ON edges(kind, source_id);
CREATE INDEX IF NOT EXISTS idx_edges_source_uri ON edges(source_uri);

CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    node_id UNINDEXED, title, summary, tokenize = 'unicode61'
);

CREATE TABLE IF NOT EXISTS graph_commits (
    commit_id    TEXT PRIMARY KEY,
    op           TEXT NOT NULL,
    agent_id     TEXT,
    run_id       TEXT,
    asserted_by  TEXT NOT NULL,
    reason       TEXT,
    committed_at TEXT NOT NULL,
    payload      TEXT NOT NULL,
    reverted_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_commits_run   ON graph_commits(run_id);
CREATE INDEX IF NOT EXISTS idx_commits_agent ON graph_commits(agent_id);

CREATE TABLE IF NOT EXISTS graph_commit_items (
    commit_id  TEXT NOT NULL,
    item_type  TEXT NOT NULL,
    item_key   TEXT NOT NULL,
    prior      TEXT,
    PRIMARY KEY (commit_id, item_type, item_key)
);
CREATE INDEX IF NOT EXISTS idx_commit_items_key ON graph_commit_items(item_type, item_key);
"""

# Columns added after the original FEAT-240 schema shipped.  ``CREATE TABLE
# IF NOT EXISTS`` silently skips existing databases, so ``_migrate`` ALTERs
# these in when missing (idempotent, no data rewrite).
_MIGRATION_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "nodes": [("assertion", "TEXT")],
    "edges": [("assertion", "TEXT")],
    "graph_commits": [("reverted_at", "TEXT")],
}


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _tags_json(node: UniversalNode) -> str:
    """Serialize a node's domain_tags to a JSON string via orjson."""
    return orjson.dumps(node.domain_tags).decode()


def _assertion_json(item: UniversalNode | UniversalEdge) -> str | None:
    """Serialize a node/edge ``assertion`` to JSON, or ``None`` when absent."""
    if item.assertion is None:
        return None
    return orjson.dumps(item.assertion.model_dump(exclude_none=True)).decode()


def _edge_key(source_id: str, target_id: str, kind: str) -> str:
    """Compose the canonical ``item_key`` string for an edge."""
    return f"{source_id}|{target_id}|{kind}"


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
            await self._migrate(conn)
            await conn.commit()
            yield conn

    async def _migrate(self, conn: aiosqlite.Connection) -> None:
        """Add columns that post-date the original schema when missing.

        ``CREATE TABLE IF NOT EXISTS`` never alters existing tables, so
        databases created before the assertion/audit columns shipped are
        upgraded here via idempotent ``ALTER TABLE ... ADD COLUMN``.

        Args:
            conn: Open database connection (schema already ensured).
        """
        for table, columns in _MIGRATION_COLUMNS.items():
            async with conn.execute(f"PRAGMA table_info({table})") as cur:
                existing = {row["name"] for row in await cur.fetchall()}
            for name, col_type in columns:
                if name not in existing:
                    await conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN {name} {col_type}"
                    )

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
                "  content_ref, embedding_ref, provenance, domain_tags, assertion)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                        _assertion_json(n),
                    )
                    for n in nodes
                ],
            )

            await conn.executemany(
                "INSERT OR REPLACE INTO edges"
                " (source_id, target_id, kind, provenance, confidence,"
                "  source_uri, assertion)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        e.source_id,
                        e.target_id,
                        e.kind.value,
                        e.provenance.value,
                        e.confidence,
                        None,
                        _assertion_json(e),
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
                "  content_ref, embedding_ref, provenance, domain_tags, assertion)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                        _assertion_json(n),
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
                    _assertion_json(e),
                ))

            await conn.executemany(
                "INSERT OR REPLACE INTO edges"
                " (source_id, target_id, kind, provenance, confidence,"
                "  source_uri, assertion)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
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

    # ------------------------------------------------------------------
    # Agent write path — GraphUpdate commits (durable graph memory)
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_node(row: aiosqlite.Row) -> Optional[UniversalNode]:
        """Rehydrate a ``UniversalNode`` from a nodes-table row.

        Returns ``None`` (with a warning) when the row carries an enum
        value unknown to this code version — forward compatibility with
        databases written by newer versions.
        """
        try:
            assertion = None
            raw_assertion = row["assertion"] if "assertion" in row.keys() else None
            if raw_assertion:
                assertion = AssertionMeta(**orjson.loads(raw_assertion))
            return UniversalNode(
                node_id=row["node_id"],
                kind=row["kind"],
                title=row["title"],
                source_uri=row["source_uri"],
                parent_id=row["parent_id"],
                summary=row["summary"],
                content_ref=row["content_ref"],
                embedding_ref=row["embedding_ref"],
                provenance=row["provenance"],
                domain_tags=orjson.loads(row["domain_tags"]) if row["domain_tags"] else {},
                assertion=assertion,
            )
        except Exception as exc:  # noqa: BLE001 — skip-and-warn on unknown kinds
            logger.warning(
                "SQLitePersistence: skipping unreadable node row %r: %s",
                row["node_id"] if "node_id" in row.keys() else "?",
                exc,
            )
            return None

    @staticmethod
    def _row_to_edge(row: aiosqlite.Row) -> Optional[UniversalEdge]:
        """Rehydrate a ``UniversalEdge`` from an edges-table row.

        Returns ``None`` (with a warning) on unknown enum values.
        """
        try:
            assertion = None
            raw_assertion = row["assertion"] if "assertion" in row.keys() else None
            if raw_assertion:
                assertion = AssertionMeta(**orjson.loads(raw_assertion))
            return UniversalEdge(
                source_id=row["source_id"],
                target_id=row["target_id"],
                kind=row["kind"],
                provenance=row["provenance"],
                confidence=row["confidence"],
                assertion=assertion,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "SQLitePersistence: skipping unreadable edge row (%r → %r): %s",
                row["source_id"] if "source_id" in row.keys() else "?",
                row["target_id"] if "target_id" in row.keys() else "?",
                exc,
            )
            return None

    async def load_graph(
        self,
        ctx: TenantContext,
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Load and rehydrate the full tenant graph as schema models.

        Rows with enum values unknown to this code version are skipped
        with a warning instead of raising, so an older library can still
        open a database written by a newer one.

        Args:
            ctx: Tenant context.

        Returns:
            ``(nodes, edges)`` lists of validated models. Empty lists
            when the database does not exist yet.
        """
        if not self._db_path(ctx).exists():
            return [], []
        nodes: list[UniversalNode] = []
        edges: list[UniversalEdge] = []
        async with self._connect(ctx) as conn:
            async with conn.execute("SELECT * FROM nodes") as cur:
                async for row in cur:
                    node = self._row_to_node(row)
                    if node is not None:
                        nodes.append(node)
            async with conn.execute("SELECT * FROM edges") as cur:
                async for row in cur:
                    edge = self._row_to_edge(row)
                    if edge is not None:
                        edges.append(edge)
        return nodes, edges

    async def apply_update(
        self,
        ctx: TenantContext,
        update: GraphUpdate,
    ) -> CommitReceipt:
        """Apply a :class:`GraphUpdate` in one audited transaction.

        Captures the pre-image of every touched row into
        ``graph_commit_items`` (enabling :meth:`revert_commit`), upserts
        nodes and edges, deletes ``removed_edges``, refreshes the FTS
        rows for exactly the written nodes (never the whole index), and
        records the commit with its full payload snapshot.

        Args:
            ctx: Tenant context.
            update: The validated update batch to apply.

        Returns:
            A :class:`CommitReceipt` describing the recorded commit.
        """
        commit_id = uuid.uuid4().hex[:16]
        committed_at = _now_iso()
        warnings: list[str] = []

        async with self._connect(ctx) as conn:
            # --- capture pre-images -----------------------------------
            node_keys = [(n.node_id, "node") for n in update.nodes] + [
                (node_id, "node_removed") for node_id in update.removed_nodes
            ]
            for node_id, item_type in node_keys:
                async with conn.execute(
                    "SELECT * FROM nodes WHERE node_id = ?", (node_id,)
                ) as cur:
                    row = await cur.fetchone()
                prior = orjson.dumps(dict(row)).decode() if row else None
                await conn.execute(
                    "INSERT OR REPLACE INTO graph_commit_items"
                    " (commit_id, item_type, item_key, prior) VALUES (?, ?, ?, ?)",
                    (commit_id, item_type, node_id, prior),
                )
            # Incident edges of removed nodes are implicitly removed —
            # capture them so the removal is fully revertible.
            implicit_removed: list[tuple[str, str, str]] = []
            for node_id in update.removed_nodes:
                async with conn.execute(
                    "SELECT source_id, target_id, kind FROM edges"
                    " WHERE source_id = ? OR target_id = ?",
                    (node_id, node_id),
                ) as cur:
                    for row in await cur.fetchall():
                        implicit_removed.append(
                            (row["source_id"], row["target_id"], row["kind"])
                        )
            removed_edge_set = {
                tuple(t) for t in update.removed_edges
            } | set(implicit_removed)

            edge_triples = [
                (e.source_id, e.target_id, e.kind.value) for e in update.edges
            ] + sorted(removed_edge_set)
            for src, tgt, kind in edge_triples:
                async with conn.execute(
                    "SELECT * FROM edges WHERE source_id = ? AND target_id = ?"
                    " AND kind = ?",
                    (src, tgt, kind),
                ) as cur:
                    row = await cur.fetchone()
                prior = orjson.dumps(dict(row)).decode() if row else None
                item_type = (
                    "edge_removed" if (src, tgt, kind) in removed_edge_set else "edge"
                )
                await conn.execute(
                    "INSERT OR REPLACE INTO graph_commit_items"
                    " (commit_id, item_type, item_key, prior) VALUES (?, ?, ?, ?)",
                    (commit_id, item_type, _edge_key(src, tgt, kind), prior),
                )

            # --- apply writes -----------------------------------------
            if update.nodes:
                await conn.executemany(
                    "INSERT OR REPLACE INTO nodes"
                    " (node_id, kind, title, source_uri, parent_id, summary,"
                    "  content_ref, embedding_ref, provenance, domain_tags,"
                    "  assertion)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                            _assertion_json(n),
                        )
                        for n in update.nodes
                    ],
                )
                # Partial FTS refresh — only the nodes in this update.
                await self._insert_nodes_fts(conn, update.nodes)
            if update.edges:
                await conn.executemany(
                    "INSERT OR REPLACE INTO edges"
                    " (source_id, target_id, kind, provenance, confidence,"
                    "  source_uri, assertion)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            e.source_id,
                            e.target_id,
                            e.kind.value,
                            e.provenance.value,
                            e.confidence,
                            None,
                            _assertion_json(e),
                        )
                        for e in update.edges
                    ],
                )
            for src, tgt, kind in sorted(removed_edge_set):
                await conn.execute(
                    "DELETE FROM edges WHERE source_id = ? AND target_id = ?"
                    " AND kind = ?",
                    (src, tgt, kind),
                )
            for node_id in update.removed_nodes:
                await conn.execute(
                    "DELETE FROM nodes WHERE node_id = ?", (node_id,)
                )
                await conn.execute(
                    "DELETE FROM nodes_fts WHERE node_id = ?", (node_id,)
                )

            # --- record the commit ------------------------------------
            await conn.execute(
                "INSERT INTO graph_commits"
                " (commit_id, op, agent_id, run_id, asserted_by, reason,"
                "  committed_at, payload)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    commit_id,
                    update.op,
                    update.agent_id,
                    update.run_id,
                    update.asserted_by,
                    update.reason,
                    committed_at,
                    orjson.dumps(update.model_dump(mode="json")).decode(),
                ),
            )
            await conn.commit()

        logger.info(
            "SQLitePersistence.apply_update: commit %s (%s) — %d nodes,"
            " %d edges, %d removed",
            commit_id,
            update.op,
            len(update.nodes),
            len(update.edges),
            len(update.removed_edges),
        )
        return CommitReceipt(
            commit_id=commit_id,
            op=update.op,
            node_ids=[n.node_id for n in update.nodes] + list(update.removed_nodes),
            edge_keys=[
                (e.source_id, e.target_id, e.kind.value) for e in update.edges
            ]
            + sorted(removed_edge_set),
            committed_at=committed_at,
            warnings=warnings,
        )

    async def get_commit(
        self,
        ctx: TenantContext,
        commit_id: str,
    ) -> Optional[dict[str, Any]]:
        """Return a recorded commit with its payload and items.

        Args:
            ctx: Tenant context.
            commit_id: The commit to fetch.

        Returns:
            A dict with the commit row, decoded ``payload`` and its
            ``items``, or ``None`` when unknown.
        """
        async with self._connect(ctx) as conn:
            async with conn.execute(
                "SELECT * FROM graph_commits WHERE commit_id = ?", (commit_id,)
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                return None
            commit = dict(row)
            commit["payload"] = orjson.loads(commit["payload"])
            async with conn.execute(
                "SELECT item_type, item_key, prior FROM graph_commit_items"
                " WHERE commit_id = ?",
                (commit_id,),
            ) as cur:
                commit["items"] = [dict(r) for r in await cur.fetchall()]
            return commit

    async def list_commits(
        self,
        ctx: TenantContext,
        run_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List recorded commits, newest first.

        Args:
            ctx: Tenant context.
            run_id: Optional filter on the producing run.
            agent_id: Optional filter on the producing agent.
            limit: Maximum rows returned.

        Returns:
            Commit rows (payload omitted for brevity) as dicts.
        """
        if not self._db_path(ctx).exists():
            return []
        clauses: list[str] = []
        params: list[Any] = []
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        if agent_id is not None:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(int(limit))
        async with self._connect(ctx) as conn:
            async with conn.execute(
                "SELECT commit_id, op, agent_id, run_id, asserted_by, reason,"
                f" committed_at, reverted_at FROM graph_commits{where}"
                " ORDER BY committed_at DESC, commit_id DESC LIMIT ?",
                params,
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def revert_commit(
        self,
        ctx: TenantContext,
        commit_id: str,
    ) -> dict[str, Any]:
        """Restore the pre-images captured by a commit.

        Rows that had a pre-image are restored to it; rows created by the
        commit (no pre-image) are deleted. The revert is refused when a
        LATER commit touched any of the same item keys — reverting would
        silently clobber the newer write.

        Args:
            ctx: Tenant context.
            commit_id: The commit to revert.

        Returns:
            ``{"status": "reverted", ...}`` on success or
            ``{"error": ...}`` on refusal/unknown commit.
        """
        async with self._connect(ctx) as conn:
            async with conn.execute(
                "SELECT committed_at, reverted_at FROM graph_commits"
                " WHERE commit_id = ?",
                (commit_id,),
            ) as cur:
                commit_row = await cur.fetchone()
            if commit_row is None:
                return {"error": f"revert_commit: unknown commit {commit_id!r}"}
            if commit_row["reverted_at"]:
                return {"error": f"revert_commit: {commit_id!r} already reverted"}

            async with conn.execute(
                "SELECT item_type, item_key, prior FROM graph_commit_items"
                " WHERE commit_id = ?",
                (commit_id,),
            ) as cur:
                items = [dict(r) for r in await cur.fetchall()]
            if not items:
                return {"error": f"revert_commit: commit {commit_id!r} has no items"}

            # Refuse when a later commit touched any of the same keys.
            # Ordering uses the commits table's implicit rowid — the
            # ISO timestamp only has 1-second resolution.
            conflicts: list[str] = []
            for item in items:
                item_key = item["item_key"]
                async with conn.execute(
                    "SELECT c.commit_id FROM graph_commit_items i"
                    " JOIN graph_commits c ON c.commit_id = i.commit_id"
                    " WHERE i.item_key = ? AND i.commit_id != ?"
                    "  AND c.reverted_at IS NULL"
                    "  AND c.rowid > (SELECT rowid FROM graph_commits"
                    "                 WHERE commit_id = ?)",
                    (item_key, commit_id, commit_id),
                ) as cur:
                    later = await cur.fetchall()
                if later:
                    conflicts.append(item_key)
            if conflicts:
                return {
                    "error": "revert_commit: later commits touched the same items",
                    "conflicts": sorted(set(conflicts)),
                }

            restored, deleted = 0, 0
            for item in items:
                prior = orjson.loads(item["prior"]) if item["prior"] else None
                if item["item_type"] in ("node", "node_removed"):
                    if prior is None:
                        await conn.execute(
                            "DELETE FROM nodes WHERE node_id = ?",
                            (item["item_key"],),
                        )
                        await conn.execute(
                            "DELETE FROM nodes_fts WHERE node_id = ?",
                            (item["item_key"],),
                        )
                        deleted += 1
                    else:
                        columns = list(prior.keys())
                        await conn.execute(
                            f"INSERT OR REPLACE INTO nodes ({', '.join(columns)})"
                            f" VALUES ({', '.join('?' for _ in columns)})",
                            [prior[c] for c in columns],
                        )
                        await conn.execute(
                            "INSERT OR REPLACE INTO nodes_fts"
                            " (node_id, title, summary) VALUES (?, ?, ?)",
                            (
                                prior.get("node_id"),
                                prior.get("title", ""),
                                prior.get("summary") or "",
                            ),
                        )
                        restored += 1
                else:  # edge / edge_removed
                    src, tgt, kind = item["item_key"].split("|", 2)
                    if prior is None:
                        await conn.execute(
                            "DELETE FROM edges WHERE source_id = ?"
                            " AND target_id = ? AND kind = ?",
                            (src, tgt, kind),
                        )
                        deleted += 1
                    else:
                        columns = list(prior.keys())
                        await conn.execute(
                            f"INSERT OR REPLACE INTO edges ({', '.join(columns)})"
                            f" VALUES ({', '.join('?' for _ in columns)})",
                            [prior[c] for c in columns],
                        )
                        restored += 1

            await conn.execute(
                "UPDATE graph_commits SET reverted_at = ? WHERE commit_id = ?",
                (_now_iso(), commit_id),
            )
            await conn.commit()

        logger.info(
            "SQLitePersistence.revert_commit: %s — %d restored, %d deleted",
            commit_id,
            restored,
            deleted,
        )
        return {
            "status": "reverted",
            "commit_id": commit_id,
            "restored": restored,
            "deleted": deleted,
        }
