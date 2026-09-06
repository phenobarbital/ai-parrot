"""SQLite + FTS5 catalog store for Bookstore cards.

One ``library.db`` per library location holds the ``books`` table (the
durable card rows) plus a plain content-carrying ``books_fts`` FTS5
table for lexical "which book covers X?" queries.

Design notes (mirroring the repo's canonical SQLite planes):

- Synchronous ``sqlite3`` with short-lived per-call connections, WAL
  journal — the :class:`~parrot.knowledge.wiki.sources.SourceCollectionManager`
  pattern. The catalog is tiny (tens of rows); every call is
  sub-millisecond, so blocking inside async tool methods is negligible
  and the Click CLI stays wrapper-free. Switching to ``aiosqlite``
  (the ``graphindex/persist_sqlite.py`` pattern) later is mechanical.
- The read-only guarantee of the MCP surface is enforced at the
  toolkit layer (``BookstoreToolkit`` simply exposes no write methods),
  not by the database connection.
- Additive column migrations via ``PRAGMA table_info`` (same shape as
  ``persist_sqlite.py``).
- FTS5 upserts are DELETE + INSERT — ``INSERT OR REPLACE`` on a
  non-rowid key silently duplicates FTS rows.
- FTS5 availability is probed at first connect; when the SQLite build
  lacks it, :meth:`CatalogStore.search` falls back to ``LIKE``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from .carding import slugify
from .models import BookCard, BookCommunity, BookRelation, RelationJudgement, SYMMETRIC_RELS

logger = logging.getLogger(__name__)

_BOOKS_DDL = """
CREATE TABLE IF NOT EXISTS books (
    book_id       TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    authors       TEXT NOT NULL DEFAULT '[]',
    year          INTEGER,
    language      TEXT,
    topics        TEXT NOT NULL DEFAULT '[]',
    summary       TEXT NOT NULL DEFAULT '',
    toc_digest    TEXT NOT NULL DEFAULT '',
    toc           TEXT NOT NULL DEFAULT '[]',
    tree_name     TEXT NOT NULL UNIQUE,
    source_path   TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    source_format TEXT NOT NULL,
    page_count    INTEGER,
    chapter_count INTEGER NOT NULL DEFAULT 0,
    added_at      TEXT NOT NULL,
    card_origin   TEXT NOT NULL DEFAULT 'llm'
)
"""

_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS books_fts USING fts5(
    book_id UNINDEXED,
    title,
    authors_text,
    topics_text,
    summary,
    toc_digest,
    genre,
    traditions_text,
    tokenize = 'unicode61 remove_diacritics 2'
)
"""

#: Expected ``books_fts`` column order (as ``PRAGMA table_info`` reports
#: it), used to detect a pre-FEAT-533 table (6 columns) that needs a
#: rebuild — FTS5 virtual tables cannot ``ALTER``.
_FTS_COLUMNS = (
    "book_id",
    "title",
    "authors_text",
    "topics_text",
    "summary",
    "toc_digest",
    "genre",
    "traditions_text",
)

#: Additive migrations: column name -> ALTER clause. Extend (never edit
#: existing entries) when the schema grows — same discipline as
#: ``graphindex/persist_sqlite.py``.
_ADDED_COLUMNS: list[tuple[str, str]] = [
    ("genre", "genre TEXT NOT NULL DEFAULT 'other'"),
    ("traditions", "traditions TEXT NOT NULL DEFAULT '[]'"),
    ("period", "period TEXT"),
    ("community_id", "community_id TEXT"),
    ("community_label", "community_label TEXT"),
]

#: The book graph (FEAT-533 spec §2). One row per typed edge; symmetric
#: relations are canonicalised ``src < dst`` on write (see
#: ``CatalogStore._canonical_pair``) so a pair never has two rows.
_RELATIONS_DDL = """
CREATE TABLE IF NOT EXISTS book_relations (
    src_book_id TEXT NOT NULL,
    dst_book_id TEXT NOT NULL,
    rel         TEXT NOT NULL,
    weight      REAL NOT NULL DEFAULT 1.0,
    origin      TEXT NOT NULL,
    confidence  REAL,
    rationale   TEXT NOT NULL DEFAULT '',
    computed_at TEXT NOT NULL,
    PRIMARY KEY (src_book_id, dst_book_id, rel),
    CHECK (src_book_id <> dst_book_id)
)
"""

