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

FEAT-520 Module 3 adds the graph commit protocol (``apply_update``/
``get_commit``/``list_commits``/``revert_commit``), mirroring
``GraphIndexPersistence``/``SQLitePersistence`` behaviorally
(``tests/knowledge/graphindex/test_persist_commit_protocol.py`` is the
parity bar). Deviation from the ArangoDB sibling, worth calling out: on
Postgres the pre-image capture, the ``commits``/``commit_items`` rows, and
every mutation happen inside ONE ``conn.transaction()`` — a mid-apply
crash rolls back everything, including the audit trail itself. Arango's
"visible in audit trail even on partial failure" compromise does not
apply here; the engine's transaction IS the atomicity guarantee, so no
per-tenant ``asyncio.Lock`` is needed (matches sibling ``seq`` ordering
via the ``commits.seq`` IDENTITY column). "Removal" (``removed_nodes``/
``removed_edges``) never physically deletes — it closes the ``validity``
range (tombstone-by-range), so history/temporal reads (TASK-2767) still
see it; ``revert_commit`` restores a pre-image by inserting a FRESH
version row (never re-opening a past range, which would violate the
append-only/EXCLUDE invariant), the same close-and-insert discipline as
every other write path in this module.

FEAT-520 Module 4 adds the temporal READ contract (``as_of``/``history``/
``diff``, spec D5) — Postgres-only in v1. ``SQLitePersistence`` and
``GraphIndexPersistence`` do NOT grow these methods; callers feature
-detect via ``hasattr``.

FEAT-520 Module 6 adds ``upsert_embeddings`` — in-schema embeddings keyed
``(version_id, model)`` (spec U4: ``PgVectorStore`` is explicitly NOT
involved; zero ``parrot.stores.*`` imports). This gives TASK-2771's
hybrid retrieval a KNN leg inside the same transaction snapshot as the
graph and FTS legs.

FEAT-520 Module 7 adds ``hybrid_retrieve`` (spec D6/G5, deliberately named
to avoid colliding with ``PgVectorStore.hybrid_search`` — spec C2): graph
expansion (recursive CTE from ``seeds``), pgvector KNN, and ``ts_rank_cd``
FTS run as CTEs of ONE SQL statement against the same ``as_of`` snapshot,
fused with RRF (``Σ w_leg/(60+rank_leg)``, ``_RRF_K=60`` parity with
``pageindex/hybrid_search.py``) in SQL. The graph leg's "rank" is derived
from BFS depth order (closest-first), unifying all three legs under the
same RRF formula rather than a separate depth-decay term. CTE order
(graph→semantic: hood-restricted KNN when both ``seeds`` and
``query_embedding`` are given) follows TASK-2770's spike decision
(``artifacts/logs/feat-520-oq3-spike.md``). Cross-encoder re-ranking runs
in Python through the existing ``parrot.rerankers`` seam, copying
``HybridPageIndexSearch._apply_reranker``'s fallback semantics (failure or
NaN score → fused order).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import asyncpg
import orjson
from pydantic import BaseModel, Field

from parrot.knowledge.graphindex.pg_schema import (
    create_pg_pool,
    ensure_schema,
    resolve_regconfig,
    validate_embedding_dim,
)
from parrot.knowledge.graphindex.schema import (
    AssertionMeta,
    CommitReceipt,
    GraphUpdate,
    UniversalEdge,
    UniversalNode,
)
from parrot.knowledge.ontology.schema import TenantContext
from parrot.models.stores import SearchResult
from parrot.rerankers.abstract import AbstractReranker

logger = logging.getLogger(__name__)

#: RRF constant — parity with ``pageindex/hybrid_search.py``'s ``_RRF_K``.
_RRF_K = 60

#: Default per-leg RRF weights for ``hybrid_retrieve`` (spec D6).
_DEFAULT_HYBRID_WEIGHTS: dict[str, float] = {"graph": 1.0, "knn": 1.0, "fts": 1.0}


class NodeVersionRow(BaseModel):
    """One row of ``graphindex.node_versions``, as returned by ``history()``/``as_of()``."""

    version_id: int
    concept_id: str
    valid_from: datetime
    valid_to: Optional[datetime] = None  # None == open range (current)
    tx_from: datetime
    title: str
    summary: str = ""
    body: Optional[str] = None  # wiki plane
    body_ref: Optional[str] = None  # graph plane (markdown on disk)
    provenance: str = "extracted"
    derived: bool = False


class TemporalDiff(BaseModel):
    """Structured output of ``diff(concept_id, t1, t2)`` — LLM-consumable.

    Never "compare these two texts": ``version_changes``/``edges_added``/
    ``edges_removed`` are structured rows, not prose.
    """

    concept_id: str
    t1: datetime
    t2: datetime
    version_changes: list[dict] = Field(default_factory=list)
    edges_added: list[dict] = Field(default_factory=list)
    edges_removed: list[dict] = Field(default_factory=list)


