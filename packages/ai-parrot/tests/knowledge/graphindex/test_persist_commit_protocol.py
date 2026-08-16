"""Behavioral tests for the ArangoDB commit protocol on GraphIndexPersistence.

Runs the FULL protocol (publish → load → history → revert → conflict)
against an in-memory ``FakeGraphStore`` that implements the
``OntologyGraphStore`` helper surface over Python dicts — real
end-to-end coverage of the persistence logic without AQL emulation or a
live ArangoDB (the ``asyncdb`` driver is not available in CI).
"""

import itertools
from typing import Any, Optional

import pytest

from parrot.knowledge.graphindex.persist import (
    COMMIT_ITEMS_COLLECTION,
    COMMITS_COLLECTION,
    GraphIndexPersistence,
    _edge_to_doc,
    _node_to_doc,
)
from parrot.knowledge.graphindex.publish import GraphPublisher
from parrot.knowledge.graphindex.schema import (
    AssertionMeta,
    EdgeKind,
    GraphUpdate,
    NodeKind,
    Provenance,
    UniversalEdge,
    UniversalNode,
)
from parrot.knowledge.ontology.schema import MergedOntology, TenantContext


def make_ctx(tenant_id: str = "test-tenant") -> TenantContext:
    """Minimal TenantContext (ontology stub bypasses validation)."""
    fake_ontology = MergedOntology.model_construct(
        name="test",
        version="1.0",
        entities={},
        relations={},
        traversal_patterns={},
        layers=[],
        merge_timestamp=None,
    )
    return TenantContext(
        tenant_id=tenant_id,
        arango_db=f"db_{tenant_id}",
        pgvector_schema=f"schema_{tenant_id}",
        ontology=fake_ontology,
    )


class _FakeUpsertResult:
    def __init__(self, inserted: int, updated: int) -> None:
        self.inserted = inserted
        self.updated = updated
        self.unchanged = 0


class FakeGraphStore:
    """In-memory double implementing the OntologyGraphStore surface used
    by GraphIndexPersistence (documents keyed per collection)."""

    def __init__(self) -> None:
        self.collections: dict[str, dict[str, dict[str, Any]]] = {}
        self.edge_collections: set[str] = set()
        self._auto_key = itertools.count(1)

    # -- helpers used by the protocol ---------------------------------

    async def ensure_collection(self, ctx, name, edge=False):
        self.collections.setdefault(name, {})
        if edge:
            self.edge_collections.add(name)

    async def get_document(self, ctx, collection, key):
        doc = self.collections.get(collection, {}).get(key)
        return dict(doc) if doc is not None else None

    async def upsert_document(self, ctx, collection, doc):
        col = self.collections.setdefault(collection, {})
        key = doc.get("_key") or f"auto{next(self._auto_key)}"
        col[key] = {**doc, "_key": key}

    async def insert_document(self, ctx, collection, doc):
        col = self.collections.setdefault(collection, {})
        key = doc.get("_key") or f"auto{next(self._auto_key)}"
        col[key] = {**doc, "_key": key}

    async def remove_document(self, ctx, collection, key):
        col = self.collections.setdefault(collection, {})
        return col.pop(key, None) is not None

    async def query_documents(
        self, ctx, collection, filters=None, sort_desc=None, limit=None
    ):
        rows = [
            dict(d)
            for d in self.collections.get(collection, {}).values()
            if all(d.get(k) == v for k, v in (filters or {}).items())
        ]
        if sort_desc is not None:
            rows.sort(key=lambda d: d.get(sort_desc) or 0, reverse=True)
        if limit is not None:
            rows = rows[:limit]
        return rows

    async def get_all_edges(self, ctx, collection):
        return [dict(d) for d in self.collections.get(collection, {}).values()]

    async def edges_incident(self, ctx, collection, node_id):
        return [
            dict(d)
            for d in self.collections.get(collection, {}).values()
            if d.get("source_id") == node_id or d.get("target_id") == node_id
        ]

    async def remove_edge_by_triple(self, ctx, collection, source_id, target_id, kind):
        col = self.collections.setdefault(collection, {})
        matches = [
            k
            for k, d in col.items()
            if d.get("source_id") == source_id
            and d.get("target_id") == target_id
            and d.get("kind") == kind
        ]
        for k in matches:
            col.pop(k)
        return bool(matches)

    # -- legacy surface used by _upsert_nodes/_create_edges -----------

    async def upsert_nodes(self, ctx, collection, nodes, key_field):
        col = self.collections.setdefault(collection, {})
        inserted = updated = 0
        for doc in nodes:
            key = doc.get("_key") or doc.get(key_field)
            if key in col:
                updated += 1
            else:
                inserted += 1
            col[key] = {**doc, "_key": key, "_active": True}
        return _FakeUpsertResult(inserted, updated)

    async def create_edges(self, ctx, edge_collection, edges):
        col = self.collections.setdefault(edge_collection, {})
        self.edge_collections.add(edge_collection)
        for doc in edges:
            # Real store upserts on the (_from, _to) composite.
            existing = [
                k
                for k, d in col.items()
                if d.get("_from") == doc.get("_from")
                and d.get("_to") == doc.get("_to")
                and d.get("kind") == doc.get("kind")
            ]
            key = existing[0] if existing else f"auto{next(self._auto_key)}"
            col[key] = {**doc, "_key": key}
        return len(edges)

    async def get_all_nodes(self, ctx, collection):
        return [
            dict(d)
            for d in self.collections.get(collection, {}).values()
            if d.get("_active") is not False
        ]

    async def soft_delete_nodes(self, ctx, collection, keys):
        col = self.collections.setdefault(collection, {})
        for key in keys:
            if key in col:
                col[key]["_active"] = False


