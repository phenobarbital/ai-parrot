"""Unit tests for ArangoStore contextual embedding wiring (FEAT-127 TASK-866)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.stores.models import Document
from parrot.stores.arango import ArangoDBStore
from parrot.stores.utils.contextual import DEFAULT_TEMPLATE


class _ConcreteArango(ArangoDBStore):
    """Minimal concrete subclass that implements the remaining abstract method."""

    async def delete_documents(self, *args, **kwargs):
        pass


@pytest.fixture
def store():
    s = _ConcreteArango.__new__(_ConcreteArango)
    s.logger = MagicMock()
    s.collection_name = "c"
    s.embedding_column = "embedding"
    s.text_column = "text"
    s._db = MagicMock()
    s._db.insert_document = AsyncMock(return_value={"_key": "k"})
    s._db.update_document = AsyncMock(return_value={"_key": "k"})
    s._generate_embedding = AsyncMock(side_effect=lambda t: [0.0] * 4)
    s._find_existing_document = AsyncMock(return_value=None)
    s._document_to_dict = lambda d: {
        s.text_column: d.page_content,
        "metadata": d.metadata,
    }
    s.contextual_embedding = False
    s.contextual_template = DEFAULT_TEMPLATE
    s.contextual_max_header_tokens = 100
    return s


@pytest.fixture
def docs():
    return [Document(page_content="Hello", metadata={
        "document_meta": {"title": "T"},
    })]


class TestArangoContextual:

    async def test_off_path_embeds_raw(self, store, docs):
        """Off-path: raw page_content used for embedding; no contextual_header."""
        await store.add_documents(docs)
        embedded_text = store._generate_embedding.await_args.args[0]
        assert embedded_text == "Hello"
        assert "contextual_header" not in docs[0].metadata

    async def test_on_path_embeds_augmented(self, store, docs):
        """On-path: augmented text used for embedding; contextual_header in metadata."""
        store.contextual_embedding = True
        await store.add_documents(docs)
        embedded_text = store._generate_embedding.await_args.args[0]
        assert embedded_text.startswith("Title: T")
        assert docs[0].metadata["contextual_header"].startswith("Title: T")

    async def test_on_path_page_content_unchanged(self, store, docs):
        """page_content not mutated."""
        before = docs[0].page_content
        store.contextual_embedding = True
        await store.add_documents(docs)
        assert docs[0].page_content == before

    async def test_dict_input_bypasses_augmentation(self, store):
        """Dict-based documents are not augmented (they have no document_meta)."""
        store.contextual_embedding = True
        dict_docs = [{"text": "raw dict", "metadata": {}}]
        # should not raise; dict path goes straight to add_document
        await store.add_documents(dict_docs)
        # _generate_embedding is called inside add_document on the dict path
        # (since embedding_column not in dict_docs[0])
        assert store._generate_embedding.await_count >= 1
