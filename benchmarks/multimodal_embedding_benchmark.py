#!/usr/bin/env python3
"""Multimodal Embedding Benchmark Harness for FEAT-229.

Compares UForm multilingual-base, UForm english-large, current HF text embedder
baseline, and multilingual-e5-large on:
  - Text retrieval: Recall@{1,5,10}, MRR, nDCG@10
  - Matryoshka recall curve: same metrics at dims {768, 512, 256, 128, 64}
  - Quantization recall delta: f32 vs i8 vs b1
  - Throughput: embeddings/sec, latency p50/p95 (CPU)
  - Footprint: model size on disk, embedding dim
  - Cross-modal (if image fixtures): image->text and text->image Recall@k

Decision gate (spec §7):
  UForm multilingual-base nDCG@10 must be within 3% of the current text embedder
  baseline. If it lags by more than 3 percentage points, retain the text-only embedder.

Usage:
    python benchmarks/multimodal_embedding_benchmark.py [--synthetic-only]
        [--output-dir OUTPUT_DIR] [--domain-data PATH]

Example:
    python benchmarks/multimodal_embedding_benchmark.py --synthetic-only --output-dir /tmp/bench
    python benchmarks/multimodal_embedding_benchmark.py --domain-data mydata.csv --output-dir results/
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Ensure the worktree packages are on the path when running standalone.
# ---------------------------------------------------------------------------
_BENCHMARK_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _BENCHMARK_DIR.parent
for _pkg in ("packages/ai-parrot/src", "packages/ai-parrot-embeddings/src"):
    _p = str(_REPO_ROOT / _pkg)
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Dataset helpers
# ---------------------------------------------------------------------------

@dataclass
class QueryDoc:
    """A query/document pair for retrieval evaluation.

    Attributes:
        query_id: Unique identifier for the query.
        query_text: Natural language query string.
        relevant_doc_id: Ground-truth document identifier.
        doc_text: Text of the relevant document.
        lang: ISO 639-1 language code.
    """

    query_id: str
    query_text: str
    relevant_doc_id: str
    doc_text: str
    lang: str = "en"


def load_synthetic_data() -> list[QueryDoc]:
    """Load the built-in synthetic query/document pairs.

    Returns:
        List of ``QueryDoc`` objects from ``benchmarks/fixtures/synthetic_queries.json``.
    """
    fixture_path = _BENCHMARK_DIR / "fixtures" / "synthetic_queries.json"
    with open(fixture_path, encoding="utf-8") as f:
        data = json.load(f)
    return [QueryDoc(**entry) for entry in data["entries"]]


def load_domain_data(csv_path: str) -> list[QueryDoc]:
    """Load real domain query/document pairs from a CSV file.

    The CSV must have columns: query_id, query_text, relevant_doc_id, doc_text, lang.

    Args:
        csv_path: Path to the CSV file with domain data.

    Returns:
        List of ``QueryDoc`` objects parsed from the CSV.

    Raises:
        FileNotFoundError: If the CSV file does not exist.
        ValueError: If required columns are missing.

    # TODO: Replace with real Spanish domain data (see benchmarks/fixtures/README.md)
    # Format: CSV with columns (query_id, query_text, relevant_doc_id, doc_text, lang)
    """
    required = {"query_id", "query_text", "relevant_doc_id", "doc_text"}
    rows = []
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"Empty CSV: {csv_path}")
        missing = required - set(reader.fieldnames)
        if missing:
            raise ValueError(f"Missing columns in {csv_path}: {missing}")
        for row in reader:
            rows.append(QueryDoc(
                query_id=row["query_id"],
                query_text=row["query_text"],
                relevant_doc_id=row["relevant_doc_id"],
                doc_text=row["doc_text"],
                lang=row.get("lang", "en"),
            ))
    return rows


# ---------------------------------------------------------------------------
# Retrieval metrics
# ---------------------------------------------------------------------------

def recall_at_k(rankings: list[list[str]], relevant_ids: list[str], k: int) -> float:
    """Compute mean Recall@k across all queries.

    Args:
        rankings: For each query, an ordered list of retrieved document IDs.
        relevant_ids: For each query, the single ground-truth document ID.
        k: Cutoff rank.

    Returns:
        Mean Recall@k across all queries.
    """
    hits = sum(1 for ranking, rel in zip(rankings, relevant_ids) if rel in ranking[:k])
    return hits / max(len(rankings), 1)


def mean_reciprocal_rank(rankings: list[list[str]], relevant_ids: list[str]) -> float:
    """Compute MRR (Mean Reciprocal Rank).

    Args:
        rankings: For each query, an ordered list of retrieved document IDs.
        relevant_ids: For each query, the single ground-truth document ID.

    Returns:
        Mean reciprocal rank across all queries.
    """
    rrs = []
    for ranking, rel in zip(rankings, relevant_ids):
        if rel in ranking:
            rank = ranking.index(rel) + 1
            rrs.append(1.0 / rank)
        else:
            rrs.append(0.0)
    return statistics.mean(rrs) if rrs else 0.0


def ndcg_at_k(rankings: list[list[str]], relevant_ids: list[str], k: int) -> float:
    """Compute mean nDCG@k (binary relevance: 1 if relevant, 0 otherwise).

    Args:
        rankings: For each query, an ordered list of retrieved document IDs.
        relevant_ids: For each query, the single ground-truth document ID.
        k: Cutoff rank.

    Returns:
        Mean nDCG@k across all queries.
    """
    scores = []
    ideal_dcg = 1.0  # ideal: relevant doc at rank 1
    for ranking, rel in zip(rankings, relevant_ids):
        dcg = 0.0
        for i, doc_id in enumerate(ranking[:k]):
            if doc_id == rel:
                dcg = 1.0 / math.log2(i + 2)
                break
        scores.append(dcg / ideal_dcg if ideal_dcg > 0 else 0.0)
    return statistics.mean(scores) if scores else 0.0


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

def cosine_similarities(query_emb: np.ndarray, corpus_embs: np.ndarray) -> np.ndarray:
    """Compute cosine similarities between a query and a corpus.

    Assumes L2-normalized embeddings (dot product == cosine).

    Args:
        query_emb: Query embedding of shape (D,).
        corpus_embs: Corpus embeddings of shape (N, D).

    Returns:
        Similarity scores of shape (N,).
    """
    q = query_emb / (np.linalg.norm(query_emb) + 1e-9)
    c = corpus_embs / (np.linalg.norm(corpus_embs, axis=1, keepdims=True) + 1e-9)
    return c @ q


def rank_documents(
    query_embs: np.ndarray,
    corpus_embs: np.ndarray,
    corpus_ids: list[str],
) -> list[list[str]]:
    """Rank corpus documents by similarity for each query.

    Args:
        query_embs: Query embeddings of shape (Q, D).
        corpus_embs: Corpus embeddings of shape (N, D).
        corpus_ids: Corpus document identifiers of length N.

    Returns:
        For each query, an ordered list of document IDs (most similar first).
    """
    rankings = []
    for q_emb in query_embs:
        sims = cosine_similarities(q_emb, corpus_embs)
        order = np.argsort(-sims)
        rankings.append([corpus_ids[i] for i in order])
    return rankings


# ---------------------------------------------------------------------------
# Throughput measurement
# ---------------------------------------------------------------------------

@dataclass
class ThroughputStats:
    """Throughput and latency statistics for an embedding provider.

    Attributes:
        model_name: Name of the model.
        embs_per_sec: Embeddings processed per second.
        latency_p50_ms: Median per-batch latency in milliseconds.
        latency_p95_ms: 95th-percentile per-batch latency in milliseconds.
        dimension: Output embedding dimension.
        quantization: Quantization mode label.
    """

    model_name: str
    embs_per_sec: float
    latency_p50_ms: float
    latency_p95_ms: float
    dimension: int
    quantization: str = "f32"


async def measure_throughput(
    embed_fn: Any,
    texts: list[str],
    n_repeats: int = 5,
) -> tuple[float, float, float]:
    """Measure embedding throughput over multiple runs.

    Args:
        embed_fn: Async callable that takes a list of texts and returns embeddings.
        texts: List of text strings to embed.
        n_repeats: Number of timed repetitions.

    Returns:
        Tuple of (embs_per_sec, p50_latency_ms, p95_latency_ms).
    """
    latencies_ms = []
    for _ in range(n_repeats):
        t0 = time.perf_counter()
        await embed_fn(texts)
        elapsed = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(elapsed)

    latencies_ms.sort()
    p50 = statistics.median(latencies_ms)
    idx_p95 = max(0, int(0.95 * len(latencies_ms)) - 1)
    p95 = latencies_ms[idx_p95]
    total_embs = len(texts) * n_repeats
    total_time_s = sum(latencies_ms) / 1000.0
    embs_per_sec = total_embs / max(total_time_s, 1e-9)
    return embs_per_sec, p50, p95


# ---------------------------------------------------------------------------
# Metric result containers
# ---------------------------------------------------------------------------

@dataclass
class RetrievalMetrics:
    """Retrieval quality metrics for a model at a specific configuration.

    Attributes:
        model_name: Name of the model.
        dimension: Embedding dimension used.
        quantization: Quantization mode label.
        recall_at_1: Recall@1.
        recall_at_5: Recall@5.
        recall_at_10: Recall@10.
        mrr: Mean reciprocal rank.
        ndcg_at_10: nDCG@10.
        lang_filter: Language filter applied ('all', 'en', 'es').
    """

    model_name: str
    dimension: int
    quantization: str
    recall_at_1: float
    recall_at_5: float
    recall_at_10: float
    mrr: float
    ndcg_at_10: float
    lang_filter: str = "all"

    def to_dict(self) -> dict:
        """Convert to a flat dictionary for CSV export.

        Returns:
            Dictionary with all metric fields.
        """
        return {
            "model_name": self.model_name,
            "dimension": self.dimension,
            "quantization": self.quantization,
            "lang_filter": self.lang_filter,
            "recall@1": f"{self.recall_at_1:.4f}",
            "recall@5": f"{self.recall_at_5:.4f}",
            "recall@10": f"{self.recall_at_10:.4f}",
            "mrr": f"{self.mrr:.4f}",
            "ndcg@10": f"{self.ndcg_at_10:.4f}",
        }


# ---------------------------------------------------------------------------
# Model wrappers
# ---------------------------------------------------------------------------

class ModelWrapper:
    """Thin wrapper around an embedding model for benchmarking.

    Args:
        name: Display name for the model.
        provider_type: Registry model_type key.
        model_id: Model identifier string.
        dimension: Output embedding dimension (post-Matryoshka if sliced).
        quantization_label: Quantization mode label string.
    """

    def __init__(
        self,
        name: str,
        provider_type: str,
        model_id: str,
        dimension: int = 768,
        quantization_label: str = "f32",
    ) -> None:
        """Initialise model wrapper.

        Args:
            name: Display name for the model.
            provider_type: Registry model_type key.
            model_id: Model identifier string.
            dimension: Output embedding dimension.
            quantization_label: Quantization mode label string.
        """
        self.name = name
        self.provider_type = provider_type
        self.model_id = model_id
        self.dimension = dimension
        self.quantization_label = quantization_label
        self._model: Any = None

    async def load(self) -> None:
        """Load the model via EmbeddingRegistry or directly.

        Raises:
            ImportError: If required packages are not installed.
        """
        from parrot.embeddings.registry import EmbeddingRegistry
        registry = EmbeddingRegistry.instance()
        self._model = await registry.get_or_create(self.model_id, self.provider_type)

    async def embed_texts(self, texts: list[str]) -> np.ndarray:
        """Embed a list of texts.

        Args:
            texts: List of text strings to embed.

        Returns:
            Embedding matrix of shape (len(texts), D).

        Raises:
            RuntimeError: If model has not been loaded.
        """
        if self._model is None:
            raise RuntimeError(f"Model {self.name} not loaded. Call load() first.")
        result = await self._model.embed_text(texts)
        return result.embeddings

    async def unload(self) -> None:
        """Unload the model and free resources."""
        if self._model is not None:
            from parrot.embeddings.registry import EmbeddingRegistry
            registry = EmbeddingRegistry.instance()
            try:
                await registry.unload(self.model_id, self.provider_type)
            except Exception:
                pass
            self._model = None


class UFormWrapper(ModelWrapper):
    """Wrapper for UForm multimodal embeddings.

    Args:
        model_id: UForm model identifier.
        output_dim: Post-Matryoshka output dimension.
        quantization: Quantization mode (QuantizationMode enum value).
        quantization_label: Human-readable quantization label.
    """

    def __init__(
        self,
        model_id: str,
        output_dim: Optional[int] = None,
        quantization: Any = None,
        quantization_label: str = "f32",
    ) -> None:
        """Initialise UForm wrapper.

        Args:
            model_id: UForm model identifier string.
            output_dim: Output embedding dimension after Matryoshka slicing.
            quantization: QuantizationMode enum value.
            quantization_label: Display label for the quantization mode.
        """
        super().__init__(
            name=f"UForm({model_id.split('/')[-1]})[{quantization_label}@{output_dim or 768}]",
            provider_type="multimodal",
            model_id=model_id,
            dimension=output_dim or 768,
            quantization_label=quantization_label,
        )
        self._output_dim = output_dim
        self._quantization = quantization

    async def load(self) -> None:
        """Directly instantiate UFormEmbedding (bypasses registry for custom params).

        Raises:
            ImportError: If uform package is not installed.
        """
        from parrot.embeddings.multimodal import UFormEmbedding, EmbeddingBackend, QuantizationMode
        quant = self._quantization or QuantizationMode.F32
        self._model = UFormEmbedding(
            model_name=self.model_id,
            backend=EmbeddingBackend.TORCH,
            output_dim=self._output_dim,
            quantization=quant,
            device="cpu",
        )
        await self._model.initialize_model()

    async def embed_texts(self, texts: list[str]) -> np.ndarray:
        """Embed texts and return f32 embeddings for metric computation.

        Args:
            texts: List of text strings.

        Returns:
            Float32 embedding matrix.
        """
        if self._model is None:
            raise RuntimeError(f"Model {self.name} not loaded.")
        result = await self._model.embed_text(texts)
        embs = result.embeddings
        # For metric computation, always work with f32 (convert back from quantized)
        if embs.dtype != np.float32:
            embs = embs.astype(np.float32)
        return embs

    async def unload(self) -> None:
        """Unload UForm model."""
        if self._model is not None:
            self._model.free()
            self._model = None


# ---------------------------------------------------------------------------
# Core evaluation loop
# ---------------------------------------------------------------------------

async def evaluate_model(
    wrapper: ModelWrapper,
    dataset: list[QueryDoc],
    matryoshka_dims: Optional[list[int]] = None,
    quantization_modes: Optional[list[tuple[str, Any]]] = None,
    n_throughput_reps: int = 3,
    output_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Evaluate a single model on retrieval and throughput metrics.

    Args:
        wrapper: An initialised model wrapper with ``load()`` already called.
        dataset: List of query/document pairs.
        matryoshka_dims: Dimensions to test for Matryoshka slicing.
        quantization_modes: List of (label, QuantizationMode) pairs to evaluate.
        n_throughput_reps: Number of throughput measurement repetitions.
        output_dir: Optional directory to write per-model CSV files.

    Returns:
        Dictionary with keys 'retrieval', 'throughput', 'matryoshka', 'quantization'.
    """
    from parrot.embeddings.multimodal.quantization import matryoshka_slice, l2_normalize

    queries = [qd.query_text for qd in dataset]
    relevant_ids = [qd.relevant_doc_id for qd in dataset]

    # Build corpus: unique docs
    corpus: dict[str, str] = {}
    for qd in dataset:
        corpus[qd.relevant_doc_id] = qd.doc_text
    corpus_texts = list(corpus.values())
    corpus_ids = list(corpus.keys())

    print(f"  Embedding {len(queries)} queries + {len(corpus_texts)} corpus docs...")

    # Base f32 embeddings
    q_embs = await wrapper.embed_texts(queries)
    c_embs = await wrapper.embed_texts(corpus_texts)

    # --- Main retrieval metrics ---
    rankings = rank_documents(q_embs, c_embs, corpus_ids)
    base_metrics = RetrievalMetrics(
        model_name=wrapper.name,
        dimension=q_embs.shape[-1],
        quantization="f32",
        recall_at_1=recall_at_k(rankings, relevant_ids, 1),
        recall_at_5=recall_at_k(rankings, relevant_ids, 5),
        recall_at_10=recall_at_k(rankings, relevant_ids, 10),
        mrr=mean_reciprocal_rank(rankings, relevant_ids),
        ndcg_at_10=ndcg_at_k(rankings, relevant_ids, 10),
        lang_filter="all",
    )

    # Per-language metrics
    lang_metrics: list[RetrievalMetrics] = []
    for lang in ("en", "es"):
        lang_items = [qd for qd in dataset if qd.lang == lang]
        if not lang_items:
            continue
        lang_queries = [qd.query_text for qd in lang_items]
        lang_relevant = [qd.relevant_doc_id for qd in lang_items]
        lang_qembs = await wrapper.embed_texts(lang_queries)
        lang_rankings = rank_documents(lang_qembs, c_embs, corpus_ids)
        lang_metrics.append(RetrievalMetrics(
            model_name=wrapper.name,
            dimension=lang_qembs.shape[-1],
            quantization="f32",
            recall_at_1=recall_at_k(lang_rankings, lang_relevant, 1),
            recall_at_5=recall_at_k(lang_rankings, lang_relevant, 5),
            recall_at_10=recall_at_k(lang_rankings, lang_relevant, 10),
            mrr=mean_reciprocal_rank(lang_rankings, lang_relevant),
            ndcg_at_10=ndcg_at_k(lang_rankings, lang_relevant, 10),
            lang_filter=lang,
        ))

    # --- Matryoshka recall curve ---
    matryoshka_results: list[RetrievalMetrics] = []
    if matryoshka_dims:
        for dim in matryoshka_dims:
            if dim >= q_embs.shape[-1]:
                sliced_q = q_embs
                sliced_c = c_embs
            else:
                sliced_q = l2_normalize(matryoshka_slice(q_embs, dim))
                sliced_c = l2_normalize(matryoshka_slice(c_embs, dim))
            rankings_m = rank_documents(sliced_q, sliced_c, corpus_ids)
            matryoshka_results.append(RetrievalMetrics(
                model_name=wrapper.name,
                dimension=dim,
                quantization="f32",
                recall_at_1=recall_at_k(rankings_m, relevant_ids, 1),
                recall_at_5=recall_at_k(rankings_m, relevant_ids, 5),
                recall_at_10=recall_at_k(rankings_m, relevant_ids, 10),
                mrr=mean_reciprocal_rank(rankings_m, relevant_ids),
                ndcg_at_10=ndcg_at_k(rankings_m, relevant_ids, 10),
                lang_filter="all",
            ))

    # --- Quantization delta ---
    quant_results: list[RetrievalMetrics] = []
    if quantization_modes:
        from parrot.embeddings.multimodal.quantization import quantize
        for qlabel, qmode in quantization_modes:
            if qlabel == "f32":
                qq_embs, qc_embs = q_embs, c_embs
            else:
                # Quantize then cast back to f32 for metric computation
                qraw_q = quantize(q_embs.copy(), qmode)
                qraw_c = quantize(c_embs.copy(), qmode)
                qq_embs = qraw_q.astype(np.float32)
                qc_embs = qraw_c.astype(np.float32)
            rankings_q = rank_documents(qq_embs, qc_embs, corpus_ids)
            quant_results.append(RetrievalMetrics(
                model_name=wrapper.name,
                dimension=q_embs.shape[-1],
                quantization=qlabel,
                recall_at_1=recall_at_k(rankings_q, relevant_ids, 1),
                recall_at_5=recall_at_k(rankings_q, relevant_ids, 5),
                recall_at_10=recall_at_k(rankings_q, relevant_ids, 10),
                mrr=mean_reciprocal_rank(rankings_q, relevant_ids),
                ndcg_at_10=ndcg_at_k(rankings_q, relevant_ids, 10),
                lang_filter="all",
            ))

    # --- Throughput ---
    print(f"  Measuring throughput ({n_throughput_reps} reps)...")
    embs_per_sec, p50, p95 = await measure_throughput(
        wrapper.embed_texts, queries[:min(10, len(queries))], n_throughput_reps
    )
    throughput = ThroughputStats(
        model_name=wrapper.name,
        embs_per_sec=embs_per_sec,
        latency_p50_ms=p50,
        latency_p95_ms=p95,
        dimension=q_embs.shape[-1],
        quantization="f32",
    )

    return {
        "base": base_metrics,
        "lang": lang_metrics,
        "matryoshka": matryoshka_results,
        "quantization": quant_results,
        "throughput": throughput,
    }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def _fmt_pct(v: float) -> str:
    """Format float as percentage string.

    Args:
        v: Float value between 0 and 1.

    Returns:
        Percentage string, e.g. '85.00%'.
    """
    return f"{v * 100:.2f}%"


