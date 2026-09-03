"""PostgresWikiStore — Postgres-backed retrieval plane for the LLM Wiki (FEAT-520 Module 5).

Fourth :class:`~parrot.knowledge.wiki.store.BaseWikiStore` backend
(alongside :class:`SQLiteWikiStore`, :class:`InMemoryWikiStore`,
:class:`ArangoDBWikiStore`), and the SECOND contract implemented over the
SAME ``graphindex.*`` schema as :class:`~parrot.knowledge.graphindex.
persist_postgres.PostgresPersistence` (spec U1 — one shared bitemporal
plane serves both the graph and wiki contracts).

Column mapping (spec §2 "The U1 mapping" is normative):

- ``nodes.concept_id`` — page identity (stable). ``nodes.namespace`` is
  used here as the wiki-instance scope (``wiki_name``): the shared schema
  can host multiple wikis, so every read in this store filters on
  ``namespace = wiki_name`` to keep them from bleeding into each other —
  this is a design decision this task had to make (the spec's mapping
  table calls ``namespace`` "domain/tenant" but does not fix its value
  per plane).
- ``nodes.node_id`` — the wiki's VOLATILE node id (secondary lookup only,
  never the primary key).
- ``node_versions.body`` — full markdown body IN THE DB (the wiki
  contract, unlike the graph plane's ``body_ref`` file pointer, which
  this store never sets).
- ``node_versions.origin``/``asserted_by``/``updated_at`` — wiki-only
  columns; ``provenance`` is left at its schema default (``'extracted'``)
  and never written here (U1 mapping rule 3 — provenance is graph-plane
  vocabulary, origin is wiki-plane vocabulary; neither plane writes the
  other's column). ``updated_at`` is caller-preserving (FEAT-461): a
  supplied ISO-8601 string is parsed and stored VERBATIM; ``None`` stamps
  ``now()``.

Writes are close-and-insert (never ``UPDATE`` content), the same
append-only discipline as the graph plane — even though ``SQLiteWikiStore``
itself has no temporal model, this backend's schema is shared and its
invariants (the EXCLUDE constraint) apply uniformly.

Two known, documented gaps versus the SQLite reference, both stemming from
the shared schema NOT modeling a wiki ``sources`` registry table (out of
this task's file scope — ``pg_schema.py`` DDL is TASK-2764's, already
closed per spec): :meth:`orphan_sources` always returns ``[]`` (there is
no registry to check "produced no pages" against), and :meth:`dump_edges`
is not namespace-scoped (``graphindex.edges`` has no ``namespace`` column
— same limitation the graph plane lives with).

FEAT-520 Module 6 (TASK-2769) upgrades :meth:`search_vector` from the
TASK-2768 interim (brute-force :func:`~parrot.knowledge.wiki.store.
rank_by_cosine`) to a native pgvector KNN query (``<=>`` cosine distance,
joined to CURRENT versions only), and adds a dimension guard to both
:meth:`upsert_embedding` and :meth:`search_vector`.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg

from parrot.knowledge.graphindex.pg_schema import (
    create_pg_pool,
    ensure_schema,
    resolve_regconfig,
    validate_embedding_dim,
)
from parrot.knowledge.wiki.store import (
    BaseWikiStore,
    WikiPageRecord,
    estimate_tokens,
)

logger = logging.getLogger(__name__)


def _parse_updated_at(value: Optional[str]) -> datetime:
    """Parse a caller-supplied ISO-8601 ``updated_at``, or stamp ``now()``.

    Args:
        value: Caller-supplied ISO-8601 string, or ``None``.

    Returns:
        The parsed, timezone-aware datetime, or ``now()`` when ``value``
        is absent/unparseable (defensive — never raises).
    """
    if value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            logger.warning("PostgresWikiStore: unparseable updated_at %r, stamping now()", value)
    return datetime.now(tz=timezone.utc)


def _fmt_ts(value: Any) -> Optional[str]:
    """Format a timestamptz value as the house ISO-8601 string convention."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.strftime("%Y-%m-%dT%H:%M:%S+00:00")