_RELATIONS_INDEX_DDL = "CREATE INDEX IF NOT EXISTS idx_book_relations_dst " "ON book_relations(dst_book_id)"

#: Log of every LLM-judged candidate pair (including ``rel="none"`` and
#: below-floor confidences) so ``bookstore relate`` never re-asks a
#: pair without ``--force``.
_JUDGEMENTS_DDL = """
CREATE TABLE IF NOT EXISTS relation_judgements (
    src_book_id TEXT NOT NULL,
    dst_book_id TEXT NOT NULL,
    judged_at   TEXT NOT NULL,
    model       TEXT NOT NULL DEFAULT '',
    rel         TEXT NOT NULL,
    confidence  REAL NOT NULL,
    PRIMARY KEY (src_book_id, dst_book_id)
)
"""

#: One persisted community partition. Written once per merged graph —
#: to the project DB when a project scope exists, else global
#: (``Bookstore`` decides; ``CatalogStore`` stays scope-agnostic).
_COMMUNITIES_DDL = """
CREATE TABLE IF NOT EXISTS communities (
    community_id     TEXT PRIMARY KEY,
    label             TEXT NOT NULL,
    label_origin      TEXT NOT NULL,
    description       TEXT NOT NULL DEFAULT '',
    algorithm         TEXT NOT NULL,
    size              INTEGER NOT NULL,
    cohesion          REAL NOT NULL,
    centroid_book_id  TEXT NOT NULL,
    members           TEXT NOT NULL,
    inter_relations   TEXT NOT NULL DEFAULT '[]',
    computed_at       TEXT NOT NULL
)
"""

_FTS_TERM_RE = re.compile(r"[^\W_]+", re.UNICODE)

# Columns stored as JSON text in the books table.
_JSON_COLUMNS = ("authors", "topics", "toc", "traditions")


