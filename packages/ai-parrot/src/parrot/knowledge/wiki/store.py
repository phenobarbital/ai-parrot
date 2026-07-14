"""WikiStore — single-file SQLite retrieval plane for the LLM Wiki.

Machine-first knowledge storage (follow-up to FEAT-260): every wiki
query is answered from indexed SQL — no YAML/markdown parsing, no tree
walks, and no dual-toolkit fan-out at retrieval time.

Design (mirrors ``graphindex/persist_sqlite.py`` patterns):

- One ``wiki.db`` per wiki (WAL journal mode, ``aiosqlite``).
- ``pages`` — page bodies live IN the database, keyed by stable
  ``concept_id`` (volatile PageIndex ``node_id`` kept as a secondary
  column).  ``category`` and edge ``rel`` are open strings — no enum
  ceremony in the machine plane.
- ``edges`` — typed relations (``summarizes``, ``references``, …).
- ``sources`` — absorbs the former ``.manifest.json`` manifest
  (SHA-1 + mtime staleness detection).
- ``pages_fts`` — FTS5/BM25 lexical index over title/summary/body.
- ``embeddings`` — optional per-page vectors for cosine re-ranking.
- ``meta`` — schema version + wiki name.

The store is a *derived* retrieval plane: PageIndex remains the
authoring/structuring engine, and the database can always be rebuilt
from a PageIndex tree via :meth:`WikiStore.rebuild_from_tree`.
"""

from __future__ import annotations

import logging
import re
import struct
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Optional

import aiosqlite
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1"

# Shared between WikiStore (async) and SourceCollectionManager (sync
# sqlite3 connection to the same file) — WAL mode allows both.
WIKI_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    source_id       TEXT PRIMARY KEY,
    source_uri      TEXT NOT NULL UNIQUE,
    file_hash       TEXT NOT NULL,
    mtime           REAL NOT NULL,
    ingested_at     TEXT NOT NULL,
    pages_generated TEXT NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'ingested'
);

CREATE TABLE IF NOT EXISTS pages (
    concept_id  TEXT PRIMARY KEY,
    node_id     TEXT,
    title       TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT 'concept',
    summary     TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL DEFAULT '',
    source_id   TEXT,
    token_count INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pages_category ON pages(category);
CREATE INDEX IF NOT EXISTS idx_pages_source   ON pages(source_id);
CREATE INDEX IF NOT EXISTS idx_pages_node     ON pages(node_id);

CREATE TABLE IF NOT EXISTS edges (
    src        TEXT NOT NULL,
    dst        TEXT NOT NULL,
    rel        TEXT NOT NULL DEFAULT 'references',
    provenance TEXT NOT NULL DEFAULT 'extracted',
    PRIMARY KEY (src, dst, rel)
);
CREATE INDEX IF NOT EXISTS idx_edges_rel_src ON edges(rel, src);
CREATE INDEX IF NOT EXISTS idx_edges_dst     ON edges(dst);

CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
    concept_id UNINDEXED, title, summary, body, tokenize = 'unicode61'
);

