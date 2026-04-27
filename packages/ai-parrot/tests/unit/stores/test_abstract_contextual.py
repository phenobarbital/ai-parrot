"""Unit tests for AbstractStore._apply_contextual_augmentation (FEAT-127 TASK-862).

Covers Module-2 rows from spec §4:
  - test_apply_contextual_augmentation_off_path_unchanged
  - test_apply_contextual_augmentation_writes_header_metadata
  - test_apply_contextual_augmentation_does_not_mutate_page_content
"""
from unittest.mock import MagicMock

import pytest

from parrot.stores.abstract import AbstractStore
from parrot.stores.models import Document


# ---------------------------------------------------------------------------
# Minimal concrete stub (implements all abstractmethods)
# ---------------------------------------------------------------------------

class _DummyStore(AbstractStore):
    """Minimal concrete store for testing the augmentation helper only."""

    async def connection(self):
        return (None, None)

    async def disconnect(self):
        pass

    def get_vector(self, metric_type=None, **kwargs):
        return None

    async def similarity_search(self, query, **kwargs):
        return []

    async def from_documents(self, documents, collection=None, **kwargs):
        return self

    async def create_collection(self, collection):
        pass

    async def add_documents(self, documents, collection=None, **kwargs):
        pass

    async def prepare_embedding_table(self, *args, **kwargs):
        pass

    async def delete_collection(self, collection):
        pass

    async def delete_documents(self, *args, **kwargs):
        pass

    async def delete_documents_by_filter(self, *args, **kwargs):
        pass

    async def update_documents(self, *args, **kwargs):
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def docs():
    return [
        Document(page_content="A", metadata={"document_meta": {"title": "T1"}}),
        Document(page_content="B", metadata={"document_meta": {}}),
        Document(page_content="C", metadata={}),
    ]


def _make_store(**kwargs) -> _DummyStore:
    """Create a _DummyStore bypassing the embedding model setup."""
    store = _DummyStore.__new__(_DummyStore)
    # Minimal attributes needed by AbstractStore internals
    store.logger = MagicMock()
    store._connected = False
    store._embed_ = None
    store.embedding_model = None
    store.client = None
    store.vector = None
    store._connection = None
    store._context_depth = 0
    store._use_database = False
    store.collection_name = "test"
    store.dimension = 768
    store._metric_type = "COSINE"
    store._index_type = "IVF_FLAT"
    store.database = ""
    store.index_name = "test_index"
    # Contextual flags
    from parrot.stores.utils.contextual import DEFAULT_TEMPLATE, DEFAULT_MAX_HEADER_TOKENS
    store.contextual_embedding = kwargs.get("contextual_embedding", False)
    store.contextual_template = kwargs.get("contextual_template", DEFAULT_TEMPLATE)
    store.contextual_max_header_tokens = kwargs.get(
        "contextual_max_header_tokens", DEFAULT_MAX_HEADER_TOKENS
    )
    return store


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestApplyContextualAugmentation:
    """Spec §4 Module-2 rows."""

    def test_off_path_unchanged(self, docs):
        """Off-path returns raw page_content, no contextual_header written."""
        store = _make_store(contextual_embedding=False)
        out = store._apply_contextual_augmentation(docs)
        assert out == ["A", "B", "C"]
        for d in docs:
            assert "contextual_header" not in d.metadata

    def test_on_path_writes_header_metadata(self, docs):
        """On-path writes contextual_header into every document's metadata."""
        store = _make_store(contextual_embedding=True)
        store._apply_contextual_augmentation(docs)
        for d in docs:
            assert "contextual_header" in d.metadata
            assert isinstance(d.metadata["contextual_header"], str)

    def test_on_path_does_not_mutate_page_content(self, docs):
        """page_content must be byte-equal before and after the call."""
        before = [d.page_content for d in docs]
        store = _make_store(contextual_embedding=True)
        store._apply_contextual_augmentation(docs)
        after = [d.page_content for d in docs]
        assert before == after

    def test_constructor_defaults(self):
        """Default flags: contextual_embedding=False, max_tokens=100."""
        store = _make_store()
        assert store.contextual_embedding is False
        assert store.contextual_max_header_tokens == 100

    def test_off_path_no_logging(self, docs):
        """Off-path must not call logger at all."""
        store = _make_store(contextual_embedding=False)
        store._apply_contextual_augmentation(docs)
        store.logger.info.assert_not_called()

    def test_on_path_logs_summary(self, docs):
        """On-path emits exactly one INFO log line per call."""
        store = _make_store(contextual_embedding=True)
        store._apply_contextual_augmentation(docs)
        assert store.logger.info.call_count == 1

    def test_on_path_augmented_text_for_doc_with_meta(self, docs):
        """Doc with title gets an augmented text that includes the header."""
        store = _make_store(contextual_embedding=True)
        out = store._apply_contextual_augmentation(docs)
        # docs[0] has title="T1", so augmented text should include the header
        assert "T1" in out[0]
        # docs[2] has no document_meta → passthrough
        assert out[2] == "C"

    def test_empty_document_list_returns_empty(self):
        """Empty input → empty output, no log."""
        store = _make_store(contextual_embedding=True)
        out = store._apply_contextual_augmentation([])
        assert out == []
        store.logger.info.assert_not_called()
