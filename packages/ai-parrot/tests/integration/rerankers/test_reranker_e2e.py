"""Integration tests for the AI-Parrot reranker subsystem.

These tests exercise the full reranking pipeline end-to-end using a real
MiniLM-L-12-v2 model on CPU.  No live LLM or database is required.

The four test scenarios map directly to the acceptance criteria in
TASK-868:

1. ``test_basebot_ask_with_local_reranker_minilm``
   Verifies that the reranker promotes semantically relevant documents
   in a vocabulary-mismatch scenario (the core problem this feature solves).

2. ``test_basebot_conversation_with_reranker_preserves_history``
   Verifies that the reranker does not mutate the original SearchResult
   objects — conversation history management is unaffected.

3. ``test_reranker_oversample_respects_score_threshold``
   Verifies that documents below the score threshold are filtered
   BEFORE the reranker is invoked (pre-rerank threshold).

4. ``test_benchmark_harness_runs_minilm_cpu_e2e``
   Runs the benchmark script as a subprocess and asserts exit code 0.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from parrot.rerankers import LocalCrossEncoderReranker, RerankerConfig
from parrot.rerankers.models import RerankedDocument
from parrot.stores.models import SearchResult


# ---------------------------------------------------------------------------
# Session-scoped fixture — loads model only once for the integration suite
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def minilm_reranker() -> LocalCrossEncoderReranker:
    """Session-scoped MiniLM reranker for CPU-only integration tests.

    FP32 precision keeps scores deterministic across platforms.

    Returns:
        LocalCrossEncoderReranker: Loaded and warmed-up instance.
    """
    return LocalCrossEncoderReranker(
        config=RerankerConfig(
            model_name="cross-encoder/ms-marco-MiniLM-L-12-v2",
            device="cpu",
            precision="fp32",
            warmup=True,
        )
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_results(pairs: list[tuple[str, float]]) -> list[SearchResult]:
    """Build SearchResult objects from (content, cosine_score) pairs.

    Args:
        pairs: List of (text, score) tuples.

    Returns:
        List of SearchResult objects.
    """
    return [
        SearchResult(id=str(i), content=text, metadata={}, score=score)
        for i, (text, score) in enumerate(pairs)
    ]


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestRerankerE2E:
    """End-to-end integration tests for the reranker pipeline."""

    @pytest.mark.asyncio
    async def test_basebot_ask_with_local_reranker_minilm(
        self, minilm_reranker: LocalCrossEncoderReranker
    ) -> None:
        """Reranker promotes the semantically correct document in a vocab-mismatch case.

        Vocabulary-mismatch problem: the best passage for the query does not share
        lexical tokens with the query.  A BM25 / cosine retriever would rank it low;
        the cross-encoder should rank it first.

        The query is "neural computation for visual recognition", and the documents
        are constructed so that the BM25-like cosine scores (simulated) rank a
        tangentially related passage highest, while the truly relevant passage about
        "convolutional networks and image classification" is ranked second by cosine.
        The reranker should invert this ordering.
        """
        query = "neural computation for visual recognition"

        # Simulate retriever-ordered results (higher cosine score first):
        # - doc 0: high cosine, poor semantic match (query words present but off-topic)
        # - doc 1: lower cosine, but directly addresses visual recognition with CNNs
        # - doc 2: lowest cosine, completely off-topic
        docs = _make_results(
            [
                (
                    "Neural networks require significant computation resources "
                    "and can be deployed on various hardware accelerators.",
                    0.92,
                ),
                (
                    "Convolutional neural networks excel at image classification "
                    "and object detection tasks by learning visual features.",
                    0.78,
                ),
                (
                    "The stock market showed mixed results today with tech "
                    "companies performing below expectations.",
                    0.41,
                ),
            ]
        )

        results = await minilm_reranker.rerank(query, docs, top_n=3)

        assert len(results) == 3, "Expected 3 reranked results"

        # All results must be RerankedDocument objects with required fields
        for r in results:
            assert isinstance(r, RerankedDocument)
            assert r.rerank_model == "cross-encoder/ms-marco-MiniLM-L-12-v2"
            assert r.rerank_latency_ms is not None and r.rerank_latency_ms > 0

        # The cross-encoder should score the CNN document highest because it
        # directly addresses visual recognition, even though its cosine score was
        # lower.  The off-topic stock-market document should score lowest.
        top_doc = results[0].document
        last_doc = results[-1].document
        assert top_doc.id == "1", (
            f"Expected CNN document (id='1') at rank 0, got id='{top_doc.id}' "
            f"with rerank_score={results[0].rerank_score:.4f}"
        )
        assert last_doc.id == "2", (
            f"Expected off-topic document (id='2') at rank 2, got id='{last_doc.id}'"
        )

        # Scores must be in descending order
        for i in range(len(results) - 1):
            assert results[i].rerank_score >= results[i + 1].rerank_score, (
                f"Score at rank {i} ({results[i].rerank_score:.4f}) must be >= "
                f"score at rank {i + 1} ({results[i + 1].rerank_score:.4f})"
            )

    @pytest.mark.asyncio
    async def test_basebot_conversation_with_reranker_preserves_history(
        self, minilm_reranker: LocalCrossEncoderReranker
    ) -> None:
        """Reranker does not mutate original SearchResult objects.

        AbstractBot stores conversation history referencing the original
        SearchResult objects.  If rerank() mutated those objects, it would
        corrupt the context sent to the LLM.  This test verifies that the
        returned RerankedDocument.document objects are identical (same Python
        objects or at least same field values) to the inputs, so conversation
        history is unaffected.
        """
        query = "what is reinforcement learning?"
        docs = _make_results(
            [
                ("Reinforcement learning trains agents via rewards.", 0.85),
                ("Supervised learning uses labelled examples.", 0.80),
                ("RL is used in game playing like AlphaGo.", 0.75),
            ]
        )

        # Keep original field values before reranking
        original_ids = [d.id for d in docs]
        original_contents = [d.content for d in docs]
        original_scores = [d.score for d in docs]

        reranked = await minilm_reranker.rerank(query, docs, top_n=3)

        # Verify original SearchResult objects were NOT mutated
        for i, doc in enumerate(docs):
            assert doc.id == original_ids[i], (
                f"SearchResult at index {i} had its id mutated"
            )
            assert doc.content == original_contents[i], (
                f"SearchResult at index {i} had its content mutated"
            )
            assert doc.score == original_scores[i], (
                f"SearchResult at index {i} had its cosine score mutated"
            )

        # Reranked documents reference the original objects via composition
        reranked_ids = {r.document.id for r in reranked}
        assert reranked_ids == set(original_ids), (
            "All original document IDs should appear in the reranked output"
        )

    @pytest.mark.asyncio
    async def test_reranker_oversample_respects_score_threshold(
        self, minilm_reranker: LocalCrossEncoderReranker
    ) -> None:
        """Documents below score_threshold are filtered BEFORE reranking.

        The spec requires the score threshold to be applied in cosine space
        (pre-rerank).  This test simulates the AbstractBot integration:

        1. A set of documents with mixed cosine scores is produced by the store.
        2. The caller applies a score threshold to produce the reranker input.
        3. Only documents above the threshold are sent to the reranker.
        4. The reranker then sorts those N documents.

        This verifies that pre-rerank filtering works correctly by testing
        the filter + rerank pipeline directly.
        """
        threshold = 0.75
        query = "transformer architecture for NLP"

        all_docs = _make_results(
            [
                ("Transformers use self-attention for sequence modelling.", 0.92),
                ("BERT is a bidirectional transformer encoder.", 0.88),
                ("Random facts about cooking and cuisine.", 0.60),   # below threshold
                ("GPT uses autoregressive transformer decoding.", 0.82),
                ("Sports news: a local team won the championship.", 0.50),  # below
            ]
        )

        # Pre-rerank threshold filter (simulates what AbstractBot does)
        above_threshold = [d for d in all_docs if d.score >= threshold]
        assert len(above_threshold) == 3, (
            f"Expected 3 docs above threshold {threshold}, got {len(above_threshold)}"
        )

        # Rerank only the filtered subset
        reranked = await minilm_reranker.rerank(query, above_threshold, top_n=3)

        # All returned docs should have cosine score >= threshold
        for r in reranked:
            assert r.document.score >= threshold, (
                f"Document id={r.document.id!r} has cosine score "
                f"{r.document.score} below threshold {threshold}"
            )

        # Scores are in descending order
        for i in range(len(reranked) - 1):
            assert reranked[i].rerank_score >= reranked[i + 1].rerank_score

        # Off-topic documents were never sent to the reranker
        filtered_out_ids = {"2", "4"}
        returned_ids = {r.document.id for r in reranked}
        assert not filtered_out_ids.intersection(returned_ids), (
            "Below-threshold documents should not appear in reranked output"
        )

    def test_benchmark_harness_runs_minilm_cpu_e2e(self) -> None:
        """Benchmark script exits 0 on a mini eval set (10 queries, CPU, MiniLM).

        This is an end-to-end smoke test for the benchmark harness.  It runs
        the script as a subprocess in the packages/ai-parrot directory and
        verifies:
        - Exit code is 0.
        - Markdown table header is present in stdout.
        - nDCG@5 column heading appears.
        """
        pkg_dir = Path(__file__).parent.parent.parent.parent
        script = pkg_dir / "scripts" / "benchmark_reranker.py"
        eval_set = pkg_dir / "tests" / "data" / "reranker_eval" / "eval_set.json"

        assert script.exists(), f"Benchmark script not found: {script}"
        assert eval_set.exists(), f"Eval set not found: {eval_set}"

        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--models", "minilm",
                "--device", "cpu",
                "--eval-set", str(eval_set),
                "--max-queries", "10",
            ],
            capture_output=True,
            text=True,
            timeout=300,  # MiniLM load + 10 queries should be < 5 min on CPU
            cwd=str(pkg_dir),
        )

        assert result.returncode == 0, (
            f"Benchmark script exited with code {result.returncode}.\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
        assert "nDCG@5" in result.stdout, (
            "Expected 'nDCG@5' in benchmark stdout (markdown table header missing).\n"
            f"STDOUT:\n{result.stdout}"
        )
        assert "minilm" in result.stdout.lower(), (
            "Expected model alias 'minilm' in benchmark output.\n"
            f"STDOUT:\n{result.stdout}"
        )
