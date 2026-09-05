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
from pathlib import Path
from typing import Iterator, Optional

from .models import BookCard

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
    tokenize = 'unicode61 remove_diacritics 2'
)
"""

#: Additive migrations: column name -> ALTER clause. Extend (never edit
#: existing entries) when the schema grows — same discipline as
#: ``graphindex/persist_sqlite.py``.
_ADDED_COLUMNS: list[tuple[str, str]] = []

_FTS_TERM_RE = re.compile(r"[^\W_]+", re.UNICODE)

# Columns stored as JSON text in the books table.
_JSON_COLUMNS = ("authors", "topics", "toc")


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
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(books)").fetchall()
        }
        for column, clause in _ADDED_COLUMNS:
            if column not in existing:
                conn.execute(f"ALTER TABLE books ADD COLUMN {clause}")
        try:
            conn.execute(_FTS_DDL)
            self._fts_available = True
        except sqlite3.OperationalError as exc:
            self._fts_available = False
            logger.warning(
                "FTS5 unavailable for %s (%s) — catalog search degrades to LIKE",
                self.db_path,
                exc,
            )
        conn.commit()

    @property
    def supports_fts(self) -> bool:
        """Whether this database has a usable ``books_fts`` table."""
        if self._fts_available is None:
            try:
                with self._connection() as conn:
                    row = conn.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name='books_fts'"
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
                conn.execute(
                    "DELETE FROM books_fts WHERE book_id = ?", (card.book_id,)
                )
                conn.execute(
                    "INSERT INTO books_fts "
                    "(book_id, title, authors_text, topics_text, summary, toc_digest) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        card.book_id,
                        card.title,
                        ", ".join(card.authors),
                        ", ".join(card.topics),
                        card.summary,
                        card.toc_digest,
                    ),
                )
            conn.commit()

    def remove(self, book_id: str) -> bool:
        """Delete a card (books row + FTS row).

        Returns:
            ``True`` when a row was actually deleted.
        """
        with self._connection() as conn:
            self._ensure_schema(conn)
            cursor = conn.execute(
                "DELETE FROM books WHERE book_id = ?", (book_id,)
            )
            if self._fts_available:
                conn.execute(
                    "DELETE FROM books_fts WHERE book_id = ?", (book_id,)
                )
            conn.commit()
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get(self, book_id: str) -> Optional[BookCard]:
        """Load one card by id, or ``None``."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM books WHERE book_id = ?", (book_id,)
            ).fetchone()
        return self._row_to_card(row) if row else None

    def find_by_sha(self, sha256: str) -> Optional[BookCard]:
        """Find the card for an already-ingested source file, if any."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM books WHERE source_sha256 = ?", (sha256,)
            ).fetchone()
        return self._row_to_card(row) if row else None

    def list_cards(self) -> list[BookCard]:
        """All cards, ordered by title."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM books ORDER BY title COLLATE NOCASE"
            ).fetchall()
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

    def _like_search(
        self, query: str, top_k: int
    ) -> list[tuple[BookCard, float]]:
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
                    "Book id %r also exists in the %s catalog — shadowed "
                    "by an earlier scope",
                    card.book_id,
                    scope,
                )
                continue
            seen.add(card.book_id)
            merged.append(card.model_copy(update={"scope": scope}))
    return merged


def merged_search(
    stores: list[tuple[str, CatalogStore]], query: str, top_k: int = 8
) -> list[BookCard]:
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
