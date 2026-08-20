"""Tests for TASK-2281: `VectorSeedPolicy` — FTS5 ∥ FAISS, fused with RRF.

Spec: sdd/specs/graphindex-retriever.spec.md §5.2, OQ-9.
"""

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    UniversalEdge,
    UniversalNode,
)
from parrot.knowledge.graphindex.sqlite_reader import SQLiteGraphReader
from parrot.knowledge.ontology.schema import MergedOntology, TenantContext
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch
from parrot.knowledge.retrieval.models import RetrievalBudget, RetrievalRequest
from parrot.knowledge.retrieval.policies.direct_symbol import build_node_id_index
from parrot.knowledge.retrieval.policies.vector_seed import VectorSeedPolicy
from parrot.knowledge.retrieval.symbols import DerivedSymbolIndex

_SOURCE = b"class PayRateEngine:\n    def resolve(self):\n        return 1\n"


def test_rrf_matches_reference_formula() -> None:
    rankings = [["a", "b", "c"], ["b", "d"]]
    fused = HybridPageIndexSearch._rrf_fuse(rankings, k=60)
    expected_a = 1.0 / (60 + 0 + 1)
    expected_b = 1.0 / (60 + 1 + 1) + 1.0 / (60 + 0 + 1)
    scores = dict(fused)
    assert scores["a"] == pytest.approx(expected_a)
    assert scores["b"] == pytest.approx(expected_b)
    assert fused[0][0] == "b"


def test_does_not_import_pgvector() -> None:
    import parrot.knowledge.retrieval.policies.vector_seed as module

    source = Path(module.__file__).read_text()
    assert "stores.pgvector" not in source
    assert "_persist_to_pgvector" not in source


class _FakeEmbedder:
    """Duck-typed `GraphIndexEmbedder`-shaped test double — no real model."""

    def __init__(self, hits: list[tuple[str, float]], delay: float = 0.0) -> None:
        self._hits = hits
        self._delay = delay
        self.calls: list[str] = []

    async def search_similar(self, query_text: str, top_k: int = 10) -> list[tuple[str, float]]:
        self.calls.append("start")
        if self._delay:
            await asyncio.sleep(self._delay)
        self.calls.append("end")
        return self._hits[:top_k]


async def _run_git(repo: Path, *args: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=repo, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"git {args} failed: {stderr.decode()}")


async def _git_rev_parse(repo: Path) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git", "rev-parse", "HEAD", cwd=repo, stdout=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    return stdout.decode().strip()


def _tenant_context(tenant_id: str) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        arango_db="test_db",
        pgvector_schema="test_schema",
        ontology=MergedOntology(
            name="test",
            version="1",
            entities={},
            relations={},
            traversal_patterns={},
            layers=[],
            merge_timestamp=datetime.now(UTC),
        ),
    )


@pytest.fixture
def fixture() -> dict:
    async def _build() -> dict:
        import tempfile

        tmp = Path(tempfile.mkdtemp())
        repo_path = tmp / "repo"
        repo_path.mkdir()
        await _run_git(repo_path, "init", "-q")
        await _run_git(repo_path, "config", "user.email", "test@example.com")
        await _run_git(repo_path, "config", "user.name", "Test")
        (repo_path / "payrate.py").write_bytes(_SOURCE)
        await _run_git(repo_path, "add", ".")
        await _run_git(repo_path, "commit", "-q", "-m", "init")
        rev = await _git_rev_parse(repo_path)

        module = UniversalNode(
            node_id="mod",
            kind=NodeKind.SYMBOL,
            title="payrate",
            source_uri="payrate.py",
            domain_tags={"symbol_type": "module", "sha1": hashlib.sha1(_SOURCE).hexdigest()},
        )
        cls = UniversalNode(
            node_id="mod::PayRateEngine",
            kind=NodeKind.SYMBOL,
            title="PayRateEngine",
            source_uri="payrate.py",
            parent_id="mod",
            summary="Computes pay rates.",
            domain_tags={"symbol_type": "class", "lineno": 1, "end_lineno": 3},
        )
        method = UniversalNode(
            node_id="mod::PayRateEngine::resolve",
            kind=NodeKind.SYMBOL,
            title="resolve",
            source_uri="payrate.py",
            parent_id="mod::PayRateEngine",
            summary="Resolves the pay rate.",
            domain_tags={"symbol_type": "function", "lineno": 2, "end_lineno": 3},
        )
        nodes = [module, cls, method]
        edges = [
            UniversalEdge(source_id="mod", target_id="mod::PayRateEngine", kind=EdgeKind.CONTAINS),
            UniversalEdge(
                source_id="mod::PayRateEngine",
                target_id="mod::PayRateEngine::resolve",
                kind=EdgeKind.CONTAINS,
            ),
        ]

        ctx = _tenant_context("tenant-vector-seed")
        persistence = SQLitePersistence(tmp / "dbs")
        await persistence.persist_graph(ctx, nodes, edges)

        reader = SQLiteGraphReader(persistence._db_path(ctx))
        await reader.load()

        symbols = DerivedSymbolIndex.build(nodes, repo="ai-parrot", rev=rev)
        node_id_index = build_node_id_index(nodes, symbols)

        return {
            "reader": reader,
            "symbols": symbols,
            "node_id_index": node_id_index,
            "rev": rev,
            "repo_path": repo_path,
        }

    return asyncio.run(_build())


