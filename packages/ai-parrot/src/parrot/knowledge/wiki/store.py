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

import asyncio
import errno
import logging
import re
import sqlite3
import struct
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Optional
from urllib.parse import quote

import aiosqlite
from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover - typing only
    from parrot.knowledge.wiki.symbols import SymbolRecord

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "2"

# Shared between WikiStore (async) and SourceCollectionManager (sync
# sqlite3 connection to the same file) — WAL mode allows both.
WIKI_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    source_id        TEXT PRIMARY KEY,
    source_uri       TEXT NOT NULL UNIQUE,
    file_hash        TEXT NOT NULL,
    mtime            REAL NOT NULL,
    ingested_at      TEXT NOT NULL,
    pages_generated  TEXT NOT NULL DEFAULT '[]',
    status           TEXT NOT NULL DEFAULT 'ingested',
    destination      TEXT,
    decision_source  TEXT,
    charter_version  TEXT,
    composite_score  REAL,
    external_id      TEXT
);
-- destination/decision_source/charter_version/composite_score (FEAT-402,
-- TASK-2073): supervised-ingestion triage decision provenance. All four
-- are nullable/defaulted (NULL) so this CREATE TABLE IF NOT EXISTS is a
-- no-op on already-existing pre-FEAT-402 databases — those get the same
-- four columns via the idempotent ALTER TABLE migration in
-- SourceCollectionManager._migrate_sources_columns (sources.py).
-- external_id (FEAT-472): immutable external identity in "<source>:<id>"
-- form (e.g. "fireflies:abc123"), nullable. Same additive-only contract:
-- pre-FEAT-472 databases gain the column via the idempotent ALTER TABLE
-- migration in _migrate_sources_columns. The idx_sources_external_id
-- index is (idempotently) created THERE too, rather than here — a fresh
-- CREATE TABLE always has the column already, but this script also runs
-- (as a no-op CREATE TABLE IF NOT EXISTS) against pre-existing databases
-- that do NOT have it yet, and _migrate_sources_columns always runs
-- right after this script, so creating the index there covers both
-- fresh and pre-existing databases from exactly one place.

CREATE TABLE IF NOT EXISTS pages (
    concept_id   TEXT PRIMARY KEY,
    node_id      TEXT,
    title        TEXT NOT NULL,
    category     TEXT NOT NULL DEFAULT 'concept',
    summary      TEXT NOT NULL DEFAULT '',
    body         TEXT NOT NULL DEFAULT '',
    source_id    TEXT,
    token_count  INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    origin       TEXT NOT NULL DEFAULT 'ingest',
    asserted_by  TEXT,
    content_hash TEXT
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

-- FEAT-498: structural symbol plane (SQLite-native; ArangoDB/InMemory
-- persist sym: pages + edges via existing methods and use BaseWikiStore's
-- default page-based symbol methods instead of this table).
CREATE TABLE IF NOT EXISTS symbols (
    concept_id  TEXT PRIMARY KEY,
    rel_path    TEXT NOT NULL,
    language    TEXT NOT NULL,
    kind        TEXT NOT NULL,
    name        TEXT NOT NULL,
    qualname    TEXT NOT NULL,
    parent      TEXT,
    signature   TEXT NOT NULL DEFAULT '',
    doc         TEXT NOT NULL DEFAULT '',
    exported    INTEGER NOT NULL DEFAULT 0,
    is_async    INTEGER NOT NULL DEFAULT 0,
    depth       INTEGER NOT NULL DEFAULT 1,
    start_line  INTEGER,
    end_line    INTEGER,
    start_byte  INTEGER,
    end_byte    INTEGER,
    node_kind   TEXT,
    content_hash TEXT,
    source_id   TEXT
);
CREATE INDEX IF NOT EXISTS idx_symbols_name   ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_path   ON symbols(rel_path);
CREATE INDEX IF NOT EXISTS idx_symbols_source ON symbols(source_id);
CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
    concept_id UNINDEXED, name, qualname, doc, signature, tokenize = 'unicode61'
);
"""

# Columns added after the original FEAT-260 schema shipped.  ``CREATE TABLE
# IF NOT EXISTS`` silently skips existing databases, so ``_migrate`` ALTERs
# these in when missing (idempotent, no data rewrite).
_MIGRATION_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "pages": [
        ("origin", "TEXT NOT NULL DEFAULT 'ingest'"),
        ("asserted_by", "TEXT"),
        ("content_hash", "TEXT"),
    ],
}

#: Tables ``WIKI_SCHEMA_SQL`` creates. The per-connection presence probe
#: replays the schema when ANY of them is missing (fresh plane, external
#: replacement, or a partial legacy database), not just ``pages``.
_SCHEMA_TABLES = frozenset({"meta", "sources", "pages", "edges", "pages_fts", "embeddings", "symbols", "symbols_fts"})

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


def _like_prefix(prefix: str) -> str:
    """Escape ``%``/``_``/``\\`` and append ``%`` for a ``LIKE ... ESCAPE '\\'`` prefix match."""
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}%"


def _row_to_symbol_record(row: aiosqlite.Row) -> SymbolRecord:
    """Decode one ``symbols`` table row into a :class:`SymbolRecord`.

    Args:
        row: A row from ``SELECT * FROM symbols`` (``aiosqlite.Row``,
            dict-like access by column name).

    Returns:
        The reconstructed, full-fidelity symbol record.
    """
    from parrot.knowledge.wiki.symbols import SymbolKind, SymbolRecord as _SymbolRecord

    return _SymbolRecord(
        rel_path=row["rel_path"],
        language=row["language"],
        kind=SymbolKind(row["kind"]),
        name=row["name"],
        qualname=row["qualname"],
        parent=row["parent"],
        signature=row["signature"] or "",
        doc=row["doc"] or "",
        exported=bool(row["exported"]),
        is_async=bool(row["is_async"]),
        start_line=row["start_line"] or 0,
        end_line=row["end_line"] or 0,
        start_byte=row["start_byte"] or 0,
        end_byte=row["end_byte"] or 0,
        node_kind=row["node_kind"] or "",
        content_hash=row["content_hash"] or "",
        depth=row["depth"] or 1,
    )


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
        origin: How the page came to exist — ``"ingest"`` (derived from
            a source), ``"authored"`` (written by an agent tool), or
            ``"memory"`` (saved via the ``remember`` authoring surface).
        asserted_by: Identity of the writer for authored/memory pages,
            e.g. ``"agent:<id>"`` or ``"human:<user>"``.
        updated_at: ISO-8601 UTC last-modified stamp (FEAT-461). On
            write, ``None`` means "stamp now" — both backends already
            persist this column and fill it in unconditionally when the
            caller does not supply one. On read, it is always populated
            from the DB. A caller-supplied value is preserved verbatim
            on upsert (never overwritten with "now"), which is what lets
            sync (TASK-2466) replicate a record without making it look
            newer than its source. Legacy/defensive ``None`` sorts
            oldest in any last-write-wins comparison.
        content_hash: SHA-1 hex digest of the page's source content
            (FEAT-498) — same digest family as
            ``SourceCollectionManager._compute_hash`` for ``file:``
            pages, and :func:`parrot.knowledge.wiki.symbols.sha1_of_text`
            of the node text for ``sym:`` pages. ``None`` for pages that
            predate the freshness plane or are not backed by scanned
            source (e.g. ``dir:`` pages).
    """

    concept_id: str = Field(..., min_length=1)
    node_id: Optional[str] = None
    title: str = ""
    category: str = "concept"
    summary: str = ""
    body: str = ""
    source_id: Optional[str] = None
    token_count: int = Field(default=0, ge=0)
    origin: str = "ingest"
    asserted_by: Optional[str] = None
    updated_at: Optional[str] = None
    content_hash: Optional[str] = None


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


