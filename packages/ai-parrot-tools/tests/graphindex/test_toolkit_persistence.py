"""Tests for GraphIndexToolkit durable write-through (graph memory).

Covers the publisher-wired toolkit built by
``parrot.knowledge.graphindex.factory.build_graph_memory_toolkit``:
  - writes persist across a fresh factory reload (cross-session memory)
  - graceful degradation when persistence fails (persist_warning)
  - legacy parity: no publisher → identical result shape, no persistence keys
  - graph_history / revert_write tool surface
  - merge_nodes alias retention on the durable plane
"""
from __future__ import annotations

import pytest

from parrot.knowledge.graphindex.factory import build_graph_memory_toolkit
from parrot_tools.graphindex.toolkit import GraphIndexToolkit


@pytest.fixture
def db_dir(tmp_path):
    return tmp_path / "graph_memory"


class _FailingPublisher:
    """Publisher double whose publish always raises."""

    async def publish(self, update):
        raise RuntimeError("disk on fire")


class TestWriteThrough:
    async def test_create_concept_returns_commit(self, db_dir):
        tk = await build_graph_memory_toolkit(db_dir=db_dir, agent_id="ag")
        result = await tk.create_concept("EventBus", "pubsub hub")
        assert result["status"] == "created"
        assert result["persisted"] is True
        assert result["commit_id"]

    async def test_writes_survive_reload(self, db_dir):
        tk = await build_graph_memory_toolkit(db_dir=db_dir, agent_id="ag")
        r1 = await tk.create_concept("EventBus", "publish subscribe hub")
        r2 = await tk.create_concept("OrderService", "emits order events")
        await tk.link_nodes(r2["node_id"], r1["node_id"], "references")

        tk2 = await build_graph_memory_toolkit(db_dir=db_dir, agent_id="ag")
        assert tk2.graph.num_nodes() == 2
        assert tk2.graph.num_edges() == 1
        assert {n.node_id for n in tk2.nodes} == {r1["node_id"], r2["node_id"]}

    async def test_unlink_survives_reload(self, db_dir):
        tk = await build_graph_memory_toolkit(db_dir=db_dir, agent_id="ag")
        r1 = await tk.create_concept("A", "a")
        r2 = await tk.create_concept("B", "b")
        await tk.link_nodes(r1["node_id"], r2["node_id"], "references")
        result = await tk.unlink_nodes(r1["node_id"], r2["node_id"])
        assert result["status"] == "unlinked"
        assert result["persisted"] is True

        tk2 = await build_graph_memory_toolkit(db_dir=db_dir, agent_id="ag")
        assert tk2.graph.num_edges() == 0

    async def test_attach_summary_and_tag_survive_reload(self, db_dir):
        tk = await build_graph_memory_toolkit(db_dir=db_dir, agent_id="ag")
        r = await tk.create_concept("A", "initial")
        await tk.attach_summary(r["node_id"], "improved summary")
        await tk.tag_node(r["node_id"], "reviewed", True)

        tk2 = await build_graph_memory_toolkit(db_dir=db_dir, agent_id="ag")
        node = [n for n in tk2.nodes if n.node_id == r["node_id"]][0]
        assert node.summary == "improved summary"
        assert node.domain_tags["reviewed"] is True

    async def test_merge_nodes_alias_retention_durable(self, db_dir):
        tk = await build_graph_memory_toolkit(db_dir=db_dir, agent_id="ag")
        canonical = await tk.create_concept("EventBus", "pubsub hub")
        dup = await tk.create_concept("Event Bus", "the pubsub hub (dup)")
        other = await tk.create_concept("Consumer", "listens to events")
        await tk.link_nodes(dup["node_id"], other["node_id"], "references")

        result = await tk.merge_nodes(canonical["node_id"], dup["node_id"])
        assert result["status"] == "merged"
        assert "Event Bus" in result["aliases_added"]
        assert result["persisted"] is True

        tk2 = await build_graph_memory_toolkit(db_dir=db_dir, agent_id="ag")
        assert {n.node_id for n in tk2.nodes} == {
            canonical["node_id"], other["node_id"],
        }
        node = [n for n in tk2.nodes if n.node_id == canonical["node_id"]][0]
        assert "Event Bus" in node.domain_tags["aliases"]
        # Redirected edge survives.
        assert tk2.graph.num_edges() == 1

    async def test_assertion_metadata_stamped(self, db_dir):
        tk = await build_graph_memory_toolkit(
            db_dir=db_dir, agent_id="ag", run_id="run-7"
        )
        r = await tk.create_concept("A", "a")
        tk2 = await build_graph_memory_toolkit(db_dir=db_dir, agent_id="ag")
        node = [n for n in tk2.nodes if n.node_id == r["node_id"]][0]
        assert node.assertion.asserted_by == "agent:ag"
        assert node.assertion.run_id == "run-7"


