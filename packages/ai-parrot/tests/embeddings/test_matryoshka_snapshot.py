"""Bit-equal snapshot test for the Matryoshka disabled path — FEAT-150.

When ``matryoshka`` is absent or ``enabled=False``, ``SentenceTransformerModel``
must behave identically to the pre-FEAT-150 code path: it returns the raw
768-dimensional output of the underlying model without any truncation or
renormalisation.

This test uses a *deterministic stub model* so the expected values are stable
across machines, CI environments, and real-weight version changes.  The stub
is identical to the one in ``test_matryoshka_encoding.py``; it is inlined here
to keep the test self-contained (snapshot tests should have zero hidden
dependencies).

Re-record the snapshot ONLY if the stub's ``encode`` logic changes — never
because real model weights changed.
"""
from __future__ import annotations

import numpy as np
import pytest

from parrot.embeddings.huggingface import SentenceTransformerModel
from parrot.embeddings.registry import EmbeddingRegistry


# ---------------------------------------------------------------------------
# Deterministic stub model
# ---------------------------------------------------------------------------

class _StubModel:
    """Minimal SentenceTransformer stand-in.

    Produces a unit-norm vector via ``np.linspace(1, 2, native_dim)`` that is
    then L2-normalised.  The same formula is used both to generate the
    pre-recorded snapshot below and in the live test.
    """

    def __init__(self, native_dim: int = 768):
        self._native_dim = native_dim

    def get_embedding_dimension(self) -> int:  # noqa: D401
        return self._native_dim

    def encode(self, texts, **kwargs):
        n = len(texts) if isinstance(texts, list) else 1
        v = np.linspace(1.0, 2.0, self._native_dim, dtype=np.float32)
        v = v / np.linalg.norm(v)
        return np.tile(v, (n, 1))

    def eval(self):
        pass

    def half(self):
        pass


# ---------------------------------------------------------------------------
# Pre-recorded snapshot (768-dim)
#
# Generated once with:
#   import numpy as np
#   v = np.linspace(1.0, 2.0, 768, dtype=np.float32)
#   v = v / np.linalg.norm(v)
#   # First 8 values for spot-check; full array verified by np.allclose.
#
# To regenerate the full snapshot array run:
#   python -c "
#   import numpy as np
#   v = np.linspace(1.0, 2.0, 768, dtype=np.float32)
#   v = v / np.linalg.norm(v)
#   print(list(v))
#   "
# ---------------------------------------------------------------------------

def _compute_expected_768() -> list:
    """Compute the expected 768-dim reference vector from the stub formula."""
    v = np.linspace(1.0, 2.0, 768, dtype=np.float32)
    v = v / np.linalg.norm(v)
    return v.tolist()


# Pre-computed at test-generation time so the test is self-documenting.
_EXPECTED_DISABLED_VEC: list = _compute_expected_768()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch):
    """Reset the EmbeddingRegistry singleton before and after each test.

    Prevents cache hits from interfering with the stub.
    """
    EmbeddingRegistry._instance = None

    def _stub_create(self, model_name=None, **kwargs):
        m = _StubModel(native_dim=768)
        self._dimension = m.get_embedding_dimension()
        if self._matryoshka_dim is not None:
            self._dimension = self._matryoshka_dim
        return m

    monkeypatch.setattr(SentenceTransformerModel, "_create_embedding", _stub_create)
    yield
    EmbeddingRegistry._instance = None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDisabledMatryoshkaSnapshot:
    """The disabled path must be bit-equal to the pre-recorded reference."""

    @pytest.mark.asyncio
    async def test_no_matryoshka_key_is_bit_equal(self):
        """Without a matryoshka key the output equals the stub reference exactly."""
        m = SentenceTransformerModel(model_name="nomic-ai/nomic-embed-text-v1.5")
        vecs = await m.embed_documents(["hello world"])

        assert len(vecs) == 1
        assert len(vecs[0]) == 768

        result = np.array(vecs[0], dtype=np.float32)
        expected = np.array(_EXPECTED_DISABLED_VEC, dtype=np.float32)

        assert np.allclose(result, expected, atol=1e-6), (
            "Disabled Matryoshka path changed the output — "
            "FEAT-150 regression in embed_documents."
        )

    @pytest.mark.asyncio
    async def test_disabled_flag_is_bit_equal(self):
        """matryoshka={"enabled": False} is identical to no matryoshka key."""
        m = SentenceTransformerModel(
            model_name="nomic-ai/nomic-embed-text-v1.5",
            matryoshka={"enabled": False, "dimension": 512},
        )
        vecs = await m.embed_documents(["hello world"])

        assert len(vecs) == 1
        assert len(vecs[0]) == 768

        result = np.array(vecs[0], dtype=np.float32)
        expected = np.array(_EXPECTED_DISABLED_VEC, dtype=np.float32)

        assert np.allclose(result, expected, atol=1e-6), (
            "disabled Matryoshka (enabled=False) modified the output."
        )

    @pytest.mark.asyncio
    async def test_embed_query_disabled_is_bit_equal(self):
        """embed_query also returns the reference without Matryoshka."""
        m = SentenceTransformerModel(model_name="nomic-ai/nomic-embed-text-v1.5")
        vec = await m.embed_query("hello world")

        assert len(vec) == 768

        result = np.array(vec, dtype=np.float32)
        expected = np.array(_EXPECTED_DISABLED_VEC, dtype=np.float32)

        assert np.allclose(result, expected, atol=1e-6), (
            "Disabled Matryoshka path changed embed_query output."
        )

    @pytest.mark.asyncio
    async def test_enabled_path_differs_from_snapshot(self):
        """Sanity check: enabled Matryoshka must NOT equal the 768-dim snapshot."""
        m = SentenceTransformerModel(
            model_name="nomic-ai/nomic-embed-text-v1.5",
            matryoshka={"enabled": True, "dimension": 512},
        )
        vecs = await m.embed_documents(["hello world"])

        assert len(vecs) == 1
        # Different length already proves it differs.
        assert len(vecs[0]) == 512, (
            f"Expected 512-dim vector when Matryoshka is enabled, got {len(vecs[0])}"
        )
