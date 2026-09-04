#!/usr/bin/env python3
"""OQ3 spike — KNN under graph filter vs. graph expansion from KNN survivors.

FEAT-520 TASK-2770, the FIRST task of Module 7 (spec §8 OQ3): pgvector KNN
restricted to a small graph-expansion "hood" can defeat the ANN index
(exact scan wins for small hoods; the index only pays off unfiltered or
with pgvector's iterative-scan feature). This spike seeds a throwaway
schema with a synthetic-but-realistic corpus (scale-free edge graph,
random embeddings, a fraction of nodes carrying a second temporal
generation) and measures both retrieval directions plus an HNSW-vs
-IVFFlat comparison, so ``hybrid_retrieve`` (TASK-2771) can freeze its CTE
order on evidence instead of a guess.

**Deliverable is the report this script prints/writes — NOT production
code.** See ``artifacts/logs/feat-520-oq3-spike.md`` for the findings and
the two recorded decisions.

Usage::

    python packages/ai-parrot/scripts/benchmark_graph_knn.py \\
        --dsn postgres://... --corpus-size 5000 --seed 42

Exit codes:

- 0: Spike completed successfully (numbers may still show a loss — that
     is a valid, honest result, not a failure).
- 1: Fatal error (no DSN resolved, DB unreachable, harness broke).
"""

from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_src_path = Path(__file__).parent.parent / "src"
if _src_path.exists():
    sys.path.insert(0, str(_src_path))

try:
    import asyncpg

    from parrot.conf import default_dsn
    from parrot.knowledge.graphindex.pg_schema import (
        GRAPHINDEX_EMBEDDING_DIM,
        create_pg_pool,
        ensure_ann_index,
        ensure_schema,
    )
except ImportError as exc:  # pragma: no cover - environment guard
    print(f"[ERROR] Cannot import parrot/asyncpg: {exc}", file=sys.stderr)
    sys.exit(1)


def _random_vector(rng: random.Random, dim: int) -> list[float]:
    """A random unit-ish vector — cosine distance is scale-invariant."""
    return [rng.gauss(0.0, 1.0) for _ in range(dim)]


async def seed_corpus(
    pool: asyncpg.Pool,
    schema: str,
    *,
    corpus_size: int,
    dim: int,
    rng: random.Random,
    attach_m: int = 3,
    second_generation_fraction: float = 0.2,
) -> dict[str, Any]:
    """Seed a synthetic scale-free corpus with embeddings and history.

    Barabási–Albert-style preferential attachment (each new node connects
    to ``attach_m`` existing nodes, weighted by current degree) — a
    realistic-shaped graph without needing a real corpus (spec's own
    NOT-in-scope note: a real-corpus re-run belongs to legal-wiki work).

    Args:
        pool: asyncpg pool for the throwaway schema.
        schema: Schema name.
        corpus_size: Number of concepts to create.
        dim: Embedding dimension.
        rng: Seeded RNG (reproducibility).
        attach_m: Preferential-attachment edges per new node.
        second_generation_fraction: Fraction of nodes given a SECOND
            (closed) temporal version, simulating history.

    Returns:
        ``{"nodes": N, "edges": M, "second_gen": K}``.
    """
    degree: dict[str, int] = {}
    concept_ids: list[str] = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            for i in range(corpus_size):
                cid = f"c{i}"
                await conn.execute(
                    f"INSERT INTO {schema}.nodes (concept_id, category) VALUES ($1, 'concept')",
                    cid,
                )
                version_id = await conn.fetchval(
                    f"""
                    INSERT INTO {schema}.node_versions (concept_id, title)
                    VALUES ($1, $2) RETURNING version_id
                    """,
                    cid,
                    f"Concept {i}",
                )
                await conn.execute(
                    f"""
                    INSERT INTO {schema}.embeddings (concept_id, version_id, embedding)
                    VALUES ($1, $2, $3)
                    """,
                    cid,
                    version_id,
                    _random_vector(rng, dim),
                )

                if concept_ids:
                    pool_ids = concept_ids
                    weights = [degree.get(c, 1) for c in pool_ids]
                    k = min(attach_m, len(pool_ids))
                    targets = rng.choices(pool_ids, weights=weights, k=k)
                    for tgt in set(targets):
                        await conn.execute(
                            f"INSERT INTO {schema}.edges (src, dst, rel) VALUES ($1, $2, 'relates_to')",
                            cid,
                            tgt,
                        )
                        degree[cid] = degree.get(cid, 0) + 1
                        degree[tgt] = degree.get(tgt, 0) + 1

                concept_ids.append(cid)

            second_gen = 0
            for cid in rng.sample(concept_ids, k=int(corpus_size * second_generation_fraction)):
                await conn.execute(
                    f"""
                    UPDATE {schema}.node_versions
                    SET validity = tstzrange(lower(validity), now())
                    WHERE concept_id = $1 AND upper_inf(validity)
                    """,
                    cid,
                )
                await conn.execute(
                    f"INSERT INTO {schema}.node_versions (concept_id, title) VALUES ($1, $2)",
                    cid,
                    f"Concept {cid} v2",
                )
                second_gen += 1

    edge_count = sum(degree.values()) // 2
    return {"nodes": corpus_size, "edges": edge_count, "second_gen": second_gen}


