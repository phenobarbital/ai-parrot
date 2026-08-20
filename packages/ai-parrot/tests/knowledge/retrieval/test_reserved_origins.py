"""Tests for TASK-2272: reserved-origin contract — no policy may emit `L2_*`.

Spec: sdd/specs/graphindex-retriever.spec.md §3.2, OQ-6.
"""

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

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
    RESERVED_ORIGINS,
    EvidenceOrigin,
    RetrievalBudget,
    RetrievalRequest,
)
from parrot.knowledge.retrieval.policies import RetrievalPolicy
from parrot.knowledge.retrieval.policies.direct_symbol import (
    DirectSymbolPolicy,
    build_node_id_index,
)
from parrot.knowledge.retrieval.policies.vector_seed import VectorSeedPolicy
from parrot.knowledge.retrieval.symbols import DerivedSymbolIndex

# Unwrap the Annotated discriminated union (spec §5.0) — derived, not
# hardcoded, so a future policy is automatically covered by this test.
POLICIES = list(get_args(get_args(RetrievalPolicy)[0]))

_SOURCE = b"class PayRateEngine:\n    def resolve(self):\n        return 1\n"


def test_reserved_set_is_exactly_the_l2_members() -> None:
    assert RESERVED_ORIGINS == {
        EvidenceOrigin.L2_DOC,
        EvidenceOrigin.L2_NORM,
        EvidenceOrigin.L2_EXTERNAL,
    }


def test_policy_list_is_non_empty() -> None:
    # Cannot vacuously pass: if the union were ever emptied out, this
    # fails loudly rather than the parametrised test silently covering 0
    # cases.
    assert len(POLICIES) > 0
    assert DirectSymbolPolicy in POLICIES
    assert VectorSeedPolicy in POLICIES


async def _run_git(repo: Path, *args: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=repo, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    await proc.communicate()


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

        ctx = _tenant_context("tenant-reserved-origins")
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


def _build_policy(policy_cls: type, fx: dict) -> object:
    """Construct `policy_cls` from the shared fixture — one branch per
    v1-cut policy. A future policy added to `RetrievalPolicy` without a
    branch here fails loudly (KeyError) rather than being silently
    skipped."""
    if policy_cls is DirectSymbolPolicy:
        return DirectSymbolPolicy(
            symbols=fx["symbols"],
            reader=fx["reader"],
            node_id_by_qualname=fx["node_id_index"],
            repo="ai-parrot",
            repo_path=fx["repo_path"],
        )
    if policy_cls is VectorSeedPolicy:
        return VectorSeedPolicy(
            symbols=fx["symbols"],
            reader=fx["reader"],
            embedder=None,
            node_id_by_qualname=fx["node_id_index"],
            repo="ai-parrot",
            rev=fx["rev"],
            repo_path=fx["repo_path"],
        )
    raise KeyError(
        f"test_reserved_origins.py: no fixture wiring for new RetrievalPolicy "
        f"member {policy_cls!r} — add one before this test can cover it"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("policy_cls", POLICIES, ids=lambda c: c.__name__)
async def test_policy_never_emits_reserved_origin(policy_cls: type, fixture: dict) -> None:
    policy = _build_policy(policy_cls, fixture)
    req = RetrievalRequest(query="`PayRateEngine`", workspace=None)
    budget = RetrievalBudget()

    seeds = await policy.seed(req, graph=None)
    subgraph = await policy.expand(seeds, graph=None, budget=budget)
    pruned = await policy.prune(subgraph, budget)
    bundle = await policy.assemble(pruned, budget)

    origins = {unit.evidence.origin for unit in bundle.units}
    assert not (origins & RESERVED_ORIGINS), (
        f"{policy_cls.__name__} emitted a RESERVED origin: {origins & RESERVED_ORIGINS}"
    )