def build_markdown_report(
    results: dict[str, Any],
    dataset_name: str,
    decision_threshold_pct: float = 3.0,
) -> str:
    """Build a markdown benchmark report from evaluation results.

    Args:
        results: Dict mapping model name to result dict from ``evaluate_model()``.
        dataset_name: Name of the dataset used.
        decision_threshold_pct: Allowed nDCG@10 lag in percentage points.

    Returns:
        Markdown report string.
    """
    lines = [
        "# Multimodal Embedding Benchmark Report",
        "",
        f"**Dataset**: {dataset_name}",
        f"**Decision gate**: UForm nDCG@10 must be within {decision_threshold_pct}% of baseline",
        "",
        "---",
        "",
        "## 1. Text Retrieval Quality (all languages, f32, full dimension)",
        "",
        "| Model | Dim | R@1 | R@5 | R@10 | MRR | nDCG@10 |",
        "|---|---|---|---|---|---|---|",
    ]
    baseline_ndcg: Optional[float] = None
    for model_name, res in results.items():
        m = res["base"]
        row = (
            f"| {m.model_name} | {m.dimension} "
            f"| {_fmt_pct(m.recall_at_1)} "
            f"| {_fmt_pct(m.recall_at_5)} "
            f"| {_fmt_pct(m.recall_at_10)} "
            f"| {_fmt_pct(m.mrr)} "
            f"| {_fmt_pct(m.ndcg_at_10)} |"
        )
        lines.append(row)
        if "baseline" in model_name.lower() and baseline_ndcg is None:
            baseline_ndcg = m.ndcg_at_10

    # Per-language
    lines += ["", "## 2. Per-Language Retrieval (f32, full dim)", ""]
    for model_name, res in results.items():
        if res.get("lang"):
            lines.append(f"### {model_name}")
            lines += [
                "| Lang | R@1 | R@5 | R@10 | MRR | nDCG@10 |",
                "|---|---|---|---|---|---|",
            ]
            for m in res["lang"]:
                lines.append(
                    f"| {m.lang_filter} "
                    f"| {_fmt_pct(m.recall_at_1)} "
                    f"| {_fmt_pct(m.recall_at_5)} "
                    f"| {_fmt_pct(m.recall_at_10)} "
                    f"| {_fmt_pct(m.mrr)} "
                    f"| {_fmt_pct(m.ndcg_at_10)} |"
                )
            lines.append("")

    # Matryoshka curve
    lines += ["## 3. Matryoshka Recall Curve (nDCG@10)", ""]
    for model_name, res in results.items():
        if res.get("matryoshka"):
            lines.append(f"### {model_name}")
            lines += [
                "| Dim | R@1 | R@10 | nDCG@10 |",
                "|---|---|---|---|",
            ]
            for m in res["matryoshka"]:
                lines.append(
                    f"| {m.dimension} "
                    f"| {_fmt_pct(m.recall_at_1)} "
                    f"| {_fmt_pct(m.recall_at_10)} "
                    f"| {_fmt_pct(m.ndcg_at_10)} |"
                )
            lines.append("")

    # Quantization delta
    lines += ["## 4. Quantization Recall Delta", ""]
    for model_name, res in results.items():
        if res.get("quantization"):
            lines.append(f"### {model_name}")
            lines += [
                "| Quant | R@1 | R@10 | nDCG@10 |",
                "|---|---|---|---|",
            ]
            for m in res["quantization"]:
                lines.append(
                    f"| {m.quantization} "
                    f"| {_fmt_pct(m.recall_at_1)} "
                    f"| {_fmt_pct(m.recall_at_10)} "
                    f"| {_fmt_pct(m.ndcg_at_10)} |"
                )
            lines.append("")

    # Throughput
    lines += ["## 5. Throughput (CPU)", ""]
    lines += [
        "| Model | emb/sec | p50 (ms) | p95 (ms) | Dim |",
        "|---|---|---|---|---|",
    ]
    for model_name, res in results.items():
        t = res["throughput"]
        lines.append(
            f"| {t.model_name} "
            f"| {t.embs_per_sec:.1f} "
            f"| {t.latency_p50_ms:.1f} "
            f"| {t.latency_p95_ms:.1f} "
            f"| {t.dimension} |"
        )

    # Decision gate
    lines += ["", "---", "", "## Decision Gate", ""]
    if baseline_ndcg is not None:
        for model_name, res in results.items():
            if "uform" in model_name.lower() or "multimodal" in model_name.lower():
                uform_ndcg = res["base"].ndcg_at_10
                lag = (baseline_ndcg - uform_ndcg) * 100
                verdict = "PASS" if lag <= decision_threshold_pct else "FAIL"
                lines.append(
                    f"- **{model_name}**: nDCG@10 = {_fmt_pct(uform_ndcg)}, "
                    f"baseline = {_fmt_pct(baseline_ndcg)}, "
                    f"lag = {lag:.2f}pp → **{verdict}** "
                    f"(threshold: {decision_threshold_pct}pp)"
                )
    else:
        lines.append(
            "_No baseline model found for decision gate comparison. "
            "Include a model named 'baseline' to activate this check._"
        )

    lines += [
        "",
        "---",
        "_Report generated by `benchmarks/multimodal_embedding_benchmark.py`_",
    ]
    return "\n".join(lines)