class CatalogStore:
    """Card catalog over one ``library.db`` file.

    Args:
        db_path: Location of the SQLite database. Parent directories
            and the schema are created on construction.
    """

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.logger = logger
        self._fts_available: Optional[bool] = None
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            self._ensure_schema(conn)

    # ------------------------------------------------------------------
    # Connection / schema
    # ------------------------------------------------------------------
    @contextlib.contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Short-lived connection that is always closed.

        ``sqlite3.Connection``'s own context manager only manages the
        transaction — it never calls ``close()`` — so a long-running
        MCP process would leak WAL file handles without this wrapper.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(_BOOKS_DDL)
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(books)").fetchall()}
        for column, clause in _ADDED_COLUMNS:
            if column not in existing:
                conn.execute(f"ALTER TABLE books ADD COLUMN {clause}")
        conn.execute(_RELATIONS_DDL)
        conn.execute(_RELATIONS_INDEX_DDL)
        conn.execute(_JUDGEMENTS_DDL)
        conn.execute(_COMMUNITIES_DDL)
        try:
            self._ensure_fts_schema(conn)
            self._fts_available = True
        except sqlite3.OperationalError as exc:
            self._fts_available = False
            logger.warning(
                "FTS5 unavailable for %s (%s) — catalog search degrades to LIKE",
                self.db_path,
                exc,
            )
        conn.commit()

    def _ensure_fts_schema(self, conn: sqlite3.Connection) -> None:
        """Create ``books_fts``, rebuilding it once if columns drifted.

        FTS5 virtual tables cannot ``ALTER``. A pre-FEAT-533
        ``books_fts`` (6 columns, no ``genre``/``traditions_text``) is
        detected via ``PRAGMA table_info`` and replaced: dropped,
        recreated from :data:`_FTS_DDL`, and repopulated from ``books``.
        Once the column set matches :data:`_FTS_COLUMNS`, this is a
        cheap no-op probe on every subsequent call (this method runs on
        every :meth:`upsert`/:meth:`remove` via ``_ensure_schema``, not
        just at ``__init__``) — the physical table is never touched
        again, so its ``sqlite_master`` identity is stable.
        """
        existing_cols = tuple(row["name"] for row in conn.execute("PRAGMA table_info(books_fts)").fetchall())
        needs_rebuild = bool(existing_cols) and existing_cols != _FTS_COLUMNS
        if needs_rebuild:
            conn.execute("DROP TABLE IF EXISTS books_fts")
        conn.execute(_FTS_DDL)
        if needs_rebuild:
            self._repopulate_fts(conn)

    @staticmethod
    def _repopulate_fts(conn: sqlite3.Connection) -> None:
        """Rebuild ``books_fts`` rows from the current ``books`` table."""
        rows = conn.execute(
            "SELECT book_id, title, authors, topics, summary, toc_digest, " "genre, traditions FROM books"
        ).fetchall()
        for row in rows:
            authors = json.loads(row["authors"] or "[]")
            topics = json.loads(row["topics"] or "[]")
            traditions = json.loads(row["traditions"] or "[]")
            conn.execute(
                "INSERT INTO books_fts "
                "(book_id, title, authors_text, topics_text, summary, "
                "toc_digest, genre, traditions_text) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["book_id"],
                    row["title"],
                    ", ".join(authors),
                    ", ".join(topics),
                    row["summary"],
                    row["toc_digest"],
                    row["genre"],
                    ", ".join(traditions),
                ),
            )

    @property
    def supports_fts(self) -> bool:
        """Whether this database has a usable ``books_fts`` table."""
        if self._fts_available is None:
            try:
                with self._connection() as conn:
                    row = conn.execute(
                        "SELECT name FROM sqlite_master " "WHERE type='table' AND name='books_fts'"
                    ).fetchone()
                self._fts_available = row is not None
            except sqlite3.Error:
                self._fts_available = False
        return bool(self._fts_available)

    # ------------------------------------------------------------------
    # Row mapping
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_card(row: sqlite3.Row) -> BookCard:
        data = dict(row)
        for column in _JSON_COLUMNS:
            raw = data.get(column) or "[]"
            try:
                data[column] = json.loads(raw)
            except (TypeError, ValueError):
                data[column] = []
        data.pop("scope", None)
        return BookCard.model_validate(data)

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def upsert(self, card: BookCard) -> None:
        """Insert or replace one card (and its FTS row) atomically.

        Args:
            card: The card to persist. ``card.scope`` is not stored —
                scope is implicit per database file.
        """
        payload = card.model_dump(mode="json")
        payload.pop("scope", None)
        traditions = self._normalise_traditions(payload.get("traditions") or [])
        payload["traditions"] = traditions
        for column in _JSON_COLUMNS:
            payload[column] = json.dumps(payload.get(column) or [])
        columns = ", ".join(payload)
        placeholders = ", ".join(f":{key}" for key in payload)
        with self._connection() as conn:
            self._ensure_schema(conn)
            conn.execute(
                f"INSERT OR REPLACE INTO books ({columns}) VALUES ({placeholders})",
                payload,
            )
            if self._fts_available:
                conn.execute("DELETE FROM books_fts WHERE book_id = ?", (card.book_id,))
                conn.execute(
                    "INSERT INTO books_fts "
                    "(book_id, title, authors_text, topics_text, summary, "
                    "toc_digest, genre, traditions_text) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        card.book_id,
                        card.title,
                        ", ".join(card.authors),
                        ", ".join(card.topics),
                        card.summary,
                        card.toc_digest,
                        card.genre,
                        ", ".join(traditions),
                    ),
                )
            conn.commit()

    @staticmethod
    def _normalise_traditions(traditions: list[str]) -> list[str]:
        """Slug-normalise traditions, deduping while keeping first-seen order.

        "Estoicismo" and "estoicismo" collide to the same slug so
        lookups/search are consistent regardless of the LLM's casing.
        """
        seen: set[str] = set()
        normalised: list[str] = []
        for tradition in traditions:
            slug = slugify(tradition)
            if slug not in seen:
                seen.add(slug)
                normalised.append(slug)
        return normalised

    def remove(self, book_id: str) -> bool:
        """Delete a card (books row + FTS row).

        Returns:
            ``True`` when a row was actually deleted.
        """
        with self._connection() as conn:
            self._ensure_schema(conn)
            cursor = conn.execute("DELETE FROM books WHERE book_id = ?", (book_id,))
            if self._fts_available:
                conn.execute("DELETE FROM books_fts WHERE book_id = ?", (book_id,))
            conn.commit()
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get(self, book_id: str) -> Optional[BookCard]:
        """Load one card by id, or ``None``."""
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM books WHERE book_id = ?", (book_id,)).fetchone()
        return self._row_to_card(row) if row else None

    def find_by_sha(self, sha256: str) -> Optional[BookCard]:
        """Find the card for an already-ingested source file, if any."""
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM books WHERE source_sha256 = ?", (sha256,)).fetchone()
        return self._row_to_card(row) if row else None

    def list_cards(self) -> list[BookCard]:
        """All cards, ordered by title."""
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM books ORDER BY title COLLATE NOCASE").fetchall()
        return [self._row_to_card(row) for row in rows]

    def taken_slugs(self) -> set[str]:
        """Book ids already used in this catalog."""
        with self._connection() as conn:
            rows = conn.execute("SELECT book_id FROM books").fetchall()
        return {row["book_id"] for row in rows}

    def search(self, query: str, top_k: int = 8) -> list[tuple[BookCard, float]]:
        """Lexical card search — "which book covers X?".

        Uses BM25 over ``books_fts`` when FTS5 is available, otherwise a
        ``LIKE`` scan over title/topics/summary/toc_digest. Scores are
        "higher is better" in both modes (BM25 rank is negated).

        Args:
            query: Free-form topic/keyword query.
            top_k: Maximum cards returned.

        Returns:
            ``(card, score)`` tuples, best first.
        """
        query = (query or "").strip()
        if not query:
            return []
        if self.supports_fts:
            match = self._fts_query(query)
            if not match:
                return []
            sql = (
                "SELECT b.*, bm25(books_fts) AS rank FROM books_fts "
                "JOIN books b ON b.book_id = books_fts.book_id "
                "WHERE books_fts MATCH ? ORDER BY rank LIMIT ?"
            )
            with self._connection() as conn:
                rows = conn.execute(sql, (match, top_k)).fetchall()
            return [(self._row_to_card(row), -float(row["rank"])) for row in rows]
        return self._like_search(query, top_k)

    @staticmethod
    def _fts_query(query: str) -> str:
        """Sanitize a free-form query into a safe FTS5 MATCH expression.

        Terms are extracted, double-quoted, and OR-joined so user
        punctuation (colons, quotes, parentheses…) can never produce an
        FTS5 syntax error.
        """
        terms = _FTS_TERM_RE.findall(query)
        return " OR ".join(f'"{term}"' for term in terms)

    def _like_search(self, query: str, top_k: int) -> list[tuple[BookCard, float]]:
        terms = [t.lower() for t in _FTS_TERM_RE.findall(query)]
        if not terms:
            return []
        scored: list[tuple[BookCard, float]] = []
        for card in self.list_cards():
            haystack = " ".join(
                (
                    card.title,
                    " ".join(card.authors),
                    " ".join(card.topics),
                    card.summary,
                    card.toc_digest,
                )
            ).lower()
            hits = sum(1 for term in terms if term in haystack)
            if hits:
                scored.append((card, float(hits)))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]

    # ------------------------------------------------------------------
    # Relations
    # ------------------------------------------------------------------
    @staticmethod
    def _canonical_pair(relation: BookRelation) -> tuple[str, str]:
        """Canonical ``(src, dst)`` for storage — sorted for symmetric rels."""
        if relation.rel in SYMMETRIC_RELS:
            pair = (relation.src_book_id, relation.dst_book_id)
            return pair if pair[0] < pair[1] else (pair[1], pair[0])
        return relation.src_book_id, relation.dst_book_id

    @staticmethod
    def _row_to_relation(row: sqlite3.Row) -> BookRelation:
        return BookRelation(
            src_book_id=row["src_book_id"],
            dst_book_id=row["dst_book_id"],
            rel=row["rel"],
            weight=row["weight"],
            origin=row["origin"],
            confidence=row["confidence"],
            rationale=row["rationale"],
            computed_at=row["computed_at"],
        )

    def upsert_relations(self, relations: list[BookRelation]) -> None:
        """Insert or replace edges, canonicalising symmetric pairs.

        Args:
            relations: Edges to persist. Existing rows sharing the
                canonical ``(src, dst, rel)`` key are replaced.
        """
        with self._connection() as conn:
            self._ensure_schema(conn)
            for relation in relations:
                src, dst = self._canonical_pair(relation)
                conn.execute(
                    "INSERT OR REPLACE INTO book_relations "
                    "(src_book_id, dst_book_id, rel, weight, origin, "
                    "confidence, rationale, computed_at) "
                    "VALUES (:src, :dst, :rel, :weight, :origin, "
                    ":confidence, :rationale, :computed_at)",
                    {
                        "src": src,
                        "dst": dst,
                        "rel": relation.rel,
                        "weight": relation.weight,
                        "origin": relation.origin,
                        "confidence": relation.confidence,
                        "rationale": relation.rationale,
                        "computed_at": relation.computed_at,
                    },
                )
            conn.commit()

    def delete_relations(self, book_id: Optional[str] = None, origin: Optional[str] = None) -> int:
        """Delete edges matching ``book_id`` (as either endpoint) and/or ``origin``.

        With no filters, deletes every edge in this store.

        Returns:
            Number of rows deleted.
        """
        clauses: list[str] = []
        params: dict[str, str] = {}
        if book_id is not None:
            clauses.append("(src_book_id = :book_id OR dst_book_id = :book_id)")
            params["book_id"] = book_id
        if origin is not None:
            clauses.append("origin = :origin")
            params["origin"] = origin
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connection() as conn:
            self._ensure_schema(conn)
            cursor = conn.execute(f"DELETE FROM book_relations {where}", params)
            conn.commit()
            return cursor.rowcount

    def delete_relation_pair(self, src_book_id: str, dst_book_id: str, *, origin: Optional[str] = None) -> int:
        """Delete edge(s) between exactly this pair, in whichever direction stored.

        Added for TASK-2916 (Stage 2 orchestration): symmetric relations
        are canonicalised ``src < dst`` on write, so the caller judging
        one book against a candidate must be able to replace "its" row
        regardless of which id ended up as ``src_book_id`` in storage —
        without touching any *other* pair (spec §7: an edge judged
        earlier from the *other* book's perspective must survive). Not
        expressible with :meth:`delete_relations`, whose ``book_id``
        filter matches either endpoint against every OTHER edge too.

        Args:
            src_book_id: One endpoint.
            dst_book_id: The other endpoint.
            origin: Optional origin filter (e.g. ``"llm"``).

        Returns:
            Number of rows deleted (0 or 1 for symmetric rels; up to 2
            if both directions happen to hold distinct ``rel`` values,
            e.g. a directed ``influenced_by`` plus a symmetric one).
        """
        clauses = ["((src_book_id = :a AND dst_book_id = :b) OR " "(src_book_id = :b AND dst_book_id = :a))"]
        params: dict[str, str] = {"a": src_book_id, "b": dst_book_id}
        if origin is not None:
            clauses.append("origin = :origin")
            params["origin"] = origin
        with self._connection() as conn:
            self._ensure_schema(conn)
            cursor = conn.execute(
                f"DELETE FROM book_relations WHERE {' AND '.join(clauses)}",
                params,
            )
            conn.commit()
            return cursor.rowcount

    def list_relations(self, book_id: str, rel: Optional[str] = None) -> list[BookRelation]:
        """Edges touching ``book_id`` in either direction, optionally filtered by ``rel``."""
        clauses = ["(src_book_id = :book_id OR dst_book_id = :book_id)"]
        params: dict[str, str] = {"book_id": book_id}
        if rel is not None:
            clauses.append("rel = :rel")
            params["rel"] = rel
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM book_relations WHERE {' AND '.join(clauses)}",
                params,
            ).fetchall()
        return [self._row_to_relation(row) for row in rows]

    def _all_relations(self) -> list[BookRelation]:
        """Every edge in this store — internal helper for :func:`merged_relations`."""
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM book_relations").fetchall()
        return [self._row_to_relation(row) for row in rows]

    # ------------------------------------------------------------------
    # Judgements (LLM conceptual-relation memory)
    # ------------------------------------------------------------------
    def record_judgements(
        self,
        src: str,
        judgements: list[RelationJudgement],
        model: str = "",
    ) -> None:
        """Log every candidate judged for ``src`` in this LLM call.

        Args:
            src: Source book id the judgements were requested for.
            judgements: One entry per candidate considered, including
                ``rel="none"`` verdicts.
            model: Model identifier, for auditability.
        """
        judged_at = datetime.now(timezone.utc).isoformat()
        with self._connection() as conn:
            self._ensure_schema(conn)
            for judgement in judgements:
                conn.execute(
                    "INSERT OR REPLACE INTO relation_judgements "
                    "(src_book_id, dst_book_id, judged_at, model, rel, confidence) "
                    "VALUES (:src, :dst, :judged_at, :model, :rel, :confidence)",
                    {
                        "src": src,
                        "dst": judgement.dst_book_id,
                        "judged_at": judged_at,
                        "model": model,
                        "rel": judgement.rel,
                        "confidence": judgement.confidence,
                    },
                )
            conn.commit()

    def judged_pairs(self, src: str) -> set[str]:
        """Book ids already judged as a candidate for ``src``."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT dst_book_id FROM relation_judgements WHERE src_book_id = ?",
                (src,),
            ).fetchall()
        return {row["dst_book_id"] for row in rows}

    def delete_judgements(self, book_id: str) -> int:
        """Delete every judgement row touching ``book_id`` in either direction."""
        with self._connection() as conn:
            self._ensure_schema(conn)
            cursor = conn.execute(
                "DELETE FROM relation_judgements " "WHERE src_book_id = ? OR dst_book_id = ?",
                (book_id, book_id),
            )
            conn.commit()
            return cursor.rowcount

    # ------------------------------------------------------------------
    # Communities
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_community(row: sqlite3.Row) -> BookCommunity:
        return BookCommunity(
            community_id=row["community_id"],
            label=row["label"],
            label_origin=row["label_origin"],
            description=row["description"],
            algorithm=row["algorithm"],
            size=row["size"],
            cohesion=row["cohesion"],
            centroid_book_id=row["centroid_book_id"],
            member_book_ids=json.loads(row["members"] or "[]"),
            inter_relations=json.loads(row["inter_relations"] or "[]"),
            computed_at=row["computed_at"],
        )

    def upsert_communities(self, communities: list[BookCommunity]) -> None:
        """Replace the entire partition with ``communities``.

        The ``communities`` table holds one merged-graph partition at a
        time — every Stage 3 run rewrites it from scratch.
        """
        with self._connection() as conn:
            self._ensure_schema(conn)
            conn.execute("DELETE FROM communities")
            for community in communities:
                conn.execute(
                    "INSERT INTO communities "
                    "(community_id, label, label_origin, description, "
                    "algorithm, size, cohesion, centroid_book_id, members, "
                    "inter_relations, computed_at) "
                    "VALUES (:community_id, :label, :label_origin, "
                    ":description, :algorithm, :size, :cohesion, "
                    ":centroid_book_id, :members, :inter_relations, "
                    ":computed_at)",
                    {
                        "community_id": community.community_id,
                        "label": community.label,
                        "label_origin": community.label_origin,
                        "description": community.description,
                        "algorithm": community.algorithm,
                        "size": community.size,
                        "cohesion": community.cohesion,
                        "centroid_book_id": community.centroid_book_id,
                        "members": json.dumps(community.member_book_ids),
                        "inter_relations": json.dumps(community.inter_relations),
                        "computed_at": community.computed_at,
                    },
                )
            conn.commit()

    def list_communities(self) -> list[BookCommunity]:
        """All communities, largest first."""
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM communities ORDER BY size DESC").fetchall()
        return [self._row_to_community(row) for row in rows]

    def get_community(self, community_id: str) -> Optional[BookCommunity]:
        """Load one community by id, or ``None``."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM communities WHERE community_id = ?",
                (community_id,),
            ).fetchone()
        return self._row_to_community(row) if row else None

    def set_card_community(self, book_id: str, community_id: Optional[str], label: Optional[str]) -> None:
        """Write back a card's community assignment (Stage 3 persistence)."""
        with self._connection() as conn:
            self._ensure_schema(conn)
            conn.execute(
                "UPDATE books SET community_id = ?, community_label = ? " "WHERE book_id = ?",
                (community_id, label, book_id),
            )
            conn.commit()