def make_node(node_id: str, title: str = "", **kwargs) -> UniversalNode:
    return UniversalNode(
        node_id=node_id,
        kind=kwargs.pop("kind", NodeKind.CONCEPT),
        title=title or f"Node {node_id}",
        source_uri=kwargs.pop("source_uri", f"agent://concept/{node_id}"),
        **kwargs,
    )


def make_edge(src: str, tgt: str, kind: EdgeKind = EdgeKind.REFERENCES) -> UniversalEdge:
    return UniversalEdge(source_id=src, target_id=tgt, kind=kind)


def make_update(**kwargs) -> GraphUpdate:
    kwargs.setdefault("agent_id", "test-agent")
    kwargs.setdefault("asserted_by", "agent:test-agent")
    return GraphUpdate(**kwargs)


@pytest.fixture
def ctx():
    return make_ctx()


@pytest.fixture
def store():
    return FakeGraphStore()


@pytest.fixture
def persistence(store):
    return GraphIndexPersistence(store)


@pytest.fixture
def publisher(persistence, ctx):
    return GraphPublisher(persistence, ctx)


# =====================================================================
# Doc mapping — assertion serialization
# =====================================================================


class TestDocMapping:
    def test_node_doc_carries_assertion(self):
        meta = AssertionMeta(
            asserted_by="agent:x",
            asserted_at="2026-01-01T00:00:00+00:00",
            run_id="r1",
        )
        doc = _node_to_doc(make_node("a", assertion=meta))
        assert doc["assertion"]["asserted_by"] == "agent:x"
        assert doc["assertion"]["run_id"] == "r1"

    def test_node_doc_assertion_none(self):
        assert _node_to_doc(make_node("a"))["assertion"] is None

    def test_edge_doc_carries_assertion(self):
        meta = AssertionMeta(
            asserted_by="agent:x", asserted_at="2026-01-01T00:00:00+00:00"
        )
        edge = UniversalEdge(
            source_id="a",
            target_id="b",
            kind=EdgeKind.REFERENCES,
            provenance=Provenance.ASSERTED,
            assertion=meta,
        )
        doc = _edge_to_doc(edge, {}, {})
        assert doc["assertion"]["asserted_by"] == "agent:x"


# =====================================================================
# Publish → load round-trip
# =====================================================================


