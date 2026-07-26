"""Tests for the durable graph write path (GraphPublisher + apply_update).

Covers the publish → load → revert cycle, assertion stamping, conflict
refusal, node-removal (merge) semantics, and the ALTER-guard migration of
databases created with the pre-assertion schema.
"""

import aiosqlite
import pytest

from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
from parrot.knowledge.graphindex.publish import GraphPublisher
from parrot.knowledge.graphindex.schema import (
    AssertionMeta,
    EdgeKind,
    GraphUpdate,
    NodeKind,
    Provenance,
    UniversalEdge,
    UniversalNode,
    stable_edge_id,
)
from parrot.knowledge.ontology.schema import MergedOntology, TenantContext


def make_ctx(tenant_id: str = "test-tenant") -> TenantContext:
    """Create a minimal TenantContext for testing."""
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


def make_node(node_id: str, title: str = "", **kwargs) -> UniversalNode:
    """Create a minimal agent-authored node."""
    return UniversalNode(
        node_id=node_id,
        kind=kwargs.pop("kind", NodeKind.CONCEPT),
        title=title or f"Node {node_id}",
        source_uri=kwargs.pop("source_uri", f"agent://concept/{node_id}"),
        **kwargs,
    )


def make_edge(src: str, tgt: str, kind: EdgeKind = EdgeKind.REFERENCES) -> UniversalEdge:
    """Create a minimal edge."""
    return UniversalEdge(source_id=src, target_id=tgt, kind=kind)


def make_update(**kwargs) -> GraphUpdate:
    """Create a GraphUpdate with default attribution."""
    kwargs.setdefault("agent_id", "test-agent")
    kwargs.setdefault("asserted_by", "agent:test-agent")
    return GraphUpdate(**kwargs)


@pytest.fixture
def ctx():
    return make_ctx()


@pytest.fixture
def persistence(tmp_path):
    return SQLitePersistence(tmp_path)


@pytest.fixture
def publisher(persistence, ctx):
    return GraphPublisher(persistence, ctx)


# =====================================================================
# Schema models
# =====================================================================


class TestSchemaAdditions:
    def test_provenance_has_asserted(self):
        assert Provenance("asserted") is Provenance.ASSERTED

    def test_node_assertion_default_none(self):
        assert make_node("a").assertion is None

    def test_edge_assertion_does_not_touch_confidence_validator(self):
        meta = AssertionMeta(asserted_by="agent:x", asserted_at="2026-01-01T00:00:00+00:00")
        edge = UniversalEdge(
            source_id="a",
            target_id="b",
            kind=EdgeKind.REFERENCES,
            provenance=Provenance.ASSERTED,
            assertion=meta,
        )
        assert edge.confidence is None
        # INFERRED still requires similarity confidence.
        with pytest.raises(ValueError):
            UniversalEdge(
                source_id="a",
                target_id="b",
                kind=EdgeKind.MENTIONS,
                provenance=Provenance.INFERRED,
            )

    def test_assertion_confidence_bounds(self):
        with pytest.raises(ValueError):
            AssertionMeta(
                asserted_by="x", asserted_at="t", confidence=1.5,
            )

    def test_stable_edge_id_deterministic(self):
        a = stable_edge_id("n1", "n2", "references")
        b = stable_edge_id("n1", "n2", "references")
        c = stable_edge_id("n2", "n1", "references")
        assert a == b
        assert a != c
        assert len(a) == 12


# =====================================================================
# Publish / stamping
# =====================================================================


