"""Unit tests for LocalCrossEncoderReranker.

All tests that load a real model use the session-scoped ``minilm_reranker``
fixture (MiniLM-L-12-v2, CPU, FP32) from conftest.py.  This keeps the suite
fast by loading the model only once per pytest session.

GPU-only tests are skipped when CUDA is unavailable.
"""

import math

import pytest

from parrot.rerankers import LocalCrossEncoderReranker, RerankerConfig
from parrot.stores.models import SearchResult


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def test_local_reranker_init_minilm_cpu(minilm_reranker):
    """MiniLM-L-12-v2 loads on CPU successfully; model_name is echoed."""
    assert minilm_reranker.config.model_name == "cross-encoder/ms-marco-MiniLM-L-12-v2"
    assert minilm_reranker._device == "cpu"
    assert minilm_reranker._precision == "fp32"
    # Model and tokenizer must be loaded
    assert minilm_reranker._model is not None
    assert minilm_reranker._tokenizer is not None


def test_local_reranker_process_cache():
    """Two instances with the same config share the same model object."""
    cfg = RerankerConfig(
        model_name="cross-encoder/ms-marco-MiniLM-L-12-v2",
        device="cpu",
        precision="fp32",
        warmup=False,
    )
    r1 = LocalCrossEncoderReranker(config=cfg)
    r2 = LocalCrossEncoderReranker(config=cfg)
    assert r1._model is r2._model, "Model should be shared via process cache"


# ---------------------------------------------------------------------------
# Core reranking behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_reranker_rerank_orders_descending(
    minilm_reranker, fake_search_results
):
    """Reranked results are in descending rerank_score order."""
    results = await minilm_reranker.rerank("What is deep learning?", fake_search_results)
    assert len(results) == len(fake_search_results)
    for i in range(len(results) - 1):
        assert results[i].rerank_score >= results[i + 1].rerank_score, (
            f"Score at rank {i} ({results[i].rerank_score}) should be >= "
            f"score at rank {i + 1} ({results[i + 1].rerank_score})"
        )


@pytest.mark.asyncio
async def test_local_reranker_top_n_truncation(minilm_reranker, fake_search_results):
    """top_n=3 returns exactly 3 items even with 5 inputs."""
    results = await minilm_reranker.rerank(
        "What is deep learning?", fake_search_results, top_n=3
    )
    assert len(results) == 3


@pytest.mark.asyncio
async def test_local_reranker_top_n_greater_than_docs(minilm_reranker, fake_search_results):
    """top_n greater than len(documents) returns all documents."""
    results = await minilm_reranker.rerank(
        "test", fake_search_results, top_n=100
    )
    assert len(results) == len(fake_search_results)


@pytest.mark.asyncio
async def test_local_reranker_preserves_original_rank(
    minilm_reranker, fake_search_results
):
    """Each RerankedDocument carries the correct original_rank."""
    results = await minilm_reranker.rerank("What is deep learning?", fake_search_results)
    original_ranks = {r.original_rank for r in results}
    expected = set(range(len(fake_search_results)))
    assert original_ranks == expected, (
        f"Expected original ranks {expected}, got {original_ranks}"
    )


@pytest.mark.asyncio
async def test_local_reranker_handles_empty_input(minilm_reranker):
    """Empty documents list returns [] without a forward pass."""
    results = await minilm_reranker.rerank("any query", [])
    assert results == []


@pytest.mark.asyncio
async def test_local_reranker_single_document(minilm_reranker):
    """Single-document input returns exactly one RerankedDocument."""
    doc = SearchResult(id="0", content="single doc", metadata={}, score=0.9)
    results = await minilm_reranker.rerank("query", [doc])
    assert len(results) == 1
    assert results[0].original_rank == 0
    assert results[0].rerank_rank == 0


@pytest.mark.asyncio
async def test_local_reranker_model_name_in_results(
    minilm_reranker, fake_search_results
):
    """rerank_model is populated on every output document."""
    results = await minilm_reranker.rerank("test", fake_search_results)
    for r in results:
        assert r.rerank_model == "cross-encoder/ms-marco-MiniLM-L-12-v2"


@pytest.mark.asyncio
async def test_local_reranker_latency_ms_populated(
    minilm_reranker, fake_search_results
):
    """rerank_latency_ms is a positive number after a real forward pass."""
    results = await minilm_reranker.rerank("query", fake_search_results)
    # All results in the same batch share the same latency_ms
    for r in results:
        assert r.rerank_latency_ms is not None
        assert r.rerank_latency_ms > 0