class TestPublishAndLoad:
    async def test_publish_persists_and_loads(self, publisher, persistence, ctx):
        receipt = await publisher.publish(
            make_update(
                nodes=[make_node("a"), make_node("b")],
                edges=[make_edge("a", "b")],
                op="create_node",
            )
        )
        assert receipt.commit_id
        nodes, edges = await persistence.load_graph(ctx)
        assert {n.node_id for n in nodes} == {"a", "b"}
        assert [(e.source_id, e.target_id) for e in edges] == [("a", "b")]

    async def test_assertion_round_trips(self, publisher, persistence, ctx):
        await publisher.publish(make_update(nodes=[make_node("a")], run_id="r9"))
        nodes, _ = await persistence.load_graph(ctx)
        node = nodes[0]
        assert node.provenance is Provenance.ASSERTED
        assert node.assertion.asserted_by == "agent:test-agent"
        assert node.assertion.run_id == "r9"

    async def test_run_and_claim_kinds_reach_their_collections(
        self, publisher, store
    ):
        await publisher.publish(
            make_update(
                nodes=[
                    make_node("run:1", kind=NodeKind.RUN),
                    make_node("claim-1", kind=NodeKind.CLAIM),
                ],
                edges=[make_edge("run:1", "claim-1", EdgeKind.PRODUCED)],
            )
        )
        assert "run:1" in store.collections["gi_runs"]
        assert "claim-1" in store.collections["gi_claims"]
        assert len(store.collections["gi_produced"]) == 1

    async def test_edge_endpoints_resolved_from_existing_graph(
        self, publisher, store
    ):
        # Nodes land in one commit; the linking edge in a later one.
        await publisher.publish(
            make_update(nodes=[make_node("a"), make_node("b")])
        )
        await publisher.publish(
            make_update(edges=[make_edge("a", "b")], op="link_nodes")
        )
        edge_doc = next(iter(store.collections["gi_references"].values()))
        # _from/_to must be fully qualified even though the endpoints
        # were not part of the same update.
        assert edge_doc["_from"] == "gi_concepts/a"
        assert edge_doc["_to"] == "gi_concepts/b"

    async def test_load_graph_excludes_soft_deleted(self, publisher, persistence, ctx):
        await publisher.publish(
            make_update(nodes=[make_node("a"), make_node("dup")])
        )
        await publisher.publish(
            make_update(removed_nodes=["dup"], op="merge_nodes")
        )
        nodes, _ = await persistence.load_graph(ctx)
        assert {n.node_id for n in nodes} == {"a"}

    async def test_load_graph_skips_unknown_kinds(self, persistence, store, ctx):
        store.collections["gi_concepts"] = {
            "good": {
                "_key": "good", "node_id": "good", "kind": "concept",
                "title": "Good", "source_uri": "x", "_active": True,
            },
            "future": {
                "_key": "future", "node_id": "future", "kind": "hologram",
                "title": "Future", "source_uri": "x", "_active": True,
            },
        }
        nodes, _ = await persistence.load_graph(ctx)
        assert {n.node_id for n in nodes} == {"good"}

    async def test_load_graph_unreachable_store_returns_empty(self, ctx):
        class _BrokenStore:
            async def get_all_nodes(self, *a, **k):
                raise RuntimeError("no connection")

        persistence = GraphIndexPersistence(_BrokenStore())
        assert await persistence.load_graph(ctx) == ([], [])


# =====================================================================
# Commit history
# =====================================================================


class TestCommitHistory:
    async def test_list_commits_ordered_and_filtered(self, publisher):
        await publisher.publish(make_update(nodes=[make_node("a")], run_id="r1"))
        await publisher.publish(make_update(nodes=[make_node("b")], run_id="r2"))
        commits = await publisher.list_commits()
        assert len(commits) == 2
        # Newest (highest seq) first.
        assert commits[0]["run_id"] == "r2"
        assert "payload" not in commits[0]
        only_r1 = await publisher.list_commits(run_id="r1")
        assert [c["run_id"] for c in only_r1] == ["r1"]
        by_agent = await publisher.list_commits(agent_id="test-agent")
        assert len(by_agent) == 2

    async def test_get_commit_payload_and_items(self, publisher):
        receipt = await publisher.publish(
            make_update(nodes=[make_node("a")], reason="why not")
        )
        commit = await publisher.get_commit(receipt.commit_id)
        assert commit["reason"] == "why not"
        assert commit["payload"]["nodes"][0]["node_id"] == "a"
        assert any(i["item_key"] == "a" for i in commit["items"])

    async def test_get_commit_unknown_returns_none(self, publisher):
        assert await publisher.get_commit("nope") is None

    async def test_list_commits_empty_store(self, persistence, ctx):
        assert await persistence.list_commits(ctx) == []


