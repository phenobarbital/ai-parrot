"""Shared fixtures for the bookstore test suite.

The fake LLM adapter mirrors the one used by the pageindex toolkit
tests (``tests/knowledge/pageindex/test_toolkit.py``): a ``MagicMock``
whose ``ask``/``ask_structured`` are ``AsyncMock``s, plus the tiktoken
stub so ingestion works offline.
"""

from __future__ import annotations

import re
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.bookstore.models import (
    CardDraft,
    CommunityLabelDraft,
    RelationDraft,
    RelationJudgement,
)
from parrot.knowledge.pageindex.ingest import IngestedMarkdown

#: Pre-FEAT-533 literals (verbatim, frozen here on purpose — the live
#: ``_BOOKS_DDL``/``_FTS_DDL`` in ``catalog.py`` have since gained the
#: classification/community columns via ``_ADDED_COLUMNS`` and the FTS
#: rebuild path this feature adds). Used by ``legacy_library_db`` below
#: to exercise the migration path against a database that predates it.
_LEGACY_BOOKS_DDL = """
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

_LEGACY_FTS_DDL = """
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

SAMPLE_MARKDOWN = (
    "# Synthetic Handbook\n\n"
    "Top level introduction to the synthetic handbook with enough "
    "text to clear the thinning threshold of the markdown parser.\n\n"
    "## Chapter One\n"
    "Chapter one covers asynchronous programming patterns in Python "
    "with plenty of descriptive content to keep the node visible.\n\n"
    "## Chapter Two\n"
    "Chapter two covers vector search and retrieval augmented "
    "generation with the remaining descriptive example content.\n"
)


def make_adapter() -> MagicMock:
    """Fake heavy adapter compatible with PageIndexToolkit + carding."""
    adapter = MagicMock()
    adapter.model = "heavy"
    client_response = MagicMock()
    client_response.output = "cot analysis"
    client_response.structured_output = None
    adapter.client = MagicMock()
    adapter.client.ask = AsyncMock(return_value=client_response)
    adapter.client.default_model = "test-model"
    adapter.ask = AsyncMock(return_value="cot analysis")

    def _structured(prompt, schema, **kwargs):
        if schema is CardDraft:
            return CardDraft(
                title="Synthetic Handbook",
                authors=["Ada Example"],
                year=2024,
                language="en",
                topics=["async python", "vector search"],
                summary="A synthetic handbook used by the tests.",
                genre="essay",
                traditions=["Estoicismo"],
                period="Imperio romano",
            )
        if schema is RelationDraft:
            # Deterministic, order-based judgements over whatever
            # candidate ids the prompt actually listed (parsed rather
            # than hardcoded, so tests control the candidates via the
            # catalog/graph, not this fixture).
            candidates_section = prompt.split("CANDIDATE books", 1)[-1]
            ids = re.findall(r"book_id=(\S+)", candidates_section)
            judgements = []
            if len(ids) >= 1:
                judgements.append(
                    RelationJudgement(
                        dst_book_id=ids[0],
                        rel="parallels",
                        confidence=0.7,
                        rationale="Explores a similar theme independently.",
                    )
                )
            if len(ids) >= 2:
                judgements.append(
                    RelationJudgement(
                        dst_book_id=ids[1],
                        rel="none",
                        confidence=0.9,
                        rationale="No meaningful conceptual relation.",
                    )
                )
            return RelationDraft(judgements=judgements)
        if schema is CommunityLabelDraft:
            return CommunityLabelDraft(
                label="Test Community",
                description="A synthetic community label used by the tests.",
            )
        return IngestedMarkdown(
            title="Synthetic Handbook",
            summary="A short summary.",
            markdown=SAMPLE_MARKDOWN,
        )

    adapter.ask_structured = AsyncMock(side_effect=_structured)
    return adapter


@pytest.fixture
def fake_adapter() -> MagicMock:
    return make_adapter()


@pytest.fixture(autouse=True)
def _stub_tiktoken(monkeypatch):
    # tiktoken downloads encodings on first use; offline environments
    # bypass it with a char-count approximation (same as pageindex tests).
    def _approx(text: str, model: str = "gpt-4o") -> int:
        return max(1, len(text or ""))

    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", _approx)
    monkeypatch.setattr("parrot.knowledge.pageindex.md_builder.count_tokens", _approx)


@pytest.fixture
def sample_tree() -> dict:
    """Hand-built PageIndex tree dict with two levels and page ranges."""
    return {
        "doc_name": "Synthetic Handbook",
        "doc_description": "A synthetic handbook about async Python.",
        "structure": [
            {
                "title": "Chapter One",
                "node_id": "0000",
                "start_index": 1,
                "end_index": 20,
                "summary": "Async patterns.",
                "nodes": [
                    {
                        "title": "Event Loops",
                        "node_id": "0001",
                        "start_index": 3,
                        "end_index": 10,
                        "summary": "Loop internals.",
                        "nodes": [
                            {
                                "title": "Too Deep",
                                "node_id": "0002",
                                "start_index": 4,
                                "end_index": 6,
                            }
                        ],
                    }
                ],
            },
            {
                "title": "Chapter Two",
                "node_id": "0003",
                "start_index": 21,
                "end_index": 40,
                "summary": "Vector search.",
                "nodes": [],
            },
        ],
    }


@pytest.fixture
def legacy_library_db(tmp_path):
    """A pre-FEAT-533 ``library.db``: no classification/community columns,
    6-column ``books_fts``, no relation/judgement/community tables.

    Built directly from :data:`_LEGACY_BOOKS_DDL`/:data:`_LEGACY_FTS_DDL`
    with one hand-inserted row, so ``CatalogStore(db_path)`` exercises
    the real additive-migration + FTS-rebuild path on open.

    Returns:
        The ``Path`` to the legacy database file.
    """
    db_path = tmp_path / "library.db"
    conn = sqlite3.connect(db_path)
    conn.execute(_LEGACY_BOOKS_DDL)
    conn.execute(_LEGACY_FTS_DDL)
    conn.execute(
        "INSERT INTO books (book_id, title, authors, year, language, topics, "
        "summary, toc_digest, toc, tree_name, source_path, source_sha256, "
        "source_format, page_count, chapter_count, added_at, card_origin) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "meditations",
            "Meditations",
            '["Marcus Aurelius"]',
            180,
            "en",
            '["stoicism", "ethics"]',
            "Personal writings on Stoic philosophy.",
            "1 Book One",
            "[]",
            "meditations",
            "/books/meditations.pdf",
            "a" * 64,
            "pdf",
            200,
            12,
            "2026-01-01T00:00:00+00:00",
            "llm",
        ),
    )
    conn.execute(
        "INSERT INTO books_fts (book_id, title, authors_text, topics_text, "
        "summary, toc_digest) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "meditations",
            "Meditations",
            "Marcus Aurelius",
            "stoicism, ethics",
            "Personal writings on Stoic philosophy.",
            "1 Book One",
        ),
    )
    conn.commit()
    conn.close()
    return db_path
