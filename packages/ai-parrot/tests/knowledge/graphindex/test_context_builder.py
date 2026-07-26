"""Tests for GraphContextBuilder and the GraphMemoryMixin.

Uses the offline factory (deterministic hashing embedder + SQLite plane)
so no model downloads or DBs are required.
"""

from pathlib import Path

import pytest

from parrot.knowledge.graphindex.context_builder import (
    ContextBuildConfig,
    GraphContextBuilder,
)
from parrot.knowledge.graphindex.factory import build_graph_memory_toolkit
from parrot.knowledge.graphindex.mixin import GraphMemoryMixin
from parrot.knowledge.graphindex.retriever import (
    ExpansionConfig,
    GraphExpandedRetriever,
)
from parrot.knowledge.graphindex.schema import stable_edge_id


async def _populated_toolkit(db_dir: Path):
    """Toolkit with a small durable knowledge graph."""
    tk = await build_graph_memory_toolkit(db_dir=db_dir, agent_id="ag")
    bus = await tk.create_concept("EventBus", "publish subscribe hub for events")
    svc = await tk.create_concept("OrderService", "emits order events onto the bus")
    pol = await tk.create_concept("Deploy policy", "prod deploys need approval")
    await tk.link_nodes(svc["node_id"], bus["node_id"], "references")
    await tk.link_nodes(pol["node_id"], bus["node_id"], "mentions", confidence=0.4)
    return tk, bus["node_id"], svc["node_id"], pol["node_id"]


def _builder(tk) -> GraphContextBuilder:
    retriever = GraphExpandedRetriever(
        graph=tk.graph, nodes=tk.nodes, embedder=tk.embedder
    )
    return GraphContextBuilder(retriever)


class TestContextBuilder:
    async def test_entity_resolution_by_mention(self, tmp_path):
        tk, bus_id, svc_id, _ = await _populated_toolkit(tmp_path)
        ctx = await _builder(tk).build(
            "How does OrderService publish to the EventBus?"
        )
        assert set(ctx.entities) == {bus_id, svc_id}

    async def test_alias_mention_resolves(self, tmp_path):
        tk, bus_id, _, _ = await _populated_toolkit(tmp_path)
        await tk.tag_node(bus_id, "aliases", ["Message Hub"])
        ctx = await _builder(tk).build("Where is the Message Hub configured?")
        assert bus_id in ctx.entities

    async def test_relations_carry_stable_edge_ids(self, tmp_path):
        tk, bus_id, svc_id, _ = await _populated_toolkit(tmp_path)
        ctx = await _builder(tk).build("OrderService and EventBus integration")
        expected = stable_edge_id(svc_id, bus_id, "references")
        assert expected in ctx.cited_edge_ids
        assert f"[edge:{expected}]" in ctx.text

    async def test_asserted_nodes_carry_attribution(self, tmp_path):
        tk, _, _, _ = await _populated_toolkit(tmp_path)
        ctx = await _builder(tk).build("EventBus knowledge")
        assert "asserted by agent:ag" in ctx.text

    async def test_budget_truncation(self, tmp_path):
        tk, _, _, _ = await _populated_toolkit(tmp_path)
        ctx = await _builder(tk).build(
            "EventBus", ContextBuildConfig(max_tokens=200)
        )
        assert ctx.budget_used <= 200

    async def test_edge_kind_filter_excludes_relations(self, tmp_path):
        tk, bus_id, svc_id, pol_id = await _populated_toolkit(tmp_path)
        ctx = await _builder(tk).build(
            "OrderService EventBus Deploy policy",
            ContextBuildConfig(allowed_edge_kinds=["references"]),
        )
        assert stable_edge_id(svc_id, bus_id, "references") in ctx.cited_edge_ids
        assert stable_edge_id(pol_id, bus_id, "mentions") not in ctx.cited_edge_ids

    async def test_conflicts_surfaced(self, tmp_path):
        tk, bus_id, svc_id, _ = await _populated_toolkit(tmp_path)
        # Force an ambiguous edge payload (conflict surface).
        import rustworkx  # noqa: F401

        src_idx = tk.node_map[bus_id]
        for _s, _t, payload in tk.graph.out_edges(src_idx):
            payload["provenance"] = "ambiguous"
        ctx = await _builder(tk).build("EventBus OrderService Deploy policy")
        # No outgoing edges from bus in fixture; add one and re-check via
        # the svc->bus edge instead.
        svc_idx = tk.node_map[svc_id]
        for _s, _t, payload in tk.graph.out_edges(svc_idx):
            payload["provenance"] = "ambiguous"
        ctx = await _builder(tk).build("EventBus OrderService Deploy policy")
        assert ctx.conflicts
        assert "Conflicts / uncertain claims" in ctx.text


