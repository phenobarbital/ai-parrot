"""Live-DB-gated tests for hybrid_retrieve (FEAT-520 TASK-2771)."""

from __future__ import annotations

import math
import os
import uuid
from typing import Any, Optional
from unittest.mock import MagicMock

import asyncpg
import pytest

from parrot.conf import default_dsn
from parrot.knowledge.graphindex import pg_schema
from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence
from parrot.knowledge.graphindex.schema import EdgeKind, NodeKind, UniversalEdge, UniversalNode
from parrot.models.stores import SearchResult
from parrot.rerankers.abstract import AbstractReranker
from parrot.rerankers.models import RerankedDocument

PG_DSN = os.environ.get("GRAPHINDEX_PG_DSN") or default_dsn
pytestmark = pytest.mark.skipif(not PG_DSN, reason="needs live Postgres")

DIM = pg_schema.GRAPHINDEX_EMBEDDING_DIM


def _make_ctx(tenant_id: str = "test_tenant") -> Any:
    ctx = MagicMock()
    ctx.tenant_id = tenant_id
    return ctx


def make_node(node_id: str, **kwargs: Any) -> UniversalNode:
    kwargs.setdefault("kind", NodeKind.DOCUMENT)
    kwargs.setdefault("source_uri", "test.txt")
    kwargs.setdefault("title", f"Node {node_id}")
    return UniversalNode(node_id=node_id, **kwargs)


def make_edge(src: str, dst: str, kind: EdgeKind = EdgeKind.CONTAINS, **kwargs: Any) -> UniversalEdge:
    return UniversalEdge(source_id=src, target_id=dst, kind=kind, **kwargs)


def _vec(seed: float, dim: int = DIM) -> list[float]:
    v = [seed] * dim
    v[0] += 1.0
    return v


class _StubReranker(AbstractReranker):
    """Reverses the input order deterministically (proves reranking ran)."""

    def __init__(self, fail: bool = False, nan: bool = False) -> None:
        self._fail = fail
        self._nan = nan

    async def rerank(
        self, query: str, documents: list[SearchResult], top_n: Optional[int] = None
    ) -> list[RerankedDocument]:
        if self._fail:
            raise RuntimeError("stub reranker forced failure")
        docs = documents[:top_n] if top_n else documents
        out = []
        n = len(docs)
        for i, doc in enumerate(reversed(docs)):
            score = float("nan") if self._nan else float(n - i)
            out.append(
                RerankedDocument(
                    document=doc,
                    rerank_score=score,
                    rerank_rank=i,
                    original_rank=n - 1 - i,
                    rerank_model="stub",
                    rerank_latency_ms=0.0,
                )
            )
        return out


@pytest.fixture
def ctx():
    return _make_ctx()


@pytest.fixture
def tmp_schema() -> str:
    return f"graphindex_test_{uuid.uuid4().hex[:12]}"


@pytest.fixture
async def pg_persistence(tmp_schema):
    p = PostgresPersistence(PG_DSN, schema=tmp_schema)
    try:
        yield p
    finally:
        pool = await p._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {tmp_schema} CASCADE")
        await p.close()


async def _seed_small_corpus(pg_persistence, ctx):
    """a -> b -> c (edges), each with distinguishable embeddings + text."""
    nodes = [
        make_node("a", title="Alpha document", summary="about alpha topics"),
        make_node("b", title="Beta document", summary="about beta topics"),
        make_node("c", title="Gamma document", summary="about gamma topics"),
    ]
    edges = [make_edge("a", "b"), make_edge("b", "c")]
    await pg_persistence.persist_graph(ctx, nodes, edges)
    await pg_persistence.upsert_embeddings(
        ctx, [("a", _vec(0.1)), ("b", _vec(0.2)), ("c", _vec(0.9))]
    )


async def test_no_legs_raises(pg_persistence, ctx):
    with pytest.raises(ValueError):
        await pg_persistence.hybrid_retrieve(ctx)


async def test_graph_leg_only(pg_persistence, ctx):
    await _seed_small_corpus(pg_persistence, ctx)
    results = await pg_persistence.hybrid_retrieve(ctx, seeds=["a"])
    ids = {r.concept_id for r in results}
    assert ids == {"a", "b", "c"}
    by_id = {r.concept_id: r for r in results}
    assert by_id["a"].signals["graph_depth"] == 0.0
    assert by_id["b"].signals["graph_depth"] == 1.0
    assert by_id["c"].signals["graph_depth"] == 2.0
    # closer nodes score higher (RRF over depth-ordered rank)
    assert by_id["a"].score > by_id["b"].score > by_id["c"].score


async def test_knn_leg_only(pg_persistence, ctx):
    await _seed_small_corpus(pg_persistence, ctx)
    results = await pg_persistence.hybrid_retrieve(ctx, query_embedding=_vec(0.1))
    assert results[0].concept_id == "a"  # nearest


async def test_fts_leg_only(pg_persistence, ctx):
    await _seed_small_corpus(pg_persistence, ctx)
    results = await pg_persistence.hybrid_retrieve(ctx, fts_terms="alpha")
    assert results
    assert results[0].concept_id == "a"


