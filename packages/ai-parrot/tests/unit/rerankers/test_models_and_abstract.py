"""Unit tests for RerankedDocument, RerankerConfig, and AbstractReranker."""

import pytest

from parrot.rerankers import AbstractReranker, RerankedDocument, RerankerConfig
from parrot.stores.models import SearchResult


# ---------------------------------------------------------------------------
# RerankedDocument
# ---------------------------------------------------------------------------


def test_reranked_document_wraps_search_result():
    """RerankedDocument holds a SearchResult via composition, not inheritance."""
    sr = SearchResult(id="1", content="test", metadata={}, score=0.9)
    rd = RerankedDocument(
        document=sr,
        rerank_score=0.95,
        rerank_rank=0,
        original_rank=2,
        rerank_model="test-model",
    )
    assert rd.document.content == "test"
    assert rd.rerank_score == 0.95
    assert rd.rerank_rank == 0
    assert rd.original_rank == 2
    assert rd.rerank_model == "test-model"
    assert rd.rerank_latency_ms is None


def test_reranked_document_with_latency():
    """rerank_latency_ms is populated when provided."""
    sr = SearchResult(id="2", content="hello", metadata={}, score=0.7)
    rd = RerankedDocument(
        document=sr,
        rerank_score=0.8,
        rerank_rank=1,
        original_rank=0,
        rerank_model="my-model",
        rerank_latency_ms=42.5,
    )
    assert rd.rerank_latency_ms == pytest.approx(42.5)


def test_reranked_document_rerank_rank_non_negative():
    """rerank_rank must be >= 0."""
    sr = SearchResult(id="3", content="x", metadata={}, score=0.5)
    with pytest.raises(Exception):
        RerankedDocument(
            document=sr,
            rerank_score=0.5,
            rerank_rank=-1,  # invalid
            original_rank=0,
            rerank_model="m",
        )


# ---------------------------------------------------------------------------
# RerankerConfig
# ---------------------------------------------------------------------------


def test_reranker_config_defaults():
    """RerankerConfig has the documented defaults."""
    cfg = RerankerConfig()
    assert cfg.model_name == "BAAI/bge-reranker-v2-m3"
    assert cfg.device == "auto"
    assert cfg.precision == "auto"
    assert cfg.max_length == 512
    assert cfg.batch_size == 32
    assert cfg.trust_remote_code is False
    assert cfg.warmup is True


def test_reranker_config_custom_values():
    """RerankerConfig accepts explicit overrides."""
    cfg = RerankerConfig(
        model_name="cross-encoder/ms-marco-MiniLM-L-12-v2",
        device="cpu",
        precision="fp32",
        max_length=256,
        batch_size=16,
        trust_remote_code=True,
        warmup=False,
    )
    assert cfg.model_name == "cross-encoder/ms-marco-MiniLM-L-12-v2"
    assert cfg.device == "cpu"
    assert cfg.precision == "fp32"
    assert cfg.max_length == 256
    assert cfg.batch_size == 16
    assert cfg.trust_remote_code is True
    assert cfg.warmup is False


# ---------------------------------------------------------------------------
# AbstractReranker
# ---------------------------------------------------------------------------


def test_abstract_reranker_is_abc():
    """AbstractReranker cannot be instantiated directly."""
    with pytest.raises(TypeError):
        AbstractReranker()


@pytest.mark.asyncio
async def test_abstract_reranker_subclass_must_implement_rerank():
    """A subclass that does not implement rerank() cannot be instantiated."""

    class IncompleteReranker(AbstractReranker):
        pass

    with pytest.raises(TypeError):
        IncompleteReranker()


@pytest.mark.asyncio
async def test_abstract_reranker_lifecycle_hooks_are_noop():
    """load() and cleanup() default to no-ops and do not raise."""

    class MinimalReranker(AbstractReranker):
        async def rerank(self, query, documents, top_n=None):
            return []

    r = MinimalReranker()
    await r.load()    # should not raise
    await r.cleanup()  # should not raise


@pytest.mark.asyncio
async def test_abstract_reranker_concrete_subclass_works():
    """A minimal concrete subclass returns results correctly."""

    class EchoReranker(AbstractReranker):
        async def rerank(self, query, documents, top_n=None):
            from parrot.rerankers.models import RerankedDocument

            results = [
                RerankedDocument(
                    document=doc,
                    rerank_score=float(i),
                    rerank_rank=i,
                    original_rank=i,
                    rerank_model="echo",
                )
                for i, doc in enumerate(documents)
            ]
            if top_n is not None:
                results = results[:top_n]
            return results

    sr = SearchResult(id="a", content="hello", metadata={}, score=0.9)
    r = EchoReranker()
    out = await r.rerank("q", [sr])
    assert len(out) == 1
    assert out[0].rerank_model == "echo"
