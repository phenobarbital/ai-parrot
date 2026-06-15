"""CPU latency benchmark harness: models x backends x dimensions.

Measures embedding inference latency (p50 + p95), peak RSS memory, and
recall@k on a compliance PageIndex tree.  Results are written as JSON and
a human-readable markdown table.

Usage::

    # Quick smoke-run (N=5 repeats, no warmup):
    python -m benchmarks.pageindex_embedding_latency.harness \\
        --output-dir /tmp/bench_results --min-repeats 5 --warmup 0

    # Full benchmark against the compliance corpus:
    python -m benchmarks.pageindex_embedding_latency.harness \\
        --storage-dir corpus/compliance_soc2_hipaa/trees \\
        --tree-name nist_800_53 \\
        --output-dir benchmarks/pageindex_embedding_latency/results

Thread affinity
---------------
OMP_NUM_THREADS, MKL_NUM_THREADS, and OPENBLAS_NUM_THREADS are pinned to 1
at *import time* so that latency numbers are reproducible across machines
with different core counts.  Import this module **before** numpy/torch if
possible.
"""
from __future__ import annotations

# ── Pin BLAS/OMP threads BEFORE numpy import ────────────────────────────────
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("BLIS_NUM_THREADS", "1")
# ─────────────────────────────────────────────────────────────────────────────

import argparse
import gc
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

from .metrics import latency_percentiles, peak_rss_mb, recall_at_k
from .report import build_report

logger = logging.getLogger("benchmarks.pageindex_embedding_latency.harness")

# ---------------------------------------------------------------------------
# Benchmark matrix — models × backends × dimensions
# ---------------------------------------------------------------------------
BENCHMARK_MATRIX: list[dict[str, Any]] = [
    {
        "model": "Qwen/Qwen3-Embedding-0.6B",
        "backends": ["torch", "onnx"],
        "dims": [512, 256],
    },
    {
        "model": "Octen/Octen-Embedding-0.6B",
        "backends": ["torch", "onnx"],
        "dims": [512, 256],
    },
    {
        "model": "intfloat/multilingual-e5-small",
        "backends": ["torch"],
        "dims": [384],
    },
    {
        "model": "minishlab/potion-base-8M",
        "backends": ["torch"],
        "dims": [256],
    },
]

WARMUP_RUNS: int = 3
MIN_REPEATS: int = 30

# Latency gate: configurations above this threshold trigger a warning in the
# recommendation report (in milliseconds).
_DEFAULT_LATENCY_GATE_MS: float = 200.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_embed_fn(
    model_name: str,
    backend: str,
    dimension: int,
) -> Callable[[list[str]], np.ndarray]:
    """Create a synchronous embedding function for *model_name*/*backend*.

    Args:
        model_name: HuggingFace-style model identifier.
        backend: One of ``"torch"`` or ``"onnx"``.
        dimension: Target output dimension (used for Matryoshka truncation).

    Returns:
        A callable ``embed_fn(texts: list[str]) -> np.ndarray`` that returns
        an ``(N, dimension)`` float32 matrix.

    Raises:
        ImportError: If the required backend library is not installed.
        RuntimeError: If the model cannot be loaded.
    """
    from parrot.embeddings.registry import EmbeddingRegistry

    registry = EmbeddingRegistry.instance()
    wrapper = registry.get_or_create_sync(
        model_name,
        model_type="huggingface",
        backend=backend,
    )
    raw_model = wrapper.model

    def embed_fn(texts: list[str]) -> np.ndarray:
        result = raw_model.encode(texts, convert_to_numpy=True)
        arr = np.asarray(result, dtype=np.float32)
        # Truncate to requested dimension (Matryoshka)
        if arr.ndim == 2 and arr.shape[1] > dimension:
            arr = arr[:, :dimension]
        return arr

    return embed_fn


def _time_embed(
    embed_fn: Callable[[list[str]], np.ndarray],
    texts: list[str],
    n_warmup: int,
    n_repeats: int,
) -> list[float]:
    """Run *embed_fn* with warmup, returning a list of elapsed-second timings.

    Args:
        embed_fn: Synchronous embedding callable.
        texts: Batch of texts to embed on each repeat.
        n_warmup: Number of warmup calls whose timings are discarded.
        n_repeats: Number of timed repetitions.

    Returns:
        List of elapsed-second durations (length == *n_repeats*).
    """
    # Warmup
    for _ in range(n_warmup):
        embed_fn(texts)

    gc.collect()
    timings: list[float] = []
    for _ in range(n_repeats):
        t0 = time.perf_counter()
        embed_fn(texts)
        timings.append(time.perf_counter() - t0)
    return timings