class HybridCandidate(BaseModel):
    """One fused candidate from ``hybrid_retrieve`` (pre- or post-rerank)."""

    concept_id: str
    version_id: int
    title: str
    score: float
    signals: dict[str, float] = Field(default_factory=dict)
    body_ref: Optional[str] = None
    evidence: list[dict] = Field(default_factory=list)


#: Private key nesting ``parent_id``/``embedding_ref`` inside the
#: ``node_versions.domain_tags`` jsonb blob (see module docstring).
_PG_EXTRA_KEY = "_pg_extra"


def _edge_key(source_id: str, target_id: str, kind: str) -> str:
    """Compose the canonical ``item_key`` string for an edge (sibling parity)."""
    return f"{source_id}|{target_id}|{kind}"


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

    # ------------------------------------------------------------------
    # Agent write path — GraphUpdate commits (durable graph memory, Module 3)
    # ------------------------------------------------------------------

    async def _node_pre_image(self, conn: asyncpg.Connection, concept_id: str) -> Optional[dict[str, Any]]:
        """Capture the current node identity+state as a revertible pre-image."""
        row = await conn.fetchrow(
            f"""
            SELECT n.namespace, n.category, n.lang, nv.title, nv.summary, nv.body, nv.body_ref,
                   nv.source_id, nv.content_hash, nv.provenance, nv.assertion, nv.domain_tags
            FROM {self._schema}.nodes n
            JOIN {self._schema}.node_versions nv ON nv.concept_id = n.concept_id
            WHERE n.concept_id = $1 AND upper_inf(nv.validity)
            """,
            concept_id,
        )
        return dict(row) if row is not None else None

    async def _edge_pre_image(
        self, conn: asyncpg.Connection, src: str, dst: str, rel: str
    ) -> Optional[dict[str, Any]]:
        """Capture the current edge state as a revertible pre-image."""
        row = await conn.fetchrow(
            f"""
            SELECT provenance, confidence, assertion, evidence_ref, source_id
            FROM {self._schema}.edges
            WHERE src = $1 AND dst = $2 AND rel = $3 AND upper_inf(validity)
            """,
            src,
            dst,
            rel,
        )
        return dict(row) if row is not None else None

    async def _restore_node(self, conn: asyncpg.Connection, concept_id: str, prior: dict[str, Any]) -> None:
        """Restore a node's pre-image as a fresh version row (revert helper)."""
        await conn.execute(
            f"""
            INSERT INTO {self._schema}.nodes (concept_id, namespace, category, lang)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (concept_id) DO UPDATE
                SET namespace = EXCLUDED.namespace, category = EXCLUDED.category, lang = EXCLUDED.lang
            """,
            concept_id,
            prior.get("namespace") or "",
            prior["category"],
            prior.get("lang") or "simple",
        )
        await conn.execute(
            f"""
            UPDATE {self._schema}.node_versions
            SET validity = tstzrange(lower(validity), now())
            WHERE concept_id = $1 AND upper_inf(validity)
            """,
            concept_id,
        )
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
            concept_id,
            prior["title"],
            prior["summary"],
            prior["body"],
            prior["body_ref"],
            prior["source_id"],
            prior["content_hash"],
            prior.get("lang") or "simple",
            prior["provenance"],
            prior["assertion"],
            prior["domain_tags"],
        )

    async def _restore_edge(
        self, conn: asyncpg.Connection, src: str, dst: str, rel: str, prior: dict[str, Any]
    ) -> None:
        """Restore an edge's pre-image as a fresh row (revert helper)."""
        await conn.execute(
            f"""
            UPDATE {self._schema}.edges
            SET validity = tstzrange(lower(validity), now())
            WHERE src = $1 AND dst = $2 AND rel = $3 AND upper_inf(validity)
            """,
            src,
            dst,
            rel,
        )
        await conn.execute(
            f"""
            INSERT INTO {self._schema}.edges
                (src, dst, rel, provenance, confidence, assertion, evidence_ref, source_id)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8)
            """,
            src,
            dst,
            rel,
            prior["provenance"],
            prior["confidence"],
            prior["assertion"],
            prior["evidence_ref"],
            prior["source_id"],
        )

    async def apply_update(self, ctx: TenantContext, update: GraphUpdate) -> CommitReceipt:
        """Apply a :class:`GraphUpdate` in one audited transaction.

        Captures the pre-image of every touched node/edge (including
        implicit incident edges of ``removed_nodes``) into
        ``commit_items``, records the commit row, then applies the
        writes: node/edge upserts reuse the TASK-2765 close-and-insert
        helpers; removals close the ``validity`` range rather than
        deleting (tombstone-by-range — history stays intact for
        TASK-2767's temporal reads). See the module docstring for the
        "one transaction" deviation from the ArangoDB sibling.

        Args:
            ctx: Tenant context.
            update: The validated update batch to apply.

        Returns:
            A :class:`CommitReceipt` describing the recorded commit.
        """
        commit_id = uuid.uuid4().hex[:16]
        committed_at = datetime.now(tz=timezone.utc)
        warnings: list[str] = []
        pool = await self._ensure_pool()

        async with pool.acquire() as conn:
            async with conn.transaction():
                # --- capture pre-images (BEFORE any mutation) -----------
                node_keys = [(n.node_id, "node") for n in update.nodes] + [
                    (node_id, "node_removed") for node_id in update.removed_nodes
                ]
                node_items = [
                    (node_id, item_type, await self._node_pre_image(conn, node_id))
                    for node_id, item_type in node_keys
                ]

                implicit_removed: list[tuple[str, str, str]] = []
                for node_id in update.removed_nodes:
                    incident = await conn.fetch(
                        f"""
                        SELECT src, dst, rel FROM {self._schema}.edges
                        WHERE (src = $1 OR dst = $1) AND upper_inf(validity)
                        """,
                        node_id,
                    )
                    for row in incident:
                        implicit_removed.append((row["src"], row["dst"], row["rel"]))

                removed_edge_set = {tuple(t) for t in update.removed_edges} | set(implicit_removed)

                edge_triples = [
                    (e.source_id, e.target_id, e.kind.value) for e in update.edges
                ] + sorted(removed_edge_set)
                edge_items = []
                for src, tgt, kind in edge_triples:
                    prior = await self._edge_pre_image(conn, src, tgt, kind)
                    item_type = "edge_removed" if (src, tgt, kind) in removed_edge_set else "edge"
                    edge_items.append(((src, tgt, kind), item_type, prior))

                # --- record the commit + items ---------------------------
                payload_json = orjson.dumps(update.model_dump(mode="json")).decode()
                await conn.execute(
                    f"""
                    INSERT INTO {self._schema}.commits
                        (commit_id, op, agent_id, run_id, asserted_by, reason, committed_at, payload)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                    """,
                    commit_id,
                    update.op,
                    update.agent_id,
                    update.run_id,
                    update.asserted_by,
                    update.reason,
                    committed_at,
                    payload_json,
                )
                for node_id, item_type, prior in node_items:
                    await conn.execute(
                        f"""
                        INSERT INTO {self._schema}.commit_items (commit_id, item_type, item_key, prior)
                        VALUES ($1, $2, $3, $4::jsonb)
                        ON CONFLICT (commit_id, item_type, item_key) DO UPDATE SET prior = EXCLUDED.prior
                        """,
                        commit_id,
                        item_type,
                        node_id,
                        orjson.dumps(prior).decode() if prior is not None else None,
                    )
                for (src, tgt, kind), item_type, prior in edge_items:
                    await conn.execute(
                        f"""
                        INSERT INTO {self._schema}.commit_items (commit_id, item_type, item_key, prior)
                        VALUES ($1, $2, $3, $4::jsonb)
                        ON CONFLICT (commit_id, item_type, item_key) DO UPDATE SET prior = EXCLUDED.prior
                        """,
                        commit_id,
                        item_type,
                        _edge_key(src, tgt, kind),
                        orjson.dumps(prior).decode() if prior is not None else None,
                    )

                # --- apply writes -----------------------------------------
                for node in update.nodes:
                    await self._upsert_node(conn, ctx, node)
                for edge in update.edges:
                    await self._upsert_edge(conn, edge)
                for src, tgt, kind in sorted(removed_edge_set):
                    await conn.execute(
                        f"""
                        UPDATE {self._schema}.edges
                        SET validity = tstzrange(lower(validity), now())
                        WHERE src = $1 AND dst = $2 AND rel = $3 AND upper_inf(validity)
                        """,
                        src,
                        tgt,
                        kind,
                    )
                for node_id in update.removed_nodes:
                    await conn.execute(
                        f"""
                        UPDATE {self._schema}.node_versions
                        SET validity = tstzrange(lower(validity), now())
                        WHERE concept_id = $1 AND upper_inf(validity)
                        """,
                        node_id,
                    )

        logger.info(
            "PostgresPersistence.apply_update: commit %s (%s) — %d nodes, %d edges, %d removed",
            commit_id,
            update.op,
            len(update.nodes),
            len(update.edges),
            len(removed_edge_set),
        )
        return CommitReceipt(
            commit_id=commit_id,
            op=update.op,
            node_ids=[n.node_id for n in update.nodes] + list(update.removed_nodes),
            edge_keys=[(e.source_id, e.target_id, e.kind.value) for e in update.edges]
            + sorted(removed_edge_set),
            committed_at=committed_at.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            warnings=warnings,
        )

    async def get_commit(self, ctx: TenantContext, commit_id: str) -> Optional[dict[str, Any]]:
        """Return a recorded commit with its decoded payload and items.

        Args:
            ctx: Tenant context (unused — the schema is shared, not
                per-tenant partitioned in v1).
            commit_id: The commit to fetch.

        Returns:
            A dict with the commit row, decoded ``payload``, and its
            ``items``, or ``None`` when unknown.
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {self._schema}.commits WHERE commit_id = $1", commit_id
            )
            if row is None:
                return None
            commit = dict(row)
            commit["payload"] = orjson.loads(commit["payload"])
            items = await conn.fetch(
                f"""
                SELECT item_type, item_key, collection, prior FROM {self._schema}.commit_items
                WHERE commit_id = $1
                """,
                commit_id,
            )
            commit["items"] = [dict(r) for r in items]
            return commit

    async def list_commits(
        self,
        ctx: TenantContext,
        run_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List recorded commits, newest (highest ``seq``) first.

        Args:
            ctx: Tenant context (unused — see ``get_commit``).
            run_id: Optional filter on the producing run.
            agent_id: Optional filter on the producing agent.
            limit: Maximum rows returned.

        Returns:
            Commit summary rows (payload omitted) as dicts; ``[]`` when
            the schema has no commits yet.
        """
        pool = await self._ensure_pool()
        clauses: list[str] = []
        params: list[Any] = []
        if run_id is not None:
            params.append(run_id)
            clauses.append(f"run_id = ${len(params)}")
        if agent_id is not None:
            params.append(agent_id)
            clauses.append(f"agent_id = ${len(params)}")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(int(limit))
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT commit_id, op, agent_id, run_id, asserted_by, reason, committed_at, reverted_at
                FROM {self._schema}.commits{where}
                ORDER BY seq DESC LIMIT ${len(params)}
                """,
                *params,
            )
        return [dict(r) for r in rows]

    async def revert_commit(self, ctx: TenantContext, commit_id: str) -> dict[str, Any]:
        """Restore the pre-images captured by a commit.

        Refused when a LATER, non-reverted commit (higher ``seq``)
        touched any of the same item keys — reverting would silently
        clobber the newer write.

        Args:
            ctx: Tenant context.
            commit_id: The commit to revert.

        Returns:
            ``{"status": "reverted", ...}`` on success or
            ``{"error": ...}`` on refusal/unknown commit.
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                commit_row = await conn.fetchrow(
                    f"SELECT seq, reverted_at FROM {self._schema}.commits WHERE commit_id = $1",
                    commit_id,
                )
                if commit_row is None:
                    return {"error": f"revert_commit: unknown commit {commit_id!r}"}
                if commit_row["reverted_at"] is not None:
                    return {"error": f"revert_commit: {commit_id!r} already reverted"}

                items = await conn.fetch(
                    f"""
                    SELECT item_type, item_key, prior FROM {self._schema}.commit_items
                    WHERE commit_id = $1
                    """,
                    commit_id,
                )
                if not items:
                    return {"error": f"revert_commit: commit {commit_id!r} has no items"}

                conflicts: list[str] = []
                for item in items:
                    later = await conn.fetchval(
                        f"""
                        SELECT count(*) FROM {self._schema}.commit_items i
                        JOIN {self._schema}.commits c ON c.commit_id = i.commit_id
                        WHERE i.item_key = $1 AND i.commit_id != $2
                          AND c.reverted_at IS NULL AND c.seq > $3
                        """,
                        item["item_key"],
                        commit_id,
                        commit_row["seq"],
                    )
                    if later:
                        conflicts.append(item["item_key"])
                if conflicts:
                    return {
                        "error": "revert_commit: later commits touched the same items",
                        "conflicts": sorted(set(conflicts)),
                    }

                restored = deleted = 0
                for item in items:
                    prior = orjson.loads(item["prior"]) if item["prior"] else None
                    if item["item_type"] in ("node", "node_removed"):
                        if prior is None:
                            await conn.execute(
                                f"""
                                UPDATE {self._schema}.node_versions
                                SET validity = tstzrange(lower(validity), now())
                                WHERE concept_id = $1 AND upper_inf(validity)
                                """,
                                item["item_key"],
                            )
                            deleted += 1
                        else:
                            await self._restore_node(conn, item["item_key"], prior)
                            restored += 1
                    else:  # edge / edge_removed
                        src, tgt, kind = item["item_key"].split("|", 2)
                        if prior is None:
                            await conn.execute(
                                f"""
                                UPDATE {self._schema}.edges
                                SET validity = tstzrange(lower(validity), now())
                                WHERE src = $1 AND dst = $2 AND rel = $3 AND upper_inf(validity)
                                """,
                                src,
                                tgt,
                                kind,
                            )
                            deleted += 1
                        else:
                            await self._restore_edge(conn, src, tgt, kind, prior)
                            restored += 1

                await conn.execute(
                    f"UPDATE {self._schema}.commits SET reverted_at = $1 WHERE commit_id = $2",
                    datetime.now(tz=timezone.utc),
                    commit_id,
                )

        logger.info(
            "PostgresPersistence.revert_commit: %s — %d restored, %d deleted",
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

    # ------------------------------------------------------------------
    # Temporal contract (Module 4, spec D5) — Postgres-only in v1
    # ------------------------------------------------------------------

    @staticmethod
    def _require_aware(t: datetime) -> None:
        """Reject naive datetimes — every temporal param is ``timestamptz``.

        Args:
            t: The datetime to validate.

        Raises:
            ValueError: When ``t`` has no timezone info.
        """
        if t.tzinfo is None:
            raise ValueError("Temporal API requires timezone-aware datetimes (got a naive datetime)")

    async def as_of(
        self,
        ctx: TenantContext,
        t: datetime,
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Return the graph snapshot valid at time ``t``.

        A caller can swap ``load_graph()`` for ``as_of(now())`` transparently
        — both filter on the same ``validity`` predicate, just expressed
        differently (``upper_inf(validity)`` vs. ``validity @> $t``).

        Args:
            ctx: Tenant context (unused — see ``load_graph``).
            t: The point in time to snapshot (must be timezone-aware).

        Returns:
            ``(nodes, edges)`` valid at ``t``.
        """
        self._require_aware(t)
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
                WHERE nv.validity @> $1::timestamptz
                """,
                t,
            )
            for row in node_rows:
                node = self._row_to_node(row)
                if node is not None:
                    nodes.append(node)

            edge_rows = await conn.fetch(
                f"""
                SELECT src, dst, rel, provenance, confidence, assertion, evidence_ref
                FROM {self._schema}.edges
                WHERE validity @> $1::timestamptz
                """,
                t,
            )
            for row in edge_rows:
                edge = self._row_to_edge(row)
                if edge is not None:
                    edges.append(edge)

        return nodes, edges

    async def history(self, ctx: TenantContext, concept_id: str) -> list[NodeVersionRow]:
        """Return every version row of a concept, ordered oldest first.

        Args:
            ctx: Tenant context (unused — see ``load_graph``).
            concept_id: The concept to list version history for.

        Returns:
            Ordered ``NodeVersionRow`` list (including closed ranges);
            ``[]`` for an unknown ``concept_id``.
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT version_id, concept_id, lower(validity) AS valid_from,
                       upper(validity) AS valid_to, tx_from, title, summary,
                       body, body_ref, provenance, derived
                FROM {self._schema}.node_versions
                WHERE concept_id = $1
                ORDER BY lower(validity), version_id
                """,
                concept_id,
            )
        return [NodeVersionRow(**dict(row)) for row in rows]

    async def diff(
        self,
        ctx: TenantContext,
        concept_id: str,
        t1: datetime,
        t2: datetime,
    ) -> TemporalDiff:
        """Return a structured diff of a concept between two points in time.

        LLM-consumable: version rows and edge deltas, never raw-text
        comparison.

        Args:
            ctx: Tenant context (unused — see ``load_graph``).
            concept_id: The concept to diff.
            t1: Start of the comparison window (timezone-aware).
            t2: End of the comparison window (timezone-aware).

        Returns:
            A :class:`TemporalDiff` with version changes and incident
            edge deltas.
        """
        self._require_aware(t1)
        self._require_aware(t2)
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            version_rows = await conn.fetch(
                f"""
                SELECT version_id, lower(validity) AS valid_from, upper(validity) AS valid_to,
                       title, summary
                FROM {self._schema}.node_versions
                WHERE concept_id = $1
                  AND (
                    (lower(validity) > $2::timestamptz AND lower(validity) <= $3::timestamptz)
                    OR (upper(validity) IS NOT NULL
                        AND upper(validity) > $2::timestamptz AND upper(validity) <= $3::timestamptz)
                  )
                ORDER BY lower(validity)
                """,
                concept_id,
                t1,
                t2,
            )
            edges_added = await conn.fetch(
                f"""
                SELECT src, dst, rel FROM {self._schema}.edges
                WHERE (src = $1 OR dst = $1)
                  AND validity @> $3::timestamptz AND NOT validity @> $2::timestamptz
                """,
                concept_id,
                t1,
                t2,
            )
            edges_removed = await conn.fetch(
                f"""
                SELECT src, dst, rel FROM {self._schema}.edges
                WHERE (src = $1 OR dst = $1)
                  AND validity @> $2::timestamptz AND NOT validity @> $3::timestamptz
                """,
                concept_id,
                t1,
                t2,
            )

        return TemporalDiff(
            concept_id=concept_id,
            t1=t1,
            t2=t2,
            version_changes=[dict(row) for row in version_rows],
            edges_added=[dict(row) for row in edges_added],
            edges_removed=[dict(row) for row in edges_removed],
        )

    # ------------------------------------------------------------------
    # In-schema embeddings (Module 6) — KNN leg feeds TASK-2771's hybrid SQL
    # ------------------------------------------------------------------

    async def upsert_embeddings(
        self,
        ctx: TenantContext,
        items: list[tuple[str, list[float]]],
        *,
        model: str = "",
    ) -> int:
        """Batch-upsert embeddings for the CURRENT version of each concept.

        The seam the graphindex embed stage (``embed.py``) writes
        through: ``(concept_id, vector)`` pairs, keyed in storage by
        ``(version_id, model)`` with ``concept_id`` denormalized (spec
        §3 Module 6). Concept ids with no current version are skipped
        (not an error — the embed stage may race a not-yet-persisted
        node; callers persist the graph first).

        Args:
            ctx: Tenant context (unused — see ``load_graph``).
            items: ``(concept_id, vector)`` pairs.
            model: Embedding model identifier.

        Returns:
            Number of embedding rows actually written.

        Raises:
            ValueError: When any vector's length does not match
                ``GRAPHINDEX_EMBEDDING_DIM``.
        """
        if not items:
            return 0
        for _, vector in items:
            validate_embedding_dim(vector)

        pool = await self._ensure_pool()
        written = 0
        async with pool.acquire() as conn:
            async with conn.transaction():
                for concept_id, vector in items:
                    version_id = await conn.fetchval(
                        f"""
                        SELECT version_id FROM {self._schema}.node_versions
                        WHERE concept_id = $1 AND upper_inf(validity)
                        """,
                        concept_id,
                    )
                    if version_id is None:
                        logger.warning(
                            "PostgresPersistence.upsert_embeddings: no current version for %r, skipped",
                            concept_id,
                        )
                        continue
                    await conn.execute(
                        f"""
                        INSERT INTO {self._schema}.embeddings (concept_id, version_id, model, embedding)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (version_id, model) DO UPDATE SET embedding = EXCLUDED.embedding
                        """,
                        concept_id,
                        version_id,
                        model,
                        vector,
                    )
                    written += 1
        return written

    # ------------------------------------------------------------------
    # hybrid_retrieve (Module 7) — graph + KNN + FTS, RRF-fused in SQL
    # ------------------------------------------------------------------

    async def _read_body_ref(self, body_ref: Optional[str]) -> str:
        """Read a graph-plane markdown body from disk (off the event loop).

        Args:
            body_ref: Filesystem path, or ``None``.

        Returns:
            The file content, or ``""`` when ``body_ref`` is absent or
            unreadable (logged, never raised — reranking degrades to
            title-only content rather than failing the whole call).
        """
        if not body_ref:
            return ""

        def _read() -> str:
            try:
                return Path(body_ref).read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning("hybrid_retrieve: could not read body_ref %r: %s", body_ref, exc)
                return ""

        return await asyncio.to_thread(_read)

    async def _apply_hybrid_reranker(
        self,
        reranker: AbstractReranker,
        query_text: str,
        candidates: list[HybridCandidate],
        top_n: int,
    ) -> list[HybridCandidate]:
        """Re-rank fused candidates, falling back to fused order on failure/NaN.

        Copies ``HybridPageIndexSearch._apply_reranker``'s semantics:
        reads full content (never the truncated row), and on any
        exception OR an unusable (NaN) score set, returns the fused
        order truncated to ``top_n`` instead of raising.

        Args:
            reranker: The caller-supplied reranker instance.
            query_text: The text to re-rank against (``fts_terms``).
            candidates: Fused candidates, already score-ordered.
            top_n: Maximum results to return.

        Returns:
            Re-ranked (or, on fallback, fused-order) candidates.
        """
        docs: list[SearchResult] = []
        for cand in candidates:
            body = await self._read_body_ref(cand.body_ref)
            content = "\n".join(part for part in (cand.title, body) if part)
            docs.append(
                SearchResult(
                    id=cand.concept_id,
                    content=content,
                    metadata={"concept_id": cand.concept_id},
                    score=cand.score,
                )
            )

        try:
            reranked = await reranker.rerank(query_text, docs, top_n=top_n)
        except Exception as exc:  # noqa: BLE001 — fallback policy, not a crash
            logger.warning("hybrid_retrieve: reranker raised, falling back to fused order: %s", exc)
            return candidates[:top_n]

        cand_by_id = {c.concept_id: c for c in candidates}
        ordered: list[HybridCandidate] = []
        saw_nan = False
        for item in reranked:
            doc_id = getattr(getattr(item, "document", item), "id", None) or getattr(item, "id", None)
            cand = cand_by_id.get(doc_id)
            if cand is None:
                continue
            score = getattr(item, "rerank_score", None)
            if isinstance(score, float) and math.isnan(score):
                saw_nan = True
                break
            new_cand = cand.model_copy(update={"score": score} if isinstance(score, float) else {})
            ordered.append(new_cand)

        if saw_nan or not ordered:
            return candidates[:top_n]
        return ordered[:top_n]

    async def hybrid_retrieve(
        self,
        ctx: TenantContext,
        *,
        query_embedding: Optional[list[float]] = None,
        fts_terms: Optional[str] = None,
        seeds: Optional[list[str]] = None,
        as_of: Optional[datetime] = None,
        weights: Optional[dict[str, float]] = None,
        limit: int = 20,
        reranker: Optional[AbstractReranker] = None,
        rerank_top_k: int = 10,
    ) -> list[HybridCandidate]:
        """One-pass hybrid retrieval: graph + KNN + FTS, RRF-fused in SQL.

        All three legs are CTEs of ONE SQL statement (one ``fetch`` call)
        against the SAME ``as_of`` snapshot — no leg can see a version/edge
        the others can't. RRF fusion (``Σ w_leg/(60+rank_leg)``, spec D6)
        happens in SQL; the graph leg's "rank" is its BFS depth order
        (closest-first) so all three legs share one fusion formula. CTE
        order follows TASK-2770's spike decision: when both ``seeds`` and
        ``query_embedding`` are given, the KNN leg is restricted to the
        graph hood (graph→semantic — the measured winner at depth <=3).

        Re-ranking uses ``fts_terms`` as the query text (this call has no
        separate ``query_text`` param — the normative signature is spec
        §2's; when a reranker is supplied without ``fts_terms``, reranking
        is skipped and the fused order is returned, documented here since
        the spec left the choice open).

        Args:
            ctx: Tenant context — its ``tenant_id`` doubles as the FTS
                regconfig namespace when ``fts_terms`` is given (this
                call has no per-row namespace to key off of, unlike the
                write paths).
            query_embedding: KNN leg query vector.
            fts_terms: FTS leg query text (``websearch_to_tsquery``
                syntax) — also the re-ranking query text.
            seeds: Graph leg seed ``concept_id``s.
            as_of: Point in time for all three legs; ``None`` → ``now()``.
                Must be timezone-aware.
            weights: Per-leg RRF weight overrides
                (``{"graph": ..., "knn": ..., "fts": ...}``).
            limit: Maximum fused candidates returned.
            reranker: Optional cross-encoder reranker.
            rerank_top_k: Maximum results after re-ranking.

        Returns:
            Fused (and optionally re-ranked) :class:`HybridCandidate` list.

        Raises:
            ValueError: When none of ``query_embedding``/``fts_terms``/
                ``seeds`` is given, or ``as_of`` is a naive datetime.
        """
        if not (query_embedding or fts_terms or seeds):
            raise ValueError(
                "hybrid_retrieve: at least one of query_embedding / fts_terms / seeds must be provided"
            )
        if as_of is not None:
            self._require_aware(as_of)
        as_of_t = as_of or datetime.now(tz=timezone.utc)
        w = {**_DEFAULT_HYBRID_WEIGHTS, **(weights or {})}
        max_depth = 5

        params: list[Any] = []

        def ph(value: Any) -> str:
            params.append(value)
            return f"${len(params)}"

        as_of_ph = ph(as_of_t)
        cte_parts: list[str] = []
        candidate_sources: list[str] = []

        if seeds:
            seeds_ph = ph(list(seeds))
            max_depth_ph = ph(max_depth)
            cte_parts.append(
                f"""
                hood AS (
                    SELECT s AS concept_id, 0 AS depth, NULL::jsonb AS evidence_ref
                    FROM unnest({seeds_ph}::text[]) AS s
                    UNION
                    SELECT e.dst, h.depth + 1, e.evidence_ref
                    FROM hood h
                    JOIN {self._schema}.edges e
                        ON e.src = h.concept_id AND e.validity @> {as_of_ph}::timestamptz
                    WHERE h.depth < {max_depth_ph}::int
                ),
                hood_dedup AS (
                    SELECT DISTINCT ON (concept_id) concept_id, depth, evidence_ref
                    FROM hood ORDER BY concept_id, depth ASC
                ),
                graph_leg AS (
                    SELECT concept_id, depth, evidence_ref,
                           row_number() OVER (ORDER BY depth ASC, concept_id ASC) AS rnk
                    FROM hood_dedup
                )
                """
            )
            candidate_sources.append("SELECT concept_id FROM graph_leg")

        if query_embedding:
            validate_embedding_dim(query_embedding)
            qvec_ph = ph(query_embedding)
            knn_limit_ph = ph(max(limit * 5, 50))
            hood_filter = (
                "AND nv.concept_id IN (SELECT concept_id FROM graph_leg)" if seeds else ""
            )
            cte_parts.append(
                f"""
                knn_leg AS (
                    SELECT nv.concept_id, emb.embedding <=> {qvec_ph} AS dist,
                           row_number() OVER (ORDER BY emb.embedding <=> {qvec_ph}) AS rnk
                    FROM {self._schema}.embeddings emb
                    JOIN {self._schema}.node_versions nv ON nv.version_id = emb.version_id
                    WHERE nv.validity @> {as_of_ph}::timestamptz
                    {hood_filter}
                    ORDER BY dist LIMIT {knn_limit_ph}::int
                )
                """
            )
            candidate_sources.append("SELECT concept_id FROM knn_leg")

        if fts_terms:
            namespace = getattr(ctx, "tenant_id", "") or ""
            regconfig = resolve_regconfig(namespace)
            reg_ph = ph(regconfig)
            terms_ph = ph(fts_terms)
            fts_limit_ph = ph(max(limit * 5, 50))
            cte_parts.append(
                f"""
                fts_leg AS (
                    SELECT nv.concept_id,
                           ts_rank_cd(nv.fts, websearch_to_tsquery({reg_ph}::regconfig, {terms_ph})) AS raw_score,
                           row_number() OVER (
                               ORDER BY ts_rank_cd(nv.fts, websearch_to_tsquery({reg_ph}::regconfig, {terms_ph})) DESC
                           ) AS rnk
                    FROM {self._schema}.node_versions nv
                    WHERE nv.validity @> {as_of_ph}::timestamptz
                      AND nv.fts @@ websearch_to_tsquery({reg_ph}::regconfig, {terms_ph})
                    ORDER BY raw_score DESC LIMIT {fts_limit_ph}::int
                )
                """
            )
            candidate_sources.append("SELECT concept_id FROM fts_leg")

        candidates_sql = " UNION ".join(candidate_sources)
        limit_ph = ph(limit)

        join_graph = "LEFT JOIN graph_leg g ON g.concept_id = c.concept_id" if seeds else ""
        join_knn = "LEFT JOIN knn_leg k ON k.concept_id = c.concept_id" if query_embedding else ""
        join_fts = "LEFT JOIN fts_leg f ON f.concept_id = c.concept_id" if fts_terms else ""

        # Weight placeholders are allocated ONLY for active legs — an
        # allocated-but-unreferenced $N anywhere in the query makes asyncpg's
        # prepare step fail with "could not determine data type of parameter"
        # (Postgres can't infer a type for a param that appears in zero
        # expressions).
        score_terms: list[str] = []
        if seeds:
            w_graph_ph = ph(w["graph"])
            score_terms.append(f"COALESCE({w_graph_ph}::float8 / (60 + g.rnk), 0)")
        if query_embedding:
            w_knn_ph = ph(w["knn"])
            score_terms.append(f"COALESCE({w_knn_ph}::float8 / (60 + k.rnk), 0)")
        if fts_terms:
            w_fts_ph = ph(w["fts"])
            score_terms.append(f"COALESCE({w_fts_ph}::float8 / (60 + f.rnk), 0)")
        score_expr = " + ".join(score_terms)

        select_extra = [
            "g.depth AS graph_depth" if seeds else "NULL::int AS graph_depth",
            "g.rnk AS graph_rank" if seeds else "NULL::bigint AS graph_rank",
            "g.evidence_ref AS evidence_ref" if seeds else "NULL::jsonb AS evidence_ref",
            "k.rnk AS knn_rank" if query_embedding else "NULL::bigint AS knn_rank",
            "f.rnk AS fts_rank" if fts_terms else "NULL::bigint AS fts_rank",
        ]

        query = f"""
            WITH RECURSIVE
            {",".join(cte_parts)},
            candidates AS ({candidates_sql})
            SELECT c.concept_id, nv.version_id, nv.title, nv.body_ref,
                   ({score_expr}) AS score,
                   {", ".join(select_extra)}
            FROM candidates c
            JOIN {self._schema}.node_versions nv
                ON nv.concept_id = c.concept_id AND nv.validity @> {as_of_ph}::timestamptz
            {join_graph}
            {join_knn}
            {join_fts}
            ORDER BY score DESC, c.concept_id
            LIMIT {limit_ph}::int
        """

        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        candidates: list[HybridCandidate] = []
        for row in rows:
            signals: dict[str, float] = {}
            if seeds and row["graph_rank"] is not None:
                signals["graph"] = w["graph"] / (_RRF_K + row["graph_rank"])
                signals["graph_depth"] = float(row["graph_depth"])
            if query_embedding and row["knn_rank"] is not None:
                signals["knn"] = w["knn"] / (_RRF_K + row["knn_rank"])
            if fts_terms and row["fts_rank"] is not None:
                signals["fts"] = w["fts"] / (_RRF_K + row["fts_rank"])

            evidence: list[dict[str, Any]] = []
            if row["evidence_ref"]:
                ev = orjson.loads(row["evidence_ref"])
                if ev:
                    evidence.append(ev)

            candidates.append(
                HybridCandidate(
                    concept_id=row["concept_id"],
                    version_id=row["version_id"],
                    title=row["title"],
                    score=float(row["score"]),
                    signals=signals,
                    body_ref=row["body_ref"],
                    evidence=evidence,
                )
            )

        if reranker is not None and fts_terms and candidates:
            candidates = await self._apply_hybrid_reranker(reranker, fts_terms, candidates, rerank_top_k)

        return candidates