# ---------------------------------------------------------------------------
# Truncation and batching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_reranker_truncates_to_max_length(minilm_reranker):
    """Passages longer than max_length are tokenised with truncation, no exception."""
    long_passage = "word " * 2000  # well beyond 512 tokens
    docs = [SearchResult(id="0", content=long_passage, metadata={}, score=0.9)]
    results = await minilm_reranker.rerank("query about long text", docs)
    assert len(results) == 1
    assert not math.isnan(results[0].rerank_score)


@pytest.mark.asyncio
async def test_local_reranker_batching_large_input(minilm_reranker):
    """More documents than batch_size are processed without error."""
    # batch_size defaults to 32; create 50 docs
    docs = [
        SearchResult(id=str(i), content=f"document {i}", metadata={}, score=0.9)
        for i in range(50)
    ]
    results = await minilm_reranker.rerank("find document 25", docs)
    assert len(results) == 50
    # All original ranks are present
    assert {r.original_rank for r in results} == set(range(50))


# ---------------------------------------------------------------------------
# Error handling / fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_reranker_failure_returns_original_order(fake_search_results):
    """When _rerank_sync raises, results preserve original order with NaN scores."""
    from unittest.mock import patch

    reranker = LocalCrossEncoderReranker(
        config=RerankerConfig(
            model_name="cross-encoder/ms-marco-MiniLM-L-12-v2",
            device="cpu",
            precision="fp32",
            warmup=False,
        )
    )
    with patch.object(reranker, "_rerank_sync", side_effect=RuntimeError("boom")):
        results = await reranker.rerank("test", fake_search_results)

    assert len(results) == len(fake_search_results)
    assert all(math.isnan(r.rerank_score) for r in results)
    assert [r.original_rank for r in results] == list(range(len(fake_search_results)))


# ---------------------------------------------------------------------------
# Precision / quantization
# ---------------------------------------------------------------------------


def test_int8_quantization_applied_on_cpu():
    """When device='cpu' and precision='int8', Linear layers are quantized."""
    import torch

    reranker = LocalCrossEncoderReranker(
        config=RerankerConfig(
            model_name="cross-encoder/ms-marco-MiniLM-L-12-v2",
            device="cpu",
            precision="int8",
            warmup=False,
        )
    )
    has_quantized = any(
        isinstance(m, torch.nn.quantized.dynamic.Linear)
        for m in reranker._model.modules()
    )
    assert has_quantized, "Expected at least one INT8-quantized Linear layer"


@pytest.mark.skipif(
    not __import__("torch").cuda.is_available(),
    reason="CUDA not available on this machine",
)
def test_fp16_applied_on_cuda():
    """When CUDA is available and precision='auto', model dtype is FP16."""
    import torch

    reranker = LocalCrossEncoderReranker(
        config=RerankerConfig(
            model_name="cross-encoder/ms-marco-MiniLM-L-12-v2",
            device="auto",
            precision="auto",
            warmup=False,
        )
    )
    assert reranker._precision == "fp16"
    # At least one parameter should have dtype float16
    has_fp16 = any(p.dtype == torch.float16 for p in reranker._model.parameters())
    assert has_fp16, "Expected at least one FP16 parameter"


# ---------------------------------------------------------------------------
# Jina v2 trust_remote_code guard
# ---------------------------------------------------------------------------


def test_jina_requires_trust_remote_code():
    """Loading a Jina v2 model with trust_remote_code=False raises ValueError."""
    with pytest.raises(ValueError, match="trust_remote_code"):
        LocalCrossEncoderReranker(
            config=RerankerConfig(
                model_name="jinaai/jina-reranker-v2-base-multilingual",
                trust_remote_code=False,
                warmup=False,
            )
        )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_reranker_duplicate_content(minilm_reranker):
    """Documents with identical content are all ranked without error."""
    docs = [
        SearchResult(id=str(i), content="identical content", metadata={}, score=0.9)
        for i in range(5)
    ]
    results = await minilm_reranker.rerank("identical content query", docs)
    assert len(results) == 5
    assert {r.original_rank for r in results} == {0, 1, 2, 3, 4}


@pytest.mark.asyncio
async def test_local_reranker_concurrent_calls(minilm_reranker, fake_search_results):
    """Concurrent rerank() calls all complete without deadlock or error."""
    import asyncio

    tasks = [
        minilm_reranker.rerank("deep learning", fake_search_results)
        for _ in range(4)
    ]
    all_results = await asyncio.gather(*tasks)
    assert len(all_results) == 4
    for r in all_results:
        assert len(r) == len(fake_search_results)