def _build_probe_texts(n: int = 50) -> list[str]:
    """Return a list of *n* synthetic probe texts for latency measurement.

    Args:
        n: Number of texts to generate.

    Returns:
        List of short strings representative of PageIndex node summaries.
    """
    templates = [
        "Access control policy for {domain} systems",
        "Encryption requirements for data at rest in {domain}",
        "Audit log retention policy for {domain} environments",
        "Incident response procedure for {domain} security breaches",
        "Vulnerability management for {domain} infrastructure",
    ]
    domains = [
        "cloud", "on-premise", "mobile", "IoT", "network",
        "application", "database", "API", "microservices", "container",
    ]
    texts = []
    for i in range(n):
        tpl = templates[i % len(templates)]
        dom = domains[i % len(domains)]
        texts.append(tpl.format(domain=dom))
    return texts


def _load_oracle(storage_dir: Optional[Path], tree_name: Optional[str]) -> dict[str, list[str]]:
    """Load or synthesise a recall oracle for recall@k computation.

    The oracle maps query texts to lists of relevant node IDs.  When no real
    tree is available, a trivial synthetic oracle is returned (all queries
    map to an empty relevant set, giving recall = 0 regardless of retrieval).

    Args:
        storage_dir: Directory containing pre-built PageIndex trees.
        tree_name: Name of the compliance tree to load.

    Returns:
        Mapping ``{query_text: [relevant_node_id, ...]}``.
    """
    if storage_dir is None or tree_name is None:
        return {}
    tree_file = storage_dir / f"{tree_name}.json"
    if not tree_file.exists():
        logger.warning("Tree file not found: %s — recall@k will be 0", tree_file)
        return {}
    try:
        data = json.loads(tree_file.read_text())
        structure = data.get("structure", [])
        if not structure:
            return {}
        # Flatten the tree using the same utility used by hybrid_search.
        from parrot.knowledge.pageindex.utils import get_nodes
        flat_nodes: list[dict] = get_nodes(structure)
        if not flat_nodes:
            return {}
        # Use first-level nodes as a simple oracle: each node is its own
        # relevant result for the query formed from its title/summary.
        oracle: dict[str, list[str]] = {}
        for node in flat_nodes[:20]:
            node_id = node.get("node_id", "")
            if not node_id:
                continue
            title = node.get("title", "")
            summary = node.get("summary") or node.get("prefix_summary", "")
            query = f"{title} {summary}".strip()
            if query:
                oracle[query] = [node_id]
        return oracle
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load oracle from %s: %s", tree_file, exc)
        return {}


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------


def run_configuration(
    model_name: str,
    backend: str,
    dimension: int,
    n_warmup: int = WARMUP_RUNS,
    n_repeats: int = MIN_REPEATS,
    oracle: Optional[dict[str, list[str]]] = None,
) -> dict[str, Any]:
    """Benchmark a single model/backend/dimension configuration.

    Args:
        model_name: HuggingFace model identifier.
        backend: One of ``"torch"`` or ``"onnx"``.
        dimension: Output embedding dimension.
        n_warmup: Warmup runs to discard (default :data:`WARMUP_RUNS`).
        n_repeats: Timed repetitions (must be >= :data:`MIN_REPEATS`).
        oracle: Optional recall oracle ``{query: [relevant_ids]}``.

    Returns:
        Dictionary with keys: ``model``, ``backend``, ``dimension``,
        ``p50_ms``, ``p95_ms``, ``p99_ms``, ``mean_ms``, ``std_ms``,
        ``rss_mb``, ``recall_at_10``, ``n_repeats``, ``error``.
    """
    result: dict[str, Any] = {
        "model": model_name,
        "backend": backend,
        "dimension": dimension,
        "p50_ms": None,
        "p95_ms": None,
        "p99_ms": None,
        "mean_ms": None,
        "std_ms": None,
        "rss_mb": None,
        "recall_at_10": None,
        "n_repeats": n_repeats,
        "error": None,
    }

    logger.info(
        "[%s | %s | dim=%d] Loading model …", model_name, backend, dimension
    )
    try:
        embed_fn = _make_embed_fn(model_name, backend, dimension)
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"load_failed: {exc}"
        logger.error(
            "[%s | %s | dim=%d] Load error: %s", model_name, backend, dimension, exc
        )
        return result

    probe_texts = _build_probe_texts(n=50)
    logger.info(
        "[%s | %s | dim=%d] Warming up (%d runs) …",
        model_name, backend, dimension, n_warmup,
    )

    try:
        timings = _time_embed(embed_fn, probe_texts, n_warmup, n_repeats)
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"bench_failed: {exc}"
        logger.error(
            "[%s | %s | dim=%d] Bench error: %s", model_name, backend, dimension, exc
        )
        return result

    stats = latency_percentiles(timings)
    rss = peak_rss_mb()

    result["p50_ms"] = round(stats["p50"] * 1000, 3)
    result["p95_ms"] = round(stats["p95"] * 1000, 3)
    result["p99_ms"] = round(stats["p99"] * 1000, 3)
    result["mean_ms"] = round(stats["mean"] * 1000, 3)
    result["std_ms"] = round(stats["std"] * 1000, 3)
    result["rss_mb"] = round(rss, 1)

    # recall@k using oracle (if provided)
    if oracle:
        queries = list(oracle.keys())[:10]
        recalls: list[float] = []
        for query in queries:
            relevant = oracle[query]
            # embed query + retrieve by cosine similarity from probe corpus
            try:
                q_emb = embed_fn([query])
                corpus_emb = embed_fn(probe_texts)
                q_norm = q_emb / (np.linalg.norm(q_emb, axis=1, keepdims=True) + 1e-9)
                c_norm = corpus_emb / (
                    np.linalg.norm(corpus_emb, axis=1, keepdims=True) + 1e-9
                )
                scores = (q_norm @ c_norm.T)[0]
                ranked_idx = np.argsort(-scores)[:10]
                retrieved_ids = [str(i) for i in ranked_idx]
                recalls.append(recall_at_k(retrieved_ids, relevant, k=10))
            except Exception as exc:  # noqa: BLE001
                logger.debug("recall@k computation failed: %s", exc)
        if recalls:
            result["recall_at_10"] = round(float(np.mean(recalls)), 4)

    logger.info(
        "[%s | %s | dim=%d] p50=%.1f ms  p95=%.1f ms  RSS=%.0f MB",
        model_name,
        backend,
        dimension,
        result["p50_ms"],
        result["p95_ms"],
        result["rss_mb"],
    )
    return result


