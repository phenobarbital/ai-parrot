"""Postgres persistence backend for GraphIndex (FEAT-520 Module 2).

``PostgresPersistence`` is the third GraphIndex backend, sitting next to
``GraphIndexPersistence`` (ArangoDB, ``persist.py``) and ``SQLitePersistence``
(``persist_sqlite.py``). Its public API mirrors ``GraphIndexPersistence``
exactly (duck-typed, same as the SQLite sibling) so ``GraphPublisher`` and
the builder pipeline work unchanged.

Writes are bitemporal and append-only from day one (spec D1/D2): a
correction to an existing node closes the current ``node_versions`` row's
``validity`` range and inserts a new row in the same transaction — content
columns are NEVER ``UPDATE``d. Reads in this module are current-time only
(``upper_inf(validity)``); the temporal contract (``as_of``/``history``/
``diff``) is added by TASK-2767 in the same file.

Two schema fields on ``UniversalNode`` (``parent_id``, ``embedding_ref``)
have no dedicated column in the shared ``graphindex.*`` schema (spec §2 DDL
— Module 1 intentionally keeps the identity/state tables lean). They round
-trip through a private ``"_pg_extra"`` key nested inside the existing
``node_versions.domain_tags`` jsonb column instead of widening the schema
outside this task's file scope. Likewise ``UniversalEdge`` has no
``evidence_ref`` field (spec U3 is a DB-level concept); the value is read
from/written to ``edge.domain_tags["evidence_ref"]``, the exact
extensibility seam the model's own docstring describes for domain-specific
data (FEAT-392 precedent).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg
import orjson

from parrot.knowledge.graphindex.pg_schema import (
    create_pg_pool,
    ensure_schema,
    resolve_regconfig,
)
from parrot.knowledge.graphindex.schema import (
    AssertionMeta,
    UniversalEdge,
    UniversalNode,
)
from parrot.knowledge.ontology.schema import TenantContext

logger = logging.getLogger(__name__)

#: Private key nesting ``parent_id``/``embedding_ref`` inside the
#: ``node_versions.domain_tags`` jsonb blob (see module docstring).
_PG_EXTRA_KEY = "_pg_extra"


def _assertion_json(item: UniversalNode | UniversalEdge) -> Optional[str]:
    """Serialize an ``assertion`` to a JSON string, or ``None`` when absent."""
    if item.assertion is None:
        return None
    return orjson.dumps(item.assertion.model_dump(exclude_none=True)).decode()


def _node_content_hash(node: UniversalNode) -> str:
    """Compute the stable no-op-detection hash for a node's content.

    Args:
        node: The node whose title/summary/content_ref triple to hash.

    Returns:
        A hex sha1 digest.
    """
    raw = f"{node.title}|{node.summary or ''}|{node.content_ref or ''}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


class PostgresPersistence:
    """Postgres-backed GraphIndex persistence over the shared ``graphindex.*`` schema.

    Public API mirrors ``GraphIndexPersistence`` (``persist.py``) — duck
    -typed, same as ``SQLitePersistence`` — plus the temporal (TASK-2767)
    and hybrid-retrieval (TASK-2771) extensions added later in this file.

    Args:
        dsn: asyncpg-compatible DSN. Ignored when ``pool`` is supplied.
        pool: An existing asyncpg pool to reuse instead of creating one.
        schema: The Postgres schema name housing the GraphIndex tables.
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        *,
        pool: Optional[asyncpg.Pool] = None,
        schema: str = "graphindex",
    ) -> None:
        self._dsn = dsn
        self._external_pool = pool
        self._schema = schema
        self._pool: Optional[asyncpg.Pool] = None
        self._pool_lock = asyncio.Lock()
        self._owns_pool = pool is None

    async def _ensure_pool(self) -> asyncpg.Pool:
        """Lazily create (or reuse) the connection pool and ensure the schema.

        Returns:
            A ready-to-use asyncpg pool with the ``graphindex.*`` schema
            already migrated.
        """
        if self._pool is not None:
            return self._pool
        async with self._pool_lock:
            if self._pool is None:
                pool = self._external_pool or await create_pg_pool(self._dsn, schema=self._schema)
                await ensure_schema(pool, schema=self._schema)
                self._pool = pool
        return self._pool

    async def close(self) -> None:
        """Close the pool if this instance created it."""
        if self._pool is not None and self._owns_pool:
            await self._pool.close()
            self._pool = None

    # ------------------------------------------------------------------
    # Internal write helpers
    # ------------------------------------------------------------------

    def _node_namespace(self, ctx: TenantContext, node: UniversalNode) -> str:
        """Resolve the FTS/regconfig namespace for a node.

        Prefers an explicit ``domain_tags["namespace"]`` override; falls
        back to the tenant id.

        Args:
            ctx: Tenant context.
            node: The node being written.

        Returns:
            The namespace string passed to ``resolve_regconfig``.
        """
        return node.domain_tags.get("namespace") or ctx.tenant_id

    async def _upsert_files(self, conn: asyncpg.Connection, nodes: list[UniversalNode]) -> None:
        """Insert or refresh ``files`` staleness rows (parity with SQLite).

        Args:
            conn: Open connection (within the caller's transaction).
            nodes: All nodes from the current batch.
        """
        indexed_at = datetime.now(tz=timezone.utc)
        for n in nodes:
            mtime = n.domain_tags.get("mtime")
            sha1 = n.domain_tags.get("sha1")
            if mtime is None or sha1 is None:
                continue
            if n.source_uri.startswith("odoo-model://"):
                continue
            await conn.execute(
                f"""
                INSERT INTO {self._schema}.files (source_uri, mtime, sha1, indexed_at)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (source_uri) DO UPDATE
                    SET mtime = EXCLUDED.mtime, sha1 = EXCLUDED.sha1, indexed_at = EXCLUDED.indexed_at
                """,
                n.source_uri,
                mtime,
                sha1,
                indexed_at,
            )

    async def _upsert_node(self, conn: asyncpg.Connection, ctx: TenantContext, node: UniversalNode) -> None:
        """Upsert one node's identity row and (append-only) state row.

        Args:
            conn: Open connection (within the caller's transaction).
            ctx: Tenant context.
            node: The node to persist.
        """
        namespace = self._node_namespace(ctx, node)
        regconfig = resolve_regconfig(namespace)

        await conn.execute(
            f"""
            INSERT INTO {self._schema}.nodes (concept_id, namespace, category, lang)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (concept_id) DO UPDATE
                SET namespace = EXCLUDED.namespace, category = EXCLUDED.category, lang = EXCLUDED.lang
            """,
            node.node_id,
            namespace,
            node.kind.value,
            regconfig,
        )

        content_hash = _node_content_hash(node)
        current = await conn.fetchrow(
            f"""
            SELECT version_id, content_hash FROM {self._schema}.node_versions
            WHERE concept_id = $1 AND upper_inf(validity)
            """,
            node.node_id,
        )
        if current is not None and current["content_hash"] == content_hash:
            return  # no-op: identical content

        if current is not None:
            await conn.execute(
                f"""
                UPDATE {self._schema}.node_versions
                SET validity = tstzrange(lower(validity), now())
                WHERE version_id = $1
                """,
                current["version_id"],
            )

        extra: dict[str, Any] = {}
        if node.parent_id is not None:
            extra["parent_id"] = node.parent_id
        if node.embedding_ref is not None:
            extra["embedding_ref"] = node.embedding_ref
        domain_tags = dict(node.domain_tags)
        if extra:
            domain_tags[_PG_EXTRA_KEY] = extra
        domain_tags_json = orjson.dumps(domain_tags).decode() if domain_tags else None

        await conn.execute(
            f"""
            INSERT INTO {self._schema}.node_versions
                (concept_id, title, summary, body, body_ref, source_id,
                 content_hash, fts, provenance, assertion, domain_tags)
            VALUES (
                $1, $2, $3, $4, $5, $6, $7,
                to_tsvector($8::regconfig, $2 || ' ' || coalesce($3, '') || ' ' || coalesce($4, '')),
                $9, $10::jsonb, $11::jsonb
            )
            """,
            node.node_id,
            node.title,
            node.summary or "",
            None,  # body — graph plane stores content on disk via body_ref (wiki plane sets body, TASK-2768)
            node.content_ref,
            node.source_uri,
            content_hash,
            regconfig,
            node.provenance.value,
            _assertion_json(node),
            domain_tags_json,
        )

    async def _upsert_edge(
        self,
        conn: asyncpg.Connection,
        edge: UniversalEdge,
        *,
        source_id: Optional[str] = None,
    ) -> None:
        """Upsert one edge (close-and-insert on change, no-op when identical).

        Args:
            conn: Open connection (within the caller's transaction).
            edge: The edge to persist.
            source_id: Optional document/source scoping stamp (set by
                ``replace_document_slice``; ``None`` for plain ``persist_graph``).
        """
        evidence_ref = edge.domain_tags.get("evidence_ref")
        assertion_json = _assertion_json(edge)
        evidence_json = orjson.dumps(evidence_ref).decode() if evidence_ref is not None else None

        current = await conn.fetchrow(
            f"""
            SELECT edge_id, provenance, confidence, assertion, evidence_ref
            FROM {self._schema}.edges
            WHERE src = $1 AND dst = $2 AND rel = $3 AND upper_inf(validity)
            """,
            edge.source_id,
            edge.target_id,
            edge.kind.value,
        )
        if current is not None:
            same = (
                current["provenance"] == edge.provenance.value
                and current["confidence"] == edge.confidence
                and current["assertion"] == assertion_json
                and current["evidence_ref"] == evidence_json
            )
            if same:
                return  # no-op: identical content
            await conn.execute(
                f"""
                UPDATE {self._schema}.edges
                SET validity = tstzrange(lower(validity), now())
                WHERE edge_id = $1
                """,
                current["edge_id"],
            )

        await conn.execute(
            f"""
            INSERT INTO {self._schema}.edges
                (src, dst, rel, provenance, confidence, assertion, evidence_ref, source_id)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8)
            """,
            edge.source_id,
            edge.target_id,
            edge.kind.value,
            edge.provenance.value,
            edge.confidence,
            assertion_json,
            evidence_json,
            source_id,
        )

    # ------------------------------------------------------------------
    # Row → model rehydration (skip-and-warn on unknown enums, sibling parity)
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_node(row: asyncpg.Record) -> Optional[UniversalNode]:
        """Rehydrate a ``UniversalNode`` from a joined nodes/node_versions row."""
        try:
            raw_tags = orjson.loads(row["domain_tags"]) if row["domain_tags"] else {}
            extra = raw_tags.pop(_PG_EXTRA_KEY, {}) if isinstance(raw_tags, dict) else {}
            assertion = None
            if row["assertion"]:
                assertion = AssertionMeta(**orjson.loads(row["assertion"]))
            return UniversalNode(
                node_id=row["concept_id"],
                kind=row["category"],
                title=row["title"],
                source_uri=row["source_id"] or "",
                content_ref=row["body_ref"],
                summary=row["summary"],
                embedding_ref=extra.get("embedding_ref"),
                domain_tags=raw_tags,
                parent_id=extra.get("parent_id"),
                provenance=row["provenance"],
                assertion=assertion,
            )
        except Exception as exc:  # noqa: BLE001 — skip-and-warn on unknown kinds
            logger.warning(
                "PostgresPersistence: skipping unreadable node row %r: %s",
                row["concept_id"] if "concept_id" in row.keys() else "?",
                exc,
            )
            return None

    @staticmethod
    def _row_to_edge(row: asyncpg.Record) -> Optional[UniversalEdge]:
        """Rehydrate a ``UniversalEdge`` from an edges row."""
        try:
            assertion = None
            if row["assertion"]:
                assertion = AssertionMeta(**orjson.loads(row["assertion"]))
            domain_tags: dict[str, Any] = {}
            if row["evidence_ref"]:
                domain_tags["evidence_ref"] = orjson.loads(row["evidence_ref"])
            return UniversalEdge(
                source_id=row["src"],
                target_id=row["dst"],
                kind=row["rel"],
                provenance=row["provenance"],
                confidence=row["confidence"],
                assertion=assertion,
                domain_tags=domain_tags,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "PostgresPersistence: skipping unreadable edge row (%r -> %r): %s",
                row["src"] if "src" in row.keys() else "?",
                row["dst"] if "dst" in row.keys() else "?",
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # Public API — mirrors GraphIndexPersistence
    # ------------------------------------------------------------------

    async def persist_graph(
        self,
        ctx: TenantContext,
        nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> dict[str, Any]:
        """Persist all nodes and edges for a tenant graph.

        Corrections close the current version's validity range and insert
        a new row (spec D2); identical content is a no-op.

        Args:
            ctx: Tenant context.
            nodes: All graph nodes to persist.
            edges: All graph edges to persist.

        Returns:
            ``{"nodes_persisted": N, "edges_persisted": M}``
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await self._upsert_files(conn, nodes)
                for node in nodes:
                    await self._upsert_node(conn, ctx, node)
                for edge in edges:
                    await self._upsert_edge(conn, edge)

        logger.info(
            "PostgresPersistence.persist_graph: %d nodes, %d edges (schema=%s)",
            len(nodes),
            len(edges),
            self._schema,
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

        Closes the current versions/edges scoped to ``document_uri`` and
        upserts the new slice, all in one transaction — a concurrent
        reader never observes a partial state. Canonical nodes
        (``source_uri`` starting with ``odoo-model://``) are never closed,
        even if their own URI is passed as ``document_uri``.

        Args:
            ctx: Tenant context.
            document_uri: URI of the document to replace.
            nodes: Replacement nodes.
            edges: Replacement edges.

        Returns:
            ``{"nodes_replaced": N, "edges_replaced": M}``
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                old_count = await conn.fetchval(
                    f"""
                    SELECT COUNT(*) FROM {self._schema}.node_versions
                    WHERE source_id = $1 AND upper_inf(validity)
                      AND source_id NOT LIKE 'odoo-model://%'
                    """,
                    document_uri,
                )
                await conn.execute(
                    f"""
                    UPDATE {self._schema}.node_versions
                    SET validity = tstzrange(lower(validity), now())
                    WHERE source_id = $1 AND upper_inf(validity)
                      AND source_id NOT LIKE 'odoo-model://%'
                    """,
                    document_uri,
                )
                await conn.execute(
                    f"""
                    UPDATE {self._schema}.edges
                    SET validity = tstzrange(lower(validity), now())
                    WHERE source_id = $1 AND upper_inf(validity)
                    """,
                    document_uri,
                )

                await self._upsert_files(conn, nodes)
                for node in nodes:
                    await self._upsert_node(conn, ctx, node)

                node_uri_by_id = {n.node_id: n.source_uri for n in nodes}
                for edge in edges:
                    src_uri = node_uri_by_id.get(edge.source_id)
                    await self._upsert_edge(conn, edge, source_id=src_uri)

        logger.info(
            "PostgresPersistence.replace_document_slice: %s -> %d nodes, %d edges",
            document_uri,
            len(nodes),
            len(edges),
        )
        return {"nodes_replaced": old_count or 0, "edges_replaced": len(edges)}

    async def is_stale(
        self,
        ctx: TenantContext,
        source_uri: str,
        mtime: float,
        sha1: str,
    ) -> bool:
        """Check whether a source file needs re-extraction.

        Args:
            ctx: Tenant context (unused — files are keyed by source_uri
                within the shared schema, parity with the SQLite sibling's
                per-tenant-file semantics).
            source_uri: The file's source URI as stored in ``files``.
            mtime: Current filesystem modification time.
            sha1: SHA-1 hex digest of the current file content.

        Returns:
            ``True`` if the file should be re-extracted; ``False`` if the
            stored snapshot is still valid.
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT mtime, sha1 FROM {self._schema}.files WHERE source_uri = $1",
                source_uri,
            )
        if row is None:
            return True
        if row["sha1"] != sha1:
            return True
        if row["mtime"] != mtime:
            return True
        return False

    async def load_graph(
        self,
        ctx: TenantContext,
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Load and rehydrate the CURRENT tenant graph as schema models.

        Only rows with an open validity range (``upper_inf(validity)``)
        are returned — the current-time read path (spec D3). Rows with
        enum values unknown to this code version are skipped with a
        warning (forward-compat, sibling parity).

        Args:
            ctx: Tenant context (unused — the schema is shared, not
                per-tenant partitioned in v1).

        Returns:
            ``(nodes, edges)`` lists of validated models.
        """
        pool = await self._ensure_pool()
        nodes: list[UniversalNode] = []
        edges: list[UniversalEdge] = []
        async with pool.acquire() as conn:
            node_rows = await conn.fetch(
                f"""
                SELECT n.concept_id, n.category, nv.title, nv.summary, nv.body_ref,
                       nv.source_id, nv.provenance, nv.assertion, nv.domain_tags
                FROM {self._schema}.nodes n
                JOIN {self._schema}.node_versions nv ON nv.concept_id = n.concept_id
                WHERE upper_inf(nv.validity)
                """
            )
            for row in node_rows:
                node = self._row_to_node(row)
                if node is not None:
                    nodes.append(node)

            edge_rows = await conn.fetch(
                f"""
                SELECT src, dst, rel, provenance, confidence, assertion, evidence_ref
                FROM {self._schema}.edges
                WHERE upper_inf(validity)
                """
            )
            for row in edge_rows:
                edge = self._row_to_edge(row)
                if edge is not None:
                    edges.append(edge)

        return nodes, edges