def merged_cards(stores: list[tuple[str, CatalogStore]]) -> list[BookCard]:
    """Merge listings from several catalogs; earlier scopes win collisions.

    Args:
        stores: Ordered ``(scope, store)`` pairs, project first.

    Returns:
        Cards with ``scope`` stamped, deduplicated by ``book_id``.
    """
    seen: set[str] = set()
    merged: list[BookCard] = []
    for scope, store in stores:
        for card in store.list_cards():
            if card.book_id in seen:
                logger.warning(
                    "Book id %r also exists in the %s catalog — shadowed " "by an earlier scope",
                    card.book_id,
                    scope,
                )
                continue
            seen.add(card.book_id)
            merged.append(card.model_copy(update={"scope": scope}))
    return merged


def merged_search(stores: list[tuple[str, CatalogStore]], query: str, top_k: int = 8) -> list[BookCard]:
    """Search several catalogs and merge by score.

    BM25 scores from different databases are not strictly comparable;
    for a shortlist that is acceptable — ties break toward the earlier
    (project) scope. Collisions on ``book_id`` keep the earlier scope's
    card only.

    Args:
        stores: Ordered ``(scope, store)`` pairs, project first.
        query: Free-form topic query.
        top_k: Maximum merged results.
    """
    ranked: list[tuple[float, int, BookCard]] = []
    seen: set[str] = set()
    for order, (scope, store) in enumerate(stores):
        for card, score in store.search(query, top_k=top_k):
            if card.book_id in seen:
                continue
            seen.add(card.book_id)
            ranked.append((score, -order, card.model_copy(update={"scope": scope})))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [card for _, _, card in ranked[:top_k]]


