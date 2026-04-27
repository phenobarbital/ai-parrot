"""Unit tests for FaissStore contextual embedding wiring (FEAT-127 TASK-865)."""
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from parrot.stores.models import Document
from parrot.stores.faiss_store import FAISSStore
from parrot.stores.utils.contextual import DEFAULT_TEMPLATE


@pytest.fixture
def docs():
    return [
        Document(page_content="Hello", metadata={
            "document_meta": {"title": "T", "section": "S"},
        }),
    ]


@pytest.fixture
def store(monkeypatch):
    s = FAISSStore.__new__(FAISSStore)
    s.logger = MagicMock()
    s._connected = True
    s._embed_ = MagicMock()
    s._embed_.embed_documents = AsyncMock(
        side_effect=lambda t: np.zeros((len(t), 4), dtype=np.float32)
    )
    s.collection_name = "c"
    s.dimension = 4
    s.distance_strategy = MagicMock()
    s.index_type = "Flat"
    s._collections = {"c": {
        "index": MagicMock(),
        "dimension": 4,
        "is_trained": True,
        "documents": {},   # {id: text}
        "metadata": {},    # {id: metadata_dict}
        "embeddings": {},  # {id: embedding_vector}
        "id_to_idx": {},
        "idx_to_id": {},
    }}
    s._initialize_collection = lambda c: None
    s._create_faiss_index = lambda d: MagicMock()
    s.contextual_embedding = False
    s.contextual_template = DEFAULT_TEMPLATE
    s.contextual_max_header_tokens = 100
    return s


class TestFaissContextual:

    async def test_off_path_embeds_raw_text(self, store, docs):
        """Off-path: embedded text == raw page_content, no contextual_header."""
        await store.add_documents(docs)
        embedded = store._embed_.embed_documents.await_args.args[0]
        assert embedded == ["Hello"]
        assert "contextual_header" not in docs[0].metadata

    async def test_on_path_embeds_augmented_text(self, store, docs):
        """On-path: augmented text used for embedding; contextual_header in metadata."""
        store.contextual_embedding = True
        await store.add_documents(docs)
        embedded = store._embed_.embed_documents.await_args.args[0]
        assert embedded[0].startswith("Title: T")
        assert docs[0].metadata["contextual_header"].startswith("Title: T")

    async def test_on_path_stores_raw_content(self, store, docs):
        """RAW page_content stored in the collection, not augmented text."""
        store.contextual_embedding = True
        await store.add_documents(docs)
        # The documents dict in the FAISS collection should hold raw text.
        coll = store._collections["c"]
        stored_text = list(coll["documents"].values())[0]
        assert stored_text == "Hello"

    async def test_page_content_unchanged(self, store, docs):
        """page_content not mutated by the hook."""
        before = docs[0].page_content
        store.contextual_embedding = True
        await store.add_documents(docs)
        assert docs[0].page_content == before