class TestDegradation:
    async def test_persist_failure_keeps_in_memory_write(self, db_dir):
        tk = await build_graph_memory_toolkit(db_dir=db_dir, agent_id="ag")
        tk.publisher = _FailingPublisher()
        result = await tk.create_concept("A", "a")
        assert result["status"] == "created"
        assert result["persisted"] is False
        assert "disk on fire" in result["persist_warning"]
        # In-memory state still mutated.
        assert tk.graph.num_nodes() == 1

    async def test_no_publisher_legacy_parity(self, db_dir):
        tk = await build_graph_memory_toolkit(db_dir=db_dir, agent_id="ag")
        tk.publisher = None
        result = await tk.create_concept("A", "a")
        assert result["status"] == "created"
        assert "persisted" not in result
        assert "commit_id" not in result


class TestHistoryAndRevert:
    async def test_graph_history_lists_commits(self, db_dir):
        tk = await build_graph_memory_toolkit(
            db_dir=db_dir, agent_id="ag", run_id="r1"
        )
        await tk.create_concept("A", "a")
        tk.run_id = "r2"
        await tk.create_concept("B", "b")
        history = await tk.graph_history()
        assert len(history) == 2
        assert {h["run_id"] for h in history} == {"r1", "r2"}
        filtered = await tk.graph_history(run_id="r2")
        assert len(filtered) == 1

    async def test_revert_write_restores_durable_plane(self, db_dir):
        tk = await build_graph_memory_toolkit(db_dir=db_dir, agent_id="ag")
        result = await tk.create_concept("A", "a")
        revert = await tk.revert_write(result["commit_id"])
        assert revert["status"] == "reverted"

        tk2 = await build_graph_memory_toolkit(db_dir=db_dir, agent_id="ag")
        assert tk2.graph.num_nodes() == 0

    async def test_history_and_revert_without_publisher(self, db_dir):
        tk = await build_graph_memory_toolkit(db_dir=db_dir, agent_id="ag")
        tk.publisher = None
        assert "error" in (await tk.graph_history())[0]
        assert "error" in await tk.revert_write("whatever")

    async def test_revert_write_is_confirming_tool(self):
        assert "revert_write" in GraphIndexToolkit.confirming_tools


class TestFactory:
    async def test_blank_dir_starts_empty(self, db_dir):
        tk = await build_graph_memory_toolkit(db_dir=db_dir)
        assert tk.graph.num_nodes() == 0
        assert await tk.graph_history() == []

    async def test_cross_session_search_finds_nodes(self, db_dir):
        tk = await build_graph_memory_toolkit(db_dir=db_dir, agent_id="ag")
        await tk.create_concept("EventBus", "publish subscribe hub for events")
        tk2 = await build_graph_memory_toolkit(db_dir=db_dir, agent_id="ag")
        found = await tk2.find_node("publish subscribe events")
        assert found.get("title") == "EventBus"