_EXTRA_BACKENDS: dict[str, Callable[..., BaseWikiStore]] = {}
"""Satellite-provided wiki backends, registered at import time (FEAT-449 M7).

Additive-only seam: core never imports a satellite package (e.g.
``parrot_tools``) — the satellite registers itself here when it is
imported. See :func:`register_wiki_backend` and the dispatch in
:func:`create_wiki_store` / ``federation.open_namespace_store``.
"""


def register_wiki_backend(name: str, factory: Callable[..., BaseWikiStore]) -> None:
    """Register a satellite-provided wiki backend (FEAT-449 M7).

    Args:
        name: Backend name (matches ``WikiNamespaceConfig.backend`` /
            ``create_wiki_store(backend=...)``). Must not collide with a
            built-in name (``"sqlite"``, ``"memory"``, ``"arangodb"``).
        factory: Callable constructing the store,
            ``factory(*, storage_dir=None, wiki_name="", **kwargs) ->
            BaseWikiStore``.
    """
    _EXTRA_BACKENDS[name] = factory


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
    async def add_edges(self, edges: list[tuple]) -> int: ...

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
    async def upsert_embedding(self, concept_id: str, vector: list[float], model: str = "") -> None: ...

    # -- read ------------------------------------------------------------
    @abstractmethod
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]: ...

    @abstractmethod
    async def list_pages(
        self,
        category: Optional[str] = None,
        limit: int = 100,
        origin: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def search_vector(self, embedding: list[float], limit: int = 10) -> list[dict[str, Any]]: ...

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

    def _assert_writable(self) -> None:
        """Hook for stores that can be opened read-only.

        The base implementation is a no-op; :class:`SQLiteWikiStore`
        overrides it to refuse writes when opened with
        ``read_only=True`` (FEAT-450).
        """

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

        Raises:
            PermissionError: When the store is read-only.
        """
        self._assert_writable()
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

    # -- FEAT-498: structural symbol plane (concrete defaults) -----------
    #
    # Deliberately NOT @abstractmethod: ArangoDBWikiStore, InMemoryWikiStore,
    # FederatedWikiStore and _EmptyStore must keep instantiating unchanged.
    # SQLiteWikiStore overrides all five with native `symbols` table
    # queries; everyone else answers from `sym:` pages via these defaults.

    async def upsert_symbols(
        self,
        symbols: list[SymbolRecord],
        source_id: Optional[str] = None,
    ) -> int:
        """Persist symbol rows in a native symbol store (default: no-op).

        Backends without a native ``symbols`` table already persist
        symbols as ``sym:`` pages via :meth:`upsert_pages` /
        :meth:`replace_source_slice` — this default simply does nothing.

        Args:
            symbols: Symbol records to persist.
            source_id: Originating source id.

        Returns:
            ``0`` — no rows written by the default implementation.
        """
        return 0

    async def symbols_for(self, rel_path: str) -> list[SymbolRecord]:
        """List every symbol extracted from one file.

        Default: filters :meth:`list_pages` (``category="symbol"``) by
        the page's ``node_id`` (== ``rel_path`` for a ``sym:`` page).

        Args:
            rel_path: POSIX path relative to the repository root.

        Returns:
            Decoded :class:`~parrot.knowledge.wiki.symbols.SymbolRecord`
            list (best-effort — see
            :func:`~parrot.knowledge.wiki.symbols.symbol_from_page`).
        """
        from parrot.knowledge.wiki.symbols import symbol_from_page

        pages = await self.list_pages(category="symbol", limit=10_000)
        out: list[SymbolRecord] = []
        for stub in pages:
            if stub.get("node_id") != rel_path:
                continue
            full = await self.get_page(stub["concept_id"], include_body=True) or stub
            record = symbol_from_page(full)
            if record is not None:
                out.append(record)
        return out

    async def find_symbols(
        self,
        name: Optional[str] = None,
        qualname_prefix: Optional[str] = None,
        kind: Optional[str] = None,
        language: Optional[str] = None,
        path_prefix: Optional[str] = None,
        limit: int = 50,
    ) -> list[SymbolRecord]:
        """Find symbols by name/qualname/kind/language/path filters.

        Default: linear scan over :meth:`list_pages` (``category="symbol"``)
        — adequate at wiki scale for backends without a native index.

        Args:
            name: Exact local-name filter.
            qualname_prefix: Qualname must start with this prefix.
            kind: Exact :class:`SymbolKind` value filter.
            language: Exact scanner-name filter.
            path_prefix: ``rel_path`` must start with this prefix.
            limit: Maximum results.

        Returns:
            Matching, decoded symbol records (name matches ranked first).
        """
        from parrot.knowledge.wiki.symbols import symbol_from_page

        pages = await self.list_pages(category="symbol", limit=10_000)
        exact_name: list[SymbolRecord] = []
        other: list[SymbolRecord] = []
        for stub in pages:
            full = await self.get_page(stub["concept_id"], include_body=True) or stub
            record = symbol_from_page(full)
            if record is None:
                continue
            if qualname_prefix and not record.qualname.startswith(qualname_prefix):
                continue
            if kind and record.kind.value != kind:
                continue
            if language and record.language != language:
                continue
            if path_prefix and not record.rel_path.startswith(path_prefix):
                continue
            if name and record.name != name:
                continue
            (exact_name if name and record.name == name else other).append(record)
        return (exact_name + other)[:limit]

    async def search_symbols_fts(self, query: str, limit: int = 20) -> list[SymbolRecord]:
        """Lexical search over symbols (default: :meth:`search_fts`).

        Args:
            query: Free-form query text.
            limit: Maximum results.

        Returns:
            Decoded symbol records ranked by the backend's lexical score.
        """
        from parrot.knowledge.wiki.symbols import symbol_from_page

        hits = await self.search_fts(query, category="symbol", limit=limit)
        out: list[SymbolRecord] = []
        for stub in hits:
            full = await self.get_page(stub["concept_id"], include_body=True) or stub
            record = symbol_from_page(full)
            if record is not None:
                out.append(record)
        return out

    async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]:
        """Look up ``content_hash`` for a batch of page ids.

        Default: one :meth:`get_page` call per id.

        Args:
            concept_ids: Page ids to look up (``file:`` or ``sym:``).

        Returns:
            ``{concept_id: content_hash_or_None}`` for every requested id.
        """
        out: dict[str, Optional[str]] = {}
        for concept_id in concept_ids:
            page = await self.get_page(concept_id, include_body=False)
            out[concept_id] = (page or {}).get("content_hash")
        return out


class SQLiteWikiStore(BaseWikiStore):
    """Async single-file SQLite retrieval plane for one wiki.

    Args:
        db_path: Path of the ``wiki.db`` file.  Parent directories are
            created automatically (except in read-only mode).
        wiki_name: Optional wiki name recorded in the ``meta`` table.
        read_only: Open the plane strictly for reading (FEAT-450). No
            parent ``mkdir``, no schema replay, no column migration and
            no sidecar creation — every connection goes straight to
            :meth:`_connect_readonly`, and every write method raises
            :class:`PermissionError`. Used for foreign namespaces, whose
            planes belong to another project and must never be mutated
            by a read here.

    Example::

        store = WikiStore(storage_dir / "wiki.db", wiki_name="my-wiki")
        await store.upsert_pages([WikiPageRecord(concept_id="intro", ...)])
        hits = await store.search_fts("neural networks", limit=5)
    """

    #: SQLite result codes that positively identify a read-only
    #: environment (exact extended codes, not primary-code families):
    #: SQLITE_READONLY (8), SQLITE_READONLY_RECOVERY (264),
    #: SQLITE_READONLY_DIRECTORY (1544) — the code an unwritable
    #: directory produces even for pure SELECTs on a WAL plane, because
    #: the reader cannot create the ``-shm`` — and plain SQLITE_CANTOPEN
    #: (14), which sandbox-denied opens produce. Extended variants like
    #: READONLY_ROLLBACK/DBMOVED or CANTOPEN_ISDIR/FULLPATH signal
    #: recovery/path problems, not a read-only filesystem, and must
    #: propagate untouched — as must locks, disk-full and I/O errors.
    #: Plain CANTOPEN is admittedly broader than "read-only" (it can
    #: also mean fd exhaustion or VFS trouble); that is bounded by the
    #: fallback design: degradation happens only if a read-only probe
    #: connection SUCCEEDS afterwards, so a resource-exhausted process
    #: fails the probe too and the original error propagates.
    _READONLY_ENV_CODES = frozenset({8, 264, 1544, 14})

    @classmethod
    def _is_readonly_env_error(cls, exc: sqlite3.OperationalError) -> bool:
        """True only for errors that mean "this database is not writable"."""
        code = getattr(exc, "sqlite_errorcode", None)
        if code is not None:
            return code in cls._READONLY_ENV_CODES
        msg = str(exc)
        return "readonly database" in msg or "unable to open database file" in msg

    def __init__(
        self,
        db_path: str | Path,
        wiki_name: str = "",
        *,
        read_only: bool = False,
    ) -> None:
        self._db_path = Path(db_path)
        self._read_only = read_only
        if read_only:
            # An unbuilt plane must fail here, not on the first query,
            # so the namespace resolver can classify it as "unbuilt".
            if not self._db_path.is_file():
                raise FileNotFoundError(f"read-only wiki store has no plane at {self._db_path}")
        else:
            try:
                self._db_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                # Tolerate a permission failure only when an existing
                # plane can plausibly be served read-only; otherwise
                # nothing can work and the caller should see the real
                # error now.
                if (
                    exc.errno
                    not in (
                        errno.EROFS,
                        errno.EACCES,
                        errno.EPERM,
                    )
                    or not self._db_path.is_file()
                ):
                    raise
        self._wiki_name = wiki_name
        self._warned_read_only = False
        self._init_lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    @property
    def db_path(self) -> Path:
        """Path of the underlying SQLite file."""
        return self._db_path

    @property
    def read_only(self) -> bool:
        """Whether this store was opened strictly for reading."""
        return self._read_only

    def _assert_writable(self) -> None:
        """Refuse a write on a store opened with ``read_only=True``.

        Raises:
            PermissionError: When the store is read-only.
        """
        if self._read_only:
            raise PermissionError(f"read-only wiki store: {self._db_path}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        """Open the database, ensure schema, and yield a connection.

        The caller is responsible for committing before exiting.

        The schema is replayed only when a cheap presence probe shows it
        missing (new or externally replaced database) — the probe also
        forces SQLite's lazy file open, and on an unwritable WAL plane
        it is what raises the read-only error (the reader cannot create
        the ``-shm`` sidecar). In that case the store degrades to the
        read-only ladder in :meth:`_connect_readonly` instead of dying.
        The fallback is attempted only for exact result codes that
        positively identify a read-only environment (see
        ``_READONLY_ENV_CODES``) raised before the connection was
        handed to the caller — transient locks, disk-full and caller
        statement errors propagate untouched. The write path is retried
        on every connection (degradation is never sticky), so a
        misclassified error cannot permanently disable writes and an
        environment that becomes writable again heals automatically.
        """
        if self._read_only:
            # Opt-in read-only (FEAT-450): never probe/replay/migrate —
            # the write-first path is what creates sidecars and mutates
            # a foreign plane. On a quiescent plane, ``immutable=1`` is
            # tried BEFORE the ``mode=ro`` ladder: a WAL reader in
            # ``mode=ro`` creates the ``-shm``/``-wal`` sidecars when
            # the directory is writable, and a foreign namespace must
            # leave no trace at all. A live sidecar means a writer is
            # around, so the ladder (which locks and sees their commits)
            # is used instead.
            if self._sidecars_quiescent():
                yielded = False
                try:
                    async with self._connect_immutable() as conn:
                        # Re-check AFTER the open: ``immutable=1`` promises
                        # SQLite the file cannot change, so a writer that
                        # started between the probe and the open would make
                        # this connection read torn data. Narrow that window
                        # by confirming the plane is still quiescent before
                        # handing the connection out; if it is not, fall
                        # through to the locking ``mode=ro`` ladder, which
                        # sees the writer's commits correctly.
                        if self._sidecars_quiescent():
                            yielded = True
                            yield conn
                            return
                except sqlite3.OperationalError:
                    if yielded:
                        raise
            async with self._connect_readonly() as conn:
                yield conn
            return
        placeholders = ", ".join("?" * len(_SCHEMA_TABLES))
        yielded = False
        try:
            async with aiosqlite.connect(str(self._db_path)) as conn:
                conn.row_factory = aiosqlite.Row
                cur = await conn.execute(
                    "SELECT count(*) FROM sqlite_master" f" WHERE type = 'table' AND name IN ({placeholders})",
                    sorted(_SCHEMA_TABLES),
                )
                if (await cur.fetchone())[0] < len(_SCHEMA_TABLES):
                    # Serialize first-time init across concurrent tasks
                    # of this instance; the DDL is idempotent, so the
                    # lock only avoids spurious cross-task lock errors.
                    async with self._init_lock:
                        await conn.executescript(WIKI_SCHEMA_SQL)
                        await conn.execute(
                            "INSERT OR IGNORE INTO meta (key, value)" " VALUES (?, ?)",
                            ("schema_version", SCHEMA_VERSION),
                        )
                        if self._wiki_name:
                            await conn.execute(
                                "INSERT OR IGNORE INTO meta (key, value)" " VALUES (?, ?)",
                                ("wiki_name", self._wiki_name),
                            )
                        await conn.commit()
                # Column migrations run on every connection — the probe
                # only proves the table exists, not that post-schema
                # columns (origin/asserted_by) are present.
                await self._migrate(conn)
                yielded = True
                yield conn
            return
        except sqlite3.OperationalError as exc:
            if yielded or not self._db_path.is_file() or not self._is_readonly_env_error(exc):
                raise
        async with self._connect_readonly() as conn:
            yield conn

    def _sidecars_quiescent(self) -> bool:
        """Whether the plane has no live ``-wal`` / ``-journal`` sidecar.

        Mirrors the safety check the read-only ladder applies before its
        ``immutable=1`` rung: a non-empty sidecar means committed data
        an immutable connection would not see. Fails closed — an
        un-inspectable sidecar counts as live.

        Returns:
            ``True`` when an immutable open is safe.
        """
        for suffix in ("-wal", "-journal"):
            sidecar = self._db_path.with_name(self._db_path.name + suffix)
            try:
                if sidecar.stat().st_size > 0:
                    return False
            except FileNotFoundError:
                continue
            except OSError:
                return False
        return True

    @asynccontextmanager
    async def _connect_immutable(self) -> AsyncIterator[aiosqlite.Connection]:
        """Open the plane with ``immutable=1`` — creates no sidecars.

        Only safe on a quiescent plane (see :meth:`_sidecars_quiescent`);
        callers are responsible for that check.

        Yields:
            A read-only connection.
        """
        base = f"file:{quote(str(self._db_path))}"
        async with aiosqlite.connect(f"{base}?mode=ro&immutable=1", uri=True) as conn:
            conn.row_factory = aiosqlite.Row
            # The file open is lazy — force it before yielding.
            await conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
            self._log_read_only_once()
            yield conn

    @asynccontextmanager
    async def _connect_readonly(self) -> AsyncIterator[aiosqlite.Connection]:
        """Read-only connection ladder for unwritable environments.

        Plain ``mode=ro`` is tried first: when readable ``-wal``/``-shm``
        sidecars exist (a live writer elsewhere keeps them up to date),
        SQLite serves consistent reads WITH locking and change
        detection, so concurrent writers are handled correctly. A
        quiescent plane (cleanly checkpointed, no sidecars) cannot be
        opened that way — the WAL reader would have to create the
        ``-shm`` file — so it falls back to ``immutable=1``, verified by
        a probe query. A live non-empty ``-wal`` without a working
        ``mode=ro`` path refuses the immutable fallback rather than
        silently serving reads that miss committed data.

        The ladder re-runs on every connection and degradation is never
        sticky, so a writer appearing later upgrades subsequent reads to
        the locking ``mode=ro`` path and a misclassified error can never
        permanently disable writes; only a connection already open in
        immutable mode has a staleness window. A hot rollback journal is
        refused the same way a live WAL is, and if either sidecar cannot
        be inspected (any error other than "it does not exist"), the
        immutable fallback is refused — fail closed rather than risk
        serving incomplete or un-rolled-back data.
        """
        base = f"file:{quote(str(self._db_path))}"
        yielded = False
        try:
            async with aiosqlite.connect(f"{base}?mode=ro", uri=True) as conn:
                conn.row_factory = aiosqlite.Row
                # The file open is lazy — force it before yielding.
                await conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
                self._log_read_only_once()
                yielded = True
                yield conn
            return
        except sqlite3.OperationalError as ro_exc:
            if yielded:
                raise
            plain_ro_error = ro_exc
        for suffix in ("-wal", "-journal"):
            sidecar = self._db_path.with_name(self._db_path.name + suffix)
            try:
                sidecar_live = sidecar.stat().st_size > 0
            except FileNotFoundError:
                sidecar_live = False  # no sidecar — nothing pending
            except OSError as os_exc:
                # Can't even inspect the sidecar: fail closed, inside
                # this path's sqlite3.OperationalError contract.
                raise sqlite3.OperationalError(
                    f"wiki database {self._db_path} is not writable and"
                    f" its {suffix} sidecar cannot be inspected —"
                    " refusing an immutable connection"
                ) from os_exc
            if sidecar_live:
                raise sqlite3.OperationalError(
                    f"wiki database {self._db_path} is not writable and"
                    f" its live {suffix} sidecar cannot be applied —"
                    " refusing an immutable connection that would serve"
                    " incomplete or un-rolled-back data"
                ) from plain_ro_error
        yielded = False
        try:
            async with aiosqlite.connect(f"{base}?mode=ro&immutable=1", uri=True) as conn:
                conn.row_factory = aiosqlite.Row
                await conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
                self._log_read_only_once()
                yielded = True
                yield conn
        except sqlite3.OperationalError as imm_exc:
            if yielded:
                raise
            # Chain the mode=ro failure so neither rung's error is lost.
            raise imm_exc from plain_ro_error

    def _log_read_only_once(self) -> None:
        """Warn (once per store) that reads are being served degraded.

        Silent when the store was opened with ``read_only=True``: that
        is the caller's explicit intent (a foreign namespace), not a
        degradation worth warning about.
        """
        if self._read_only:
            return
        if not self._warned_read_only:
            self._warned_read_only = True
            self.logger.warning(
                "Wiki database %s is not writable; serving read-only" " connections.",
                self._db_path,
            )

    async def _migrate(self, conn: aiosqlite.Connection) -> None:
        """Add columns that post-date the original schema when missing.

        ``CREATE TABLE IF NOT EXISTS`` never alters existing tables, so
        wiki databases created before the origin/asserted_by columns
        shipped are upgraded here via idempotent ``ALTER TABLE``.
        """
        for table, columns in _MIGRATION_COLUMNS.items():
            async with conn.execute(f"PRAGMA table_info({table})") as cur:
                existing = {row["name"] for row in await cur.fetchall()}
            for name, col_type in columns:
                if name not in existing:
                    await conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}")

        # FEAT-498: bump a pre-existing plane's recorded schema version once
        # the symbols/symbols_fts tables and content_hash column above are
        # in place (INSERT OR IGNORE in _connect() never touches an
        # existing row, so a v1 plane would otherwise keep reporting "1").
        await conn.execute(
            "UPDATE meta SET value = ? WHERE key = 'schema_version' AND value != ?",
            (SCHEMA_VERSION, SCHEMA_VERSION),
        )
        await conn.commit()

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
            "  source_id, token_count, created_at, updated_at,"
            "  origin, asserted_by, content_hash)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(concept_id) DO UPDATE SET"
            "  node_id=excluded.node_id, title=excluded.title,"
            "  category=excluded.category, summary=excluded.summary,"
            "  body=excluded.body, source_id=excluded.source_id,"
            "  token_count=excluded.token_count, updated_at=excluded.updated_at,"
            "  origin=excluded.origin, asserted_by=excluded.asserted_by,"
            "  content_hash=excluded.content_hash",
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
                    p.updated_at or now,
                    p.origin,
                    p.asserted_by,
                    p.content_hash,
                )
                for p in pages
            ],
        )
        await conn.executemany(
            "DELETE FROM pages_fts WHERE concept_id = ?",
            [(p.concept_id,) for p in pages],
        )
        await conn.executemany(
            "INSERT INTO pages_fts (concept_id, title, summary, body)" " VALUES (?, ?, ?, ?)",
            [(p.concept_id, p.title, p.summary, p.body) for p in pages],
        )

    async def _insert_edges_conn(
        self,
        conn: aiosqlite.Connection,
        edges: list[tuple],
    ) -> None:
        """Insert edge tuples on an open connection.

        Accepts both ``(src, dst, rel)`` (provenance defaults to
        ``'extracted'``) and ``(src, dst, rel, provenance)`` tuples —
        the 4th element marks agent/human-authored edges ``'asserted'``.
        """
        rows = [(e[0], e[1], e[2], e[3] if len(e) > 3 else "extracted") for e in edges]
        await conn.executemany(
            "INSERT OR REPLACE INTO edges (src, dst, rel, provenance)" " VALUES (?, ?, ?, ?)",
            rows,
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

        Raises:
            PermissionError: When the store is read-only.
        """
        self._assert_writable()
        if not pages:
            return 0
        async with self._connect() as conn:
            await self._upsert_pages_conn(conn, pages)
            await conn.commit()
        return len(pages)

    async def add_edges(self, edges: list[tuple]) -> int:
        """Insert typed edges.

        Args:
            edges: ``(src, dst, rel)`` or ``(src, dst, rel, provenance)``
                tuples; ``rel`` is an open string. A missing provenance
                defaults to ``'extracted'``.

        Returns:
            Number of edges written.

        Raises:
            PermissionError: When the store is read-only.
        """
        self._assert_writable()
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

        Incoming edges from OTHER sources (e.g. a directory ``contains``
        edge, or a ``references`` edge from an importing file) are
        preserved when the replacement re-inserts the same stable
        ``concept_id`` — the slice owns its outgoing edges, but links
        pointing INTO it stay valid across a re-ingest.

        Args:
            source_id: Source whose derived pages are being replaced.
            pages: Replacement page records.
            edges: Optional replacement ``(src, dst, rel)`` edges.

        Returns:
            ``{"pages_deleted": N, "pages_written": M, "edges_written": K}``

        Raises:
            PermissionError: When the store is read-only.
        """
        self._assert_writable()
        edges = edges or []
        new_ids = {page.concept_id for page in pages}
        async with self._connect() as conn:
            async with conn.execute(
                "SELECT concept_id FROM pages WHERE source_id = ?",
                (source_id,),
            ) as cur:
                old_ids = [row["concept_id"] for row in await cur.fetchall()]

            preserved: list[tuple[str, str, str]] = []
            if old_ids:
                # Snapshot incoming edges whose target survives the
                # replacement (same concept_id re-inserted below).
                old_set = set(old_ids)
                placeholders = ",".join("?" for _ in old_ids)
                async with conn.execute(
                    "SELECT src, dst, rel FROM edges" f" WHERE dst IN ({placeholders})",
                    old_ids,
                ) as cur:
                    preserved = [
                        (row["src"], row["dst"], row["rel"])
                        for row in await cur.fetchall()
                        if row["src"] not in old_set and row["dst"] in new_ids
                    ]
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
                await conn.execute("DELETE FROM pages WHERE source_id = ?", (source_id,))

            # FEAT-498: symbols/symbols_fts rows for this source are
            # cleared in the same transaction as the file/sym: pages
            # above, so a re-scan never accumulates stale symbol rows.
            async with conn.execute("SELECT concept_id FROM symbols WHERE source_id = ?", (source_id,)) as cur:
                old_symbol_ids = [row["concept_id"] for row in await cur.fetchall()]
            if old_symbol_ids:
                await conn.executemany(
                    "DELETE FROM symbols_fts WHERE concept_id = ?",
                    [(cid,) for cid in old_symbol_ids],
                )
            await conn.execute("DELETE FROM symbols WHERE source_id = ?", (source_id,))

            await self._upsert_pages_conn(conn, pages)
            await self._insert_edges_conn(conn, edges)
            if preserved:
                await self._insert_edges_conn(conn, preserved)
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

        Raises:
            PermissionError: When the store is read-only.
        """
        self._assert_writable()
        async with self._connect() as conn:
            cur = await conn.execute("DELETE FROM pages WHERE concept_id = ?", (concept_id,))
            deleted = cur.rowcount > 0
            await conn.execute("DELETE FROM pages_fts WHERE concept_id = ?", (concept_id,))
            await conn.execute("DELETE FROM embeddings WHERE concept_id = ?", (concept_id,))
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

        Raises:
            PermissionError: When the store is read-only.
        """
        self._assert_writable()
        async with self._connect() as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO embeddings (concept_id, vector, model)" " VALUES (?, ?, ?)",
                (concept_id, _pack_vector(vector), model),
            )
            await conn.commit()

    async def upsert_symbols(
        self,
        symbols: list[SymbolRecord],
        source_id: Optional[str] = None,
    ) -> int:
        """Insert or update rows in the native ``symbols`` table + FTS.

        Args:
            symbols: Symbol records to persist.
            source_id: Originating source id, stamped on every row.

        Returns:
            Number of symbols written.

        Raises:
            PermissionError: When the store is read-only.
        """
        self._assert_writable()
        if not symbols:
            return 0
        from parrot.knowledge.wiki.symbols import sym_concept_id

        rows = []
        for sym in symbols:
            concept_id = sym_concept_id(sym.rel_path, sym.qualname)
            rows.append(
                (
                    concept_id,
                    sym.rel_path,
                    sym.language,
                    sym.kind.value,
                    sym.name,
                    sym.qualname,
                    sym.parent,
                    sym.signature,
                    sym.doc,
                    int(sym.exported),
                    int(sym.is_async),
                    sym.depth,
                    sym.start_line,
                    sym.end_line,
                    sym.start_byte,
                    sym.end_byte,
                    sym.node_kind,
                    sym.content_hash,
                    source_id,
                )
            )
        async with self._connect() as conn:
            await conn.executemany(
                "INSERT INTO symbols"
                " (concept_id, rel_path, language, kind, name, qualname, parent,"
                "  signature, doc, exported, is_async, depth, start_line, end_line,"
                "  start_byte, end_byte, node_kind, content_hash, source_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(concept_id) DO UPDATE SET"
                "  rel_path=excluded.rel_path, language=excluded.language,"
                "  kind=excluded.kind, name=excluded.name, qualname=excluded.qualname,"
                "  parent=excluded.parent, signature=excluded.signature, doc=excluded.doc,"
                "  exported=excluded.exported, is_async=excluded.is_async, depth=excluded.depth,"
                "  start_line=excluded.start_line, end_line=excluded.end_line,"
                "  start_byte=excluded.start_byte, end_byte=excluded.end_byte,"
                "  node_kind=excluded.node_kind, content_hash=excluded.content_hash,"
                "  source_id=excluded.source_id",
                rows,
            )
            await conn.executemany(
                "DELETE FROM symbols_fts WHERE concept_id = ?",
                [(r[0],) for r in rows],
            )
            await conn.executemany(
                "INSERT INTO symbols_fts (concept_id, name, qualname, doc, signature)" " VALUES (?, ?, ?, ?, ?)",
                [(r[0], r[4], r[5], r[8], r[7]) for r in rows],
            )
            await conn.commit()
        return len(rows)

    async def symbols_for(self, rel_path: str) -> list[SymbolRecord]:
        """List every symbol row extracted from one file.

        Args:
            rel_path: POSIX path relative to the repository root.

        Returns:
            Symbol records for ``rel_path``, ordered by ``start_line``.
        """
        async with self._connect() as conn:
            async with conn.execute(
                "SELECT * FROM symbols WHERE rel_path = ? ORDER BY start_line",
                (rel_path,),
            ) as cur:
                return [_row_to_symbol_record(row) for row in await cur.fetchall()]

    async def find_symbols(
        self,
        name: Optional[str] = None,
        qualname_prefix: Optional[str] = None,
        kind: Optional[str] = None,
        language: Optional[str] = None,
        path_prefix: Optional[str] = None,
        limit: int = 50,
    ) -> list[SymbolRecord]:
        """Find symbols in the native ``symbols`` table by filter.

        Args:
            name: Exact local-name filter.
            qualname_prefix: Qualname must start with this prefix.
            kind: Exact :class:`SymbolKind` value filter.
            language: Exact scanner-name filter.
            path_prefix: ``rel_path`` must start with this prefix.
            limit: Maximum results.

        Returns:
            Matching symbol records — exact ``name`` matches first (when
            ``name`` is not itself a filter), then by ``rel_path``,
            ``qualname``.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if name is not None:
            clauses.append("name = ?")
            params.append(name)
        if qualname_prefix is not None:
            clauses.append("qualname LIKE ? ESCAPE '\\'")
            params.append(_like_prefix(qualname_prefix))
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if language is not None:
            clauses.append("language = ?")
            params.append(language)
        if path_prefix is not None:
            clauses.append("rel_path LIKE ? ESCAPE '\\'")
            params.append(_like_prefix(path_prefix))
        sql = "SELECT * FROM symbols"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY rel_path, qualname LIMIT ?"
        params = [*params, limit]
        async with self._connect() as conn:
            async with conn.execute(sql, params) as cur:
                return [_row_to_symbol_record(row) for row in await cur.fetchall()]

    async def search_symbols_fts(self, query: str, limit: int = 20) -> list[SymbolRecord]:
        """BM25 lexical search over ``symbols_fts`` (name/qualname/doc/signature).

        Args:
            query: Free-form query text.
            limit: Maximum results.

        Returns:
            Symbol records ranked by BM25 score (best match first).
        """
        match_expr = _fts_query(query)
        if not match_expr:
            return []
        async with self._connect() as conn:
            async with conn.execute(
                "SELECT s.* FROM symbols_fts JOIN symbols s ON s.concept_id = symbols_fts.concept_id"
                " WHERE symbols_fts MATCH ? ORDER BY bm25(symbols_fts) LIMIT ?",
                (match_expr, limit),
            ) as cur:
                return [_row_to_symbol_record(row) for row in await cur.fetchall()]

    async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]:
        """Batch look-up of ``pages.content_hash`` for the given ids.

        Args:
            concept_ids: Page ids to look up (``file:`` or ``sym:``).

        Returns:
            ``{concept_id: content_hash_or_None}`` for every requested id
            (``None`` both when the row is absent and when its hash is
            unset).
        """
        if not concept_ids:
            return {}
        out: dict[str, Optional[str]] = {cid: None for cid in concept_ids}
        placeholders = ",".join("?" for _ in concept_ids)
        async with self._connect() as conn:
            async with conn.execute(
                f"SELECT concept_id, content_hash FROM pages WHERE concept_id IN ({placeholders})",
                concept_ids,
            ) as cur:
                for row in await cur.fetchall():
                    out[row["concept_id"]] = row["content_hash"]
        return out

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]:
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
            " token_count, created_at, updated_at, origin, asserted_by, content_hash"
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
        origin: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """List page stubs (no bodies), optionally filtered.

        Args:
            category: Exact category pre-filter (open string).
            limit: Maximum rows returned.
            origin: Optional origin filter, e.g. ``["memory", "authored"]``
                to list only agent-saved knowledge.

        Returns:
            List of stub dicts ordered by ``updated_at`` (newest first).
        """
        sql = (
            "SELECT concept_id, node_id, title, category, summary,"
            " source_id, token_count, updated_at, origin, asserted_by, content_hash"
            " FROM pages"
        )
        clauses: list[str] = []
        params: tuple[Any, ...] = ()
        if category is not None:
            clauses.append("category = ?")
            params += (category,)
        if origin:
            clauses.append(f"origin IN ({', '.join('?' for _ in origin)})")
            params += tuple(origin)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
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
                gate applied before ranking). When ``None`` (the
                default), ``"archive"``-category pages are excluded from
                the results (FEAT-402 — supervised-ingestion archive
                pages are opt-in only, retrievable via
                ``category="archive"``).
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
        else:
            # FEAT-402: default ranking excludes the archive category.
            # `category` is an open string in this machine plane (see
            # module docstring) — no enum import needed here.
            sql += " AND (p.category IS NULL OR p.category != ?)"
            params += ("archive",)
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
                    f"SELECT e.{other} AS concept_id, e.rel, e.provenance,"  # noqa: S608
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
                " source_id, token_count, created_at, updated_at, content_hash"
                " FROM pages ORDER BY concept_id"
            ) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def dump_edges(self) -> list[dict[str, Any]]:
        """Return every edge row (bulk export path)."""
        async with self._connect() as conn:
            async with conn.execute("SELECT src, dst, rel FROM edges ORDER BY src, dst, rel") as cur:
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
                ("symbols", "SELECT COUNT(*) FROM symbols"),
                ("total_tokens", "SELECT COALESCE(SUM(token_count), 0) FROM pages"),
            ):
                async with conn.execute(sql) as cur:
                    row = await cur.fetchone()
                    out[key] = row[0] if row else 0
            async with conn.execute("SELECT category, COUNT(*) AS n FROM pages GROUP BY category") as cur:
                out["categories"] = {row["category"]: row["n"] for row in await cur.fetchall()}
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
            async with conn.execute("SELECT concept_id FROM pages WHERE body = ''") as cur:
                return [row["concept_id"] for row in await cur.fetchall()]


