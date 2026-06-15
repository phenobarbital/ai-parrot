"""Unit tests for OKF projection module (TASK-1556).

Tests verify:
- flatten_concept_id_for_filename handles slashes correctly.
- project_sidecar combines frontmatter and body.
- project_sidecars regenerates all sidecars byte-deterministically.
- generate_index_md produces a deterministic root-level index.
- Sidecar filenames are <flattened_concept_id>.md not <node_id>.md.
- Old node_id.md sidecars are cleaned up when renamed.
"""

import pytest
from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.okf.projection import (
    flatten_concept_id_for_filename,
    generate_index_md,
    project_sidecar,
    project_sidecars,
)


class TestFlattenConceptId:
    """Tests for flatten_concept_id_for_filename."""

    def test_simple_id_unchanged(self):
        """ID without slashes is unchanged."""
        assert flatten_concept_id_for_filename("aws-ir") == "aws-ir"

    def test_slash_replaced_with_double_dash(self):
        """Single slash becomes double-dash."""
        assert flatten_concept_id_for_filename("playbooks/aws-ir") == "playbooks--aws-ir"

    def test_multiple_slashes(self):
        """Multiple slashes all become double-dashes."""
        result = flatten_concept_id_for_filename("a/b/c")
        assert "/" not in result
        assert result == "a--b--c"

    def test_no_slashes_preserved(self):
        """Result contains no forward slashes."""
        result = flatten_concept_id_for_filename("section/sub/topic")
        assert "/" not in result

    def test_long_id_truncated(self):
        """Very long flat IDs are truncated with hash suffix."""
        long_id = "a" * 40 + "/" + "b" * 40
        result = flatten_concept_id_for_filename(long_id)
        assert len(result) <= 64


class TestProjectSidecar:
    """Tests for project_sidecar."""

    def test_combines_frontmatter_and_body(self):
        """Output contains both frontmatter and body."""
        node = {
            "node_id": "0001",
            "concept_id": "test-concept",
            "type": "Section",
            "title": "Test",
            "summary": "A test node",
        }
        result = project_sidecar(node, "tree1", "Body content here.")
        assert result.startswith("---\n")
        assert "Body content here." in result

    def test_byte_deterministic(self):
        """Same inputs → identical output."""
        node = {
            "node_id": "0001",
            "concept_id": "test",
            "type": "Section",
            "title": "Test",
            "summary": "",
        }
        a = project_sidecar(node, "t", "body")
        b = project_sidecar(node, "t", "body")
        assert a == b

    def test_frontmatter_before_body(self):
        """Frontmatter precedes body in output."""
        node = {
            "node_id": "0001",
            "concept_id": "x",
            "type": "Section",
            "title": "X",
            "summary": "",
        }
        result = project_sidecar(node, "t", "## Body Heading")
        fm_end = result.find("\n---\n")
        body_start = result.find("## Body Heading")
        assert fm_end < body_start


