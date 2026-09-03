"""Live-DB-gated tests for PostgresPersistence's commit protocol (FEAT-520 TASK-2766).

Ports the behavioral scenarios of test_persist_commit_protocol.py against
``PostgresPersistence`` + ``GraphPublisher``.
"""

from __future__ import annotations

import os
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from parrot.conf import default_dsn
from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence
from parrot.knowledge.graphindex.publish import GraphPublisher
from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    GraphUpdate,
    NodeKind,
    UniversalEdge,
    UniversalNode,
)

PG_DSN = os.environ.get("GRAPHINDEX_PG_DSN") or default_dsn
pytestmark = pytest.mark.skipif(not PG_DSN, reason="needs live Postgres")


def _make_ctx(tenant_id: str = "test_tenant") -> Any:
    ctx = MagicMock()
    ctx.tenant_id = tenant_id
    return ctx


def make_node(node_id: str, title: str = "", **kwargs: Any) -> UniversalNode:
    return UniversalNode(
        node_id=node_id,
        kind=kwargs.pop("kind", NodeKind.CONCEPT),
        title=title or f"Node {node_id}",
        source_uri=kwargs.pop("source_uri", f"agent://concept/{node_id}"),
        **kwargs,
    )


def make_edge(src: str, tgt: str, kind: EdgeKind = EdgeKind.REFERENCES) -> UniversalEdge:
    return UniversalEdge(source_id=src, target_id=tgt, kind=kind)


def make_update(**kwargs: Any) -> GraphUpdate:
    kwargs.setdefault("agent_id", "test-agent")
    kwargs.setdefault("asserted_by", "agent:test-agent")
    return GraphUpdate(**kwargs)


@pytest.fixture
def ctx():
    return _make_ctx()


@pytest.fixture
def tmp_schema() -> str:
    return f"graphindex_test_{uuid.uuid4().hex[:12]}"


@pytest.fixture
async def persistence(tmp_schema):
    p = PostgresPersistence(PG_DSN, schema=tmp_schema)
    try:
        yield p
    finally:
        pool = await p._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {tmp_schema} CASCADE")
        await p.close()


@pytest.fixture
def publisher(persistence, ctx):
    return GraphPublisher(persistence, ctx)


# =====================================================================
# Publish -> load round-trip
# =====================================================================


async def test_publish_persists_and_loads(publisher, persistence, ctx):
    receipt = await publisher.publish(
        make_update(nodes=[make_node("a"), make_node("b")], edges=[make_edge("a", "b")], op="create_node")
    )
    assert receipt.commit_id
    nodes, edges = await persistence.load_graph(ctx)
    assert {n.node_id for n in nodes} == {"a", "b"}
    assert [(e.source_id, e.target_id) for e in edges] == [("a", "b")]


async def test_assertion_round_trips(publisher, persistence, ctx):
    await publisher.publish(make_update(nodes=[make_node("a")], run_id="r9"))
    nodes, _ = await persistence.load_graph(ctx)
    node = nodes[0]
    assert node.provenance.value == "asserted"
    assert node.assertion.asserted_by == "agent:test-agent"
    assert node.assertion.run_id == "r9"


async def test_load_graph_excludes_removed(publisher, persistence, ctx):
    await publisher.publish(make_update(nodes=[make_node("a"), make_node("dup")]))
    await publisher.publish(make_update(removed_nodes=["dup"], op="merge_nodes"))
    nodes, _ = await persistence.load_graph(ctx)
    assert {n.node_id for n in nodes} == {"a"}


# =====================================================================
# Commit history
# =====================================================================


async def test_list_commits_ordered_and_filtered(publisher):
    await publisher.publish(make_update(nodes=[make_node("a")], run_id="r1"))
    await publisher.publish(make_update(nodes=[make_node("b")], run_id="r2"))
    commits = await publisher.list_commits()
    assert len(commits) == 2
    assert commits[0]["run_id"] == "r2"  # newest (highest seq) first
    assert "payload" not in commits[0]
    only_r1 = await publisher.list_commits(run_id="r1")
    assert [c["run_id"] for c in only_r1] == ["r1"]
    by_agent = await publisher.list_commits(agent_id="test-agent")
    assert len(by_agent) == 2


