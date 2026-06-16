"""Unit tests for OKF bundle export/import (TASK-1567, TASK-1568).

Tests verify:
- Export creates directory hierarchy grouped by concept type
- Exported frontmatter omits node_id and resource fields
- pageindex:// URIs in body are rewritten to relative paths
- index.md is generated at bundle root
- Import reads frontmatter into PageIndex nodes
- Known ConceptType values mapped correctly
- Unknown type → ConceptType.OTHER
- Markdown links resolved to relates_to edges
- Round-trip export → import preserves concept_id, type, relates_to, body
"""

import pytest

from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.okf.bundle import (
    ExportReport,
    ImportReport,
    export_okf_bundle,
    import_okf_bundle,
)
from parrot.knowledge.pageindex.okf.ontology import ConceptType
from parrot.knowledge.pageindex.store import JSONTreeStore


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def content_store(tmp_path):
    """NodeContentStore backed by tmp_path."""
    return NodeContentStore(tmp_path / "content")


@pytest.fixture
def tree_store(tmp_path):
    """JSONTreeStore backed by tmp_path."""
    return JSONTreeStore(tmp_path / "trees")


@pytest.fixture
def enriched_tree():
    """OKF-enriched tree with two typed nodes and a relates_to edge."""
    return {
        "tree_name": "test-kb",
        "structure": [
            {
                "node_id": "0001",
                "concept_id": "access-control-policy",
                "type": "Policy",
                "title": "Access Control Policy",
                "summary": "Manages access control.",
                "categories": ["access-control"],
                "timestamp": "2026-01-01T00:00:00Z",
                "relates_to": [
                    {"concept": "audit-logging", "rel": "references"}
                ],
                "nodes": [],
            },
            {
                "node_id": "0002",
                "concept_id": "audit-logging",
                "type": "Control",
                "title": "Audit Logging",
                "summary": "All access events are logged.",
                "categories": ["logging"],
                "timestamp": "2026-01-01T00:00:00Z",
                "relates_to": [],
                "nodes": [],
            },
        ],
    }