class TestExpansionEdgeKindFilter:
    async def test_expansion_respects_allowed_kinds(self, tmp_path):
        tk, bus_id, svc_id, pol_id = await _populated_toolkit(tmp_path)
        retriever = GraphExpandedRetriever(
            graph=tk.graph, nodes=tk.nodes, embedder=tk.embedder
        )
        result = await retriever.search(
            "publish subscribe hub for events",
            seed_top_k=1,
            expansion=ExpansionConfig(
                max_hops=2, allowed_edge_kinds=["references"]
            ),
        )
        ids = {n.node_id for n in result.nodes}
        assert bus_id in ids
        # pol is only reachable via a 'mentions' edge — must be excluded.
        assert pol_id not in ids

    async def test_expansion_default_traverses_all(self, tmp_path):
        tk, bus_id, svc_id, pol_id = await _populated_toolkit(tmp_path)
        retriever = GraphExpandedRetriever(
            graph=tk.graph, nodes=tk.nodes, embedder=tk.embedder
        )
        result = await retriever.search(
            "publish subscribe hub for events", seed_top_k=1
        )
        ids = {n.node_id for n in result.nodes}
        assert pol_id in ids


class _StubToolManager:
    def __init__(self):
        self.tools: dict[str, object] = {}

    def get_tool(self, name):
        return self.tools.get(name)

    def register_tool(self, tool):
        self.tools[tool.name] = tool


class _MemoryBot(GraphMemoryMixin):
    enable_graph_memory = True
    name = "memo-agent"

    def __init__(self, path: Path):
        self.graph_memory_path = str(path)
        self.tool_manager = _StubToolManager()


class TestGraphMemoryMixin:
    async def test_configure_registers_tools(self, tmp_path):
        bot = _MemoryBot(tmp_path)
        await bot._configure_graph_memory()
        assert bot._graph_memory_toolkit is not None
        assert bot.tool_manager.get_tool("graph_history") is not None
        assert bot.tool_manager.get_tool("create_concept") is not None
        # Exposed on the knowledge-toolkit slot too.
        assert bot._graphindex_toolkit is bot._graph_memory_toolkit

    async def test_configure_is_idempotent(self, tmp_path):
        bot = _MemoryBot(tmp_path)
        await bot._configure_graph_memory()
        first = bot._graph_memory_toolkit
        await bot._configure_graph_memory()
        assert bot._graph_memory_toolkit is first

    async def test_disabled_mixin_is_inert(self, tmp_path):
        bot = _MemoryBot(tmp_path)
        bot.enable_graph_memory = False
        await bot._configure_graph_memory()
        assert bot._graph_memory_toolkit is None
        assert await bot._build_graph_context("anything") is None

    async def test_memory_survives_restart_and_injects_context(self, tmp_path):
        bot = _MemoryBot(tmp_path)
        await bot._configure_graph_memory()
        tk = bot._graph_memory_toolkit
        await tk.create_concept("EventBus", "publish subscribe hub")

        bot2 = _MemoryBot(tmp_path)
        await bot2._configure_graph_memory()
        context = await bot2._build_graph_context("Tell me about the EventBus")
        assert context is not None
        assert "EventBus" in context
        assert "asserted by agent:memo-agent" in context

    async def test_empty_graph_yields_no_context(self, tmp_path):
        bot = _MemoryBot(tmp_path)
        await bot._configure_graph_memory()
        assert await bot._build_graph_context("anything") is None

    async def test_run_id_stamping(self, tmp_path):
        bot = _MemoryBot(tmp_path)
        await bot._configure_graph_memory()
        bot.set_graph_memory_run("run-42")
        tk = bot._graph_memory_toolkit
        await tk.create_concept("Fact", "something")
        history = await tk.graph_history(run_id="run-42")
        assert len(history) == 1

    async def test_flush_clears_plane(self, tmp_path):
        bot = _MemoryBot(tmp_path)
        await bot._configure_graph_memory()
        await bot._graph_memory_toolkit.create_concept("Fact", "x")
        await bot.flush_graph_memory()
        assert bot._graph_memory_toolkit is None

        bot2 = _MemoryBot(tmp_path)
        await bot2._configure_graph_memory()
        assert bot2._graph_memory_toolkit.graph.num_nodes() == 0