class TestPublish:
    async def test_publish_persists_nodes_and_edges(self, publisher, persistence, ctx):
        receipt = await publisher.publish(
            make_update(
                nodes=[make_node("a"), make_node("b")],
                edges=[make_edge("a", "b")],
                op="create_node",
            )
        )
        assert receipt.op == "create_node"
        assert set(receipt.node_ids) == {"a", "b"}
        nodes, edges = await persistence.load_graph(ctx)
        assert {n.node_id for n in nodes} == {"a", "b"}
        assert [(e.source_id, e.target_id) for e in edges] == [("a", "b")]

    async def test_publish_stamps_assertion_and_provenance(
        self, publisher, persistence, ctx
    ):
        await publisher.publish(
            make_update(nodes=[make_node("a")], run_id="run-9")
        )
        nodes, _ = await persistence.load_graph(ctx)
        node = nodes[0]
        assert node.provenance is Provenance.ASSERTED
        assert node.assertion is not None
        assert node.assertion.asserted_by == "agent:test-agent"
        assert node.assertion.agent_id == "test-agent"
        assert node.assertion.run_id == "run-9"

    async def test_publish_preserves_extracted_provenance_of_pipeline_nodes(
        self, publisher, persistence, ctx
    ):
        pipeline_node = make_node("mod", source_uri="src/module.py")
        await publisher.publish(make_update(nodes=[pipeline_node]))
        nodes, _ = await persistence.load_graph(ctx)
        # Not agent-minted (no agent:// URI) → provenance untouched,
        # but the write is still attributed.
        assert nodes[0].provenance is Provenance.EXTRACTED
        assert nodes[0].assertion is not None

    async def test_publish_preserves_existing_assertion(
        self, publisher, persistence, ctx
    ):
        meta = AssertionMeta(
            asserted_by="human:reviewer", asserted_at="2026-01-01T00:00:00+00:00"
        )
        await publisher.publish(
            make_update(nodes=[make_node("a", assertion=meta)])
        )
        nodes, _ = await persistence.load_graph(ctx)
        assert nodes[0].assertion.asserted_by == "human:reviewer"

    async def test_fts_partial_update_preserves_other_rows(
        self, publisher, persistence, ctx
    ):
        await publisher.publish(
            make_update(nodes=[make_node("a", title="Alpha topic")])
        )
        await publisher.publish(
            make_update(nodes=[make_node("b", title="Beta topic")])
        )
        db = persistence._db_path(ctx)
        async with aiosqlite.connect(str(db)) as conn:
            async with conn.execute(
                "SELECT node_id FROM nodes_fts WHERE nodes_fts MATCH 'Alpha'"
            ) as cur:
                rows = await cur.fetchall()
        assert [r[0] for r in rows] == ["a"]


# =====================================================================
# Commit history
# =====================================================================


class TestCommitHistory:
    async def test_list_commits_filters(self, publisher):
        await publisher.publish(make_update(nodes=[make_node("a")], run_id="r1"))
        await publisher.publish(make_update(nodes=[make_node("b")], run_id="r2"))
        all_commits = await publisher.list_commits()
        assert len(all_commits) == 2
        r1_commits = await publisher.list_commits(run_id="r1")
        assert len(r1_commits) == 1
        assert r1_commits[0]["run_id"] == "r1"

    async def test_get_commit_returns_payload_and_items(self, publisher):
        receipt = await publisher.publish(
            make_update(nodes=[make_node("a")], edges=[], reason="why not")
        )
        commit = await publisher.get_commit(receipt.commit_id)
        assert commit["reason"] == "why not"
        assert commit["payload"]["nodes"][0]["node_id"] == "a"
        assert any(i["item_key"] == "a" for i in commit["items"])

    async def test_get_commit_unknown_returns_none(self, publisher):
        assert await publisher.get_commit("nope") is None


# =====================================================================
# Revert
# =====================================================================


