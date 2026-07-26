"""Tests for LLM-typed graph extraction (stub client — no live LLM).

Covers the ExtractedGraph contract, additive entity deduplication
(exact/alias/fuzzy), relation resolution, durable publish + revert, and
the toolkit's ``extract_knowledge`` in-memory mirror.
"""

import pytest

from parrot.knowledge.graphindex.extractors.llm import (
    ExtractedEntity,
    ExtractedGraph,
    ExtractedRelation,
    LLMGraphExtractor,
)
from parrot.knowledge.graphindex.factory import (
    build_graph_memory_toolkit,
    make_stub_tenant_context,
)
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
from parrot.knowledge.graphindex.publish import GraphPublisher
from parrot.knowledge.graphindex.schema import Provenance


class _StubInvokeResult:
    def __init__(self, output):
        self.output = output


class _StubClient:
    """AbstractClient double: invoke() returns a canned ExtractedGraph."""

    def __init__(self, graph: ExtractedGraph):
        self._graph = graph
        self.calls: list[dict] = []

    async def invoke(self, prompt, *, output_type=None, system_prompt=None, **kw):
        self.calls.append({"prompt": prompt, "output_type": output_type})
        return _StubInvokeResult(self._graph)


def _sample_graph() -> ExtractedGraph:
    return ExtractedGraph(
        entities=[
            ExtractedEntity(
                name="EventBus",
                kind="concept",
                summary="publish subscribe hub",
                aliases=["Message Bus"],
            ),
            ExtractedEntity(
                name="OrderService",
                kind="concept",
                summary="emits order events",
            ),
        ],
        relations=[
            ExtractedRelation(
                source="OrderService", target="EventBus", kind="references"
            ),
            ExtractedRelation(
                source="OrderService", target="Ghost", kind="references"
            ),
        ],
    )


@pytest.fixture
def publisher(tmp_path):
    ctx = make_stub_tenant_context("t1")
    return GraphPublisher(SQLitePersistence(tmp_path), ctx)


class TestExtract:
    async def test_extract_returns_graph(self, publisher):
        extractor = LLMGraphExtractor(_StubClient(_sample_graph()), publisher)
        graph = await extractor.extract("some text")
        assert len(graph.entities) == 2
        assert len(graph.relations) == 2

    async def test_extract_uses_structured_output(self, publisher):
        client = _StubClient(_sample_graph())
        extractor = LLMGraphExtractor(client, publisher)
        await extractor.extract("some text")
        assert client.calls[0]["output_type"] is ExtractedGraph