def run_matrix(
    matrix: list[dict[str, Any]] = BENCHMARK_MATRIX,
    n_warmup: int = WARMUP_RUNS,
    n_repeats: int = MIN_REPEATS,
    oracle: Optional[dict[str, list[str]]] = None,
) -> list[dict[str, Any]]:
    """Run the full benchmark matrix and return all results.

    Args:
        matrix: List of ``{model, backends, dims}`` entries.  Defaults to
            :data:`BENCHMARK_MATRIX`.
        n_warmup: Warmup runs per configuration.
        n_repeats: Timed repetitions per configuration.
        oracle: Optional recall oracle.

    Returns:
        List of result dictionaries, one per (model, backend, dimension) tuple.
    """
    results: list[dict[str, Any]] = []
    for entry in matrix:
        model = entry["model"]
        for backend in entry["backends"]:
            for dim in entry["dims"]:
                r = run_configuration(
                    model_name=model,
                    backend=backend,
                    dimension=dim,
                    n_warmup=n_warmup,
                    n_repeats=n_repeats,
                    oracle=oracle,
                )
                results.append(r)
    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for ``python -m benchmarks.pageindex_embedding_latency.harness``.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code (0 = success, 1 = error).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(
        description="PageIndex embedding latency benchmark"
    )
    parser.add_argument(
        "--storage-dir",
        default=None,
        help="Directory containing pre-built PageIndex trees (optional)",
    )
    parser.add_argument(
        "--tree-name",
        default="nist_800_53",
        help="Name of the compliance tree for oracle loading (default: nist_800_53)",
    )
    parser.add_argument(
        "--output-dir",
        default="benchmarks/pageindex_embedding_latency/results",
        help="Directory for JSON + markdown output",
    )
    parser.add_argument(
        "--min-repeats",
        type=int,
        default=MIN_REPEATS,
        help=f"Minimum timed repetitions per config (default: {MIN_REPEATS})",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=WARMUP_RUNS,
        help=f"Warmup runs to discard (default: {WARMUP_RUNS})",
    )
    parser.add_argument(
        "--latency-gate-ms",
        type=float,
        default=_DEFAULT_LATENCY_GATE_MS,
        help=(
            f"p95 latency threshold in ms above which a warning is emitted"
            f" (default: {_DEFAULT_LATENCY_GATE_MS})"
        ),
    )
    parser.add_argument(
        "--model",
        action="append",
        dest="models",
        default=None,
        help="Restrict to specific model (can be repeated)",
    )
    args = parser.parse_args(argv)

    n_repeats = max(args.min_repeats, MIN_REPEATS)
    storage_dir = Path(args.storage_dir) if args.storage_dir else None
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build oracle
    oracle = _load_oracle(storage_dir, args.tree_name)

    # Filter matrix if --model supplied
    matrix = BENCHMARK_MATRIX
    if args.models:
        requested = set(args.models)
        matrix = [e for e in BENCHMARK_MATRIX if e["model"] in requested]
        if not matrix:
            logger.error("No matching models in BENCHMARK_MATRIX for: %s", args.models)
            return 1

    logger.info(
        "Running benchmark matrix: %d configurations, %d repeats each",
        sum(len(e["backends"]) * len(e["dims"]) for e in matrix),
        n_repeats,
    )

    results = run_matrix(
        matrix=matrix,
        n_warmup=args.warmup,
        n_repeats=n_repeats,
        oracle=oracle,
    )

    # Write JSON
    json_path = output_dir / "results.json"
    json_path.write_text(json.dumps(results, indent=2))
    logger.info("JSON results written to %s", json_path)

    # Write markdown + recommendation
    md_path = output_dir / "report.md"
    report_md = build_report(results, latency_gate_ms=args.latency_gate_ms)
    md_path.write_text(report_md)
    logger.info("Markdown report written to %s", md_path)

    # Print summary table to stdout
    print(report_md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