CREATE TABLE IF NOT EXISTS embeddings (
    concept_id TEXT PRIMARY KEY,
    vector     BLOB NOT NULL,
    model      TEXT NOT NULL DEFAULT ''
);
"""

_FTS_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


_TOKEN_ENCODER: Any = None  # resolved lazily; False = unavailable


def _get_token_encoder() -> Any:
    """Load and cache the tiktoken encoder once per process.

    ``tiktoken.get_encoding`` may hit the network on first use — caching
    the result (or the failure) keeps ``estimate_tokens`` O(text) and
    prevents repeated download attempts in offline environments.
    """
    global _TOKEN_ENCODER
    if _TOKEN_ENCODER is None:
        try:
            import tiktoken

            _TOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")
        except Exception:  # noqa: BLE001 — tokenizer optional
            _TOKEN_ENCODER = False
    return _TOKEN_ENCODER


def estimate_tokens(text: str) -> int:
    """Cheap deterministic token estimate for budget accounting.

    Uses ``tiktoken`` (``cl100k_base``) when available, falling back to
    the ``len(text) // 4`` heuristic.  The result is stored per page so
    context packing can budget without re-tokenising at query time.

    Args:
        text: Text to measure.

    Returns:
        Estimated token count (>= 0).
    """
    if not text:
        return 0
    enc = _get_token_encoder()
    if enc:
        try:
            return len(enc.encode(text, disallowed_special=()))
        except Exception:  # noqa: BLE001
            pass
    return max(1, len(text) // 4)


def _fts_query(query: str) -> str:
    """Build a safe FTS5 MATCH expression from free-form user text.

    Extracts word tokens and joins them with ``OR`` so partial matches
    still rank (BM25 handles precision).  All FTS5 operators/quotes in
    the raw query are discarded — user input can never inject syntax.

    Args:
        query: Free-form natural-language query.

    Returns:
        FTS5 MATCH expression, or ``""`` when no tokens survive.
    """
    tokens = _FTS_TOKEN_RE.findall(query)
    return " OR ".join(f'"{t}"' for t in tokens)


def _pack_vector(vector: list[float]) -> bytes:
    """Serialise an embedding vector to a float32 blob."""
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack_vector(blob: bytes) -> list[float]:
    """Deserialise a float32 blob back to a list of floats."""
    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob))


class WikiPageRecord(BaseModel):
    """A single wiki page row in the retrieval plane.

    Attributes:
        concept_id: Stable page identity (primary key, link target).
        node_id: Volatile PageIndex node id (secondary lookup only).
        title: Page title.
        category: Open-string category (e.g. ``"summary"``, ``"entity"``).
        summary: Short summary used for stubs and FTS.
        body: Full markdown body (lives in the DB — no sidecar reads).
        source_id: Originating source id (``sources.source_id``).
        token_count: Estimated token cost of the body.
    """

    concept_id: str = Field(..., min_length=1)
    node_id: Optional[str] = None
    title: str = ""
    category: str = "concept"
    summary: str = ""
    body: str = ""
    source_id: Optional[str] = None
    token_count: int = Field(default=0, ge=0)


def rank_by_cosine(
    embedding: list[float],
    candidates: list[tuple[dict[str, Any], list[float]]],
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Rank candidate stubs by cosine similarity to a query vector.

    Shared by every backend — brute-force in-process scan, appropriate
    at wiki scale (10³–10⁴ pages).  Candidates whose vector dimension
    does not match the query are skipped.

    Args:
        embedding: Query vector.
        candidates: ``(stub_dict, vector)`` pairs.
        limit: Maximum results.

    Returns:
        Stub dicts with a ``score`` key in [-1, 1], best first.
    """
    if not candidates:
        return []

    import numpy as np

    query_vec = np.asarray(embedding, dtype=np.float32)
    q_norm = float(np.linalg.norm(query_vec))
    if q_norm == 0.0:
        return []

    scored: list[dict[str, Any]] = []
    for stub, vector in candidates:
        vec = np.asarray(vector, dtype=np.float32)
        if vec.shape != query_vec.shape:
            continue
        denom = q_norm * float(np.linalg.norm(vec))
        score = float(np.dot(query_vec, vec) / denom) if denom else 0.0
        item = dict(stub)
        item["score"] = score
        scored.append(item)
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:limit]