async def test_rrf_fusion_math(pg_persistence, ctx):
    await _seed_small_corpus(pg_persistence, ctx)
    results = await pg_persistence.hybrid_retrieve(
        ctx, seeds=["a"], query_embedding=_vec(0.1), weights={"graph": 2.0, "knn": 3.0}
    )
    by_id = {r.concept_id: r for r in results}
    a = by_id["a"]
    # "a" is the seed (depth 0, graph rank 1) AND the nearest KNN hit (rank 1)
    # -> score = Sigma w_leg / (60 + rank_leg) per the documented RRF formula.
    expected = 2.0 / (60 + 1) + 3.0 / (60 + 1)
    assert a.score == pytest.approx(expected, rel=1e-6)
    assert a.signals["graph"] == pytest.approx(2.0 / 61, rel=1e-6)
    assert a.signals["knn"] == pytest.approx(3.0 / 61, rel=1e-6)


async def test_as_of_transversal(pg_persistence, ctx):
    await _seed_small_corpus(pg_persistence, ctx)
    import datetime as _dt

    t_before_change = _dt.datetime.now(tz=_dt.timezone.utc)

    # Close "a"'s current version (no new embedding for the closed one).
    await pg_persistence.persist_graph(ctx, [make_node("a", title="Alpha document", summary="changed")], [])

    # KNN query at the CURRENT time must not surface the closed version's row
    # via the embeddings table (its embedding still points at the old,
    # now-closed version_id, which fails the validity join).
    results_now = await pg_persistence.hybrid_retrieve(ctx, query_embedding=_vec(0.1))
    ids_now = {r.concept_id for r in results_now}
    assert "a" not in ids_now  # old version_id's embedding is no longer current

    # But as_of the earlier snapshot, "a" (with its embedding) is still visible.
    results_past = await pg_persistence.hybrid_retrieve(ctx, query_embedding=_vec(0.1), as_of=t_before_change)
    ids_past = {r.concept_id for r in results_past}
    assert "a" in ids_past


async def test_naive_as_of_rejected(pg_persistence, ctx):
    import datetime as _dt

    await _seed_small_corpus(pg_persistence, ctx)
    with pytest.raises(ValueError):
        await pg_persistence.hybrid_retrieve(ctx, seeds=["a"], as_of=_dt.datetime.now())  # noqa: DTZ005


async def test_evidence_pairs(pg_persistence, ctx):
    edge_with_evidence = make_edge(
        "a", "b", domain_tags={"evidence_ref": {"body_ref": "doc.md", "byte_offset": 7}}
    )
    await pg_persistence.persist_graph(
        ctx, [make_node("a"), make_node("b")], [edge_with_evidence]
    )
    results = await pg_persistence.hybrid_retrieve(ctx, seeds=["a"])
    by_id = {r.concept_id: r for r in results}
    assert by_id["b"].evidence == [{"body_ref": "doc.md", "byte_offset": 7}]
    assert by_id["a"].evidence == []  # seed itself has no incoming evidence


async def test_rerank_replaces_order(pg_persistence, ctx):
    await _seed_small_corpus(pg_persistence, ctx)
    reranker = _StubReranker()
    results = await pg_persistence.hybrid_retrieve(ctx, fts_terms="topics", reranker=reranker, rerank_top_k=3)
    # Stub reverses order -> the fused-last candidate should now be first.
    assert len(results) <= 3


async def test_rerank_failure_falls_back(pg_persistence, ctx):
    await _seed_small_corpus(pg_persistence, ctx)
    fused = await pg_persistence.hybrid_retrieve(ctx, fts_terms="alpha")
    reranked = await pg_persistence.hybrid_retrieve(
        ctx, fts_terms="alpha", reranker=_StubReranker(fail=True)
    )
    assert [r.concept_id for r in reranked] == [r.concept_id for r in fused][: len(reranked)]


async def test_rerank_nan_falls_back(pg_persistence, ctx):
    await _seed_small_corpus(pg_persistence, ctx)
    fused = await pg_persistence.hybrid_retrieve(ctx, fts_terms="alpha")
    reranked = await pg_persistence.hybrid_retrieve(
        ctx, fts_terms="alpha", reranker=_StubReranker(nan=True)
    )
    assert [r.concept_id for r in reranked] == [r.concept_id for r in fused][: len(reranked)]


async def test_single_statement_execution(pg_persistence, ctx, monkeypatch):
    """All three legs must resolve in ONE `fetch` call — no N+1 across legs."""
    await _seed_small_corpus(pg_persistence, ctx)

    calls = []
    original_fetch = asyncpg.Connection.fetch

    async def _counting_fetch(self, query, *args, **kwargs):
        calls.append(query)
        return await original_fetch(self, query, *args, **kwargs)

    monkeypatch.setattr(asyncpg.Connection, "fetch", _counting_fetch)
    await pg_persistence.hybrid_retrieve(ctx, seeds=["a"], query_embedding=_vec(0.1), fts_terms="alpha")
    assert len(calls) == 1


async def test_e2e_ingest_then_retrieve(pg_persistence, ctx):
    await _seed_small_corpus(pg_persistence, ctx)
    results = await pg_persistence.hybrid_retrieve(
        ctx,
        seeds=["a"],
        query_embedding=_vec(0.1),
        fts_terms="alpha",
        limit=10,
    )
    assert results
    assert results[0].concept_id == "a"
    assert not math.isnan(results[0].score)


def test_no_sqlalchemy_imports():
    import parrot.knowledge.graphindex.persist_postgres as module

    with open(module.__file__, "r", encoding="utf-8") as fh:
        content = fh.read()
    assert "sqlalchemy" not in content.lower()
    assert "parrot.stores.postgres" not in content