async def test_get_commit_payload_and_items(publisher):
    receipt = await publisher.publish(make_update(nodes=[make_node("a")], reason="why not"))
    commit = await publisher.get_commit(receipt.commit_id)
    assert commit["reason"] == "why not"
    assert commit["payload"]["nodes"][0]["node_id"] == "a"
    assert any(i["item_key"] == "a" for i in commit["items"])


async def test_get_commit_unknown_returns_none(publisher):
    assert await publisher.get_commit("nope") is None


async def test_list_commits_empty_store(persistence, ctx):
    assert await persistence.list_commits(ctx) == []


# =====================================================================
# Revert
# =====================================================================


async def test_revert_create_closes_validity(publisher, persistence, ctx):
    receipt = await publisher.publish(make_update(nodes=[make_node("a")], edges=[]))
    result = await publisher.revert_commit(receipt.commit_id)
    assert result["status"] == "reverted"
    nodes, _ = await persistence.load_graph(ctx)
    assert nodes == []


async def test_revert_update_restores_pre_image(publisher, persistence, ctx):
    await publisher.publish(make_update(nodes=[make_node("a", title="v1")]))
    r2 = await publisher.publish(make_update(nodes=[make_node("a", title="v2")]))
    assert (await publisher.revert_commit(r2.commit_id))["status"] == "reverted"
    nodes, _ = await persistence.load_graph(ctx)
    assert nodes[0].title == "v1"


async def test_revert_merge_restores_duplicate_and_edges(publisher, persistence, ctx):
    await publisher.publish(
        make_update(nodes=[make_node("a"), make_node("b"), make_node("dup")], edges=[make_edge("dup", "b")])
    )
    merge = await publisher.publish(
        make_update(edges=[make_edge("a", "b")], removed_nodes=["dup"], op="merge_nodes")
    )
    nodes, edges = await persistence.load_graph(ctx)
    assert {n.node_id for n in nodes} == {"a", "b"}
    assert ("dup", "b") not in [(e.source_id, e.target_id) for e in edges]

    result = await publisher.revert_commit(merge.commit_id)
    assert result["status"] == "reverted"
    nodes, edges = await persistence.load_graph(ctx)
    assert {n.node_id for n in nodes} == {"a", "b", "dup"}
    pairs = [(e.source_id, e.target_id) for e in edges]
    assert ("dup", "b") in pairs
    assert ("a", "b") not in pairs


async def test_revert_refused_on_later_conflicting_commit(publisher):
    r1 = await publisher.publish(make_update(nodes=[make_node("a")]))
    await publisher.publish(make_update(nodes=[make_node("a", title="v2")]))
    result = await publisher.revert_commit(r1.commit_id)
    assert "error" in result
    assert result["conflicts"] == ["a"]


async def test_reverse_order_unwind(publisher, persistence, ctx):
    r1 = await publisher.publish(make_update(nodes=[make_node("a", title="v1")]))
    r2 = await publisher.publish(make_update(nodes=[make_node("a", title="v2")]))
    assert (await publisher.revert_commit(r2.commit_id))["status"] == "reverted"
    assert (await publisher.revert_commit(r1.commit_id))["status"] == "reverted"
    nodes, _ = await persistence.load_graph(ctx)
    assert nodes == []


async def test_revert_twice_refused(publisher):
    r1 = await publisher.publish(make_update(nodes=[make_node("a")]))
    assert (await publisher.revert_commit(r1.commit_id))["status"] == "reverted"
    assert "error" in await publisher.revert_commit(r1.commit_id)


async def test_revert_unknown_commit(publisher):
    assert "error" in await publisher.revert_commit("missing")


# =====================================================================
# Receipt + implicit edges
# =====================================================================