class TestExtractAndPublish:
    async def test_publishes_nodes_and_resolved_relations(self, publisher):
        extractor = LLMGraphExtractor(_StubClient(_sample_graph()), publisher)
        result = await extractor.extract_and_publish(
            "text", source_uri="doc://spec.md", agent_id="ag", run_id="r1"
        )
        assert len(result.update.nodes) == 2
        # The Ghost relation is unresolvable and must be skipped.
        assert len(result.update.edges) == 1

        nodes, edges = await publisher.persistence.load_graph(publisher.ctx)
        by_title = {n.title: n for n in nodes}
        assert by_title["EventBus"].provenance is Provenance.ASSERTED
        assert by_title["EventBus"].assertion.run_id == "r1"
        assert by_title["EventBus"].domain_tags["aliases"] == ["Message Bus"]
        assert len(edges) == 1
        assert edges[0].source_id == by_title["OrderService"].node_id

    async def test_dedup_fuzzy_merges_additively(self, publisher):
        # Seed the graph with a canonical node.
        first = LLMGraphExtractor(
            _StubClient(
                ExtractedGraph(
                    entities=[
                        ExtractedEntity(name="EventBus", summary="the hub")
                    ]
                )
            ),
            publisher,
        )
        await first.extract_and_publish("t", source_uri="a", agent_id="ag")

        # Re-extract with a variant surface form → alias merge, no new node.
        second = LLMGraphExtractor(
            _StubClient(
                ExtractedGraph(
                    entities=[
                        ExtractedEntity(
                            name="Event Bus", summary="pubsub hub again"
                        )
                    ]
                )
            ),
            publisher,
        )
        result = await second.extract_and_publish(
            "t", source_uri="b", agent_id="ag"
        )
        nodes, _ = await publisher.persistence.load_graph(publisher.ctx)
        assert len(nodes) == 1
        node = nodes[0]
        assert node.title == "EventBus"
        assert "Event Bus" in node.domain_tags["aliases"]
        assert any(
            "Event Bus" in r for r in node.domain_tags["merge_rationale"]
        )
        assert result.update.nodes[0].node_id == node.node_id

    async def test_dedup_by_alias(self, publisher):
        await LLMGraphExtractor(
            _StubClient(_sample_graph()), publisher
        ).extract_and_publish("t", source_uri="a", agent_id="ag")
        # "Message Bus" is an alias of EventBus.
        result = await LLMGraphExtractor(
            _StubClient(
                ExtractedGraph(
                    entities=[
                        ExtractedEntity(name="Message Bus", summary="x")
                    ]
                )
            ),
            publisher,
        ).extract_and_publish("t", source_uri="b", agent_id="ag")
        nodes, _ = await publisher.persistence.load_graph(publisher.ctx)
        titles = [n.title for n in nodes]
        assert "Message Bus" not in titles  # merged, not created

    async def test_unknown_kinds_fall_back(self, publisher):
        graph = ExtractedGraph(
            entities=[
                ExtractedEntity(name="A", kind="hologram", summary="s"),
                ExtractedEntity(name="B", kind="concept", summary="s"),
            ],
            relations=[
                ExtractedRelation(source="A", target="B", kind="quantum-links")
            ],
        )
        result = await LLMGraphExtractor(
            _StubClient(graph), publisher
        ).extract_and_publish("t", source_uri="a", agent_id="ag")
        kinds = {n.kind.value for n in result.update.nodes}
        assert kinds == {"concept"}
        assert result.update.edges[0].kind.value == "references"

    async def test_extraction_commit_is_revertible(self, publisher):
        result = await LLMGraphExtractor(
            _StubClient(_sample_graph()), publisher
        ).extract_and_publish("t", source_uri="a", agent_id="ag")
        revert = await publisher.revert_commit(result.receipt.commit_id)
        assert revert["status"] == "reverted"
        nodes, edges = await publisher.persistence.load_graph(publisher.ctx)
        assert nodes == [] and edges == []

    async def test_requires_publisher(self):
        extractor = LLMGraphExtractor(_StubClient(_sample_graph()), None)
        with pytest.raises(RuntimeError):
            await extractor.extract_and_publish("t", source_uri="a")


class TestToolkitExtractKnowledge:
    async def test_extract_knowledge_mirrors_in_memory(self, tmp_path):
        tk = await build_graph_memory_toolkit(
            db_dir=tmp_path, agent_id="ag", run_id="r1"
        )
        tk.client = _StubClient(_sample_graph())
        result = await tk.extract_knowledge("text", source_uri="doc://x")
        assert result["persisted"] is True
        assert result["entities"] == 2
        assert result["edges_written"] == 1
        assert tk.graph.num_nodes() == 2
        assert tk.graph.num_edges() == 1
        found = await tk.find_node("publish subscribe hub")
        assert found.get("title") == "EventBus"

        # And it is durable across a reload.
        tk2 = await build_graph_memory_toolkit(db_dir=tmp_path, agent_id="ag")
        assert tk2.graph.num_nodes() == 2

    async def test_extract_knowledge_without_client(self, tmp_path):
        tk = await build_graph_memory_toolkit(db_dir=tmp_path, agent_id="ag")
        result = await tk.extract_knowledge("text")
        assert "error" in result