@pytest.fixture
def sample_okf_bundle(tmp_path):
    """A minimal OKF v0.1 bundle directory on disk."""
    policies = tmp_path / "policies"
    policies.mkdir()
    (policies / "access-control-policy.md").write_text(
        "---\n"
        "type: Policy\n"
        "title: Access Control Policy\n"
        "id: access-control-policy\n"
        "tags: [access-control]\n"
        "timestamp: '2026-01-01T00:00:00Z'\n"
        "summary: Manages access control.\n"
        "relates_to:\n"
        "- concept: audit-logging\n"
        "  rel: references\n"
        "---\n\n"
        "# Access Control Policy\n\n"
        "See [Audit Logging](../controls/audit-logging.md).\n",
        encoding="utf-8",
    )
    controls = tmp_path / "controls"
    controls.mkdir()
    (controls / "audit-logging.md").write_text(
        "---\n"
        "type: Control\n"
        "title: Audit Logging\n"
        "id: audit-logging\n"
        "tags: [logging]\n"
        "timestamp: '2026-01-01T00:00:00Z'\n"
        "summary: All access events are logged.\n"
        "relates_to: []\n"
        "---\n\n"
        "# Audit Logging\n\nAll access events are logged.\n",
        encoding="utf-8",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------


class TestExportDirectoryHierarchy:
    """Export creates type-grouped directory hierarchy."""

    def test_export_creates_type_directories(
        self, enriched_tree, content_store, tmp_path
    ):
        """Export creates policies/ and controls/ subdirectories."""
        export_dir = tmp_path / "bundle"
        export_okf_bundle(enriched_tree, "test-kb", content_store, export_dir)
        assert (export_dir / "policies").is_dir()
        assert (export_dir / "controls").is_dir()

    def test_export_files_in_correct_dirs(
        self, enriched_tree, content_store, tmp_path
    ):
        """Each file lands in the directory matching its concept type."""
        export_dir = tmp_path / "bundle"
        export_okf_bundle(enriched_tree, "test-kb", content_store, export_dir)
        assert (export_dir / "policies" / "access-control-policy.md").exists()
        assert (export_dir / "controls" / "audit-logging.md").exists()

    def test_export_report_files_written(
        self, enriched_tree, content_store, tmp_path
    ):
        """ExportReport.files_written equals number of concept files."""
        export_dir = tmp_path / "bundle"
        report = export_okf_bundle(enriched_tree, "test-kb", content_store, export_dir)
        assert isinstance(report, ExportReport)
        assert report.files_written == 2


class TestExportFrontmatter:
    """Exported frontmatter contains only OKF fields."""

    def test_export_strips_node_id(self, enriched_tree, content_store, tmp_path):
        """Exported frontmatter does NOT include node_id."""
        export_dir = tmp_path / "bundle"
        export_okf_bundle(enriched_tree, "test-kb", content_store, export_dir)
        content = (export_dir / "policies" / "access-control-policy.md").read_text()
        assert "node_id" not in content

    def test_export_strips_resource(self, enriched_tree, content_store, tmp_path):
        """Exported frontmatter does NOT include pageindex:// resource URI."""
        export_dir = tmp_path / "bundle"
        export_okf_bundle(enriched_tree, "test-kb", content_store, export_dir)
        content = (export_dir / "policies" / "access-control-policy.md").read_text()
        assert "pageindex://" not in content
        assert "resource:" not in content

    def test_export_includes_okf_fields(self, enriched_tree, content_store, tmp_path):
        """Exported frontmatter includes type, title, id, tags, timestamp."""
        export_dir = tmp_path / "bundle"
        export_okf_bundle(enriched_tree, "test-kb", content_store, export_dir)
        content = (export_dir / "policies" / "access-control-policy.md").read_text()
        assert "type: Policy" in content
        assert "title: Access Control Policy" in content
        assert "id: access-control-policy" in content

    def test_export_includes_relates_to(self, enriched_tree, content_store, tmp_path):
        """Exported frontmatter preserves relates_to edges."""
        export_dir = tmp_path / "bundle"
        export_okf_bundle(enriched_tree, "test-kb", content_store, export_dir)
        content = (export_dir / "policies" / "access-control-policy.md").read_text()
        assert "audit-logging" in content


class TestExportURIRewriting:
    """pageindex:// URIs in body are rewritten to relative paths."""

    def test_export_rewrites_uris_in_body(self, enriched_tree, content_store, tmp_path):
        """Body text with pageindex:// URIs gets relative links."""
        # Pre-seed a sidecar body with a pageindex:// URI
        content_store.save(
            "test-kb",
            "access-control-policy",
            "# Policy\n\nSee pageindex://test-kb/audit-logging for details.\n",
        )
        export_dir = tmp_path / "bundle"
        report = export_okf_bundle(enriched_tree, "test-kb", content_store, export_dir)
        content = (export_dir / "policies" / "access-control-policy.md").read_text()
        assert "pageindex://" not in content
        assert report.uris_rewritten > 0

    def test_export_preserves_external_urls(
        self, enriched_tree, content_store, tmp_path
    ):
        """External https:// URLs in body are left unchanged."""
        content_store.save(
            "test-kb",
            "access-control-policy",
            "# Policy\n\nSee https://example.com for reference.\n",
        )
        export_dir = tmp_path / "bundle"
        export_okf_bundle(enriched_tree, "test-kb", content_store, export_dir)
        content = (export_dir / "policies" / "access-control-policy.md").read_text()
        assert "https://example.com" in content


class TestExportIndexMd:
    """Root index.md is generated."""

    def test_export_generates_index(self, enriched_tree, content_store, tmp_path):
        """index.md is created at the bundle root."""
        export_dir = tmp_path / "bundle"
        report = export_okf_bundle(enriched_tree, "test-kb", content_store, export_dir)
        assert (export_dir / "index.md").exists()
        assert report.index_generated is True

    def test_export_index_contains_tree_name(
        self, enriched_tree, content_store, tmp_path
    ):
        """index.md title contains tree_name."""
        export_dir = tmp_path / "bundle"
        export_okf_bundle(enriched_tree, "test-kb", content_store, export_dir)
        index = (export_dir / "index.md").read_text()
        assert "test-kb" in index


# ---------------------------------------------------------------------------
# Import tests
# ---------------------------------------------------------------------------


class TestImportFrontmatter:
    """Import reads YAML frontmatter into PageIndex nodes."""

    def test_import_reads_frontmatter(
        self, sample_okf_bundle, tree_store, content_store
    ):
        """Imported tree has nodes with correct concept_ids and types."""
        report = import_okf_bundle(
            sample_okf_bundle, "imported", tree_store, content_store
        )
        assert report.nodes_created == 2
        tree = tree_store.load("imported")
        nodes = tree.get("structure", [])
        cids = {n["concept_id"] for n in nodes}
        assert "access-control-policy" in cids
        assert "audit-logging" in cids

    def test_import_preserves_type(
        self, sample_okf_bundle, tree_store, content_store
    ):
        """Imported nodes have the correct ConceptType from frontmatter."""
        import_okf_bundle(sample_okf_bundle, "imported", tree_store, content_store)
        tree = tree_store.load("imported")
        by_cid = {n["concept_id"]: n for n in tree.get("structure", [])}
        assert by_cid["access-control-policy"]["type"] == "Policy"
        assert by_cid["audit-logging"]["type"] == "Control"


class TestImportTypeMapping:
    """Type mapping: known → ConceptType enum, unknown → OTHER."""

    def test_import_maps_known_types(
        self, sample_okf_bundle, tree_store, content_store
    ):
        """Known types are mapped to ConceptType values without OTHER."""
        report = import_okf_bundle(
            sample_okf_bundle, "imported", tree_store, content_store
        )
        assert "Policy" in report.types_mapped
        assert "Control" in report.types_mapped
        assert report.types_mapped["Policy"] == ConceptType.POLICY.value
        assert report.types_mapped["Control"] == ConceptType.CONTROL.value

    def test_import_maps_unknown_types_to_other(
        self, tmp_path, tree_store, content_store
    ):
        """Unknown type string → ConceptType.OTHER."""
        exotic_dir = tmp_path / "exotic"
        exotic_dir.mkdir()
        (exotic_dir / "thing.md").write_text(
            "---\n"
            "type: CustomExoticType\n"
            "title: Exotic Thing\n"
            "id: exotic-thing\n"
            "tags: []\n"
            "timestamp: '2026-01-01T00:00:00Z'\n"
            "summary: ''\n"
            "relates_to: []\n"
            "---\n\n"
            "# Exotic Thing\n",
            encoding="utf-8",
        )
        report = import_okf_bundle(exotic_dir, "imported", tree_store, content_store)
        tree = tree_store.load("imported")
        node = tree["structure"][0]
        assert node["type"] == ConceptType.OTHER.value
        assert "CustomExoticType" in report.unknown_types

    def test_import_other_type_round_trips(
        self, tmp_path, tree_store, content_store
    ):
        """ConceptType.OTHER value round-trips through import."""
        other_dir = tmp_path / "others"
        other_dir.mkdir()
        (other_dir / "thing.md").write_text(
            "---\n"
            "type: Other\n"
            "title: Generic Thing\n"
            "id: generic-thing\n"
            "tags: []\n"
            "timestamp: '2026-01-01T00:00:00Z'\n"
            "summary: ''\n"
            "relates_to: []\n"
            "---\n\n"
            "# Generic Thing\n",
            encoding="utf-8",
        )
        report = import_okf_bundle(other_dir, "imported", tree_store, content_store)
        tree = tree_store.load("imported")
        assert tree["structure"][0]["type"] == "Other"
        # "Other" is a known ConceptType now — not counted as unknown
        assert "Other" not in report.unknown_types


class TestImportEdges:
    """Markdown links are resolved to relates_to edges."""

    def test_import_resolves_markdown_links(
        self, sample_okf_bundle, tree_store, content_store
    ):
        """Link [Audit Logging](../controls/audit-logging.md) creates an edge."""
        import_okf_bundle(
            sample_okf_bundle, "imported", tree_store, content_store
        )
        tree = tree_store.load("imported")
        by_cid = {n["concept_id"]: n for n in tree.get("structure", [])}
        relates = by_cid.get("access-control-policy", {}).get("relates_to", [])
        targets = {r["concept"] for r in relates}
        assert "audit-logging" in targets

    def test_import_edges_created_count(
        self, sample_okf_bundle, tree_store, content_store
    ):
        """ImportReport.edges_created reflects all resolved edges."""
        report = import_okf_bundle(
            sample_okf_bundle, "imported", tree_store, content_store
        )
        assert report.edges_created >= 1


class TestImportIndexSkip:
    """index.md files are skipped during import."""

    def test_import_skips_index_md(self, tmp_path, tree_store, content_store):
        """index.md at bundle root is not imported as a node."""
        (tmp_path / "index.md").write_text(
            "# Test KB\n\nThis is the index.\n", encoding="utf-8"
        )
        controls = tmp_path / "controls"
        controls.mkdir()
        (controls / "ctrl.md").write_text(
            "---\ntype: Control\ntitle: Ctrl\nid: ctrl\ntags: []\n"
            "timestamp: '2026-01-01T00:00:00Z'\nsummary: ''\nrelates_to: []\n---\n\n# Ctrl\n",
            encoding="utf-8",
        )
        report = import_okf_bundle(tmp_path, "imported", tree_store, content_store)
        assert report.nodes_created == 1  # only ctrl, not index.md


# ---------------------------------------------------------------------------
# Round-trip test
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Export → Import preserves concept_id, type, relates_to, body."""

    def test_round_trip_fidelity(self, enriched_tree, content_store, tmp_path):
        """Full export → import cycle preserves key fields."""
        # Pre-seed body content for both nodes
        content_store.save("test-kb", "access-control-policy", "# Policy body\n")
        content_store.save("test-kb", "audit-logging", "# Control body\n")

        # Export
        export_dir = tmp_path / "bundle"
        export_report = export_okf_bundle(
            enriched_tree, "test-kb", content_store, export_dir
        )
        assert export_report.files_written == 2

        # Import into a fresh store
        reimport_content = NodeContentStore(tmp_path / "reimport_content")
        reimport_store = JSONTreeStore(tmp_path / "reimport_trees")

        import_report = import_okf_bundle(
            export_dir, "reimported", reimport_store, reimport_content
        )
        assert import_report.nodes_created == 2

        # Verify concept_ids
        tree = reimport_store.load("reimported")
        by_cid = {n["concept_id"]: n for n in tree.get("structure", [])}
        assert "access-control-policy" in by_cid
        assert "audit-logging" in by_cid

        # Verify types
        assert by_cid["access-control-policy"]["type"] == "Policy"
        assert by_cid["audit-logging"]["type"] == "Control"

        # Verify relates_to edge preserved
        relates = by_cid["access-control-policy"].get("relates_to", [])
        targets = {r["concept"] for r in relates}
        assert "audit-logging" in targets

        # Verify body content preserved
        body = reimport_content.load("reimported", "access-control-policy")
        assert body is not None
        assert "Policy body" in body