def write_csv(rows: list[dict], path: Path) -> None:
    """Write a list of dicts as CSV.

    Args:
        rows: List of dictionaries with identical keys.
        path: Output file path.
    """
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Returns:
        Configured ``ArgumentParser`` instance.
    """
    parser = argparse.ArgumentParser(
        description="Multimodal Embedding Benchmark for FEAT-229",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--synthetic-only",
        action="store_true",
        default=False,
        help="Use only the built-in synthetic fallback dataset (no model downloads).",
    )
    parser.add_argument(
        "--domain-data",
        metavar="CSV_PATH",
        default=None,
        help=(
            "Path to a real domain data CSV. Columns: query_id, query_text, "
            "relevant_doc_id, doc_text, lang. Merged with synthetic data unless "
            "--no-synthetic is set."
        ),
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        default="benchmark_results",
        help="Directory to write markdown report and CSV files (default: benchmark_results/).",
    )
    parser.add_argument(
        "--matryoshka-dims",
        nargs="+",
        type=int,
        default=[768, 512, 256, 128, 64],
        metavar="DIM",
        help="Matryoshka dimensions to evaluate (default: 768 512 256 128 64).",
    )
    parser.add_argument(
        "--skip-quantization",
        action="store_true",
        default=False,
        help="Skip quantization delta evaluation.",
    )
    parser.add_argument(
        "--throughput-reps",
        type=int,
        default=3,
        help="Number of throughput measurement repetitions (default: 3).",
    )
    parser.add_argument(
        "--uform-model",
        default="unum-cloud/uform3-image-text-multilingual-base",
        help="UForm model ID to benchmark.",
    )
    parser.add_argument(
        "--decision-threshold",
        type=float,
        default=3.0,
        metavar="PCT",
        help=(
            "Maximum allowed nDCG@10 lag in percentage points for the PASS verdict "
            "(default: 3.0)."
        ),
    )
    return parser


async def run_benchmark(args: argparse.Namespace) -> None:
    """Run the full benchmark pipeline.

    Args:
        args: Parsed CLI arguments.
    """
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Load dataset ---
    dataset: list[QueryDoc] = load_synthetic_data()
    dataset_name = "synthetic"

    if args.domain_data:
        extra = load_domain_data(args.domain_data)
        dataset = dataset + extra
        dataset_name = f"synthetic+{Path(args.domain_data).stem}"

    print("\n=== Multimodal Embedding Benchmark ===")
    print(f"Dataset: {dataset_name} ({len(dataset)} query/doc pairs)")
    print(f"Output dir: {output_dir}")

    # --- Import quantization modes ---
    quant_modes = None
    if not args.skip_quantization:
        try:
            from parrot.embeddings.multimodal.quantization import QuantizationMode
            quant_modes = [
                ("f32", QuantizationMode.F32),
                ("i8", QuantizationMode.I8),
                ("b1", QuantizationMode.B1),
            ]
        except ImportError:
            print("  [WARN] parrot.embeddings.multimodal not found; skipping quantization.")

    # --- Build model list ---
    models_to_run: list[ModelWrapper] = []

    # UForm multilingual-base (primary candidate)
    try:
        import uform  # noqa: F401
        models_to_run.append(UFormWrapper(
            model_id=args.uform_model,
            output_dim=None,
            quantization_label="f32",
        ))
        print(f"  + UForm model: {args.uform_model}")
    except ImportError:
        print("  [SKIP] uform not installed. Install with: uv pip install 'uform>=3.1'")

    # Baseline: lightweight HF model (if available and not synthetic-only)
    if not args.synthetic_only:
        try:
            from sentence_transformers import SentenceTransformer  # noqa: F401
            _baseline_id = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

            class HFBaseline(ModelWrapper):
                """Sentence-Transformers baseline wrapper."""

                def __init__(self, model_id: str) -> None:
                    super().__init__(
                        name=f"baseline({model_id.split('/')[-1]})",
                        provider_type="huggingface",
                        model_id=model_id,
                        dimension=384,
                        quantization_label="f32",
                    )
                    self._st_model: Any = None

                async def load(self) -> None:
                    loop = asyncio.get_event_loop()
                    self._st_model = await loop.run_in_executor(
                        None,
                        lambda: SentenceTransformer(self.model_id),
                    )

                async def embed_texts(self, texts: list[str]) -> np.ndarray:
                    loop = asyncio.get_event_loop()
                    embs = await loop.run_in_executor(
                        None,
                        lambda: self._st_model.encode(texts, normalize_embeddings=True),
                    )
                    return np.array(embs, dtype=np.float32)

                async def unload(self) -> None:
                    self._st_model = None

            models_to_run.append(HFBaseline(_baseline_id))
            print(f"  + Baseline: {_baseline_id}")
        except ImportError:
            print("  [SKIP] sentence-transformers not installed; no baseline.")

    if not models_to_run:
        print("\n[ERROR] No models available to benchmark. Install uform or sentence-transformers.")
        sys.exit(1)

    # --- Run evaluations ---
    all_results: dict[str, Any] = {}
    for wrapper in models_to_run:
        print(f"\n--- Evaluating: {wrapper.name} ---")
        try:
            await wrapper.load()
            result = await evaluate_model(
                wrapper=wrapper,
                dataset=dataset,
                matryoshka_dims=args.matryoshka_dims,
                quantization_modes=quant_modes,
                n_throughput_reps=args.throughput_reps,
                output_dir=output_dir,
            )
            all_results[wrapper.name] = result
        except Exception as exc:
            print(f"  [ERROR] {wrapper.name} failed: {exc}")
        finally:
            await wrapper.unload()

    if not all_results:
        print("\n[ERROR] No models produced results.")
        sys.exit(1)

    # --- Write CSVs ---
    base_rows = [r["base"].to_dict() for r in all_results.values()]
    write_csv(base_rows, output_dir / "retrieval_base.csv")

    lang_rows = [m.to_dict() for r in all_results.values() for m in r.get("lang", [])]
    if lang_rows:
        write_csv(lang_rows, output_dir / "retrieval_per_lang.csv")

    mat_rows = [m.to_dict() for r in all_results.values() for m in r.get("matryoshka", [])]
    if mat_rows:
        write_csv(mat_rows, output_dir / "matryoshka_curve.csv")

    quant_rows = [m.to_dict() for r in all_results.values() for m in r.get("quantization", [])]
    if quant_rows:
        write_csv(quant_rows, output_dir / "quantization_delta.csv")

    tp_rows = [
        {
            "model_name": r["throughput"].model_name,
            "embs_per_sec": f"{r['throughput'].embs_per_sec:.1f}",
            "p50_ms": f"{r['throughput'].latency_p50_ms:.1f}",
            "p95_ms": f"{r['throughput'].latency_p95_ms:.1f}",
            "dimension": r["throughput"].dimension,
        }
        for r in all_results.values()
    ]
    write_csv(tp_rows, output_dir / "throughput.csv")

    # --- Write markdown report ---
    report_md = build_markdown_report(
        all_results,
        dataset_name=dataset_name,
        decision_threshold_pct=args.decision_threshold,
    )
    report_path = output_dir / "report.md"
    report_path.write_text(report_md, encoding="utf-8")

    print("\n=== Benchmark complete ===")
    print(f"  Report  : {report_path}")
    print(f"  CSVs    : {list(output_dir.glob('*.csv'))}")
    print()
    # Print key decision gate lines from report
    for line in report_md.splitlines():
        if "PASS" in line or "FAIL" in line:
            print(f"  {line.strip()}")


def main() -> None:
    """Entry point for the benchmark CLI."""
    parser = build_argument_parser()
    args = parser.parse_args()
    asyncio.run(run_benchmark(args))


if __name__ == "__main__":
    main()
