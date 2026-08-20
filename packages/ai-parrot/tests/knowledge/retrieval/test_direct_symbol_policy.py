"""Tests for TASK-2280: `DirectSymbolPolicy` — the no-traversal fast path.

Spec: sdd/specs/graphindex-retriever.spec.md §5.1.
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
from parrot.knowledge.retrieval.models import (
    EvidenceOrigin,
    RetrievalBudget,
    RetrievalRequest,
)
from parrot.knowledge.retrieval.policies.direct_symbol import (
    DirectSymbolPolicy,
    build_node_id_index,
)
from parrot.knowledge.retrieval.symbols import DerivedSymbolIndex

_SOURCE = (
    b"class PayRateEngine:\n"
    b"    # WHY: rate freezes at clock-out to avoid double counting\n"
    b"    def resolve(self):\n"
    b"        return 1\n"
)


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
            domain_tags={"symbol_type": "class", "lineno": 1, "end_lineno": 4},
        )
        method = UniversalNode(
            node_id="mod::PayRateEngine::resolve",
            kind=NodeKind.SYMBOL,
            title="resolve",
            source_uri="payrate.py",
            parent_id="mod::PayRateEngine",
            domain_tags={"symbol_type": "function", "lineno": 3, "end_lineno": 4},
        )
        rationale = UniversalNode(
            node_id="mod::__rationale__0",
            kind=NodeKind.RATIONALE,
            title="WHY: rate freezes at clock-out",
            source_uri="payrate.py",
            summary="rate freezes at clock-out to avoid double counting",
            domain_tags={"tag": "WHY"},
        )
        nodes = [module, cls, method, rationale]
        edges = [
            UniversalEdge(source_id="mod", target_id="mod::PayRateEngine", kind=EdgeKind.CONTAINS),
            UniversalEdge(
                source_id="mod::PayRateEngine",
                target_id="mod::PayRateEngine::resolve",
                kind=EdgeKind.CONTAINS,
            ),
            UniversalEdge(
                source_id="mod::__rationale__0",
                target_id="mod::PayRateEngine",
                kind=EdgeKind.EXPLAINS,
            ),
        ]

        ctx = _tenant_context("tenant-direct-symbol")
        persistence = SQLitePersistence(tmp / "dbs")
        await persistence.persist_graph(ctx, nodes, edges)

        reader = SQLiteGraphReader(persistence._db_path(ctx))
        await reader.load()

        symbols = DerivedSymbolIndex.build(nodes, repo="ai-parrot", rev=rev)
        node_id_index = build_node_id_index(nodes, symbols)

        policy = DirectSymbolPolicy(
            symbols=symbols,
            reader=reader,
            node_id_by_qualname=node_id_index,
            repo="ai-parrot",
            repo_path=repo_path,
        )
        return {
            "policy": policy,
            "reader": reader,
            "rev": rev,
            "repo_path": repo_path,
        }

    return asyncio.run(_build())


@pytest.mark.asyncio
async def test_no_vector_or_fts_calls(fixture: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args: object, **kwargs: object) -> None:
        raise AssertionError("DirectSymbolPolicy must not call FTS/vector search")

    monkeypatch.setattr(
        "parrot.knowledge.graphindex.sqlite_reader.SQLiteGraphReader.search_symbols", _raise
    )

    policy: DirectSymbolPolicy = fixture["policy"]
    req = RetrievalRequest(query="`PayRateEngine.resolve`", workspace=None)
    seeds = await policy.seed(req, graph=None)
    assert len(seeds) == 1


@pytest.mark.asyncio
async def test_expands_only_inbound_explains_edges(fixture: dict) -> None:
    policy: DirectSymbolPolicy = fixture["policy"]
    req = RetrievalRequest(query="`PayRateEngine`", workspace=None)
    seeds = await policy.seed(req, graph=None)
    subgraph = await policy.expand(seeds, graph=None, budget=RetrievalBudget())

    kinds = {n.kind for n in subgraph.nodes}
    assert NodeKind.RATIONALE in kinds
    assert len(subgraph.nodes) == 2  # the seed class + its one rationale child


@pytest.mark.asyncio
async def test_rationale_units_have_none_line_span(fixture: dict) -> None:
    policy: DirectSymbolPolicy = fixture["policy"]
    req = RetrievalRequest(query="`PayRateEngine`", workspace=None)
    seeds = await policy.seed(req, graph=None)
    subgraph = await policy.expand(seeds, graph=None, budget=RetrievalBudget())
    pruned = await policy.prune(subgraph, RetrievalBudget())
    bundle = await policy.assemble(pruned, RetrievalBudget())

    rationale_units = [u for u in bundle.units if u.evidence.node.kind == NodeKind.RATIONALE]
    assert rationale_units
    for unit in rationale_units:
        assert unit.evidence.line_span is None
        assert unit.evidence.origin == EvidenceOrigin.L1_RATIONALE


@pytest.mark.asyncio
async def test_symbol_units_have_l0_source_origin_and_line_span(fixture: dict) -> None:
    policy: DirectSymbolPolicy = fixture["policy"]
    req = RetrievalRequest(query="`PayRateEngine.resolve`", workspace=None)
    seeds = await policy.seed(req, graph=None)
    subgraph = await policy.expand(seeds, graph=None, budget=RetrievalBudget())
    pruned = await policy.prune(subgraph, RetrievalBudget())
    bundle = await policy.assemble(pruned, RetrievalBudget())

    symbol_units = [u for u in bundle.units if u.evidence.node.kind == NodeKind.SYMBOL]
    assert symbol_units
    for unit in symbol_units:
        assert unit.evidence.origin == EvidenceOrigin.L0_SOURCE
        assert unit.evidence.line_span is not None


@pytest.mark.asyncio
async def test_digest_matches_recomputation_over_served_text(fixture: dict) -> None:
    policy: DirectSymbolPolicy = fixture["policy"]
    req = RetrievalRequest(query="`PayRateEngine.resolve`", workspace=None)
    seeds = await policy.seed(req, graph=None)
    subgraph = await policy.expand(seeds, graph=None, budget=RetrievalBudget())
    pruned = await policy.prune(subgraph, RetrievalBudget())
    bundle = await policy.assemble(pruned, RetrievalBudget())

    for unit in bundle.units:
        if unit.evidence.line_span is None:
            continue
        recomputed = hashlib.sha256(unit.text.encode("utf-8")).hexdigest()
        assert recomputed == unit.evidence.digest


@pytest.mark.asyncio
async def test_respects_deadline_sets_truncated(
    fixture: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy: DirectSymbolPolicy = fixture["policy"]
    req = RetrievalRequest(query="`PayRateEngine`", workspace=None)
    seeds = await policy.seed(req, graph=None)

    call_count = {"n": 0}

    def _fake_monotonic() -> float:
        call_count["n"] += 1
        # First call establishes `start`; every subsequent call reports a
        # huge elapsed time, deterministically forcing truncation.
        return 0.0 if call_count["n"] == 1 else 1_000_000.0

    monkeypatch.setattr(
        "parrot.knowledge.retrieval.policies.direct_symbol.time.monotonic", _fake_monotonic
    )

    subgraph = await policy.expand(seeds, graph=None, budget=RetrievalBudget(deadline_ms=1))
    assert subgraph.truncated is True


@pytest.mark.asyncio
async def test_no_truncation_under_generous_deadline(fixture: dict) -> None:
    policy: DirectSymbolPolicy = fixture["policy"]
    req = RetrievalRequest(query="`PayRateEngine`", workspace=None)
    seeds = await policy.seed(req, graph=None)
    subgraph = await policy.expand(seeds, graph=None, budget=RetrievalBudget())
    assert subgraph.truncated is False


@pytest.mark.asyncio
async def test_prune_trims_to_max_expansion_nodes(fixture: dict) -> None:
    policy: DirectSymbolPolicy = fixture["policy"]
    req = RetrievalRequest(query="`PayRateEngine`", workspace=None)
    seeds = await policy.seed(req, graph=None)
    subgraph = await policy.expand(seeds, graph=None, budget=RetrievalBudget())
    pruned = await policy.prune(subgraph, RetrievalBudget(max_expansion_nodes=1))
    assert len(pruned.nodes) == 1
    assert pruned.truncated is True


@pytest.mark.asyncio
async def test_empty_query_no_anchor_returns_empty_bundle(fixture: dict) -> None:
    policy: DirectSymbolPolicy = fixture["policy"]
    req = RetrievalRequest(query="hello there", workspace=None)
    seeds = await policy.seed(req, graph=None)
    assert seeds == ()
