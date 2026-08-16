"""Tests for ObsidianGraphBridge (FEAT-392 Module 5)."""
import pytest

from parrot.interfaces.obsidian import LocalVaultBackend
from parrot.knowledge.graphindex.schema import EdgeKind, NodeKind
from parrot.loaders.obsidian import ObsidianGraphBridge, ObsidianVaultLoader

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def graph(fixture_vault):
    vault = LocalVaultBackend(fixture_vault, vault_name="testvault")
    loader = ObsidianVaultLoader(vault)
    notes, canvases = await loader.discover()
    bridge = ObsidianGraphBridge(
        notes, canvases, await vault.build_index(), vault_name="testvault"
    )
    return bridge.build_graph()


class TestGraphNodes:
    async def test_document_nodes_for_notes(self, graph):
        nodes, _ = graph
        by_id = {node.node_id: node for node in nodes}
        note_node = by_id["obsidian::testvault::projects/ai-parrot"]
        assert note_node.kind == NodeKind.DOCUMENT
        assert note_node.domain_tags["obsidian_type"] == "note"
        assert note_node.source_uri == "obsidian://testvault/projects/ai-parrot.md"

    async def test_aliases_in_domain_tags(self, graph):
        nodes, _ = graph
        by_id = {node.node_id: node for node in nodes}
        note_node = by_id["obsidian::testvault::projects/ai-parrot"]
        assert note_node.domain_tags["aliases"] == ["parrot", "AI Parrot"]

    async def test_tag_nodes_are_concepts(self, graph):
        nodes, _ = graph
        tag_node = next(
            node for node in nodes
            if node.node_id == "obsidian::testvault::tag::daily"
        )
        assert tag_node.kind == NodeKind.CONCEPT
        assert tag_node.domain_tags["obsidian_type"] == "tag"

    async def test_folder_nodes(self, graph):
        nodes, _ = graph
        folder = next(
            node for node in nodes
            if node.node_id == "obsidian::testvault::folder::daily"
        )
        assert folder.kind == NodeKind.DOCUMENT
        assert folder.domain_tags["obsidian_type"] == "folder"

    async def test_canvas_nodes(self, graph):
        nodes, _ = graph
        canvas = next(
            node for node in nodes
            if node.node_id == "obsidian::testvault::canvas::canvas/overview"
        )
        assert canvas.kind == NodeKind.DOCUMENT
        assert canvas.domain_tags["obsidian_type"] == "canvas"

    async def test_broken_link_placeholder(self, graph):
        nodes, _ = graph
        placeholder = next(
            node for node in nodes
            if node.domain_tags.get("status") == "unresolved"
        )
        assert placeholder.title == "nonexistent-target"


class TestGraphEdges:
    async def test_wikilink_references(self, graph):
        _, edges = graph
        assert any(
            edge.source_id == "obsidian::testvault::daily/2026-07-30"
            and edge.target_id == "obsidian::testvault::projects/ai-parrot"
            and edge.kind == EdgeKind.REFERENCES
            for edge in edges
        )

    async def test_embed_edges_tagged(self, graph):
        _, edges = graph
        embed = next(
            edge for edge in edges
            if edge.source_id == "obsidian::testvault::projects/ai-parrot"
            and edge.domain_tags.get("embed")
        )
        assert embed.kind == EdgeKind.REFERENCES

    async def test_tag_link_edges(self, graph):
        _, edges = graph
        assert any(
            edge.target_id == "obsidian::testvault::tag::project"
            and edge.domain_tags.get("obsidian_type") == "tag_link"
            for edge in edges
        )

    async def test_folder_contains_edges(self, graph):
        _, edges = graph
        assert any(
            edge.source_id == "obsidian::testvault::folder::daily"
            and edge.target_id == "obsidian::testvault::daily/2026-07-30"
            and edge.kind == EdgeKind.CONTAINS
            for edge in edges
        )

    async def test_canvas_card_references(self, graph):
        _, edges = graph
        assert any(
            edge.source_id == "obsidian::testvault::canvas::canvas/overview"
            and edge.target_id == "obsidian::testvault::projects/ai-parrot"
            and edge.kind == EdgeKind.REFERENCES
            for edge in edges
        )

    async def test_edges_deduplicated(self, graph):
        _, edges = graph
        keys = [(e.source_id, e.target_id, e.kind.value) for e in edges]
        assert len(keys) == len(set(keys))