class TestProjectSidecars:
    """Tests for project_sidecars with a real NodeContentStore."""

    @pytest.fixture
    def store(self, tmp_path):
        """NodeContentStore backed by tmp_path."""
        return NodeContentStore(tmp_path)

    @pytest.fixture
    def enriched_tree(self):
        """OKF-enriched tree with two nodes."""
        return {
            "structure": [
                {
                    "node_id": "0000",
                    "concept_id": "intro",
                    "type": "Section",
                    "title": "Introduction",
                    "summary": "Overview",
                    "nodes": [],
                },
                {
                    "node_id": "0001",
                    "concept_id": "controls/nist-ir-4",
                    "type": "Control",
                    "title": "NIST IR-4",
                    "summary": "Incident handling",
                    "nodes": [],
                },
            ]
        }

    def test_projects_all_nodes(self, store, enriched_tree):
        """All nodes in the tree receive a sidecar file."""
        report = project_sidecars(enriched_tree, "test_tree", store)
        assert report.nodes_projected == 2

    def test_sidecars_named_by_flat_concept_id(self, store, enriched_tree, tmp_path):
        """Sidecar files are named by flattened concept_id, not node_id."""
        project_sidecars(enriched_tree, "test_tree", store)
        # Check that flattened concept_id files exist
        assert store.has("test_tree", "intro")
        assert store.has("test_tree", "controls--nist-ir-4")
        # Old node_id files should NOT exist
        assert not store.has("test_tree", "0000")
        assert not store.has("test_tree", "0001")

    def test_byte_deterministic(self, store, enriched_tree):
        """Two runs on the same tree → identical sidecar content."""
        project_sidecars(enriched_tree, "test_tree", store)
        first_intro = store.load("test_tree", "intro")
        first_control = store.load("test_tree", "controls--nist-ir-4")

        project_sidecars(enriched_tree, "test_tree", store)
        second_intro = store.load("test_tree", "intro")
        second_control = store.load("test_tree", "controls--nist-ir-4")

        assert first_intro == second_intro
        assert first_control == second_control

    def test_body_preserved(self, store, enriched_tree):
        """Existing body content is preserved after projection."""
        # Pre-populate body by concept_id key
        store.save("test_tree", "intro", "Original body content.")
        project_sidecars(enriched_tree, "test_tree", store)
        content = store.load("test_tree", "intro")
        assert "Original body content." in content

    def test_old_node_id_sidecar_removed(self, store, enriched_tree):
        """Old node_id.md sidecar is removed when concept_id sidecar is written."""
        # Pre-populate an old node_id-keyed sidecar
        store.save("test_tree", "0000", "Body for node 0000")
        report = project_sidecars(enriched_tree, "test_tree", store)
        # Old file removed
        assert not store.has("test_tree", "0000")
        assert "0000" in report.old_files_removed

    def test_sidecar_has_frontmatter(self, store, enriched_tree):
        """Written sidecars start with YAML frontmatter."""
        project_sidecars(enriched_tree, "test_tree", store)
        content = store.load("test_tree", "intro")
        assert content.startswith("---\n")

    def test_report_files_written(self, store, enriched_tree):
        """Report lists all written filenames."""
        report = project_sidecars(enriched_tree, "test_tree", store)
        assert "intro" in report.files_written
        assert "controls--nist-ir-4" in report.files_written

    def test_nodes_without_concept_id_skipped(self, store):
        """Nodes without concept_id are skipped gracefully."""
        tree = {
            "structure": [
                {"node_id": "0000", "title": "No CID", "nodes": []},
            ]
        }
        report = project_sidecars(tree, "t", store)
        assert report.nodes_projected == 0


class TestGenerateIndexMd:
    """Tests for generate_index_md."""

    def test_lists_top_level_concepts(self):
        """Top-level nodes appear in the index."""
        tree = {
            "structure": [
                {"concept_id": "alpha", "title": "Alpha", "summary": "First", "nodes": []},
                {"concept_id": "beta", "title": "Beta", "summary": "Second", "nodes": []},
            ]
        }
        index = generate_index_md(tree, "test_tree")
        assert "Alpha" in index
        assert "Beta" in index

    def test_deterministic(self):
        """Same tree → identical index.md string."""
        tree = {
            "structure": [
                {"concept_id": "a", "title": "A", "summary": "", "nodes": []},
            ]
        }
        assert generate_index_md(tree, "t") == generate_index_md(tree, "t")

    def test_links_use_flat_concept_id(self):
        """Links in index.md use flattened concept_id filenames."""
        tree = {
            "structure": [
                {"concept_id": "controls/nist-ir-4", "title": "NIST IR-4", "summary": "", "nodes": []},
            ]
        }
        index = generate_index_md(tree, "t")
        assert "controls--nist-ir-4.md" in index

    def test_tree_name_as_heading(self):
        """Tree name appears as top-level heading."""
        tree = {"structure": []}
        index = generate_index_md(tree, "my_corpus")
        assert "# my_corpus" in index

    def test_no_yaml_frontmatter(self):
        """index.md does not contain YAML frontmatter delimiters."""
        tree = {
            "structure": [
                {"concept_id": "a", "title": "A", "summary": "S", "nodes": []},
            ]
        }
        index = generate_index_md(tree, "t")
        # No YAML frontmatter block
        assert not index.startswith("---\n")

    def test_includes_summary(self):
        """Node summaries appear in the index."""
        tree = {
            "structure": [
                {"concept_id": "a", "title": "A", "summary": "Test summary text", "nodes": []},
            ]
        }
        index = generate_index_md(tree, "t")
        assert "Test summary text" in index