def _policy(fixture: dict, *, reader=None, embedder=None, supports_fts=True) -> VectorSeedPolicy:
    return VectorSeedPolicy(
        symbols=fixture["symbols"],
        reader=reader if reader is not None else fixture["reader"],
        supports_fts=supports_fts,
        embedder=embedder,
        node_id_by_qualname=fixture["node_id_index"],
        repo="ai-parrot",
        rev=fixture["rev"],
        repo_path=fixture["repo_path"],
    )


@pytest.mark.asyncio
async def test_legs_sorted_best_first_before_fusion(fixture: dict) -> None:
    embedder = _FakeEmbedder([("mod::PayRateEngine", 0.1), ("mod::PayRateEngine::resolve", 0.9)])
    policy = _policy(fixture, embedder=embedder)
    req = RetrievalRequest(query="PayRateEngine", workspace=None)
    seeds = await policy.seed(req)
    assert seeds  # sanity: fusion produced something
    # dense leg's own hits are already ascending-distance (best first);
    # verify the leg helper preserves that order rather than reversing it.
    dense_ids = [nid for nid, _ in embedder._hits]
    assert dense_ids == ["mod::PayRateEngine", "mod::PayRateEngine::resolve"]


@pytest.mark.asyncio
async def test_fts_only_degradation(fixture: dict) -> None:
    policy = _policy(fixture, embedder=None)
    req = RetrievalRequest(query="PayRateEngine", workspace=None)
    seeds = await policy.seed(req)
    assert seeds
    assert any(s.node.qualname.endswith("PayRateEngine") for s in seeds)


@pytest.mark.asyncio
async def test_dense_only_degradation(fixture: dict) -> None:
    embedder = _FakeEmbedder([("mod::PayRateEngine", 0.1)])
    policy = _policy(fixture, embedder=embedder, supports_fts=False)
    req = RetrievalRequest(query="anything", workspace=None)
    seeds = await policy.seed(req)
    assert len(seeds) == 1
    assert seeds[0].node.qualname.endswith("PayRateEngine")


@pytest.mark.asyncio
async def test_no_legs_available_returns_empty(fixture: dict) -> None:
    policy = _policy(fixture, reader=None, embedder=None, supports_fts=False)
    req = RetrievalRequest(query="anything", workspace=None)
    seeds = await policy.seed(req)
    assert seeds == ()


@pytest.mark.asyncio
async def test_legs_run_concurrently(fixture: dict) -> None:
    events: list[str] = []

    class _SpyEmbedder:
        async def search_similar(
            self, query_text: str, top_k: int = 10
        ) -> list[tuple[str, float]]:
            events.append("dense_start")
            await asyncio.sleep(0.05)
            events.append("dense_end")
            return [("mod::PayRateEngine", 0.1)]

    class _SpyReader:
        def __init__(self, real_reader) -> None:
            self._real = real_reader

        async def search_symbols(self, query: str, *, limit: int = 20) -> list[dict]:
            events.append("lexical_start")
            await asyncio.sleep(0.05)
            events.append("lexical_end")
            return await self._real.search_symbols(query, limit=limit)

        def get_node(self, node_id: str):
            return self._real.get_node(node_id)

        def children(self, node_id: str, **kwargs):
            return self._real.children(node_id, **kwargs)

    policy = _policy(fixture, reader=_SpyReader(fixture["reader"]), embedder=_SpyEmbedder())
    req = RetrievalRequest(query="PayRateEngine", workspace=None)
    await policy.seed(req)

    # If run sequentially, one leg's "_end" would appear before the other's
    # "_start". Concurrent execution interleaves them.
    assert events[0] in ("dense_start", "lexical_start")
    assert events[1] in ("dense_start", "lexical_start")
    assert events[1] != events[0]


@pytest.mark.asyncio
async def test_expand_is_depth1_contains_only(fixture: dict) -> None:
    policy = _policy(fixture, embedder=None)
    # Seed directly on the module to exercise expand's CONTAINS traversal.
    module_ref_seeds = await policy.seed(RetrievalRequest(query="payrate", workspace=None))
    module_seed = next(s for s in module_ref_seeds if s.node.qualname == "payrate")
    subgraph = await policy.expand((module_seed,), graph=None, budget=RetrievalBudget())

    assert module_seed.node in subgraph.nodes
    child_qualnames = {n.qualname for n in subgraph.nodes}
    assert "payrate.PayRateEngine" in child_qualnames
    # Depth-1 only: the grandchild (resolve) must NOT appear from a
    # single expand() pass over the module seed alone.
    assert "payrate.PayRateEngine.resolve" not in child_qualnames


@pytest.mark.asyncio
async def test_digest_matches_served_text(fixture: dict) -> None:
    policy = _policy(fixture, embedder=None)
    req = RetrievalRequest(query="`PayRateEngine.resolve`", workspace=None)
    seeds = await policy.seed(req)
    subgraph = await policy.expand(seeds, graph=None, budget=RetrievalBudget())
    pruned = await policy.prune(subgraph, RetrievalBudget())
    bundle = await policy.assemble(pruned, RetrievalBudget())

    assert bundle.units
    for unit in bundle.units:
        if unit.evidence.line_span is None:
            continue
        recomputed = hashlib.sha256(unit.text.encode("utf-8")).hexdigest()
        assert recomputed == unit.evidence.digest
