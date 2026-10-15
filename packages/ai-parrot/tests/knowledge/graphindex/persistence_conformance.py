"""Reusable GraphPersistence conformance cases (FEAT-540 M7).

Import the ``case_*`` coroutines (or ``ALL_CASES`` / ``STATELESS_CASES``) from a per-backend test and call each
with a fresh ``persistence`` and a ``ctx`` that has a ``tenant_id``. Every case derives its expectations from the
semantics documented on ``parrot.knowledge.graphindex.protocols.GraphPersistence``.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from parrot.knowledge.graphindex.protocols import edge_key
from parrot.knowledge.graphindex.schema import EdgeKind, GraphUpdate, NodeKind, UniversalEdge, UniversalNode

Case = Callable[[Any, Any], Awaitable[None]]


def _node(node_id: str, title: str = "", source_uri: str = "doc.py") -> UniversalNode:
    return UniversalNode(node_id=node_id, kind=NodeKind.SYMBOL, title=title or node_id, source_uri=source_uri)


def _edge(src: str, dst: str, kind: EdgeKind = EdgeKind.REFERENCES) -> UniversalEdge:
    return UniversalEdge(source_id=src, target_id=dst, kind=kind)


def _update(**kwargs: Any) -> GraphUpdate:
    kwargs.setdefault("agent_id", "conformance")
    kwargs.setdefault("asserted_by", "conformance")
    return GraphUpdate(**kwargs)


async def _graph(persistence: Any, ctx: Any) -> tuple[dict[str, Any], list[tuple[str, str, str]]]:
    nodes, edges = await persistence.load_graph(ctx)
    return {n.node_id: n for n in nodes}, sorted((e.source_id, e.target_id, e.kind.value) for e in edges)


async def case_apply_and_revert(persistence: Any, ctx: Any) -> None:
    """apply_update lands the write; reverting restores the pre-image (no node left behind)."""
    receipt = await persistence.apply_update(ctx, _update(nodes=[_node("a")]))
    nodes, _ = await _graph(persistence, ctx)
    assert set(nodes) == {"a"}
    result = await persistence.revert_commit(ctx, receipt.commit_id)
    assert "error" not in result, result
    nodes, _ = await _graph(persistence, ctx)
    assert nodes == {}


async def case_seq_monotonic(persistence: Any, ctx: Any) -> None:
    """Successive commits get distinct ids and all appear in the commit history."""
    ids = []
    for i in range(3):
        receipt = await persistence.apply_update(ctx, _update(nodes=[_node(f"n{i}")]))
        ids.append(receipt.commit_id)
    assert len(set(ids)) == 3
    listed = {c["commit_id"] for c in await persistence.list_commits(ctx, limit=10)}
    assert set(ids) <= listed


async def case_edge_key_identity(persistence: Any, ctx: Any) -> None:
    """Edge identity is ``source|target|kind``; a duplicate in one commit yields one stored edge."""
    assert edge_key("a", "b", "references") == "a|b|references"
    edge = _edge("a", "b")
    await persistence.apply_update(ctx, _update(nodes=[_node("a"), _node("b")], edges=[edge, edge]))
    _, edges = await _graph(persistence, ctx)
    assert edges == [("a", "b", EdgeKind.REFERENCES.value)]


async def case_incident_edge_preimages(persistence: Any, ctx: Any) -> None:
    """Removing a node removes its incident edges; reverting restores the node AND the edges."""
    await persistence.apply_update(ctx, _update(nodes=[_node("a"), _node("b")], edges=[_edge("a", "b")]))
    receipt = await persistence.apply_update(ctx, _update(removed_nodes=["a"]))
    nodes, edges = await _graph(persistence, ctx)
    assert set(nodes) == {"b"} and edges == []
    result = await persistence.revert_commit(ctx, receipt.commit_id)
    assert "error" not in result, result
    nodes, edges = await _graph(persistence, ctx)
    assert set(nodes) == {"a", "b"}
    assert edges == [("a", "b", EdgeKind.REFERENCES.value)]


async def case_revert_conflict(persistence: Any, ctx: Any) -> None:
    """Reverting a commit is refused while a later commit touched one of its items."""
    first = await persistence.apply_update(ctx, _update(nodes=[_node("a", "one")]))
    await persistence.apply_update(ctx, _update(nodes=[_node("a", "two")]))
    result = await persistence.revert_commit(ctx, first.commit_id)
    assert "error" in result, result
    nodes, _ = await _graph(persistence, ctx)
    assert nodes["a"].title == "two"


async def case_slice_atomic_idempotent(persistence: Any, ctx: Any, *, stores: bool = True) -> None:
    """replace_document_slice swaps a document's items and is idempotent on identical input.

    Args:
        persistence: Backend under test.
        ctx: Tenant context.
        stores: ``False`` for a backend that keeps nothing (the null backend): only idempotence is asserted.
    """
    uri = "slice.py"
    nodes = [_node("s1", source_uri=uri), _node("s2", source_uri=uri)]
    edges = [_edge("s1", "s2")]
    await persistence.replace_document_slice(ctx, uri, nodes, edges)
    first = await _graph(persistence, ctx)
    await persistence.replace_document_slice(ctx, uri, nodes, edges)
    second = await _graph(persistence, ctx)
    assert set(first[0]) == set(second[0]) and first[1] == second[1]
    if stores:
        assert set(first[0]) == {"s1", "s2"}
        assert first[1] == [("s1", "s2", EdgeKind.REFERENCES.value)]
        await persistence.replace_document_slice(ctx, uri, [_node("s3", source_uri=uri)], [])
        swapped, swapped_edges = await _graph(persistence, ctx)
        assert set(swapped) == {"s3"} and swapped_edges == []


async def case_missing_store_reads_empty(persistence: Any, ctx: Any) -> None:
    """A tenant that never wrote reads as an empty graph, never as an error."""
    nodes, edges = await persistence.load_graph(ctx)
    assert list(nodes) == [] and list(edges) == []


async def case_errors_propagate(broken: Any, ctx: Any) -> None:
    """A write against a backend whose store is unusable raises instead of returning an empty result.

    Args:
        broken: A backend instance whose underlying store cannot be written (supplied by the per-backend test).
        ctx: Tenant context.
    """
    try:
        await broken.persist_graph(ctx, [_node("x")], [])
    except Exception:  # noqa: BLE001 - any driver exception proves propagation
        return
    raise AssertionError("backend swallowed a store failure")


# Cases that need a backend that actually stores data.
ALL_CASES: list[Case] = [
    case_apply_and_revert,
    case_seq_monotonic,
    case_edge_key_identity,
    case_incident_edge_preimages,
    case_revert_conflict,
    case_slice_atomic_idempotent,
    case_missing_store_reads_empty,
]

# Cases whose assertions hold for a store-nothing backend such as ``NullPersistence``.
STATELESS_CASES: list[Case] = [case_missing_store_reads_empty]
