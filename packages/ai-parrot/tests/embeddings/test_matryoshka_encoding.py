"""Unit tests for SentenceTransformerModel Matryoshka encoding.

Tests spec §3 Module 2.  A stub ``_create_embedding`` is monkeypatched so
that no real model weights are downloaded.  The stub returns deterministic
native-dim numpy arrays so the truncation math can be verified without
relying on sentence-transformers internals.
"""
import numpy as np
import pytest
from unittest.mock import patch

from parrot.embeddings.huggingface import SentenceTransformerModel
from parrot.exceptions import ConfigError


class _StubModel:
    """Minimal stand-in for SentenceTransformer.

    Returns a deterministic, non-zero native-dim array so that L2
    renormalisation has meaningful work to do.  Vectors are unit-norm
    by construction (``linspace`` normalised before returning).
    """

    def __init__(self, native_dim: int = 768):
        self._native_dim = native_dim

    def get_embedding_dimension(self) -> int:
        return self._native_dim

    def encode(self, texts, **kwargs):
        """Return one normalised vector per input text."""
        n = len(texts) if isinstance(texts, list) else 1
        v = np.linspace(1.0, 2.0, self._native_dim, dtype=np.float32)
        v = v / np.linalg.norm(v)
        return np.tile(v, (n, 1))

    def eval(self):
        pass

    def half(self):
        pass


@pytest.fixture
def stub_create(monkeypatch):
    """Replace _create_embedding with a stub that never loads real weights.

    Also resets the EmbeddingRegistry singleton so each test starts with a
    fresh cache.  Without this, the second test in a class would get a cache
    hit on the first test's instance, bypassing ``_create_embedding`` and
    leaving ``_dimension`` as ``None`` on the new wrapper object.
    """
    from parrot.embeddings.registry import EmbeddingRegistry

    # Clear the singleton and its internal cache.
    EmbeddingRegistry._instance = None

    def _stub(self, model_name=None, **kwargs):
        m = _StubModel(native_dim=768)
        self._dimension = m.get_embedding_dimension()
        # Honour the Matryoshka override after native dim is set.
        if self._matryoshka_dim is not None:
            self._dimension = self._matryoshka_dim
        return m

    monkeypatch.setattr(SentenceTransformerModel, "_create_embedding", _stub)
    yield
    # Restore a clean singleton after each test.
    EmbeddingRegistry._instance = None