# =====================================================================
# Revert
# =====================================================================


class TestRevert:
    async def test_revert_create_removes_docs(self, publisher, persistence, ctx, store):
        receipt = await publisher.publish(
            make_update(nodes=[make_node("a")], edges=[])
        )
        result = await publisher.revert_commit(receipt.commit_id)
        assert result["status"] == "reverted"
        nodes, _ = await persistence.load_graph(ctx)
        assert nodes == []
        # Hard-removed, not just soft-deleted (created by the commit).
        assert "a" not in store.collections["gi_concepts"]

    async def test_revert_update_restores_pre_image(
        self, publisher, persistence, ctx
    ):
        await publisher.publish(make_update(nodes=[make_node("a", title="v1")]))
        r2 = await publisher.publish(make_update(nodes=[make_node("a", title="v2")]))
        assert (await publisher.revert_commit(r2.commit_id))["status"] == "reverted"
        nodes, _ = await persistence.load_graph(ctx)
        assert nodes[0].title == "v1"

    async def test_revert_merge_restores_duplicate_and_edges(
        self, publisher, persistence, ctx
    ):
        await publisher.publish(
            make_update(
                nodes=[make_node("a"), make_node("b"), make_node("dup")],
                edges=[make_edge("dup", "b")],
            )
        )
        merge = await publisher.publish(
            make_update(
                edges=[make_edge("a", "b")],
                removed_nodes=["dup"],
                op="merge_nodes",
            )
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

    async def test_revert_refused_on_later_conflicting_commit(self, publisher):
        r1 = await publisher.publish(make_update(nodes=[make_node("a")]))
        await publisher.publish(make_update(nodes=[make_node("a", title="v2")]))
        result = await publisher.revert_commit(r1.commit_id)
        assert "error" in result
        assert result["conflicts"] == ["a"]

    async def test_reverse_order_unwind(self, publisher, persistence, ctx):
        r1 = await publisher.publish(make_update(nodes=[make_node("a", title="v1")]))
        r2 = await publisher.publish(make_update(nodes=[make_node("a", title="v2")]))
        assert (await publisher.revert_commit(r2.commit_id))["status"] == "reverted"
        assert (await publisher.revert_commit(r1.commit_id))["status"] == "reverted"
        nodes, _ = await persistence.load_graph(ctx)
        assert nodes == []

    async def test_revert_twice_refused(self, publisher):
        r1 = await publisher.publish(make_update(nodes=[make_node("a")]))
        assert (await publisher.revert_commit(r1.commit_id))["status"] == "reverted"
        assert "error" in await publisher.revert_commit(r1.commit_id)

    async def test_revert_unknown_commit(self, publisher):
        assert "error" in await publisher.revert_commit("missing")


# =====================================================================
# Receipt composition + audit-first ordering
# =====================================================================


class TestReceiptAndAudit:
    async def test_receipt_includes_removed(self, publisher):
        await publisher.publish(
            make_update(nodes=[make_node("a"), make_node("dup")],
                        edges=[make_edge("dup", "a")])
        )
        receipt = await publisher.publish(
            make_update(removed_nodes=["dup"], op="merge_nodes")
        )
        assert "dup" in receipt.node_ids
        # Implicit incident edge of the removed node is captured.
        assert ("dup", "a", "references") in receipt.edge_keys

    async def test_unknown_kind_warns_in_receipt(self, publisher, monkeypatch):
        import parrot.knowledge.graphindex.persist as persist_mod

        monkeypatch.setattr(persist_mod, "KIND_TO_COLLECTION", {})
        receipt = await publisher.publish(make_update(nodes=[make_node("a")]))
        assert receipt.warnings
        assert "unknown kind" in receipt.warnings[0]

    async def test_commit_doc_written_with_seq(self, publisher, store, ctx):
        r1 = await publisher.publish(make_update(nodes=[make_node("a")]))
        r2 = await publisher.publish(make_update(nodes=[make_node("b")]))
        commits = store.collections[COMMITS_COLLECTION]
        assert commits[r1.commit_id]["seq"] == 1
        assert commits[r2.commit_id]["seq"] == 2
        items = store.collections[COMMIT_ITEMS_COLLECTION]
        assert len(items) == 2