class TestRevert:
    async def test_revert_create_deletes_rows(self, publisher, persistence, ctx):
        receipt = await publisher.publish(
            make_update(nodes=[make_node("a")], edges=[])
        )
        result = await publisher.revert_commit(receipt.commit_id)
        assert result["status"] == "reverted"
        nodes, _ = await persistence.load_graph(ctx)
        assert nodes == []

    async def test_revert_update_restores_pre_image(
        self, publisher, persistence, ctx
    ):
        await publisher.publish(make_update(nodes=[make_node("a", title="v1")]))
        r2 = await publisher.publish(make_update(nodes=[make_node("a", title="v2")]))
        await publisher.revert_commit(r2.commit_id)
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
        result = await publisher.revert_commit(merge.commit_id)
        assert result["status"] == "reverted"
        nodes, edges = await persistence.load_graph(ctx)
        assert {n.node_id for n in nodes} == {"a", "b", "dup"}
        assert ("dup", "b") in [(e.source_id, e.target_id) for e in edges]
        assert ("a", "b") not in [(e.source_id, e.target_id) for e in edges]

    async def test_revert_refused_on_later_conflicting_commit(self, publisher):
        r1 = await publisher.publish(make_update(nodes=[make_node("a")]))
        await publisher.publish(make_update(nodes=[make_node("a", title="v2")]))
        result = await publisher.revert_commit(r1.commit_id)
        assert "error" in result
        assert result["conflicts"] == ["a"]

    async def test_revert_twice_refused(self, publisher):
        r1 = await publisher.publish(make_update(nodes=[make_node("a")]))
        assert (await publisher.revert_commit(r1.commit_id))["status"] == "reverted"
        assert "error" in await publisher.revert_commit(r1.commit_id)

    async def test_revert_unknown_commit(self, publisher):
        assert "error" in await publisher.revert_commit("missing")

    async def test_reverse_order_unwind(self, publisher, persistence, ctx):
        r1 = await publisher.publish(make_update(nodes=[make_node("a", title="v1")]))
        r2 = await publisher.publish(make_update(nodes=[make_node("a", title="v2")]))
        assert (await publisher.revert_commit(r2.commit_id))["status"] == "reverted"
        assert (await publisher.revert_commit(r1.commit_id))["status"] == "reverted"
        nodes, _ = await persistence.load_graph(ctx)
        assert nodes == []


# =====================================================================
# Migration of pre-assertion databases
# =====================================================================

_OLD_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS files (
    source_uri  TEXT PRIMARY KEY,
    mtime       REAL NOT NULL,
    sha1        TEXT NOT NULL,
    indexed_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nodes (
    node_id       TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    title         TEXT NOT NULL,
    source_uri    TEXT NOT NULL,
    parent_id     TEXT,
    summary       TEXT,
    content_ref   TEXT,
    embedding_ref TEXT,
    provenance    TEXT NOT NULL,
    domain_tags   TEXT
);
CREATE TABLE IF NOT EXISTS edges (
    source_id   TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    kind        TEXT NOT NULL,
    provenance  TEXT NOT NULL,
    confidence  REAL,
    source_uri  TEXT,
    PRIMARY KEY (source_id, target_id, kind)
);
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    node_id UNINDEXED, title, summary, tokenize = 'unicode61'
);
"""


class TestMigration:
    async def test_old_schema_db_migrates_and_accepts_writes(
        self, tmp_path, ctx
    ):
        # Build a DB file with the pre-assertion schema and a legacy row.
        db_path = tmp_path / f"{ctx.tenant_id}.db"
        async with aiosqlite.connect(str(db_path)) as conn:
            await conn.executescript(_OLD_SCHEMA_SQL)
            await conn.execute(
                "INSERT INTO nodes (node_id, kind, title, source_uri, provenance)"
                " VALUES ('legacy', 'concept', 'Legacy', 'x.py', 'extracted')"
            )
            await conn.commit()

        persistence = SQLitePersistence(tmp_path)
        publisher = GraphPublisher(persistence, ctx)
        receipt = await publisher.publish(make_update(nodes=[make_node("new")]))
        assert receipt.commit_id

        nodes, _ = await persistence.load_graph(ctx)
        by_id = {n.node_id: n for n in nodes}
        assert by_id["legacy"].assertion is None
        assert by_id["new"].assertion is not None

    async def test_unknown_enum_rows_skipped_not_raised(self, tmp_path, ctx):
        persistence = SQLitePersistence(tmp_path)
        await persistence.persist_graph(ctx, [make_node("known")], [])
        db_path = persistence._db_path(ctx)
        async with aiosqlite.connect(str(db_path)) as conn:
            await conn.execute(
                "INSERT INTO nodes (node_id, kind, title, source_uri, provenance)"
                " VALUES ('future', 'hologram', 'Future kind', 'x', 'extracted')"
            )
            await conn.commit()
        nodes, _ = await persistence.load_graph(ctx)
        assert {n.node_id for n in nodes} == {"known"}
