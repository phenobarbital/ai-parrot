"""Deterministic, non-gating 1,000-row ingestion/search baseline (FEAT-542, AC10).

Records numbers. Asserts nothing. No latency or recall target was ever
supplied for this feature, so this script must not be turned into a gate.

Run:
    python examples/lancedb_benchmark.py --rows 1000 --dimension 8 \\
        --warmup 3 --samples 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "ai-parrot-embeddings" / "tests"))


def environment() -> dict:
    """Versions that make a recorded number interpretable."""
    import pyarrow

    try:
        import lancedb

        lancedb_version = lancedb.__version__
    except ImportError:
        lancedb_version = None
    return {
        "lancedb": lancedb_version,
        "pyarrow": pyarrow.__version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }


def _deterministic_corpus(rows: int) -> list[dict]:
    """A fixed, reproducible corpus recipe — same content every run."""
    return [
        {
            "id": f"row-{i}",
            "text": f"Deterministic benchmark document number {i} about topic {i % 25}",
            "metadata": {"source": "benchmark", "source_type": "synthetic"},
        }
        for i in range(rows)
    ]


async def run(rows: int, dimension: int, warmup: int, samples: int) -> dict:
    """Ingest, then time vector/FTS/hybrid over the same corpus."""
    import tempfile

    from lancedb_fixtures import DeterministicEmbedding

    from parrot.stores.lancedb import LanceDBStore
    from parrot.stores.models import Document

    with tempfile.TemporaryDirectory() as tmp:
        store = LanceDBStore(uri=tmp, dimension=dimension, embedding_id="benchmark-v1", collection_name="benchmark")
        store._embedding_callable_input = DeterministicEmbedding()

        docs = [
            Document(page_content=row["text"], metadata={**row["metadata"], "id": row["id"]})
            for row in _deterministic_corpus(rows)
        ]

        ingest_start = time.perf_counter()
        await store.from_documents(docs, collection="benchmark")
        ingest_elapsed = time.perf_counter() - ingest_start

        async def _timed_runs(coro_factory, n: int) -> list[float]:
            elapsed_samples: list[float] = []
            for _ in range(n):
                start = time.perf_counter()
                await coro_factory()
                elapsed_samples.append(time.perf_counter() - start)
            return elapsed_samples

        query = "deterministic benchmark document about topic 3"

        # Discard warmup runs — only the post-warmup samples are reported.
        await _timed_runs(lambda: store.similarity_search(query, limit=10), warmup)
        vector_samples = await _timed_runs(lambda: store.similarity_search(query, limit=10), samples)

        await _timed_runs(lambda: store.fulltext_search(query, limit=10), warmup)
        fts_samples = await _timed_runs(lambda: store.fulltext_search(query, limit=10), samples)

        await _timed_runs(lambda: store.hybrid_search(query, limit=10), warmup)
        hybrid_samples = await _timed_runs(lambda: store.hybrid_search(query, limit=10), samples)

        await store.disconnect()

    return {
        "rows": rows,
        "dimension": dimension,
        "warmup": warmup,
        "samples": samples,
        "ingest_seconds": ingest_elapsed,
        "vector_search_seconds": vector_samples,
        "fts_search_seconds": fts_samples,
        "hybrid_search_seconds": hybrid_samples,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--dimension", type=int, default=8)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--samples", type=int, default=10)
    args = parser.parse_args()

    result = {
        "environment": environment(),
        "corpus_recipe": "deterministic synthetic rows, see _deterministic_corpus()",
        "note": "NOT an SLO. No latency or recall target was supplied for this feature.",
        **(await run(args.rows, args.dimension, args.warmup, args.samples)),
    }

    log_dir = Path(__file__).resolve().parent.parent / "artifacts" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    out_path = log_dir / "lancedb-vector-store-benchmark.log"
    out_path.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
