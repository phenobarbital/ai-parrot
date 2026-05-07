"""Unit tests for AbstractStore.create_embedding Matryoshka forwarding.

Tests spec §3 Module 4 — the surgical change that forwards the ``matryoshka``
sub-dict from the ``embedding_model`` config dict into the registry call as a
kwarg, so downstream Matryoshka-aware model constructors receive it.
"""
import pytest
from unittest.mock import MagicMock, patch

from parrot.embeddings.registry import EmbeddingRegistry


@pytest.fixture(autouse=True)
def clean_registry():
    """Reset EmbeddingRegistry singleton between tests."""
    EmbeddingRegistry._instance = None
    yield
    EmbeddingRegistry._instance = None


def _make_store():
    """Return a minimal concrete AbstractStore subclass for testing."""
    from parrot.stores.abstract import AbstractStore

    class _Stub(AbstractStore):
        async def add_documents(self, *a, **k):
            pass

        async def prepare_embedding_table(self, *a, **k):
            pass

        async def delete_documents(self, *a, **k):
            pass

        async def delete_documents_by_filter(self, *a, **k):
            pass

        async def connection(self):
            pass

        async def disconnect(self):
            pass

        async def create_collection(self, *a, **k):
            pass

        async def from_documents(self, *a, **k):
            pass

        async def get_vector(self, *a, **k):
            return None

        async def similarity_search(self, *a, **k):
            return []

        async def search(self, *a, **k):
            return []

    return _Stub()


class TestCreateEmbeddingForwarding:
    """Tests for the Matryoshka kwarg forwarding in create_embedding."""

    def test_forwards_matryoshka_from_dict(self, monkeypatch):
        """matryoshka from the embedding_model dict is forwarded to the registry."""
        captured = {}

        def fake_get_or_create_sync(self_reg, name, mtype, **kwargs):
            captured["kwargs"] = kwargs
            return MagicMock()

        monkeypatch.setattr(
            EmbeddingRegistry, "get_or_create_sync", fake_get_or_create_sync
        )
        # Ensure the singleton is created so instance() returns our patched class.
        EmbeddingRegistry._instance = EmbeddingRegistry.__new__(EmbeddingRegistry)
        EmbeddingRegistry._instance._supported_embeddings = {
            "huggingface": "SentenceTransformerModel"
        }

        store = _make_store()
        store.create_embedding({
            "model_name": "nomic-ai/nomic-embed-text-v1.5",
            "model_type": "huggingface",
            "matryoshka": {"enabled": True, "dimension": 512},
        })
        assert captured["kwargs"].get("matryoshka") == {"enabled": True, "dimension": 512}

    def test_caller_kwarg_wins(self, monkeypatch):
        """Explicitly supplied matryoshka kwarg overrides the dict value."""
        captured = {}

        def fake_get_or_create_sync(self_reg, name, mtype, **kwargs):
            captured["kwargs"] = kwargs
            return MagicMock()

        monkeypatch.setattr(
            EmbeddingRegistry, "get_or_create_sync", fake_get_or_create_sync
        )
        EmbeddingRegistry._instance = EmbeddingRegistry.__new__(EmbeddingRegistry)
        EmbeddingRegistry._instance._supported_embeddings = {
            "huggingface": "SentenceTransformerModel"
        }

        store = _make_store()
        store.create_embedding(
            {
                "model_name": "nomic-ai/nomic-embed-text-v1.5",
                "model_type": "huggingface",
                "matryoshka": {"enabled": True, "dimension": 512},
            },
            matryoshka={"enabled": True, "dimension": 256},
        )
        # Caller's kwarg (256) must win over the dict's (512).
        assert captured["kwargs"]["matryoshka"]["dimension"] == 256

    def test_no_matryoshka_no_change(self, monkeypatch):
        """When matryoshka is absent from the dict, kwargs are unchanged."""
        captured = {}

        def fake_get_or_create_sync(self_reg, name, mtype, **kwargs):
            captured["kwargs"] = kwargs
            return MagicMock()

        monkeypatch.setattr(
            EmbeddingRegistry, "get_or_create_sync", fake_get_or_create_sync
        )
        EmbeddingRegistry._instance = EmbeddingRegistry.__new__(EmbeddingRegistry)
        EmbeddingRegistry._instance._supported_embeddings = {
            "huggingface": "SentenceTransformerModel"
        }

        store = _make_store()
        store.create_embedding({
            "model_name": "BAAI/bge-base-en-v1.5",
            "model_type": "huggingface",
        })
        assert "matryoshka" not in captured["kwargs"]

    def test_matryoshka_none_in_dict_not_forwarded(self, monkeypatch):
        """matryoshka=None in the dict does not inject the kwarg."""
        captured = {}

        def fake_get_or_create_sync(self_reg, name, mtype, **kwargs):
            captured["kwargs"] = kwargs
            return MagicMock()

        monkeypatch.setattr(
            EmbeddingRegistry, "get_or_create_sync", fake_get_or_create_sync
        )
        EmbeddingRegistry._instance = EmbeddingRegistry.__new__(EmbeddingRegistry)
        EmbeddingRegistry._instance._supported_embeddings = {
            "huggingface": "SentenceTransformerModel"
        }

        store = _make_store()
        store.create_embedding({
            "model_name": "nomic-ai/nomic-embed-text-v1.5",
            "model_type": "huggingface",
            "matryoshka": None,
        })
        # None is falsy but present; however the guard is `if matryoshka is not None`
        # so None DOES trigger (matryoshka=None), but None is sent only if key exists.
        # With None value the condition `if matryoshka is not None` is False → not forwarded.
        assert "matryoshka" not in captured["kwargs"]