class TestMatryoshkaEncoding:
    """Tests for the Matryoshka hot-path in embed_documents / embed_query."""

    @pytest.mark.asyncio
    async def test_truncated_dim_embed_documents(self, stub_create):
        """embed_documents returns vectors of the requested (truncated) length."""
        m = SentenceTransformerModel(
            model_name="nomic-ai/nomic-embed-text-v1.5",
            matryoshka={"enabled": True, "dimension": 512},
        )
        _ = m.model  # trigger lazy load
        vecs = await m.embed_documents(["hello", "world"])
        assert len(vecs) == 2
        assert all(len(v) == 512 for v in vecs)

    @pytest.mark.asyncio
    async def test_truncated_dim_embed_query(self, stub_create):
        """embed_query returns a vector of the requested (truncated) length."""
        m = SentenceTransformerModel(
            model_name="nomic-ai/nomic-embed-text-v1.5",
            matryoshka={"enabled": True, "dimension": 256},
        )
        _ = m.model
        v = await m.embed_query("hello")
        assert len(v) == 256

    @pytest.mark.asyncio
    async def test_truncated_renorm_unit_norm(self, stub_create):
        """After truncation and renormalisation the vector has L2 norm ≈ 1.0."""
        m = SentenceTransformerModel(
            model_name="nomic-ai/nomic-embed-text-v1.5",
            matryoshka={"enabled": True, "dimension": 256},
        )
        _ = m.model
        v = await m.embed_query("hello")
        norm = float(np.linalg.norm(np.asarray(v)))
        assert abs(norm - 1.0) < 1e-5

    @pytest.mark.asyncio
    async def test_documents_renorm_unit_norm(self, stub_create):
        """embed_documents vectors are unit-norm after truncation."""
        m = SentenceTransformerModel(
            model_name="nomic-ai/nomic-embed-text-v1.5",
            matryoshka={"enabled": True, "dimension": 128},
        )
        _ = m.model
        vecs = await m.embed_documents(["a", "b", "c"])
        for v in vecs:
            norm = float(np.linalg.norm(np.asarray(v)))
            assert abs(norm - 1.0) < 1e-5, f"Expected unit norm, got {norm}"

    @pytest.mark.asyncio
    async def test_disabled_no_change(self, stub_create):
        """Without matryoshka kwarg the output is the native 768-dim vector."""
        m = SentenceTransformerModel(model_name="nomic-ai/nomic-embed-text-v1.5")
        _ = m.model
        v = await m.embed_query("hello")
        assert len(v) == 768

    @pytest.mark.asyncio
    async def test_disabled_explicit_false(self, stub_create):
        """matryoshka={"enabled": False} behaves identically to no kwarg."""
        m = SentenceTransformerModel(
            model_name="nomic-ai/nomic-embed-text-v1.5",
            matryoshka={"enabled": False, "dimension": 512},
        )
        _ = m.model
        v = await m.embed_query("hello")
        assert len(v) == 768

    def test_get_embedding_dimension_truncated(self, stub_create):
        """get_embedding_dimension() returns the truncated dim when active."""
        m = SentenceTransformerModel(
            model_name="nomic-ai/nomic-embed-text-v1.5",
            matryoshka={"enabled": True, "dimension": 512},
        )
        _ = m.model
        assert m.get_embedding_dimension() == 512

    def test_get_embedding_dimension_native(self, stub_create):
        """get_embedding_dimension() returns native dim when Matryoshka off."""
        m = SentenceTransformerModel(model_name="nomic-ai/nomic-embed-text-v1.5")
        _ = m.model
        assert m.get_embedding_dimension() == 768

    def test_invalid_dim_raises(self):
        """Unsupported dimension raises ConfigError at __init__ time."""
        with pytest.raises(ConfigError):
            SentenceTransformerModel(
                model_name="nomic-ai/nomic-embed-text-v1.5",
                matryoshka={"enabled": True, "dimension": 300},
            )

    def test_unknown_model_raises(self):
        """Unknown model with matryoshka enabled raises ConfigError at __init__."""
        with pytest.raises(ConfigError):
            SentenceTransformerModel(
                model_name="does-not-exist/foo",
                matryoshka={"enabled": True, "dimension": 512},
            )

    def test_matryoshka_none_ok(self):
        """matryoshka=None (the default) should construct without error."""
        # Validation should not raise; only loading the model triggers I/O.
        m = SentenceTransformerModel(
            model_name="nomic-ai/nomic-embed-text-v1.5",
            matryoshka=None,
        )
        assert m._matryoshka_dim is None

    def test_matryoshka_empty_dict_ok(self):
        """matryoshka={} (empty dict) should construct without error (disabled)."""
        # Empty dict → MatryoshkaConfig() → enabled=False → no truncation.
        m = SentenceTransformerModel(
            model_name="nomic-ai/nomic-embed-text-v1.5",
            matryoshka={},
        )
        assert m._matryoshka_dim is None

    def test_apply_matryoshka_noop_when_disabled(self):
        """_apply_matryoshka returns the input unchanged when disabled."""
        m = SentenceTransformerModel(model_name="nomic-ai/nomic-embed-text-v1.5")
        arr = np.ones((3, 768), dtype=np.float32)
        result = m._apply_matryoshka(arr)
        # Should be the same object (no copy) since it short-circuits.
        assert result is arr

    def test_apply_matryoshka_slices_and_renorms(self):
        """_apply_matryoshka slices to target dim and renormalises correctly."""
        m = SentenceTransformerModel(
            model_name="nomic-ai/nomic-embed-text-v1.5",
            matryoshka={"enabled": True, "dimension": 64},
        )
        # Construct a deterministic input array (not unit-norm after slicing).
        arr = np.linspace(1.0, 2.0, 768, dtype=np.float32).reshape(1, 768)
        result = m._apply_matryoshka(arr)
        assert result.shape == (1, 64)
        norm = float(np.linalg.norm(result[0]))
        assert abs(norm - 1.0) < 1e-5

    def test_apply_matryoshka_list_input_list_output(self):
        """_apply_matryoshka returns list when given list input."""
        m = SentenceTransformerModel(
            model_name="nomic-ai/nomic-embed-text-v1.5",
            matryoshka={"enabled": True, "dimension": 64},
        )
        arr = np.linspace(1.0, 2.0, 768, dtype=np.float32)
        list_input = [arr.tolist()]
        result = m._apply_matryoshka(list_input)
        assert isinstance(result, list)
        assert len(result[0]) == 64