async def _timed(coro_fn, runs: int) -> tuple[float, list[float]]:
    """Run ``coro_fn`` ``runs`` times, return (median_seconds, all_seconds)."""
    samples: list[float] = []
    for _ in range(runs):
        start = time.monotonic()
        await coro_fn()
        samples.append(time.monotonic() - start)
    return statistics.median(samples), samples


async def bench_graph_to_semantic(
    pool: asyncpg.Pool, schema: str, seed_id: str, depth: int, query_vec: list[float], k: int, runs: int
) -> dict[str, Any]:
    """Recursive-CTE hood expansion first, KNN restricted to the hood (exact scan)."""

    async def _run() -> None:
        async with pool.acquire() as conn:
            await conn.fetch(
                f"""
                WITH RECURSIVE hood AS (
                    SELECT $1::text AS concept_id, 0 AS depth
                    UNION
                    SELECT CASE WHEN e.src = h.concept_id THEN e.dst ELSE e.src END, h.depth + 1
                    FROM {schema}.edges e JOIN hood h
                        ON (e.src = h.concept_id OR e.dst = h.concept_id)
                    WHERE h.depth < $2
                )
                SELECT emb.concept_id, emb.embedding <=> $3 AS dist
                FROM {schema}.embeddings emb
                JOIN {schema}.node_versions nv ON nv.version_id = emb.version_id
                WHERE upper_inf(nv.validity)
                  AND nv.concept_id IN (SELECT DISTINCT concept_id FROM hood)
                ORDER BY dist LIMIT $4
                """,
                seed_id,
                depth,
                query_vec,
                k,
            )

    median_s, samples = await _timed(_run, runs)

    async with pool.acquire() as conn:
        hood_size = await conn.fetchval(
            f"""
            WITH RECURSIVE hood AS (
                SELECT $1::text AS concept_id, 0 AS depth
                UNION
                SELECT CASE WHEN e.src = h.concept_id THEN e.dst ELSE e.src END, h.depth + 1
                FROM {schema}.edges e JOIN hood h ON (e.src = h.concept_id OR e.dst = h.concept_id)
                WHERE h.depth < $2
            )
            SELECT COUNT(DISTINCT concept_id) FROM hood
            """,
            seed_id,
            depth,
        )
        explain_rows = await conn.fetch(
            f"""
            EXPLAIN (ANALYZE, BUFFERS)
            WITH RECURSIVE hood AS (
                SELECT $1::text AS concept_id, 0 AS depth
                UNION
                SELECT CASE WHEN e.src = h.concept_id THEN e.dst ELSE e.src END, h.depth + 1
                FROM {schema}.edges e JOIN hood h ON (e.src = h.concept_id OR e.dst = h.concept_id)
                WHERE h.depth < $2
            )
            SELECT emb.concept_id, emb.embedding <=> $3 AS dist
            FROM {schema}.embeddings emb
            JOIN {schema}.node_versions nv ON nv.version_id = emb.version_id
            WHERE upper_inf(nv.validity) AND nv.concept_id IN (SELECT DISTINCT concept_id FROM hood)
            ORDER BY dist LIMIT $4
            """,
            seed_id,
            depth,
            query_vec,
            k,
        )
    return {
        "depth": depth,
        "hood_size": hood_size,
        "median_s": median_s,
        "samples_s": samples,
        "explain": "\n".join(r["QUERY PLAN"] for r in explain_rows),
    }


