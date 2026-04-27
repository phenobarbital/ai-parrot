#!/usr/bin/env python3
"""Reproducible benchmark harness for the AI-Parrot reranker subsystem.

Computes nDCG@5, MRR, and P50/P95 latency for each supported cross-encoder
model on CPU (and CUDA when available) using a labelled evaluation dataset.

Usage::

    python scripts/benchmark_reranker.py \\
        --models minilm \\
        --device cpu \\
        --eval-set tests/data/reranker_eval/eval_set.json \\
        --max-queries 10

Outputs:

- Markdown table to stdout.
- JSON artifact to ``artifacts/benchmarks/reranker-<date>.json``.

Exit codes:

- 0: All benchmarks completed successfully.
- 1: Fatal error (missing eval set, import failure, etc.).

Note:
    ``bge`` and ``jina`` model downloads are skipped in CI to avoid long
    download times.  Use ``--models minilm`` for CI runs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Capture original CWD before parrot is imported.
# parrot.conf calls os.chdir() to the project root during initialisation, which
# would break relative paths supplied via --eval-set / --output-dir.
# We resolve those paths against _INVOCATION_DIR in main() before the import
# has had a chance to change the working directory.
# ---------------------------------------------------------------------------
_INVOCATION_DIR: Path = Path(os.getcwd()).resolve()

# ---------------------------------------------------------------------------
# Validate that the package is importable before doing anything else
# ---------------------------------------------------------------------------
try:
    # Allow running from the packages/ai-parrot/ directory
    _src_path = Path(__file__).parent.parent / "src"
    if _src_path.exists():
        sys.path.insert(0, str(_src_path))

    from parrot.rerankers import LocalCrossEncoderReranker, RerankerConfig
    from parrot.stores.models import SearchResult
except ImportError as _e:
    print(f"[ERROR] Cannot import parrot.rerankers: {_e}", file=sys.stderr)
    print(
        "Make sure you run this script from the packages/ai-parrot directory "
        "with the virtual environment activated.",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------
MODEL_ALIASES: dict[str, str] = {
    "minilm": "cross-encoder/ms-marco-MiniLM-L-12-v2",
    "bge": "BAAI/bge-reranker-v2-m3",
    "jina": "jinaai/jina-reranker-v2-base-multilingual",
}

TRUST_REMOTE_CODE: dict[str, bool] = {
    "jina": True,
}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def compute_ndcg_at_k(
    relevances_in_rank_order: list[int],
    k: int = 5,
) -> float:
    """Compute nDCG@k for a single query.

    Args:
        relevances_in_rank_order: Relevance scores of retrieved documents
            in the order they were returned by the reranker.
        k: Cutoff rank.

    Returns:
        nDCG@k score in [0, 1].
    """
    if not relevances_in_rank_order:
        return 0.0

    # DCG@k of the reranker output
    dcg = 0.0
    for i, rel in enumerate(relevances_in_rank_order[:k]):
        dcg += (2**rel - 1) / math.log2(i + 2)

    # Ideal DCG@k (ideal ordering)
    ideal_rels = sorted(relevances_in_rank_order, reverse=True)
    idcg = 0.0
    for i, rel in enumerate(ideal_rels[:k]):
        idcg += (2**rel - 1) / math.log2(i + 2)

    return (dcg / idcg) if idcg > 0 else 0.0


def compute_mrr(
    relevances_in_rank_order: list[int],
    relevance_threshold: int = 1,
) -> float:
    """Compute Mean Reciprocal Rank for a single query.

    Args:
        relevances_in_rank_order: Relevance scores in reranker order.
        relevance_threshold: Minimum relevance to count as a hit.

    Returns:
        Reciprocal rank, or 0.0 if no relevant document found.
    """
    for i, rel in enumerate(relevances_in_rank_order):
        if rel >= relevance_threshold:
            return 1.0 / (i + 1)
    return 0.0


def percentile(values: list[float], p: float) -> float:
    """Compute the p-th percentile of a sorted list.

    Args:
        values: Unsorted numeric values.
        p: Percentile in [0, 100].

    Returns:
        p-th percentile value.
    """
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = (p / 100) * (len(sorted_v) - 1)
    lower = int(idx)
    upper = min(lower + 1, len(sorted_v) - 1)
    frac = idx - lower
    return sorted_v[lower] * (1 - frac) + sorted_v[upper] * frac


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------


async def benchmark_model(
    model_alias: str,
    model_name: str,
    device: str,
    eval_data: list[dict[str, Any]],
    trust_remote_code: bool = False,
    top_n: int = 5,
    max_queries: int | None = None,
) -> dict[str, Any]:
    """Run the benchmark for a single (model, device) combination.

    Args:
        model_alias: Short alias (e.g. "minilm").
        model_name: Full HuggingFace model ID.
        device: "cpu" or "cuda".
        eval_data: Evaluation dataset loaded from JSON.
        trust_remote_code: Whether the model requires trust_remote_code=True.
        top_n: Rank cutoff for nDCG and MRR.
        max_queries: If set, only evaluate this many queries.

    Returns:
        Dictionary of benchmark results for this run.
    """
    print(f"\n  Loading {model_alias} ({model_name}) on {device} …", flush=True)

    # Determine precision
    try:
        import torch

        precision = "auto"
    except ImportError:
        precision = "fp32"

    try:
        reranker = LocalCrossEncoderReranker(
            config=RerankerConfig(
                model_name=model_name,
                device=device,
                precision=precision,
                warmup=True,
                trust_remote_code=trust_remote_code,
            )
        )
    except Exception as exc:
        print(f"  [SKIP] Failed to load {model_name}: {exc}")
        return {
            "model_alias": model_alias,
            "model_name": model_name,
            "device": device,
            "status": "failed",
            "error": str(exc),
        }

    queries = eval_data[:max_queries] if max_queries else eval_data
    ndcg_scores: list[float] = []
    mrr_scores: list[float] = []
    latencies_ms: list[float] = []

    print(f"  Evaluating {len(queries)} queries …", flush=True)
    for item in queries:
        query = item["query"]
        passages = item["passages"]
        relevance_by_id = {p["id"]: p["relevance"] for p in passages}

        docs = [
            SearchResult(
                id=p["id"],
                content=p["text"],
                metadata={},
                score=0.9,  # placeholder cosine score
            )
            for p in passages
        ]

        t0 = time.monotonic()
        try:
            reranked = await reranker.rerank(query, docs, top_n=len(docs))
        except Exception as exc:
            print(f"  [WARN] rerank failed for query '{query[:50]}': {exc}")
            continue
        latency_ms = (time.monotonic() - t0) * 1000.0
        latencies_ms.append(latency_ms)

        # Build relevance list in reranker-returned order
        relevances_ranked = [relevance_by_id[r.document.id] for r in reranked]
        ndcg = compute_ndcg_at_k(relevances_ranked, k=top_n)
        mrr = compute_mrr(relevances_ranked)
        ndcg_scores.append(ndcg)
        mrr_scores.append(mrr)

    if not ndcg_scores:
        return {
            "model_alias": model_alias,
            "model_name": model_name,
            "device": device,
            "status": "no_results",
        }

    avg_ndcg = sum(ndcg_scores) / len(ndcg_scores)
    avg_mrr = sum(mrr_scores) / len(mrr_scores)
    p50_ms = percentile(latencies_ms, 50)
    p95_ms = percentile(latencies_ms, 95)

    print(
        f"  ✓ nDCG@{top_n}={avg_ndcg:.4f}  MRR={avg_mrr:.4f}  "
        f"P50={p50_ms:.1f}ms  P95={p95_ms:.1f}ms",
        flush=True,
    )

    return {
        "model_alias": model_alias,
        "model_name": model_name,
        "device": device,
        "precision": reranker._precision,
        "num_queries": len(ndcg_scores),
        "ndcg_at_5": round(avg_ndcg, 4),
        "mrr": round(avg_mrr, 4),
        "p50_latency_ms": round(p50_ms, 1),
        "p95_latency_ms": round(p95_ms, 1),
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def format_markdown_table(results: list[dict[str, Any]]) -> str:
    """Format benchmark results as a Markdown table.

    Args:
        results: List of per-run result dictionaries.

    Returns:
        Markdown-formatted table string.
    """
    header = (
        "| Model | Device | Precision | nDCG@5 | MRR | P50 (ms) | P95 (ms) | Status |\n"
        "|-------|--------|-----------|--------|-----|----------|----------|--------|\n"
    )
    rows = []
    for r in results:
        if r.get("status") != "ok":
            row = (
                f"| {r.get('model_alias', 'N/A')} "
                f"| {r.get('device', 'N/A')} "
                f"| N/A | N/A | N/A | N/A | N/A "
                f"| {r.get('status', 'N/A')} |"
            )
        else:
            row = (
                f"| {r['model_alias']} "
                f"| {r['device']} "
                f"| {r['precision']} "
                f"| {r['ndcg_at_5']:.4f} "
                f"| {r['mrr']:.4f} "
                f"| {r['p50_latency_ms']:.1f} "
                f"| {r['p95_latency_ms']:.1f} "
                f"| ok |"
            )
        rows.append(row)
    return header + "\n".join(rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        description="Benchmark AI-Parrot reranker models.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--models",
        default="minilm",
        help="Comma-separated model aliases: minilm,bge,jina",
    )
    parser.add_argument(
        "--device",
        default="auto",
        help="Device: 'auto' | 'cpu' | 'cuda'",
    )
    parser.add_argument(
        "--eval-set",
        default="tests/data/reranker_eval/eval_set.json",
        help="Path to evaluation dataset JSON.",
    )
    parser.add_argument(
        "--max-queries",
        type=int,
        default=None,
        help="Limit number of queries evaluated (useful for quick CI runs).",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=5,
        help="Rank cutoff for nDCG and MRR.",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/benchmarks",
        help="Directory for the JSON artifact.",
    )
    return parser.parse_args()


async def main() -> int:
    """Run the benchmark harness.

    Returns:
        Exit code (0 = success, 1 = failure).
    """
    args = parse_args()

    # Resolve eval_set and output_dir paths against the invocation directory.
    # parrot.conf changes os.getcwd() to the project root on import, so relative
    # paths must be anchored to where the user invoked the script from.
    eval_path = Path(args.eval_set)
    if not eval_path.is_absolute():
        eval_path = _INVOCATION_DIR / eval_path
    eval_path = eval_path.resolve()

    if not eval_path.exists():
        print(f"[ERROR] Eval set not found: {eval_path}", file=sys.stderr)
        return 1

    with eval_path.open() as f:
        eval_data = json.load(f)
    print(f"Loaded {len(eval_data)} queries from {eval_path}")

    # Resolve device(s)
    try:
        import torch

        auto_device = "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        auto_device = "cpu"

    if args.device == "auto":
        devices = ["cpu"]
        if auto_device == "cuda":
            devices.append("cuda")
    else:
        devices = [args.device]

    # Resolve models
    model_aliases = [m.strip() for m in args.models.split(",")]
    unknown = set(model_aliases) - set(MODEL_ALIASES)
    if unknown:
        print(f"[ERROR] Unknown model aliases: {unknown}", file=sys.stderr)
        print(f"Available: {list(MODEL_ALIASES.keys())}", file=sys.stderr)
        return 1

    print(f"\nBenchmarking: models={model_aliases}  devices={devices}")
    print(f"Queries: {args.max_queries or len(eval_data)}")

    results = []
    for alias in model_aliases:
        model_name = MODEL_ALIASES[alias]
        trust_remote_code = TRUST_REMOTE_CODE.get(alias, False)
        for device in devices:
            result = await benchmark_model(
                model_alias=alias,
                model_name=model_name,
                device=device,
                eval_data=eval_data,
                trust_remote_code=trust_remote_code,
                top_n=args.top_n,
                max_queries=args.max_queries,
            )
            results.append(result)

    # Print markdown table
    print("\n## Benchmark Results\n")
    print(format_markdown_table(results))

    # Write JSON artifact (resolve output_dir against invocation CWD)
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = _INVOCATION_DIR / output_dir
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    artifact_path = output_dir / f"reranker-{date_str}.json"
    artifact = {
        "benchmark_timestamp": datetime.now(timezone.utc).isoformat(),
        "eval_set": str(eval_path),
        "total_queries_available": len(eval_data),
        "max_queries_evaluated": args.max_queries,
        "top_n": args.top_n,
        "results": results,
    }
    with artifact_path.open("w") as f:
        json.dump(artifact, f, indent=2)
    print(f"\nJSON artifact written to: {artifact_path}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