class BaseWikiStore(ABC):
    """Contract for wiki retrieval-plane backends.

    Every consumer (``wiki/search.py``, ``wiki/ingest.py``,
    ``wiki/toolkit.py``, ``wiki/export.py``) talks only to this
    surface, so backends are interchangeable via
    :func:`create_wiki_store`:

    - :class:`SQLiteWikiStore` — single-file ``wiki.db`` (FTS5/BM25).
    - :class:`InMemoryWikiStore` — RAM indexes persisted as an OKF
      markdown bundle directory (``wiki/file_store.py``).

    ``search_fts`` is the lexical-search entry point on all backends
    (the name predates the second backend; semantics are
    backend-defined lexical ranking, not necessarily SQLite FTS).
    """

    # -- write -----------------------------------------------------------
    @abstractmethod
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...

    @abstractmethod
    async def add_edges(self, edges: list[tuple[str, str, str]]) -> int: ...

    @abstractmethod
    async def replace_source_slice(
        self,
        source_id: str,
        pages: list[WikiPageRecord],
        edges: Optional[list[tuple[str, str, str]]] = None,
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def delete_page(self, concept_id: str) -> bool: ...

    @abstractmethod
    async def upsert_embedding(
        self, concept_id: str, vector: list[float], model: str = ""
    ) -> None: ...

    # -- read ------------------------------------------------------------
    @abstractmethod
    async def get_page(
        self, concept_id: str, include_body: bool = True
    ) -> Optional[dict[str, Any]]: ...

    @abstractmethod
    async def list_pages(
        self, category: Optional[str] = None, limit: int = 100
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def search_fts(
        self, query: str, category: Optional[str] = None, limit: int = 10
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def search_vector(
        self, embedding: list[float], limit: int = 10
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def neighbors(
        self,
        concept_id: str,
        rel: Optional[str] = None,
        direction: str = "both",
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def dump_pages(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def dump_edges(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def stats(self) -> dict[str, Any]: ...

    # -- lint --------------------------------------------------------------
    @abstractmethod
    async def orphan_sources(self) -> list[str]: ...

    @abstractmethod
    async def broken_edges(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def missing_bodies(self) -> list[str]: ...

    # -- shared concrete behaviour ----------------------------------------

    async def rebuild_from_tree(
        self,
        tree: dict[str, Any],
        content_loader: Optional[Callable[[str], Optional[str]]] = None,
        source_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Rebuild page rows from a PageIndex tree (derived-plane refresh).

        Backend-agnostic: walks every node once and calls
        :meth:`upsert_pages`.  Page identity prefers ``concept_id``
        (assigned by ``splice_subtree``) and falls back to ``node_id``.
        Bodies are loaded through ``content_loader`` (typically
        ``NodeContentStore.loader_for(tree_name)``).

        Args:
            tree: PageIndex tree dict (``{"structure": [...]}``).
            content_loader: ``node_id -> markdown`` callable, or ``None``
                to store summary-only rows.
            source_id: Optional source id stamped on every rebuilt page.

        Returns:
            ``{"pages_written": N}``
        """
        from parrot.knowledge.pageindex.utils import get_nodes

        structure = tree.get("structure", tree)
        nodes = get_nodes(structure)
        pages: list[WikiPageRecord] = []
        for node in nodes:
            node_id = str(node.get("node_id") or "")
            concept_id = str(node.get("concept_id") or node_id)
            if not concept_id:
                continue
            body = ""
            if content_loader is not None:
                for key in (concept_id, node_id):
                    if not key:
                        continue
                    loaded = content_loader(key)
                    if loaded:
                        body = loaded
                        break
            summary = str(node.get("summary") or "")
            pages.append(
                WikiPageRecord(
                    concept_id=concept_id,
                    node_id=node_id or None,
                    title=str(node.get("title") or concept_id),
                    category=str(node.get("category") or node.get("type") or "concept").lower(),
                    summary=summary,
                    body=body,
                    source_id=source_id,
                    token_count=estimate_tokens(body or summary),
                )
            )
        written = await self.upsert_pages(pages)
        return {"pages_written": written}


class SQLiteWikiStore(BaseWikiStore):
    """Async single-file SQLite retrieval plane for one wiki.

    Args:
        db_path: Path of the ``wiki.db`` file.  Parent directories are
            created automatically.
        wiki_name: Optional wiki name recorded in the ``meta`` table.

    Example::

        store = WikiStore(storage_dir / "wiki.db", wiki_name="my-wiki")
        await store.upsert_pages([WikiPageRecord(concept_id="intro", ...)])
        hits = await store.search_fts("neural networks", limit=5)
    """

    def __init__(self, db_path: str | Path, wiki_name: str = "") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._wiki_name = wiki_name
        self.logger = logging.getLogger(__name__)

    @property
    def db_path(self) -> Path:
        """Path of the underlying SQLite file."""
        return self._db_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        """Open the database, ensure schema, and yield a connection.

        The caller is responsible for committing before exiting.
        """
        async with aiosqlite.connect(str(self._db_path)) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.executescript(WIKI_SCHEMA_SQL)
            await conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                ("schema_version", SCHEMA_VERSION),
            )
            if self._wiki_name:
                await conn.execute(
                    "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                    ("wiki_name", self._wiki_name),
                )
            await conn.commit()
            yield conn

    async def _upsert_pages_conn(
        self,
        conn: aiosqlite.Connection,
        pages: list[WikiPageRecord],
    ) -> None:
        """Upsert page rows + FTS entries on an open connection."""
        now = _now_iso()
        await conn.executemany(
            "INSERT INTO pages"
            " (concept_id, node_id, title, category, summary, body,"
            "  source_id, token_count, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(concept_id) DO UPDATE SET"
            "  node_id=excluded.node_id, title=excluded.title,"
            "  category=excluded.category, summary=excluded.summary,"
            "  body=excluded.body, source_id=excluded.source_id,"
            "  token_count=excluded.token_count, updated_at=excluded.updated_at",
            [
                (
                    p.concept_id,
                    p.node_id,
                    p.title,
                    p.category,
                    p.summary,
                    p.body,
                    p.source_id,
                    p.token_count or estimate_tokens(p.body),
                    now,
                    now,
                )
                for p in pages
            ],
        )
        await conn.executemany(
            "DELETE FROM pages_fts WHERE concept_id = ?",
            [(p.concept_id,) for p in pages],
        )
        await conn.executemany(
            "INSERT INTO pages_fts (concept_id, title, summary, body)"
            " VALUES (?, ?, ?, ?)",
            [(p.concept_id, p.title, p.summary, p.body) for p in pages],
        )

    async def _insert_edges_conn(
        self,
        conn: aiosqlite.Connection,
        edges: list[tuple[str, str, str]],
    ) -> None:
        """Insert (src, dst, rel) edge tuples on an open connection."""
        await conn.executemany(
            "INSERT OR REPLACE INTO edges (src, dst, rel) VALUES (?, ?, ?)",
            edges,
        )

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int:
        """Insert or update wiki pages (and their FTS index rows).

        Args:
            pages: Page records to write.

        Returns:
            Number of pages written.
        """
        if not pages:
            return 0
        async with self._connect() as conn:
            await self._upsert_pages_conn(conn, pages)
            await conn.commit()
        return len(pages)

    async def add_edges(self, edges: list[tuple[str, str, str]]) -> int:
        """Insert typed edges.

        Args:
            edges: ``(src, dst, rel)`` tuples; ``rel`` is an open string.

        Returns:
            Number of edges written.
        """
        if not edges:
            return 0
        async with self._connect() as conn:
            await self._insert_edges_conn(conn, edges)
            await conn.commit()
        return len(edges)

    async def replace_source_slice(
        self,
        source_id: str,
        pages: list[WikiPageRecord],
        edges: Optional[list[tuple[str, str, str]]] = None,
    ) -> dict[str, Any]:
        """Atomically replace all pages/edges derived from one source.

        Deletes existing pages whose ``source_id`` matches (plus their
        FTS rows, embeddings, and any edges touching them), then inserts
        the replacements — so re-ingest never accumulates duplicates.

        Args:
            source_id: Source whose derived pages are being replaced.
            pages: Replacement page records.
            edges: Optional replacement ``(src, dst, rel)`` edges.

        Returns:
            ``{"pages_deleted": N, "pages_written": M, "edges_written": K}``
        """
        edges = edges or []
        async with self._connect() as conn:
            async with conn.execute(
                "SELECT concept_id FROM pages WHERE source_id = ?",
                (source_id,),
            ) as cur:
                old_ids = [row["concept_id"] for row in await cur.fetchall()]

            if old_ids:
                await conn.executemany(
                    "DELETE FROM pages_fts WHERE concept_id = ?",
                    [(cid,) for cid in old_ids],
                )
                await conn.executemany(
                    "DELETE FROM embeddings WHERE concept_id = ?",
                    [(cid,) for cid in old_ids],
                )
                await conn.executemany(
                    "DELETE FROM edges WHERE src = ? OR dst = ?",
                    [(cid, cid) for cid in old_ids],
                )
                await conn.execute(
                    "DELETE FROM pages WHERE source_id = ?", (source_id,)
                )

            await self._upsert_pages_conn(conn, pages)
            await self._insert_edges_conn(conn, edges)
            await conn.commit()

        self.logger.debug(
            "replace_source_slice: source=%s deleted=%d written=%d",
            source_id,
            len(old_ids),
            len(pages),
        )
        return {
            "pages_deleted": len(old_ids),
            "pages_written": len(pages),
            "edges_written": len(edges),
        }

    async def delete_page(self, concept_id: str) -> bool:
        """Delete a page and its FTS row, embeddings, and edges.

        Args:
            concept_id: Page identity to delete.

        Returns:
            ``True`` when a page row was actually deleted.
        """
        async with self._connect() as conn:
            cur = await conn.execute(
                "DELETE FROM pages WHERE concept_id = ?", (concept_id,)
            )
            deleted = cur.rowcount > 0
            await conn.execute(
                "DELETE FROM pages_fts WHERE concept_id = ?", (concept_id,)
            )
            await conn.execute(
                "DELETE FROM embeddings WHERE concept_id = ?", (concept_id,)
            )
            await conn.execute(
                "DELETE FROM edges WHERE src = ? OR dst = ?",
                (concept_id, concept_id),
            )
            await conn.commit()
        return deleted

    async def upsert_embedding(
        self,
        concept_id: str,
        vector: list[float],
        model: str = "",
    ) -> None:
        """Store (or replace) the embedding vector for a page.

        Args:
            concept_id: Page the vector belongs to.
            vector: Embedding as a list of floats (stored as float32).
            model: Identifier of the embedding model used.
        """
        async with self._connect() as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO embeddings (concept_id, vector, model)"
                " VALUES (?, ?, ?)",
                (concept_id, _pack_vector(vector), model),
            )
            await conn.commit()

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    async def get_page(
        self, concept_id: str, include_body: bool = True
    ) -> Optional[dict[str, Any]]:
        """Fetch a single page by ``concept_id`` (falls back to ``node_id``).

        Args:
            concept_id: Stable page identity — for convenience a volatile
                PageIndex ``node_id`` is also accepted.
            include_body: When ``False`` the body column is omitted
                (cheaper for stub-only reads).

        Returns:
            Page row as a dict, or ``None`` when not found.
        """
        cols = (
            "concept_id, node_id, title, category, summary, source_id,"
            " token_count, created_at, updated_at"
        )
        if include_body:
            cols += ", body"
        async with self._connect() as conn:
            for key_col in ("concept_id", "node_id"):
                async with conn.execute(
                    f"SELECT {cols} FROM pages WHERE {key_col} = ? LIMIT 1",  # noqa: S608
                    (concept_id,),
                ) as cur:
                    row = await cur.fetchone()
                if row:
                    return dict(row)
        return None

    async def list_pages(
        self,
        category: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List page stubs (no bodies), optionally filtered by category.

        Args:
            category: Exact category pre-filter (open string).
            limit: Maximum rows returned.

        Returns:
            List of stub dicts ordered by ``updated_at`` (newest first).
        """
        sql = (
            "SELECT concept_id, node_id, title, category, summary,"
            " source_id, token_count, updated_at FROM pages"
        )
        params: tuple[Any, ...] = ()
        if category is not None:
            sql += " WHERE category = ?"
            params = (category,)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params += (limit,)
        async with self._connect() as conn:
            async with conn.execute(sql, params) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def search_fts(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """BM25 lexical search over title/summary/body.

        Args:
            query: Free-form natural-language query (sanitised before
                reaching FTS5 — no operator injection).
            category: Optional exact category pre-filter (deterministic
                gate applied before ranking).
            limit: Maximum results.

        Returns:
            Stub dicts with a ``score`` key (higher is better; scores
            are ``-bm25`` and NOT normalised — callers normalise).
        """
        match_expr = _fts_query(query)
        if not match_expr:
            return []
        sql = (
            "SELECT p.concept_id, p.node_id, p.title, p.category, p.summary,"
            " p.source_id, p.token_count, -bm25(pages_fts) AS score"
            " FROM pages_fts JOIN pages p ON p.concept_id = pages_fts.concept_id"
            " WHERE pages_fts MATCH ?"
        )
        params: tuple[Any, ...] = (match_expr,)
        if category is not None:
            sql += " AND p.category = ?"
            params += (category,)
        sql += " ORDER BY bm25(pages_fts) LIMIT ?"
        params += (limit,)
        async with self._connect() as conn:
            async with conn.execute(sql, params) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def search_vector(
        self,
        embedding: list[float],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Cosine-similarity search over stored page embeddings.

        Brute-force in-process scan — appropriate at wiki scale (10³–10⁴
        pages) and keeps the store dependency-free.

        Args:
            embedding: Query vector.
            limit: Maximum results.

        Returns:
            Stub dicts with a ``score`` key in [-1, 1] (cosine).
        """
        async with self._connect() as conn:
            async with conn.execute(
                "SELECT e.concept_id, e.vector, p.node_id, p.title,"
                " p.category, p.summary, p.source_id, p.token_count"
                " FROM embeddings e JOIN pages p ON p.concept_id = e.concept_id"
            ) as cur:
                rows = await cur.fetchall()

        candidates: list[tuple[dict[str, Any], list[float]]] = []
        for row in rows:
            stub = {
                k: row[k]
                for k in (
                    "concept_id",
                    "node_id",
                    "title",
                    "category",
                    "summary",
                    "source_id",
                    "token_count",
                )
            }
            candidates.append((stub, _unpack_vector(row["vector"])))
        return rank_by_cosine(embedding, candidates, limit=limit)

    async def neighbors(
        self,
        concept_id: str,
        rel: Optional[str] = None,
        direction: str = "both",
    ) -> list[dict[str, Any]]:
        """Return edge-adjacent pages/targets of a concept.

        Args:
            concept_id: Seed page identity.
            rel: Optional exact relation filter (open string).
            direction: ``"out"``, ``"in"``, or ``"both"``.

        Returns:
            Dicts with ``concept_id``, ``rel``, ``direction`` and — when
            the target is a known page — its ``title``/``summary`` stub.
        """
        clauses: list[tuple[str, str]] = []
        if direction in ("out", "both"):
            clauses.append(("src", "dst"))
        if direction in ("in", "both"):
            clauses.append(("dst", "src"))

        results: list[dict[str, Any]] = []
        async with self._connect() as conn:
            for anchor, other in clauses:
                sql = (
                    f"SELECT e.{other} AS concept_id, e.rel,"  # noqa: S608
                    " p.title, p.category, p.summary, p.token_count"
                    f" FROM edges e LEFT JOIN pages p ON p.concept_id = e.{other}"
                    f" WHERE e.{anchor} = ?"
                )
                params: tuple[Any, ...] = (concept_id,)
                if rel is not None:
                    sql += " AND e.rel = ?"
                    params += (rel,)
                async with conn.execute(sql, params) as cur:
                    for row in await cur.fetchall():
                        item = dict(row)
                        item["direction"] = "out" if anchor == "src" else "in"
                        results.append(item)
        return results

    async def dump_pages(self) -> list[dict[str, Any]]:
        """Return every page row WITH bodies (bulk export path).

        Returns:
            Full page dicts ordered by ``concept_id``.
        """
        async with self._connect() as conn:
            async with conn.execute(
                "SELECT concept_id, node_id, title, category, summary, body,"
                " source_id, token_count, created_at, updated_at"
                " FROM pages ORDER BY concept_id"
            ) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def dump_edges(self) -> list[dict[str, Any]]:
        """Return every edge row (bulk export path)."""
        async with self._connect() as conn:
            async with conn.execute(
                "SELECT src, dst, rel FROM edges ORDER BY src, dst, rel"
            ) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def stats(self) -> dict[str, Any]:
        """Aggregate counters for the wiki (single fast query set).

        Returns:
            ``{"pages": N, "edges": M, "sources": S, "embeddings": E,
            "total_tokens": T, "categories": {...}}``
        """
        async with self._connect() as conn:
            out: dict[str, Any] = {}
            for key, sql in (
                ("pages", "SELECT COUNT(*) FROM pages"),
                ("edges", "SELECT COUNT(*) FROM edges"),
                ("sources", "SELECT COUNT(*) FROM sources"),
                ("embeddings", "SELECT COUNT(*) FROM embeddings"),
                ("total_tokens", "SELECT COALESCE(SUM(token_count), 0) FROM pages"),
            ):
                async with conn.execute(sql) as cur:
                    row = await cur.fetchone()
                    out[key] = row[0] if row else 0
            async with conn.execute(
                "SELECT category, COUNT(*) AS n FROM pages GROUP BY category"
            ) as cur:
                out["categories"] = {
                    row["category"]: row["n"] for row in await cur.fetchall()
                }
        return out

    # ------------------------------------------------------------------
    # Lint API (fast SQL checks)
    # ------------------------------------------------------------------

    async def orphan_sources(self) -> list[str]:
        """Sources that produced no pages (zero rows in ``pages``)."""
        async with self._connect() as conn:
            async with conn.execute(
                "SELECT s.source_id FROM sources s"
                " LEFT JOIN pages p ON p.source_id = s.source_id"
                " WHERE p.concept_id IS NULL"
            ) as cur:
                return [row["source_id"] for row in await cur.fetchall()]

    async def broken_edges(self) -> list[dict[str, Any]]:
        """Edges whose destination is neither a page nor a source."""
        async with self._connect() as conn:
            async with conn.execute(
                "SELECT e.src, e.dst, e.rel FROM edges e"
                " WHERE e.dst NOT IN (SELECT concept_id FROM pages)"
                " AND e.dst NOT IN (SELECT source_id FROM sources)"
            ) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def missing_bodies(self) -> list[str]:
        """Pages with an empty body (stub rows without content)."""
        async with self._connect() as conn:
            async with conn.execute(
                "SELECT concept_id FROM pages WHERE body = ''"
            ) as cur:
                return [row["concept_id"] for row in await cur.fetchall()]


# Backwards-compatible alias — the SQLite plane was the only backend
# before the pluggable-store refactor.
WikiStore = SQLiteWikiStore


def create_wiki_store(
    storage_dir: str | Path,
    wiki_name: str = "",
    backend: str = "sqlite",
) -> BaseWikiStore:
    """Instantiate the configured wiki retrieval-plane backend.

    Selection is explicit (``WikiConfig.storage_backend``) — there is no
    silent fallback: a broken/unavailable backend is a hard error.

    Args:
        storage_dir: Wiki storage root.  ``sqlite`` uses
            ``{storage_dir}/wiki.db``; ``memory`` uses the OKF bundle
            directory ``{storage_dir}/pages/``.
        wiki_name: Wiki name recorded by the backend.
        backend: ``"sqlite"`` (single-file SQLite plane) or
            ``"memory"`` (in-memory indexes + OKF markdown directory).

    Returns:
        A :class:`BaseWikiStore` implementation.

    Raises:
        ValueError: For an unknown ``backend`` value.
    """
    storage_dir = Path(storage_dir)
    if backend == "sqlite":
        return SQLiteWikiStore(storage_dir / "wiki.db", wiki_name=wiki_name)
    if backend == "memory":
        # Imported lazily — file_store imports export helpers which
        # import this module.
        from parrot.knowledge.wiki.file_store import InMemoryWikiStore

        return InMemoryWikiStore(storage_dir / "pages", wiki_name=wiki_name)
    raise ValueError(
        f"Unknown wiki storage backend {backend!r} — expected 'sqlite' or 'memory'"
    )