async def bench_semantic_to_graph(
    pool: asyncpg.Pool, schema: str, seed_id: str, depth: int, query_vec: list[float], k: int, runs: int
) -> dict[str, Any]:
    """KNN top-K first (ANN, unrestricted), then check hood membership of survivors."""

    async def _run() -> None:
        async with pool.acquire() as conn:
            survivors = await conn.fetch(
                f"""
                SELECT emb.concept_id FROM {schema}.embeddings emb
                JOIN {schema}.node_versions nv ON nv.version_id = emb.version_id
                WHERE upper_inf(nv.validity)
                ORDER BY emb.embedding <=> $1 LIMIT $2
                """,
                query_vec,
                k,
            )
            survivor_ids = [r["concept_id"] for r in survivors]
            if survivor_ids:
                await conn.fetch(
                    f"""
                    WITH RECURSIVE hood AS (
                        SELECT $1::text AS concept_id, 0 AS depth
                        UNION
                        SELECT CASE WHEN e.src = h.concept_id THEN e.dst ELSE e.src END, h.depth + 1
                        FROM {schema}.edges e JOIN hood h ON (e.src = h.concept_id OR e.dst = h.concept_id)
                        WHERE h.depth < $2
                    )
                    SELECT concept_id FROM hood WHERE concept_id = ANY($3::text[])
                    """,
                    seed_id,
                    depth,
                    survivor_ids,
                )

    median_s, samples = await _timed(_run, runs)

    async with pool.acquire() as conn:
        explain_rows = await conn.fetch(
            f"""
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT emb.concept_id FROM {schema}.embeddings emb
            JOIN {schema}.node_versions nv ON nv.version_id = emb.version_id
            WHERE upper_inf(nv.validity)
            ORDER BY emb.embedding <=> $1 LIMIT $2
            """,
            query_vec,
            k,
        )
    return {
        "depth": depth,
        "median_s": median_s,
        "samples_s": samples,
        "explain": "\n".join(r["QUERY PLAN"] for r in explain_rows),
    }


async def bench_ann_index_type(
    pool: asyncpg.Pool, schema: str, query_vec: list[float], k: int, runs: int
) -> dict[str, Any]:
    """Compare HNSW vs IVFFlat unfiltered top-K query latency (+ build time)."""
    results: dict[str, Any] = {}
    for kind in ("hnsw", "ivfflat"):
        start = time.monotonic()
        try:
            await ensure_ann_index(pool, schema=schema, kind=kind)
            build_s = time.monotonic() - start
        except Exception as exc:  # noqa: BLE001 — report, don't crash the spike
            results[kind] = {"error": str(exc)}
            continue

        async def _run(k_=kind) -> None:  # noqa: ARG001 - closure capture
            async with pool.acquire() as conn:
                await conn.fetch(
                    f"""
                    SELECT concept_id FROM {schema}.embeddings
                    ORDER BY embedding <=> $1 LIMIT $2
                    """,
                    query_vec,
                    k,
                )

        median_s, samples = await _timed(_run, runs)
        results[kind] = {"build_s": build_s, "median_query_s": median_s, "samples_s": samples}
        async with pool.acquire() as conn:
            await conn.execute(f"DROP INDEX IF EXISTS {schema}.embeddings_{kind}_idx")
    return results


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments.

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        description="FEAT-520 TASK-2770 — OQ3 KNN-under-graph-filter spike.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--dsn", default=None, help="Postgres DSN; defaults to GRAPHINDEX_PG_DSN/default_dsn.")
    parser.add_argument("--corpus-size", type=int, default=5000, help="Number of synthetic concepts.")
    parser.add_argument("--depths", default="1,2,3", help="Comma-separated graph-expansion depths to test.")
    parser.add_argument("--top-k", type=int, default=10, help="KNN result count.")
    parser.add_argument("--runs", type=int, default=5, help="Timed repetitions per cell (median reported).")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed (printed in the report for reproducibility).")
    parser.add_argument("--output", default="artifacts/logs/feat-520-oq3-spike.md", help="Report output path.")
    parser.add_argument("--keep-schema", action="store_true", help="Do not drop the throwaway schema (debugging).")
    return parser.parse_args()


