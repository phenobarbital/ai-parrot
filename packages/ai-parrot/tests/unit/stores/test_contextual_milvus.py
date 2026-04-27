"""Unit tests for MilvusStore contextual embedding wiring (FEAT-127 TASK-864)."""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

# ── Stub pymilvus before importing MilvusStore ────────────────────────────
# pymilvus has a marshmallow version incompatibility in this environment;
# stub it out so tests can run without the library being importable.
if "pymilvus" not in sys.modules:
    _pymilvus = ModuleType("pymilvus")
    _pymilvus.MilvusClient = MagicMock  # type: ignore[attr-defined]
    _pymilvus.Collection = MagicMock   # type: ignore[attr-defined]
    _pymilvus.connections = MagicMock() # type: ignore[attr-defined]
    sys.modules["pymilvus"] = _pymilvus

from parrot.stores.models import Document  # noqa: E402
from parrot.stores.milvus import MilvusStore  # noqa: E402
from parrot.stores.utils.contextual import DEFAULT_TEMPLATE  # noqa: E402


@pytest.fixture
def docs():
    return [
        Document(
            page_content="Body A",
            metadata={"document_meta": {"title": "Doc A", "section": "S"}},
        ),
        Document(page_content="Body B", metadata={}),
    ]


@pytest.fixture
def store():
    s = MilvusStore.__new__(MilvusStore)
    s.logger = MagicMock()
    s._connected = True
    s._connection = MagicMock()
    s._connection.insert = MagicMock()
    s._embed_ = MagicMock()
    s._embed_.embed_documents = AsyncMock(
        side_effect=lambda t: np.zeros((len(t), 4))
    )
    s.collection_name = "c"
    s._id_column = "id"
    s._embedding_column = "emb"
    s._document_column = "doc"
    s._text_column = "text"
    s._metadata_column = "meta"
    s.contextual_embedding = False
    s.contextual_template = DEFAULT_TEMPLATE
    s.contextual_max_header_tokens = 100
    return s


class TestMilvusContextual:

    async def test_off_path_uses_raw_text(self, store, docs):
        """Off-path: embedded texts == raw page_content, no contextual_header."""
        await store.add_documents(docs)
        embedded = store._embed_.embed_documents.await_args.args[0]
        assert embedded == ["Body A", "Body B"]
        rows = store._connection.insert.call_args.kwargs["data"]
        assert rows[0]["doc"] == "Body A"
        assert "contextual_header" not in docs[0].metadata

    async def test_on_path_embeds_header(self, store, docs):
        """On-path: augmented text used for embedding; raw content stored; header in metadata."""
        store.contextual_embedding = True
        await store.add_documents(docs)
        embedded = store._embed_.embed_documents.await_args.args[0]
        assert embedded[0].startswith("Title: Doc A")
        rows = store._connection.insert.call_args.kwargs["data"]
        # Document column stores RAW content, not augmented.
        assert rows[0]["doc"] == "Body A"
        # Metadata carries the header.
        assert rows[0]["meta"]["contextual_header"].startswith("Title: Doc A")

    async def test_on_path_page_content_unchanged(self, store, docs):
        """page_content is never mutated."""
        before = [d.page_content for d in docs]
        store.contextual_embedding = True
        await store.add_documents(docs)
        assert [d.page_content for d in docs] == before
