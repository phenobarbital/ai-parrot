"""Integration tests: vault → PageIndex + GraphIndex, entity extraction."""
from typing import Any, Optional

import pytest

from parrot.interfaces.obsidian import LocalVaultBackend
from parrot.loaders.obsidian import ObsidianGraphBridge, ObsidianVaultLoader

pytestmark = pytest.mark.asyncio


class TestVaultToWikiPipeline:
    async def test_vault_to_wiki_pipeline(
        self, fixture_vault, stub_pageindex, source_manager
    ):
        """Phase 1 + Phase 1b: fixture vault → PageIndex + graph structures."""
        vault = LocalVaultBackend(fixture_vault, vault_name="pipeline")
        loader = ObsidianVaultLoader(vault)

        report = await loader.ingest(stub_pageindex, "wiki", source_manager)
        assert report.nodes_created == 8
        assert not [
            error for error in report.errors if "Circular" not in error
        ]

        notes, canvases = await loader.discover()
        bridge = ObsidianGraphBridge(
            notes, canvases, await vault.build_index(), vault_name="pipeline"
        )
        nodes, edges = bridge.build_graph()
        kinds = {node.kind.value for node in nodes}
        assert {"document", "concept"} <= kinds
        assert len(edges) > len(notes)  # links + tags + containment

    async def test_incremental_pipeline(
        self, fixture_vault, stub_pageindex, source_manager
    ):
        loader = ObsidianVaultLoader(fixture_vault)
        await loader.ingest(stub_pageindex, "wiki", source_manager)
        (fixture_vault / "late-arrival.md").write_text(
            "Points to [[orphan]].", encoding="utf-8"
        )
        loader.vault.invalidate_index()
        report = await loader.incremental_update(
            stub_pageindex, "wiki", source_manager
        )
        assert report.files_added == 1
        assert "late-arrival" in stub_pageindex.node_titles("wiki")


class _StubAdapter:
    """LLM adapter stub returning canned entity JSON."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def ask_json(self, prompt: str, **kwargs: Any) -> Any:
        self.calls.append(prompt)
        return [
            {"name": "AI-Parrot", "kind": "entity", "summary": "The framework."},
            {"name": "Machine Learning", "kind": "concept", "summary": "A field."},
        ]


class _StubContentStore:
    def __init__(self, bodies: dict[str, str]) -> None:
        self._bodies = bodies

    def loader_for(self, tree_name: str):
        return lambda key: self._bodies.get(key, "")


class _StubGraph:
    def __init__(self) -> None:
        self.concepts: list[str] = []

    async def create_concept(
        self,
        title: str,
        summary: str,
        source_uri: Optional[str] = None,
        categories: Optional[list] = None,
    ) -> dict:
        self.concepts.append(title)
        return {"node_id": f"g-{len(self.concepts)}", "status": "created"}


class TestExtractEntities:
    async def test_extract_entities(self, stub_pageindex, source_manager):
        from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
        from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator
        from parrot.knowledge.wiki.models import WikiConfig

        await stub_pageindex.create_tree("wiki")
        result = await stub_pageindex.add_node(
            "wiki", title="Page", body="A page about AI-Parrot and ML."
        )
        page_id = result["node_id"]
        stub_pageindex._adapter = _StubAdapter()
        stub_pageindex._light_adapter = None
        stub_pageindex._content_store = _StubContentStore(
            {page_id: "A long enough body describing AI-Parrot and ML."}
        )
        graph = _StubGraph()

        orchestrator = WikiIngestOrchestrator(
            stub_pageindex,
            graph,
            source_manager,
            WikiBookkeeper(),
        )
        config = WikiConfig(wiki_name="wiki", storage_dir="/tmp/unused")
        report = await orchestrator.extract_entities(
            "wiki", config, granularity="standard"
        )
        assert report.status == "ok"
        assert report.pages_created == 2
        assert report.graph_nodes_created == 2
        assert graph.concepts == ["AI-Parrot", "Machine Learning"]
        titles = stub_pageindex.node_titles("wiki")
        assert "AI-Parrot" in titles
        # Sub-nodes are marked so re-extraction skips them.
        entity = stub_pageindex.node_by_title("wiki", "AI-Parrot")
        assert entity["metadata"]["extracted_from"] == page_id
        assert entity["metadata"]["granularity"] == "standard"

    async def test_extract_entities_missing_tree(
        self, stub_pageindex, source_manager
    ):
        from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
        from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator
        from parrot.knowledge.wiki.models import WikiConfig

        stub_pageindex._adapter = _StubAdapter()
        orchestrator = WikiIngestOrchestrator(
            stub_pageindex, None, source_manager, WikiBookkeeper()
        )
        config = WikiConfig(wiki_name="wiki", storage_dir="/tmp/unused")
        report = await orchestrator.extract_entities("missing", config)
        assert report.status == "error"