async def main() -> int:
    """Run the OQ3 spike end-to-end.

    Returns:
        Exit code (0 = success, 1 = fatal harness error).
    """
    args = parse_args()
    dsn = args.dsn or default_dsn
    if not dsn:
        print("[ERROR] No DSN resolved (pass --dsn or configure GRAPHINDEX_PG_DSN/default_dsn).", file=sys.stderr)
        return 1

    rng = random.Random(args.seed)
    schema = f"graphindex_spike_{uuid.uuid4().hex[:12]}"
    depths = [int(d) for d in args.depths.split(",")]

    pool = await create_pg_pool(dsn, schema=schema)
    try:
        await ensure_schema(pool, schema=schema)
        print(
            f"Seeding synthetic corpus: {args.corpus_size} concepts, seed={args.seed}, dim={GRAPHINDEX_EMBEDDING_DIM}"
        )
        corpus_stats = await seed_corpus(
            pool, schema, corpus_size=args.corpus_size, dim=GRAPHINDEX_EMBEDDING_DIM, rng=rng
        )
        print(f"Corpus seeded: {corpus_stats}")

        query_vec = _random_vector(rng, GRAPHINDEX_EMBEDDING_DIM)
        seed_ids = [f"c{i}" for i in rng.sample(range(args.corpus_size), k=min(5, args.corpus_size))]

        g2s_results: list[dict[str, Any]] = []
        s2g_results: list[dict[str, Any]] = []
        for seed_id in seed_ids:
            for depth in depths:
                g2s_results.append(
                    await bench_graph_to_semantic(pool, schema, seed_id, depth, query_vec, args.top_k, args.runs)
                )
                s2g_results.append(
                    await bench_semantic_to_graph(pool, schema, seed_id, depth, query_vec, args.top_k, args.runs)
                )

        print("Benchmarking HNSW vs IVFFlat (unfiltered top-K)...")
        ann_results = await bench_ann_index_type(pool, schema, query_vec, args.top_k, args.runs)

        report = render_report(
            seed=args.seed,
            corpus_stats=corpus_stats,
            depths=depths,
            g2s_results=g2s_results,
            s2g_results=s2g_results,
            ann_results=ann_results,
        )
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report)
        print(f"\nReport written to: {output_path}")
        print(report)
    finally:
        if not args.keep_schema:
            async with pool.acquire() as conn:
                await conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        await pool.close()

    return 0


