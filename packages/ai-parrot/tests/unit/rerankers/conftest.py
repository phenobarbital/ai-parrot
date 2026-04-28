"""Shared pytest fixtures for the reranker unit test suite.

The ``minilm_reranker`` fixture is session-scoped to avoid reloading the model
for every test — MiniLM-L-12-v2 loads in ~4 seconds; session scope keeps the
total suite runtime under 60 seconds.
"""

import pytest

from parrot.stores.models import SearchResult


@pytest.fixture(scope="session")
def minilm_reranker():
    """Session-scoped MiniLM reranker for CPU-only tests.

    Uses FP32 precision (no quantization) to keep scores deterministic
    across platforms.  INT8 quantization is tested separately.

    Returns:
        LocalCrossEncoderReranker: Loaded and warmed up instance.
    """
    from parrot.rerankers import LocalCrossEncoderReranker, RerankerConfig

    return LocalCrossEncoderReranker(
        config=RerankerConfig(
            model_name="cross-encoder/ms-marco-MiniLM-L-12-v2",
            device="cpu",
            precision="fp32",
            warmup=True,
        )
    )


@pytest.fixture
def fake_search_results():
    """Five deterministic SearchResult objects for ordering tests.

    The texts are chosen so that a deep-learning query should rank
    'Deep learning frameworks comparison' highest and 'The weather today
    is sunny' lowest.

    Returns:
        list[SearchResult]: Five results with descending cosine scores.
    """
    texts = [
        "Python is a programming language used for AI",
        "The weather today is sunny and warm",
        "Machine learning uses neural networks for prediction",
        "Cooking recipes for Italian pasta dishes",
        "Deep learning frameworks like PyTorch and TensorFlow",
    ]
    return [
        SearchResult(id=str(i), content=text, metadata={}, score=0.9 - i * 0.1)
        for i, text in enumerate(texts)
    ]