# Backwards-compatible alias — the SQLite plane was the only backend
# before the pluggable-store refactor.
WikiStore = SQLiteWikiStore


def create_wiki_store(
    storage_dir: str | Path,
    wiki_name: str = "",
    backend: str = "sqlite",
    **kwargs: Any,
) -> BaseWikiStore:
    """Instantiate the configured wiki retrieval-plane backend.

    Selection is explicit (``WikiConfig.storage_backend``) — there is no
    silent fallback: a broken/unavailable backend is a hard error.

    Args:
        storage_dir: Wiki storage root.  ``sqlite`` uses
            ``{storage_dir}/wiki.db``; ``memory`` uses the OKF bundle
            directory ``{storage_dir}/pages/``.  Unused by ``arangodb``
            (server-hosted — no local directory).
        wiki_name: Wiki name recorded by the backend.
        backend: ``"sqlite"`` (single-file SQLite plane), ``"memory"``
            (in-memory indexes + OKF markdown directory), or
            ``"arangodb"`` (server-hosted, shared retrieval plane).
        **kwargs: Backend-specific extras. For ``"arangodb"``:
            ``arango_params`` (connection params dict for
            ``AsyncDB("arangodb", ...)`` — see
            :func:`parrot.knowledge.wiki.project.resolve_arango_params`),
            ``database`` (target database name, defaults to
            ``wiki_{wiki_name}``), and ``text_analyzer`` (ArangoSearch
            text analyzer, defaults to ``"text_en"``).

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
    if backend == "arangodb":
        # Imported lazily — arango_store imports asyncdb, an optional
        # dependency not needed by the sqlite/memory paths.
        from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore

        return ArangoDBWikiStore(
            arango_params=kwargs.get("arango_params", {}),
            database=kwargs.get("database", ""),
            wiki_name=wiki_name,
            text_analyzer=kwargs.get("text_analyzer", "text_en"),
        )
    if backend in _EXTRA_BACKENDS:
        return _EXTRA_BACKENDS[backend](storage_dir=storage_dir, wiki_name=wiki_name, **kwargs)
    known = ", ".join(["'sqlite'", "'memory'", "'arangodb'", *(repr(b) for b in _EXTRA_BACKENDS)])
    raise ValueError(f"Unknown wiki storage backend {backend!r} — expected one of {known}")
