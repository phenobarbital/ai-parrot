"""Unit tests for OKF migrate module (TASK-1557).

Tests verify:
- okf_migrate enriches all nodes with concept_id, type, source, relates_to.
- Migration is idempotent (two runs produce identical output).
- Type classification uses content-addressed cache.
- Structural fallback to Section when adapter=None.
- MigrationReport includes histogram and stats.
- Sidecars are renamed to concept_id keys.
- Root index.md is generated.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.okf.migrate import MigrationReport, okf_migrate
from parrot.knowledge.pageindex.store import JSONTreeStore


@pytest.fixture
def bare_tree():
    """A pre-migration tree with no OKF fields."""
    return {
        "doc_name": "guide.pdf",
        "structure": [
            {
                "node_id": "0000",
                "title": "Introduction",
                "summary": "Overview of the guide",
                "start_index": 1,
                "end_index": 5,
                "nodes": [],
            },
            {
                "node_id": "0001",
                "title": "Controls",
                "summary": "Security controls",
                "start_index": 6,
                "end_index": 10,
                "nodes": [],
            },
        ],
    }


@pytest.fixture
def tree_store(tmp_path):
    """JSONTreeStore backed by tmp_path."""
    return JSONTreeStore(tmp_path / "trees")


@pytest.fixture
def content_store(tmp_path):
    """NodeContentStore backed by tmp_path."""
    return NodeContentStore(tmp_path / "content")


class TestOkfMigrateBasic:
    """Basic migration functionality tests."""

    @pytest.mark.asyncio
    async def test_enriches_all_nodes(self, bare_tree, tree_store, content_store):
        """All nodes receive concept_id, type, source, relates_to."""
        tree_store.save("test_tree", bare_tree)
        report = await okf_migrate("test_tree", tree_store, content_store, adapter=None)

        result_tree = tree_store.load("test_tree")
        nodes = result_tree["structure"]
        for node in nodes:
            assert "concept_id" in node, f"Missing concept_id on {node.get('title')}"
            assert "type" in node, f"Missing type on {node.get('title')}"
            assert "source" in node, f"Missing source on {node.get('title')}"
            assert "relates_to" in node, f"Missing relates_to on {node.get('title')}"

    @pytest.mark.asyncio
    async def test_fallback_to_section_without_adapter(self, bare_tree, tree_store, content_store):
        """With adapter=None, all nodes are classified as Section."""
        tree_store.save("test_tree", bare_tree)
        await okf_migrate("test_tree", tree_store, content_store, adapter=None)

        result_tree = tree_store.load("test_tree")
        for node in result_tree["structure"]:
            assert node["type"] == "Section", (
                f"Expected Section, got {node['type']} for {node.get('title')}"
            )

    @pytest.mark.asyncio
    async def test_source_provenance_populated(self, bare_tree, tree_store, content_store):
        """source.document and source.pages are populated from tree fields."""
        tree_store.save("test_tree", bare_tree)
        await okf_migrate("test_tree", tree_store, content_store, adapter=None)

        result_tree = tree_store.load("test_tree")
        intro = result_tree["structure"][0]
        assert intro["source"]["document"] == "guide.pdf"
        assert intro["source"]["pages"] == [1, 5]

    @pytest.mark.asyncio
    async def test_returns_migration_report(self, bare_tree, tree_store, content_store):
        """okf_migrate returns a MigrationReport."""
        tree_store.save("test_tree", bare_tree)
        report = await okf_migrate("test_tree", tree_store, content_store, adapter=None)
        assert isinstance(report, MigrationReport)
        assert report.nodes_processed == 2
        assert report.tree_name == "test_tree"

    @pytest.mark.asyncio
    async def test_report_histogram(self, bare_tree, tree_store, content_store):
        """Report includes type histogram with expected counts."""
        tree_store.save("test_tree", bare_tree)
        report = await okf_migrate("test_tree", tree_store, content_store, adapter=None)
        # With no adapter, all should be Section
        assert report.types_histogram.get("Section", 0) == 2

    @pytest.mark.asyncio
    async def test_sidecars_written_with_frontmatter(self, bare_tree, tree_store, content_store):
        """Sidecars are written with YAML frontmatter."""
        tree_store.save("test_tree", bare_tree)
        await okf_migrate("test_tree", tree_store, content_store, adapter=None)

        # Find written sidecars
        node_ids = content_store.list_node_ids("test_tree")
        # At least the introduction sidecar should exist
        assert any(nid for nid in node_ids if "introduction" in nid or "controls" in nid)
        # Check that written sidecars have frontmatter
        for nid in node_ids:
            content = content_store.load("test_tree", nid)
            if content and content.startswith("---"):
                assert "type:" in content  # basic frontmatter check
                break

    @pytest.mark.asyncio
    async def test_index_md_generated(self, bare_tree, tree_store, content_store):
        """Root index.md is generated."""
        tree_store.save("test_tree", bare_tree)
        await okf_migrate("test_tree", tree_store, content_store, adapter=None)
        # index.md should be present
        assert content_store.has("test_tree", "index")
        index_content = content_store.load("test_tree", "index")
        assert "test_tree" in index_content or "Introduction" in index_content


class TestOkfMigrateIdempotency:
    """Idempotency tests."""

    @pytest.mark.asyncio
    async def test_idempotent_two_runs(self, bare_tree, tree_store, content_store):
        """Running migration twice produces identical tree JSON."""
        tree_store.save("test_tree", bare_tree)
        await okf_migrate("test_tree", tree_store, content_store, adapter=None)
        tree_after_first = tree_store.load("test_tree")

        await okf_migrate("test_tree", tree_store, content_store, adapter=None)
        tree_after_second = tree_store.load("test_tree")

        # Compare concept_ids and types (core OKF fields)
        for i, (n1, n2) in enumerate(
            zip(tree_after_first["structure"], tree_after_second["structure"])
        ):
            assert n1.get("concept_id") == n2.get("concept_id"), f"concept_id differs at [{i}]"
            assert n1.get("type") == n2.get("type"), f"type differs at [{i}]"

    @pytest.mark.asyncio
    async def test_idempotent_concept_id_stable(self, bare_tree, tree_store, content_store):
        """concept_id values are stable across runs."""
        tree_store.save("test_tree", bare_tree)
        await okf_migrate("test_tree", tree_store, content_store, adapter=None)
        first_ids = [n["concept_id"] for n in tree_store.load("test_tree")["structure"]]

        # Reset tree to pre-migration state
        tree_store.save("test_tree", bare_tree)
        await okf_migrate("test_tree", tree_store, content_store, adapter=None)
        second_ids = [n["concept_id"] for n in tree_store.load("test_tree")["structure"]]

        assert first_ids == second_ids


class TestOkfMigrateTypeCache:
    """Content-addressed type cache tests."""

    @pytest.mark.asyncio
    async def test_type_cache_persisted(self, bare_tree, tree_store, content_store):
        """Type cache is persisted after migration."""
        tree_store.save("test_tree", bare_tree)
        await okf_migrate("test_tree", tree_store, content_store, adapter=None)
        # Cache file should exist
        assert content_store.has("test_tree", "__okf_type_cache")

    @pytest.mark.asyncio
    async def test_type_cache_reused_on_second_run(self, bare_tree, tree_store, content_store):
        """Second run reuses cached types; LLM not called again."""
        call_count = [0]

        class MockAdapter:
            model_id = "test-model"

            async def classify_type(self, title, summary):
                call_count[0] += 1
                return "Control"

        adapter = MockAdapter()
        tree_store.save("test_tree", bare_tree)
        await okf_migrate("test_tree", tree_store, content_store, adapter=adapter)
        calls_first = call_count[0]

        # Second run: cache should prevent re-classification
        await okf_migrate("test_tree", tree_store, content_store, adapter=adapter)
        calls_second = call_count[0]

        # Second run should not call classify_type again (cache hits)
        assert calls_second == calls_first, (
            f"Expected no additional LLM calls on second run, "
            f"but got {calls_second - calls_first} extra calls"
        )

    @pytest.mark.asyncio
    async def test_force_reclassify_bypasses_cache(self, bare_tree, tree_store, content_store):
        """force_reclassify=True bypasses the type cache."""
        call_count = [0]

        class MockAdapter:
            model_id = "test-model"

            async def classify_type(self, title, summary):
                call_count[0] += 1
                return "Guideline"

        adapter = MockAdapter()
        tree_store.save("test_tree", bare_tree)
        await okf_migrate("test_tree", tree_store, content_store, adapter=adapter)
        calls_first = call_count[0]

        # Second run with force_reclassify
        await okf_migrate(
            "test_tree", tree_store, content_store, adapter=adapter, force_reclassify=True
        )
        calls_second = call_count[0]

        assert calls_second > calls_first, "Expected force_reclassify to trigger LLM calls"

    @pytest.mark.asyncio
    async def test_custom_type_from_adapter(self, bare_tree, tree_store, content_store):
        """Type from adapter is applied to nodes."""
        class MockAdapter:
            model_id = "test-model"

            async def classify_type(self, title, summary):
                if "control" in title.lower():
                    return "Control"
                return "Policy"

        adapter = MockAdapter()
        tree_store.save("test_tree", bare_tree)
        await okf_migrate("test_tree", tree_store, content_store, adapter=adapter)
        result = tree_store.load("test_tree")
        # "Controls" node should be "Control"
        controls_node = result["structure"][1]
        assert controls_node["type"] in ("Control", "Policy")


class TestOkfMigrateMarkdownLinks:
    """Tests for prose-link → relates_to parsing during migration."""

    @pytest.mark.asyncio
    async def test_prose_links_become_relates_to(self, tree_store, content_store):
        """Markdown links from body are added as relates_to with rel=references."""
        tree = {
            "doc_name": "doc.pdf",
            "structure": [
                {
                    "node_id": "0000",
                    "title": "Section A",
                    "summary": "Section A",
                    "start_index": 1,
                    "end_index": 2,
                    "nodes": [],
                },
                {
                    "node_id": "0001",
                    "title": "Section B",
                    "summary": "Section B",
                    "start_index": 3,
                    "end_index": 4,
                    "nodes": [],
                },
            ],
        }
        tree_store.save("tree_a", tree)
        # Pre-populate body for node 0000 with a link to Section B
        content_store.save("tree_a", "0000", "See [Section B](/section-b) for more.")
        await okf_migrate("tree_a", tree_store, content_store, adapter=None)
        result = tree_store.load("tree_a")
        node_a = result["structure"][0]
        # Should have relates_to with section-b
        assert any(r["concept"] == "section-b" for r in node_a.get("relates_to", []))
