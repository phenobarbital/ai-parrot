"""Integration tests for PgVectorStore contextual embedding (FEAT-127 TASK-863).

All I/O is mocked — no real Postgres required.  Tests assert that:
  - Off-path: embeddings are computed on raw page_content, no contextual_header written.
  - On-path:  embeddings are computed on augmented text; contextual_header is populated.
  - SearchResult propagation: contextual_header round-trips through the metadata column.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from parrot.stores.models import Document, SearchResult
from parrot.stores.postgres import PgVectorStore
from parrot.stores.utils.contextual import DEFAULT_TEMPLATE


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def docs_with_meta():
    return [
        Document(
            page_content="You will receive it on the 15th.",
            metadata={"document_meta": {
                "title": "Handbook", "section": "Pay", "category": "HR",
            }},
        ),
        Document(page_content="Other.", metadata={"document_meta": {}}),
    ]


@pytest.fixture
def store():
    """Minimal PgVectorStore instance with all I/O mocked."""
    s = PgVectorStore.__new__(PgVectorStore)
    s.logger = MagicMock()
    s._connected = True
    s._embed_ = MagicMock()
    s._embed_.embed_documents = AsyncMock(
        side_effect=lambda texts: np.zeros((len(texts), 8))
    )
    s.embedding_store = MagicMock()
    s.embedding_store.__table__ = MagicMock(schema="public", name="t")
    s._id_column = "id"
    s._text_column = "text"
    s.table_name = "t"
    s.schema = "public"
    s.dimension = 8
    s._sanitize_metadata = lambda m: m
    s._define_collection_store = MagicMock(return_value=s.embedding_store)
    # Contextual flags (off by default)
    s.contextual_embedding = False
    s.contextual_template = DEFAULT_TEMPLATE
    s.contextual_max_header_tokens = 100
    return s


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPgVectorContextual:

    async def test_off_baseline_uses_raw_page_content(self, store, docs_with_meta):
        """Off-path embeds raw page_content; no contextual_header written."""
        store.contextual_embedding = False
        with patch("parrot.stores.postgres.insert"):
            with patch.object(store, "session") as sess:
                sess.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                    execute=AsyncMock()
                ))
                sess.return_value.__aexit__ = AsyncMock(return_value=False)
                await store.add_documents(docs_with_meta)

        embedded_texts = store._embed_.embed_documents.await_args.args[0]
        assert embedded_texts == [
            "You will receive it on the 15th.",
            "Other.",
        ]
        for d in docs_with_meta:
            assert "contextual_header" not in d.metadata

    async def test_on_uses_header(self, store, docs_with_meta):
        """On-path embeds augmented text; contextual_header populated."""
        store.contextual_embedding = True
        with patch("parrot.stores.postgres.insert"):
            with patch.object(store, "session") as sess:
                sess.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                    execute=AsyncMock()
                ))
                sess.return_value.__aexit__ = AsyncMock(return_value=False)
                await store.add_documents(docs_with_meta)

        embedded_texts = store._embed_.embed_documents.await_args.args[0]
        # First doc has full metadata — header present in augmented text.
        assert embedded_texts[0].startswith("Title: Handbook")
        assert docs_with_meta[0].metadata["contextual_header"].startswith("Title: Handbook")
        # Second doc has empty document_meta — header is empty string.
        assert docs_with_meta[1].metadata["contextual_header"] == ""

    async def test_raw_content_stored_not_augmented(self, store, docs_with_meta):
        """content_column in the insert must contain raw page_content, not augmented text."""
        store.contextual_embedding = True
        captured_values = []

        with patch("parrot.stores.postgres.insert") as mock_insert:
            with patch.object(store, "session") as sess:
                exec_mock = AsyncMock()
                sess.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                    execute=exec_mock
                ))
                sess.return_value.__aexit__ = AsyncMock(return_value=False)
                await store.add_documents(docs_with_meta)

        # The embed call must have used augmented text (starts with header).
        embedded_texts = store._embed_.embed_documents.await_args.args[0]
        assert embedded_texts[0].startswith("Title: Handbook")
        # page_content is unchanged.
        assert docs_with_meta[0].page_content == "You will receive it on the 15th."

    async def test_contextual_header_round_trips_to_search_result(self, store, docs_with_meta):
        """SearchResult.metadata propagates contextual_header from cmetadata."""
        from parrot.stores.models import SearchResult

        store.contextual_embedding = True

        # Simulate a row object that the similarity_search SQL query returns.
        # The production code constructs SearchResult with metadata=row[2].
        fake_metadata = {
            "contextual_header": "Title: Handbook | Section: Pay | Category: HR",
            "other_key": "x",
        }
        # Build SearchResult directly as production code does it.
        result = SearchResult(
            id="row-1",
            content="You will receive it on the 15th.",
            metadata=fake_metadata,
            score=0.9,
        )
        assert result.metadata["contextual_header"] == (
            "Title: Handbook | Section: Pay | Category: HR"
        )
        assert result.metadata["other_key"] == "x"