class PostgresWikiStore(BaseWikiStore):
    """Postgres-backed wiki retrieval plane over the shared ``graphindex.*`` schema.

    Server-hosted like :class:`ArangoDBWikiStore` — the constructor takes
    a DSN, not a ``storage_dir``. Connection/schema setup is lazy (see
    :meth:`_ensure_pool`), mirroring ``PostgresPersistence``.

    Args:
        dsn: asyncpg-compatible DSN. Defaults to
            ``pg_schema.GRAPHINDEX_PG_DSN`` when not given via
            :func:`~parrot.knowledge.wiki.store.create_wiki_store`.
        wiki_name: This wiki's namespace scope within the shared schema.
        schema: The Postgres schema name housing the GraphIndex tables.
        pool: An existing asyncpg pool to reuse instead of creating one.
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        *,
        wiki_name: str = "",
        schema: str = "graphindex",
        pool: Optional[asyncpg.Pool] = None,
    ) -> None:
        self._dsn = dsn
        self._wiki_name = wiki_name
        self._schema = schema
        self._external_pool = pool
        self._pool: Optional[asyncpg.Pool] = None
        self._pool_lock = asyncio.Lock()
        self._owns_pool = pool is None
        self.logger = logging.getLogger(__name__)

    async def _ensure_pool(self) -> asyncpg.Pool:
        """Lazily create (or reuse) the pool and ensure the schema."""
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

    async def _upsert_page(self, conn: asyncpg.Connection, page: WikiPageRecord) -> None:
        """Close-and-insert one page's identity + version row."""
        regconfig = resolve_regconfig(self._wiki_name)
        await conn.execute(
            f"""
            INSERT INTO {self._schema}.nodes (concept_id, namespace, category, node_id, lang)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (concept_id) DO UPDATE
                SET namespace = EXCLUDED.namespace, category = EXCLUDED.category,
                    node_id = EXCLUDED.node_id, lang = EXCLUDED.lang
            """,
            page.concept_id,
            self._wiki_name,
            page.category,
            page.node_id,
            regconfig,
        )
        await conn.execute(
            f"""
            UPDATE {self._schema}.node_versions
            SET validity = tstzrange(lower(validity), now())
            WHERE concept_id = $1 AND upper_inf(validity)
            """,
            page.concept_id,
        )
        updated_at = _parse_updated_at(page.updated_at)
        token_count = page.token_count or estimate_tokens(page.body)
        await conn.execute(
            f"""
            INSERT INTO {self._schema}.node_versions
                (concept_id, title, summary, body, source_id, content_hash,
                 token_count, origin, asserted_by, updated_at, fts)
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                to_tsvector($11::regconfig, $2 || ' ' || coalesce($3, '') || ' ' || coalesce($4, ''))
            )
            """,
            page.concept_id,
            page.title,
            page.summary,
            page.body,
            page.source_id,
            page.content_hash,
            token_count,
            page.origin,
            page.asserted_by,
            updated_at,
            regconfig,
        )

    async def _upsert_wiki_edge(
        self, conn: asyncpg.Connection, src: str, dst: str, rel: str, provenance: str = "extracted"
    ) -> None:
        """Close-and-insert one wiki edge (no-op when identical provenance)."""
        current = await conn.fetchrow(
            f"""
            SELECT edge_id, provenance FROM {self._schema}.edges
            WHERE src = $1 AND dst = $2 AND rel = $3 AND upper_inf(validity)
            """,
            src,
            dst,
            rel,
        )
        if current is not None:
            if current["provenance"] == provenance:
                return
            await conn.execute(
                f"""
                UPDATE {self._schema}.edges
                SET validity = tstzrange(lower(validity), now())
                WHERE edge_id = $1
                """,
                current["edge_id"],
            )
        await conn.execute(
            f"INSERT INTO {self._schema}.edges (src, dst, rel, provenance) VALUES ($1, $2, $3, $4)",
            src,
            dst,
            rel,
            provenance,
        )

    @staticmethod
    def _fmt_row(row: dict[str, Any]) -> dict[str, Any]:
        """Format any timestamp fields in a row dict to ISO-8601 strings."""
        for key in ("created_at", "updated_at"):
            if key in row:
                row[key] = _fmt_ts(row[key])
        return row

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int:
        """Insert or update wiki pages (close-and-insert per U1 mapping).

        Args:
            pages: Page records to write.

        Returns:
            Number of pages written.
        """
        if not pages:
            return 0
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                for page in pages:
                    await self._upsert_page(conn, page)
        return len(pages)

    async def add_edges(self, edges: list[tuple]) -> int:
        """Insert typed wiki edges (close-and-insert on provenance change).

        Args:
            edges: ``(src, dst, rel)`` or ``(src, dst, rel, provenance)``
                tuples; ``rel`` is an open string. Missing provenance
                defaults to ``'extracted'`` (SQLite parity).

        Returns:
            Number of edges written.
        """
        if not edges:
            return 0
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                for e in edges:
                    provenance = e[3] if len(e) > 3 else "extracted"
                    await self._upsert_wiki_edge(conn, e[0], e[1], e[2], provenance)
        return len(edges)

    async def replace_source_slice(
        self,
        source_id: str,
        pages: list[WikiPageRecord],
        edges: Optional[list[tuple[str, str, str]]] = None,
    ) -> dict[str, Any]:
        """Atomically replace all pages/edges derived from one source.

        Closes existing version rows scoped by ``source_id``, closes
        edges touching them, then upserts the replacement slice —
        incoming edges from OTHER sources whose target survives (same
        ``concept_id`` re-inserted) are preserved, matching
        ``SQLiteWikiStore.replace_source_slice``.

        Args:
            source_id: Source whose derived pages are being replaced.
            pages: Replacement page records.
            edges: Optional replacement ``(src, dst, rel)`` edges.

        Returns:
            ``{"pages_deleted": N, "pages_written": M, "edges_written": K}``
        """
        edges = edges or []
        new_ids = {p.concept_id for p in pages}
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                old_rows = await conn.fetch(
                    f"""
                    SELECT concept_id FROM {self._schema}.node_versions
                    WHERE source_id = $1 AND upper_inf(validity)
                    """,
                    source_id,
                )
                old_ids = [r["concept_id"] for r in old_rows]

                preserved: list[tuple[str, str, str]] = []
                if old_ids:
                    old_set = set(old_ids)
                    incoming = await conn.fetch(
                        f"""
                        SELECT src, dst, rel FROM {self._schema}.edges
                        WHERE dst = ANY($1::text[]) AND upper_inf(validity)
                        """,
                        old_ids,
                    )
                    preserved = [
                        (r["src"], r["dst"], r["rel"])
                        for r in incoming
                        if r["src"] not in old_set and r["dst"] in new_ids
                    ]
                    await conn.execute(
                        f"""
                        UPDATE {self._schema}.node_versions
                        SET validity = tstzrange(lower(validity), now())
                        WHERE source_id = $1 AND upper_inf(validity)
                        """,
                        source_id,
                    )
                    await conn.execute(
                        f"""
                        UPDATE {self._schema}.edges
                        SET validity = tstzrange(lower(validity), now())
                        WHERE (src = ANY($1::text[]) OR dst = ANY($1::text[])) AND upper_inf(validity)
                        """,
                        old_ids,
                    )

                for page in pages:
                    await self._upsert_page(conn, page)
                for e in edges:
                    provenance = e[3] if len(e) > 3 else "extracted"
                    await self._upsert_wiki_edge(conn, e[0], e[1], e[2], provenance)
                for src, dst, rel in preserved:
                    await self._upsert_wiki_edge(conn, src, dst, rel, "extracted")

        return {"pages_deleted": len(old_ids), "pages_written": len(pages), "edges_written": len(edges)}

    async def delete_page(self, concept_id: str) -> bool:
        """Close a page's current version and its current edges (tombstone-by-range).

        Never physically deletes — the append-only invariant applies
        schema-wide, so "delete" closes the ``validity`` range instead of
        removing rows (history stays intact for TASK-2767 temporal reads).

        Args:
            concept_id: Page identity to close.

        Returns:
            ``True`` when an open version row was actually closed.
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                status = await conn.execute(
                    f"""
                    UPDATE {self._schema}.node_versions
                    SET validity = tstzrange(lower(validity), now())
                    WHERE concept_id = $1 AND upper_inf(validity)
                    """,
                    concept_id,
                )
                await conn.execute(
                    f"""
                    UPDATE {self._schema}.edges
                    SET validity = tstzrange(lower(validity), now())
                    WHERE (src = $1 OR dst = $1) AND upper_inf(validity)
                    """,
                    concept_id,
                )
        return status.split()[-1] != "0"

    async def upsert_embedding(self, concept_id: str, vector: list[float], model: str = "") -> None:
        """Store (or replace) the embedding vector for a page's current version.

        Args:
            concept_id: Page the vector belongs to.
            vector: Embedding as a list of floats.
            model: Identifier of the embedding model used.

        Raises:
            ValueError: When ``len(vector)`` does not match
                ``GRAPHINDEX_EMBEDDING_DIM``.
        """
        validate_embedding_dim(vector)
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            version_id = await conn.fetchval(
                f"""
                SELECT version_id FROM {self._schema}.node_versions
                WHERE concept_id = $1 AND upper_inf(validity)
                """,
                concept_id,
            )
            if version_id is None:
                self.logger.warning(
                    "PostgresWikiStore.upsert_embedding: no current version for %r, skipped", concept_id
                )
                return
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

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]:
        """Fetch a single page by ``concept_id`` (falls back to ``node_id``).

        Args:
            concept_id: Stable page identity — a volatile ``node_id`` is
                also accepted, matching the SQLite fallback lookup.
            include_body: When ``False`` the body column is omitted.

        Returns:
            The CURRENT version's page dict, or ``None`` when not found.
        """
        cols = (
            "n.concept_id, n.node_id, nv.title, n.category, nv.summary, nv.source_id,"
            " nv.token_count, n.created_at, nv.updated_at, nv.origin, nv.asserted_by, nv.content_hash"
        )
        if include_body:
            cols += ", nv.body"
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            for key_col in ("n.concept_id", "n.node_id"):
                row = await conn.fetchrow(
                    f"""
                    SELECT {cols} FROM {self._schema}.nodes n
                    JOIN {self._schema}.node_versions nv ON nv.concept_id = n.concept_id
                    WHERE {key_col} = $1 AND upper_inf(nv.validity) LIMIT 1
                    """,
                    concept_id,
                )
                if row is not None:
                    return self._fmt_row(dict(row))
        return None

    async def list_pages(
        self,
        category: Optional[str] = None,
        limit: int = 100,
        origin: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """List CURRENT-version page stubs (no bodies), optionally filtered.

        Args:
            category: Exact category pre-filter.
            limit: Maximum rows returned.
            origin: Optional origin filter, e.g. ``["memory", "authored"]``.

        Returns:
            Stub dicts ordered by ``updated_at`` (newest first), scoped
            to this store's ``wiki_name`` namespace.
        """
        clauses = ["upper_inf(nv.validity)", "n.namespace = $1"]
        params: list[Any] = [self._wiki_name]
        if category is not None:
            params.append(category)
            clauses.append(f"n.category = ${len(params)}")
        if origin:
            params.append(list(origin))
            clauses.append(f"nv.origin = ANY(${len(params)}::text[])")
        where = " AND ".join(clauses)
        params.append(limit)
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT n.concept_id, n.node_id, nv.title, n.category, nv.summary,
                       nv.source_id, nv.token_count, nv.updated_at, nv.origin, nv.asserted_by, nv.content_hash
                FROM {self._schema}.nodes n
                JOIN {self._schema}.node_versions nv ON nv.concept_id = n.concept_id
                WHERE {where}
                ORDER BY nv.updated_at DESC LIMIT ${len(params)}
                """,
                *params,
            )
        return [self._fmt_row(dict(row)) for row in rows]

    async def search_fts(
        self, query: str, category: Optional[str] = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Lexical search over title/summary/body via the shared ``fts`` column.

        Args:
            query: Free-form natural-language query.
            category: Optional exact category pre-filter. When ``None``,
                ``"archive"``-category pages are excluded (FEAT-402 parity).
            limit: Maximum results.

        Returns:
            Stub dicts with a ``score`` key (``ts_rank_cd``, higher is
            better), scoped to this store's namespace.
        """
        regconfig = resolve_regconfig(self._wiki_name)
        clauses = [
            "upper_inf(nv.validity)",
            "n.namespace = $1",
            "nv.fts @@ plainto_tsquery($2::regconfig, $3)",
        ]
        params: list[Any] = [self._wiki_name, regconfig, query]
        if category is not None:
            params.append(category)
            clauses.append(f"n.category = ${len(params)}")
        else:
            clauses.append("(n.category IS NULL OR n.category != 'archive')")
        where = " AND ".join(clauses)
        params.append(limit)
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT n.concept_id, n.node_id, nv.title, n.category, nv.summary, nv.source_id, nv.token_count,
                       ts_rank_cd(nv.fts, plainto_tsquery($2::regconfig, $3)) AS score
                FROM {self._schema}.nodes n
                JOIN {self._schema}.node_versions nv ON nv.concept_id = n.concept_id
                WHERE {where}
                ORDER BY score DESC LIMIT ${len(params)}
                """,
                *params,
            )
        return [dict(row) for row in rows]

    async def search_vector(self, embedding: list[float], limit: int = 10) -> list[dict[str, Any]]:
        """Cosine-similarity KNN search over stored page embeddings (pgvector).

        Native ``<=>`` (cosine distance) ANN operator, joined to CURRENT
        versions only (spec D3) — the KNN leg TASK-2769 lands, superseding
        the brute-force :func:`~parrot.knowledge.wiki.store.rank_by_cosine`
        path TASK-2768 shipped as an interim.

        Args:
            embedding: Query vector.
            limit: Maximum results.

        Returns:
            Stub dicts with a ``score`` key in [-1, 1] (``1 - cosine
            distance``, matching :func:`rank_by_cosine`'s scale),
            nearest-first.

        Raises:
            ValueError: When ``len(embedding)`` does not match
                ``GRAPHINDEX_EMBEDDING_DIM``.
        """
        validate_embedding_dim(embedding)
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT n.concept_id, n.node_id, nv.title, n.category, nv.summary,
                       nv.source_id, nv.token_count, 1 - (emb.embedding <=> $1) AS score
                FROM {self._schema}.embeddings emb
                JOIN {self._schema}.node_versions nv ON nv.version_id = emb.version_id
                JOIN {self._schema}.nodes n ON n.concept_id = nv.concept_id
                WHERE upper_inf(nv.validity) AND n.namespace = $2
                ORDER BY emb.embedding <=> $1
                LIMIT $3
                """,
                embedding,
                self._wiki_name,
                limit,
            )
        return [dict(row) for row in rows]

    async def neighbors(
        self,
        concept_id: str,
        rel: Optional[str] = None,
        direction: str = "both",
    ) -> list[dict[str, Any]]:
        """Return edge-adjacent pages/targets of a concept.

        Args:
            concept_id: Seed page identity.
            rel: Optional exact relation filter.
            direction: ``"out"``, ``"in"``, or ``"both"``.

        Returns:
            Dicts with ``concept_id``, ``rel``, ``provenance``,
            ``direction`` and — when the target is a known CURRENT page —
            its ``title``/``category``/``summary``/``token_count`` stub.
        """
        clauses: list[tuple[str, str]] = []
        if direction in ("out", "both"):
            clauses.append(("src", "dst"))
        if direction in ("in", "both"):
            clauses.append(("dst", "src"))

        results: list[dict[str, Any]] = []
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            for anchor, other in clauses:
                sql = f"""
                    SELECT e.{other} AS concept_id, e.rel, e.provenance,
                           nv.title, n.category, nv.summary, nv.token_count
                    FROM {self._schema}.edges e
                    LEFT JOIN {self._schema}.nodes n ON n.concept_id = e.{other}
                    LEFT JOIN {self._schema}.node_versions nv
                        ON nv.concept_id = e.{other} AND upper_inf(nv.validity)
                    WHERE e.{anchor} = $1 AND upper_inf(e.validity)
                """
                params: list[Any] = [concept_id]
                if rel is not None:
                    sql += " AND e.rel = $2"
                    params.append(rel)
                rows = await conn.fetch(sql, *params)
                for row in rows:
                    item = dict(row)
                    item["direction"] = "out" if anchor == "src" else "in"
                    results.append(item)
        return results

    async def dump_pages(self) -> list[dict[str, Any]]:
        """Return every CURRENT page row WITH bodies (bulk export path).

        Returns:
            Full page dicts ordered by ``concept_id``, scoped to this
            store's namespace.
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT n.concept_id, n.node_id, nv.title, n.category, nv.summary, nv.body,
                       nv.source_id, nv.token_count, n.created_at, nv.updated_at, nv.content_hash
                FROM {self._schema}.nodes n
                JOIN {self._schema}.node_versions nv ON nv.concept_id = n.concept_id
                WHERE upper_inf(nv.validity) AND n.namespace = $1
                ORDER BY n.concept_id
                """,
                self._wiki_name,
            )
        return [self._fmt_row(dict(row)) for row in rows]

    async def dump_edges(self) -> list[dict[str, Any]]:
        """Return every CURRENT edge row (bulk export path).

        Not namespace-scoped — ``graphindex.edges`` has no ``namespace``
        column (same limitation the graph plane lives with).
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT src, dst, rel FROM {self._schema}.edges
                WHERE upper_inf(validity) ORDER BY src, dst, rel
                """
            )
        return [dict(row) for row in rows]

    async def stats(self) -> dict[str, Any]:
        """Aggregate counters for this wiki's namespace.

        Returns:
            ``{"pages": N, "edges": M, "sources": S, "embeddings": E,
            "symbols": 0, "total_tokens": T, "categories": {...}}``
            (``symbols`` is always 0 until TASK-2772).
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            pages = await conn.fetchval(
                f"""
                SELECT COUNT(*) FROM {self._schema}.nodes n
                JOIN {self._schema}.node_versions nv ON nv.concept_id = n.concept_id
                WHERE upper_inf(nv.validity) AND n.namespace = $1
                """,
                self._wiki_name,
            )
            edges = await conn.fetchval(f"SELECT COUNT(*) FROM {self._schema}.edges WHERE upper_inf(validity)")
            sources = await conn.fetchval(
                f"""
                SELECT COUNT(DISTINCT nv.source_id) FROM {self._schema}.node_versions nv
                JOIN {self._schema}.nodes n ON n.concept_id = nv.concept_id
                WHERE upper_inf(nv.validity) AND n.namespace = $1 AND nv.source_id IS NOT NULL
                """,
                self._wiki_name,
            )
            embeddings = await conn.fetchval(
                f"""
                SELECT COUNT(*) FROM {self._schema}.embeddings emb
                JOIN {self._schema}.node_versions nv ON nv.version_id = emb.version_id
                JOIN {self._schema}.nodes n ON n.concept_id = nv.concept_id
                WHERE upper_inf(nv.validity) AND n.namespace = $1
                """,
                self._wiki_name,
            )
            total_tokens = await conn.fetchval(
                f"""
                SELECT COALESCE(SUM(nv.token_count), 0) FROM {self._schema}.node_versions nv
                JOIN {self._schema}.nodes n ON n.concept_id = nv.concept_id
                WHERE upper_inf(nv.validity) AND n.namespace = $1
                """,
                self._wiki_name,
            )
            category_rows = await conn.fetch(
                f"""
                SELECT n.category, COUNT(*) AS n FROM {self._schema}.nodes n
                JOIN {self._schema}.node_versions nv ON nv.concept_id = n.concept_id
                WHERE upper_inf(nv.validity) AND n.namespace = $1
                GROUP BY n.category
                """,
                self._wiki_name,
            )
        return {
            "pages": pages,
            "edges": edges,
            "sources": sources,
            "embeddings": embeddings,
            "symbols": 0,
            "total_tokens": total_tokens,
            "categories": {row["category"]: row["n"] for row in category_rows},
        }

    # ------------------------------------------------------------------
    # Lint API
    # ------------------------------------------------------------------

    async def orphan_sources(self) -> list[str]:
        """Always ``[]`` — the shared schema has no ``sources`` registry table.

        See the module docstring for why: without a registry there is no
        "produced no pages" set to compute against.
        """
        return []

    async def broken_edges(self) -> list[dict[str, Any]]:
        """CURRENT edges whose destination is not a CURRENT page."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT e.src, e.dst, e.rel FROM {self._schema}.edges e
                WHERE upper_inf(e.validity)
                  AND NOT EXISTS (
                    SELECT 1 FROM {self._schema}.node_versions nv
                    WHERE nv.concept_id = e.dst AND upper_inf(nv.validity)
                  )
                """
            )
        return [dict(row) for row in rows]

    async def missing_bodies(self) -> list[str]:
        """CURRENT pages (in this namespace) with an empty body."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT n.concept_id FROM {self._schema}.nodes n
                JOIN {self._schema}.node_versions nv ON nv.concept_id = n.concept_id
                WHERE upper_inf(nv.validity) AND n.namespace = $1
                  AND (nv.body IS NULL OR nv.body = '')
                """,
                self._wiki_name,
            )
        return [row["concept_id"] for row in rows]

    async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]:
        """Batch look-up of ``content_hash`` for the given ids (override for efficiency).

        Args:
            concept_ids: Page ids to look up.

        Returns:
            ``{concept_id: content_hash_or_None}`` for every requested id.
        """
        if not concept_ids:
            return {}
        out: dict[str, Optional[str]] = {cid: None for cid in concept_ids}
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT n.concept_id, nv.content_hash FROM {self._schema}.nodes n
                JOIN {self._schema}.node_versions nv ON nv.concept_id = n.concept_id
                WHERE upper_inf(nv.validity) AND n.concept_id = ANY($1::text[])
                """,
                concept_ids,
            )
        for row in rows:
            out[row["concept_id"]] = row["content_hash"]
        return out