async def test_receipt_includes_removed_and_implicit_edges(publisher):
    await publisher.publish(
        make_update(nodes=[make_node("a"), make_node("dup")], edges=[make_edge("dup", "a")])
    )
    receipt = await publisher.publish(make_update(removed_nodes=["dup"], op="merge_nodes"))
    assert "dup" in receipt.node_ids
    assert ("dup", "a", "references") in receipt.edge_keys


async def test_commit_doc_written_with_seq(publisher, persistence):
    r1 = await publisher.publish(make_update(nodes=[make_node("a")]))
    r2 = await publisher.publish(make_update(nodes=[make_node("b")]))
    pool = await persistence._ensure_pool()
    async with pool.acquire() as conn:
        seq1 = await conn.fetchval(
            f"SELECT seq FROM {persistence._schema}.commits WHERE commit_id = $1", r1.commit_id
        )
        seq2 = await conn.fetchval(
            f"SELECT seq FROM {persistence._schema}.commits WHERE commit_id = $1", r2.commit_id
        )
    assert seq1 == 1
    assert seq2 == 2


# =====================================================================
# Postgres-specific: transactional atomicity + tombstone-by-range
# =====================================================================


async def test_apply_update_atomic_rollback(persistence, ctx):
    """A forced failure mid-apply must roll back commit + items + mutations.

    Trigger: pre-insert a commit row under a fixed id, then monkeypatch
    ``uuid.uuid4`` so ``apply_update`` mints the SAME commit_id — the
    commits table's PRIMARY KEY rejects the duplicate INSERT partway
    through the transaction. If the transaction is truly atomic, the
    node upsert issued earlier in the same call never becomes visible.
    """
    forced_id = "dupcommitid12345"  # exactly 16 chars — matches uuid4().hex[:16] slicing
    pool = await persistence._ensure_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            f"""INSERT INTO {persistence._schema}.commits
                (commit_id, op, agent_id, run_id, asserted_by, reason, payload)
                VALUES ($1, 'publish', 'a', null, 'agent:a', null, '{{}}'::jsonb)""",
            forced_id,
        )

    update = GraphUpdate(nodes=[make_node("should_not_persist")], agent_id="a", asserted_by="agent:a")

    class _FixedUUID:
        hex = forced_id

    with patch("parrot.knowledge.graphindex.persist_postgres.uuid.uuid4", return_value=_FixedUUID()):
        with pytest.raises(Exception):  # noqa: B017 — asyncpg.UniqueViolationError, checked broadly on purpose
            await persistence.apply_update(ctx, update)

    nodes, _ = await persistence.load_graph(ctx)
    assert "should_not_persist" not in {n.node_id for n in nodes}


async def test_removed_node_closes_validity_not_delete(persistence, ctx):
    update = GraphUpdate(nodes=[make_node("a")], agent_id="a", asserted_by="agent:a")
    await persistence.apply_update(ctx, update)

    removal = GraphUpdate(removed_nodes=["a"], agent_id="a", asserted_by="agent:a", op="merge_nodes")
    await persistence.apply_update(ctx, removal)

    pool = await persistence._ensure_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM {persistence._schema}.node_versions WHERE concept_id = 'a'"
        )
        open_count = await conn.fetchval(
            f"""SELECT COUNT(*) FROM {persistence._schema}.node_versions
                WHERE concept_id = 'a' AND upper_inf(validity)"""
        )
    assert total == 1  # the row still exists (tombstone-by-range, not DELETE)
    assert open_count == 0  # but its validity range is closed


async def test_graphpublisher_smoke(persistence, ctx):
    """GraphPublisher works unchanged over PostgresPersistence (spec integration point)."""
    publisher = GraphPublisher(persistence, ctx)
    receipt = await publisher.publish(make_update(nodes=[make_node("smoke")]))
    assert receipt.commit_id
    commit = await publisher.get_commit(receipt.commit_id)
    assert commit is not None
