"""End-to-end integration tests for OKF knowledge layer (FEAT-238 / TASK-1559).

Covers:
- tree_ops concept_id preservation across reindex and splice.
- content_store flattened concept_id dual-key loading.
- toolkit T3 classification step with Section fallback (no LLM required).
- toolkit OKF tool registration via set_okf_toolkit().
- toolkit delete_node cleanup of concept_id-keyed sidecars.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.okf.graph import KnowledgeGraph
from parrot.knowledge.pageindex.okf.ontology import ConceptType
from parrot.knowledge.pageindex.okf.tools import OKFToolkit
from parrot.knowledge.pageindex.tree_ops import (
    delete_node,
    reindex_node_ids,
    splice_subtree,
)
from parrot.knowledge.pageindex.utils import structure_to_list


# ---- helpers ----------------------------------------------------------------

def _enriched_tree() -> dict[str, Any]:
    """OKF-enriched tree with three typed nodes."""
    return {
        "doc_name": "guide.pdf",
        "structure": [
            {
                "node_id": "0000",
                "concept_id": "safeguards/hipaa-164",
                "type": "Safeguard",
                "title": "HIPAA §164",
                "summary": "Security safeguard",
                "relates_to": [{"concept": "controls/nist-ir-4", "rel": "maps_to"}],
                "nodes": [],
            },
            {
                "node_id": "0001",
                "concept_id": "controls/nist-ir-4",
                "type": "Control",
                "title": "NIST IR-4",
                "summary": "Incident handling",
                "relates_to": [{"concept": "evidence/ir-plan", "rel": "satisfied_by"}],
                "nodes": [],
            },
            {
                "node_id": "0002",
                "concept_id": "evidence/ir-plan",
                "type": "Evidence",
                "title": "IR Plan",
                "summary": "Incident response plan",
                "relates_to": [],
                "nodes": [],
            },
        ],
    }


# ---- TestTreeOpsConceptIdPreservation ---------------------------------------

class TestTreeOpsConceptIdPreservation:
    """Verify concept_id is preserved through tree mutations."""

    def test_reindex_preserves_concept_id(self):
        """reindex_node_ids must not overwrite concept_id."""
        tree = {
            "structure": [
                {"node_id": "0000", "concept_id": "intro", "title": "Intro", "nodes": []},
                {"node_id": "0001", "concept_id": "controls", "title": "Controls", "nodes": []},
            ]
        }
        reindex_node_ids(tree)
        assert tree["structure"][0]["concept_id"] == "intro"
        assert tree["structure"][1]["concept_id"] == "controls"

    def test_splice_preserves_existing_concept_id(self):
        """Splice a new subtree; existing nodes keep their concept_id."""
        tree = {
            "structure": [
                {"title": "A", "concept_id": "section/a", "nodes": []},
            ]
        }
        reindex_node_ids(tree)
        splice_subtree(tree, {"title": "B"})
        a_node = tree["structure"][0]
        assert a_node["concept_id"] == "section/a"

    def test_splice_assigns_concept_id_to_new_nodes(self):
        """New nodes without concept_id receive one after splice."""
        tree = {"structure": [{"title": "A", "concept_id": "section/a", "nodes": []}]}
        reindex_node_ids(tree)
        new_node = {"title": "B", "summary": "A new node"}
        splice_subtree(tree, new_node)
        # new_node should have been assigned a concept_id.
        b_node = next(n for n in structure_to_list(tree["structure"]) if n["title"] == "B")
        assert b_node.get("concept_id") is not None

    def test_delete_preserves_sibling_concept_id(self):
        """Delete a node; remaining nodes keep their concept_id."""
        tree = {
            "structure": [
                {"title": "A", "concept_id": "section/a", "nodes": []},
                {"title": "B", "concept_id": "section/b", "nodes": []},
            ]
        }
        reindex_node_ids(tree)
        b_id = tree["structure"][1]["node_id"]
        delete_node(tree, b_id)
        a_node = tree["structure"][0]
        assert a_node["concept_id"] == "section/a"

    def test_multiple_reindexes_idempotent_concept_ids(self):
        """Running reindex multiple times must produce identical concept_ids."""
        tree = {
            "structure": [
                {"title": "X", "concept_id": "x", "nodes": []},
                {"title": "Y", "concept_id": "y", "nodes": []},
            ]
        }
        reindex_node_ids(tree)
        ids_first = [n.get("concept_id") for n in structure_to_list(tree["structure"])]
        reindex_node_ids(tree)
        ids_second = [n.get("concept_id") for n in structure_to_list(tree["structure"])]
        assert ids_first == ids_second


# ---- TestContentStoreDualKey ------------------------------------------------

class TestContentStoreDualKey:
    """Verify content_store handles flattened concept_id keys."""

    def test_load_by_flattened_concept_id(self, tmp_path: Path):
        """Direct save/load by flattened concept_id key."""
        store = NodeContentStore(tmp_path)
        store.save("tree", "playbooks--aws-ir", "content")
        assert store.load("tree", "playbooks--aws-ir") == "content"

    def test_loader_for_concept_id(self, tmp_path: Path):
        """loader_for closure handles flattened concept_id keys."""
        store = NodeContentStore(tmp_path)
        store.save("tree", "playbooks--aws-ir", "content")
        loader = store.loader_for("tree")
        assert loader("playbooks--aws-ir") == "content"

    def test_loader_for_legacy_node_id(self, tmp_path: Path):
        """loader_for closure still handles plain node_id keys (backward compat)."""
        store = NodeContentStore(tmp_path)
        store.save("tree", "0042", "legacy content")
        loader = store.loader_for("tree")
        assert loader("0042") == "legacy content"

    def test_loader_for_missing_key_returns_none(self, tmp_path: Path):
        """loader_for returns None for absent keys."""
        store = NodeContentStore(tmp_path)
        loader = store.loader_for("tree")
        assert loader("nonexistent--key") is None

    def test_delete_node_by_flattened_concept_id(self, tmp_path: Path):
        """delete_node removes flattened concept_id keyed sidecar."""
        store = NodeContentStore(tmp_path)
        store.save("tree", "controls--nist", "body")
        assert store.delete_node("tree", "controls--nist") is True
        assert store.load("tree", "controls--nist") is None


# ---- TestToolkitT3Step ------------------------------------------------------

class TestToolkitT3Step:
    """Verify toolkit T3 classification step behavior."""

    @pytest.mark.asyncio
    async def test_insert_markdown_t3_classifies_new_nodes_in_enriched_tree(
        self, tmp_path: Path
    ):
        """T3 classifies untyped new nodes in already-OKF-enriched trees.

        T3 only runs when the tree already has at least one typed node
        (i.e., was previously OKF-migrated).  Fresh trees are left untouched.
        """
        from parrot.knowledge.pageindex.store import JSONTreeStore
        from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

        store = JSONTreeStore(tmp_path)
        # Seed the tree with a pre-existing typed node so T3 gate passes.
        tree_data = {
            "doc_name": "test.md",
            "structure": [
                {
                    "node_id": "0000",
                    "concept_id": "existing/section",
                    "type": "Section",
                    "title": "Existing Section",
                    "summary": "pre-existing",
                    "nodes": [],
                }
            ],
        }
        store.save("my_tree", tree_data)

        # Create a minimal mock adapter.
        mock_adapter = MagicMock()
        mock_adapter.model = "mock-model"
        mock_adapter.client = MagicMock()

        # md_to_tree result — a new untyped node.
        mock_subtree = {
            "doc_name": "ingested.md",
            "structure": [
                {"title": "New Section", "summary": "A new section", "nodes": []}
            ],
        }

        with patch(
            "parrot.knowledge.pageindex.toolkit.md_to_tree",
            new=AsyncMock(return_value=mock_subtree),
        ):
            toolkit = PageIndexToolkit(adapter=mock_adapter, storage_dir=tmp_path)
            await toolkit.insert_markdown("my_tree", "# New Section\n\nBody text.")

        # The new node must have received a type (Section fallback via mock).
        loaded = store.load("my_tree")
        nodes = structure_to_list(loaded.get("structure", []))
        new_nodes = [n for n in nodes if n.get("title") == "New Section"]
        assert new_nodes, "New node not found in tree"
        for node in new_nodes:
            assert node.get("type") == ConceptType.SECTION.value, (
                f"Node {node.get('node_id')!r} missing Section type; "
                f"got {node.get('type')!r}"
            )


# ---- TestToolkitOKFToolRegistration -----------------------------------------

class TestToolkitOKFToolRegistration:
    """Verify OKF tools are included in PageIndexToolkit.get_tools()."""

    def test_set_okf_toolkit_and_get_tools(self, tmp_path: Path):
        """Tools from a registered OKFToolkit appear in get_tools()."""
        from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

        mock_adapter = MagicMock()
        mock_adapter.model = "mock-model"
        mock_adapter.client = MagicMock()

        toolkit = PageIndexToolkit(adapter=mock_adapter, storage_dir=tmp_path)

        tree = _enriched_tree()
        graph = KnowledgeGraph(tree)
        store = NodeContentStore(tmp_path)
        okf_tk = OKFToolkit(tree, graph, store, "test_tree")

        toolkit.set_okf_toolkit("test_tree", okf_tk)

        all_tools = toolkit.get_tools()
        # OKF toolkit returns 6 tools; combined list must contain them.
        assert len(okf_tk.get_tools()) == 6
        # Combined list must be larger than base tools alone.
        base_count = len(PageIndexToolkit(adapter=mock_adapter, storage_dir=tmp_path).get_tools())
        assert len(all_tools) >= base_count + 6

    def test_get_tools_without_okf_toolkit_unchanged(self, tmp_path: Path):
        """get_tools without OKF toolkit returns only base tools (no crash)."""
        from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

        mock_adapter = MagicMock()
        mock_adapter.model = "mock-model"
        mock_adapter.client = MagicMock()

        toolkit = PageIndexToolkit(adapter=mock_adapter, storage_dir=tmp_path)
        tools = toolkit.get_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0


# ---- TestToolkitDeleteNodeConceptIdCleanup ----------------------------------

class TestToolkitDeleteNodeConceptIdCleanup:
    """Verify delete_node cleans up concept_id-keyed sidecars."""

    @pytest.mark.asyncio
    async def test_delete_node_removes_concept_id_sidecar(self, tmp_path: Path):
        """delete_node also removes concept_id-keyed sidecar (OKF migration)."""
        from parrot.knowledge.pageindex.store import JSONTreeStore
        from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

        store_dir = tmp_path
        tree_store = JSONTreeStore(store_dir)

        tree = _enriched_tree()
        tree_store.save("guide", tree)

        mock_adapter = MagicMock()
        mock_adapter.model = "mock-model"
        mock_adapter.client = MagicMock()

        toolkit = PageIndexToolkit(adapter=mock_adapter, storage_dir=store_dir)
        # Write concept_id-keyed sidecar via the SAME content store as the toolkit.
        toolkit._content_store.save("guide", "safeguards--hipaa-164", "safeguard body")

        # Confirm the sidecar exists before deletion.
        assert toolkit._content_store.has("guide", "safeguards--hipaa-164")

        # Delete the safeguard node.
        result = await toolkit.delete_node("guide", "0000")
        assert result["removed"] is True

        # The concept_id-keyed sidecar must be gone.
        # Use the toolkit's own content_store to avoid cross-instance cache issues.
        assert toolkit._content_store.load("guide", "safeguards--hipaa-164") is None