def merged_relations(stores: list[tuple[str, CatalogStore]], visible_ids: set[str]) -> list[BookRelation]:
    """Union relation edges across scopes, dropping dangling endpoints.

    A global book may relate to books in several projects; each project
    only ever sees edges whose *both* endpoints it can currently see
    (spec §7 cross-scope dangling rule) — never raises on an unknown
    endpoint, just silently filters it out.

    Args:
        stores: Ordered ``(scope, store)`` pairs, project first.
        visible_ids: Book ids visible to the caller — typically
            ``{c.book_id for c in merged_cards(stores)}``.

    Returns:
        Deduplicated edges; the earlier scope wins ``(src, dst, rel)``
        collisions.
    """
    seen: set[tuple[str, str, str]] = set()
    merged: list[BookRelation] = []
    for _scope, store in stores:
        for relation in store._all_relations():
            if relation.src_book_id not in visible_ids or relation.dst_book_id not in visible_ids:
                continue
            key = (relation.src_book_id, relation.dst_book_id, relation.rel)
            if key in seen:
                continue
            seen.add(key)
            merged.append(relation)
    return merged


def merged_communities(
    stores: list[tuple[str, CatalogStore]],
) -> list[BookCommunity]:
    """Return the community partition from the first store that has one.

    Communities are computed once over the merged project+global graph
    and persisted to a single scope DB (project when present, else
    global — spec §2 step 3); this returns whichever store actually
    holds the rows, never merges partitions from multiple stores.

    Args:
        stores: Ordered ``(scope, store)`` pairs, project first.
    """
    for _scope, store in stores:
        communities = store.list_communities()
        if communities:
            return communities
    return []