def render_report(
    *,
    seed: int,
    corpus_stats: dict[str, Any],
    depths: list[int],
    g2s_results: list[dict[str, Any]],
    s2g_results: list[dict[str, Any]],
    ann_results: dict[str, Any],
) -> str:
    """Render the markdown findings report.

    Args:
        seed: RNG seed used (reproducibility).
        corpus_stats: Output of ``seed_corpus``.
        depths: Graph-expansion depths tested.
        g2s_results: ``bench_graph_to_semantic`` results.
        s2g_results: ``bench_semantic_to_graph`` results.
        ann_results: ``bench_ann_index_type`` results.

    Returns:
        The full markdown report text.
    """
    # --- data-driven decisions (never hardcode a winner — report what the
    # run actually measured, including a loss) --------------------------
    g2s_by_depth: dict[int, list[float]] = {}
    for r in g2s_results:
        g2s_by_depth.setdefault(r["depth"], []).append(r["median_s"])
    s2g_by_depth: dict[int, list[float]] = {}
    for r in s2g_results:
        s2g_by_depth.setdefault(r["depth"], []).append(r["median_s"])

    g2s_wins = sum(
        1
        for d in depths
        if d in g2s_by_depth
        and d in s2g_by_depth
        and statistics.mean(g2s_by_depth[d]) <= statistics.mean(s2g_by_depth[d])
    )
    comparable_depths = [d for d in depths if d in g2s_by_depth and d in s2g_by_depth]
    if comparable_depths and g2s_wins == len(comparable_depths):
        cte_decision = (
            "graph→semantic (recursive CTE hood first, KNN restricted to the "
            f"hood) — faster at every tested depth ({comparable_depths}) in "
            "this run. See the numbers above. Cardinality-dependent: if a "
            "future caller requests a depth beyond what was tested here, "
            "re-run this spike before assuming the same ordering holds."
        )
    elif g2s_wins == 0:
        cte_decision = (
            "semantic→graph (unfiltered ANN top-K first, then a hood "
            f"-membership check) — faster at every tested depth "
            f"({comparable_depths}) in this run, contradicting the spec's "
            "prior hypothesis. See the numbers above — this is the honest "
            "result, not the expected one."
        )
    else:
        cte_decision = (
            f"MIXED — graph→semantic won at {g2s_wins}/{len(comparable_depths)} "
            f"tested depths ({comparable_depths}). Cardinality-dependent: "
            "`hybrid_retrieve` should pick the CTE order per-request based on "
            "the estimated hood size at the requested depth, not a single "
            "fixed default. See the per-depth numbers above for the crossover."
        )

    hnsw_q = ann_results.get("hnsw", {}).get("median_query_s")
    ivfflat_q = ann_results.get("ivfflat", {}).get("median_query_s")
    if hnsw_q is not None and ivfflat_q is not None:
        if hnsw_q <= ivfflat_q:
            ann_decision = (
                f"`hnsw` — median query {hnsw_q:.5f}s vs ivfflat's "
                f"{ivfflat_q:.5f}s in this run (build time {ann_results['hnsw']['build_s']:.3f}s "
                f"vs {ann_results['ivfflat']['build_s']:.3f}s). Confirms TASK-2769's provisional "
                "default; no change to `pg_schema.py`'s `GRAPHINDEX_ANN_INDEX_KIND` needed."
            )
        else:
            ann_decision = (
                f"`ivfflat` — median query {ivfflat_q:.5f}s beat hnsw's "
                f"{hnsw_q:.5f}s in this run (build time {ann_results['ivfflat']['build_s']:.3f}s "
                f"vs hnsw's {ann_results['hnsw']['build_s']:.3f}s). This CONTRADICTS TASK-2769's "
                "provisional `hnsw` default at this corpus size — see the Caveats section before "
                "changing the config default (corpus size / recall were not exhaustively swept)."
            )
    else:
        ann_decision = f"INCONCLUSIVE — one or both index builds failed: {ann_results}"

    lines = [
        "# FEAT-520 TASK-2770 — OQ3 spike: KNN under graph filter",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Seed: {seed} (reproducible: pass `--seed {seed}`)",
        f"Corpus: {corpus_stats}",
        "",
        "## graph→semantic (recursive CTE hood, exact scan within hood)",
        "",
        "| depth | hood_size | median_s |",
        "|---|---|---|",
    ]
    by_depth_g2s: dict[int, list[dict[str, Any]]] = {}
    for r in g2s_results:
        by_depth_g2s.setdefault(r["depth"], []).append(r)
    for depth in depths:
        rows = by_depth_g2s.get(depth, [])
        if not rows:
            continue
        avg_hood = statistics.mean(r["hood_size"] for r in rows)
        avg_median = statistics.mean(r["median_s"] for r in rows)
        lines.append(f"| {depth} | {avg_hood:.0f} | {avg_median:.5f} |")

    lines += [
        "",
        "## semantic→graph (unfiltered ANN top-K, then hood-membership check)",
        "",
        "| depth | median_s |",
        "|---|---|",
    ]
    by_depth_s2g: dict[int, list[dict[str, Any]]] = {}
    for r in s2g_results:
        by_depth_s2g.setdefault(r["depth"], []).append(r)
    for depth in depths:
        rows = by_depth_s2g.get(depth, [])
        if not rows:
            continue
        avg_median = statistics.mean(r["median_s"] for r in rows)
        lines.append(f"| {depth} | {avg_median:.5f} |")

    lines += ["", "## HNSW vs IVFFlat (unfiltered top-K)", "", "```", str(ann_results), "```"]

    lines += [
        "",
        "## EXPLAIN excerpts (first seed/depth cell)",
        "",
        "### graph→semantic",
        "```",
        g2s_results[0]["explain"] if g2s_results else "(no data)",
        "```",
        "",
        "### semantic→graph",
        "```",
        s2g_results[0]["explain"] if s2g_results else "(no data)",
        "```",
        "",
        "## Caveats",
        "",
        "- The resolved dev Postgres carries pgvector 0.5.0 — the `hnsw."
        "iterative_scan`/`ivfflat.iterative_scan` GUCs (pgvector >=0.8, the "
        "spec's own OQ3 mitigation) are NOT available on this server. The "
        "'exact scan within hood' numbers above are what a pre-0.8 server "
        "actually does today; the iterative-scan mitigation itself is "
        "untested here and should be re-verified once the deployment target "
        "runs pgvector >=0.8.",
        "- Synthetic scale-free corpus, not a real BOE/legal corpus — a "
        "real-corpus re-run belongs to legal-wiki work (out of this task's "
        "scope per the task file).",
        "",
        "## Decisions",
        "",
        f"1. **Default CTE order for `hybrid_retrieve`**: {cte_decision}",
        f"2. **ANN index default**: {ann_decision}",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
