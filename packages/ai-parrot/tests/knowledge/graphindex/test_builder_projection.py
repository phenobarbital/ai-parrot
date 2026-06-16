"""Integration tests for TASK-1564: Builder & Analytics Integration (FEAT-239).

Tests verify:
- generate_report() produces GRAPH_REPORT.md starting with OKF frontmatter.
- BuildResult has optional projection_report field.
- graphindex.__init__.py exports projection symbols.
- The frontmatter in GRAPH_REPORT.md is parseable and has title='Knowledge Graph Report'.
"""

from pathlib import Path

from parrot.knowledge.graphindex.analytics import generate_report, AnalyticsResult
from parrot.knowledge.graphindex.schema import BuildResult
from parrot.knowledge.graphindex.projection import GraphProjectionReport
from parrot.knowledge.okf.frontmatter import parse_frontmatter
from parrot.knowledge.okf.ontology import ConceptType


# ---------------------------------------------------------------------------
# Tests: generate_report() with frontmatter
# ---------------------------------------------------------------------------


class TestGenerateReportFrontmatter:
    """Tests that generate_report() prepends OKF frontmatter."""

    def test_report_starts_with_frontmatter(self, tmp_path: Path) -> None:
        """GRAPH_REPORT.md must start with --- YAML frontmatter."""
        analytics = AnalyticsResult()
        path = generate_report(analytics, tmp_path)
        content = path.read_text()
        assert content.startswith("---\n"), (
            "GRAPH_REPORT.md should start with YAML frontmatter '---'"
        )

    def test_report_contains_type_document(self, tmp_path: Path) -> None:
        """GRAPH_REPORT.md frontmatter must include type: Document."""
        analytics = AnalyticsResult()
        path = generate_report(analytics, tmp_path)
        content = path.read_text()
        assert "type: Document" in content

    def test_report_frontmatter_parseable(self, tmp_path: Path) -> None:
        """Frontmatter in GRAPH_REPORT.md must be parseable by parse_frontmatter()."""
        analytics = AnalyticsResult()
        path = generate_report(analytics, tmp_path)
        content = path.read_text()
        fm = parse_frontmatter(content)
        assert fm.title == "Knowledge Graph Report"
        assert fm.type == ConceptType.DOCUMENT_NODE

    def test_report_still_contains_markdown_body(self, tmp_path: Path) -> None:
        """Report body (Markdown content) must remain after frontmatter."""
        analytics = AnalyticsResult()
        path = generate_report(analytics, tmp_path)
        content = path.read_text()
        # The Markdown body starts after the frontmatter block
        assert "# Knowledge Graph Report" in content

    def test_report_tenant_id_in_resource(self, tmp_path: Path) -> None:
        """Tenant ID is reflected in the report frontmatter resource URI."""
        analytics = AnalyticsResult()
        path = generate_report(analytics, tmp_path, tenant_id="my-tenant")
        content = path.read_text()
        assert "my-tenant" in content

    def test_default_tenant_id(self, tmp_path: Path) -> None:
        """generate_report() uses 'default' as tenant_id when not specified."""
        analytics = AnalyticsResult()
        path = generate_report(analytics, tmp_path)
        content = path.read_text()
        # Should not raise and should produce valid frontmatter
        fm = parse_frontmatter(content)
        assert fm.id.startswith("graph-report-")

    def test_report_filename_unchanged(self, tmp_path: Path) -> None:
        """GRAPH_REPORT.md filename is still GRAPH_REPORT.md."""
        analytics = AnalyticsResult()
        path = generate_report(analytics, tmp_path)
        assert path.name == "GRAPH_REPORT.md"


# ---------------------------------------------------------------------------
# Tests: BuildResult projection_report field
# ---------------------------------------------------------------------------


class TestBuildResultProjectionField:
    """Tests for the projection_report field on BuildResult."""

    def test_projection_report_optional_and_none_by_default(self) -> None:
        """BuildResult.projection_report defaults to None."""
        result = BuildResult(tenant_id="test")
        assert result.projection_report is None

    def test_projection_report_can_be_populated(self) -> None:
        """BuildResult accepts a GraphProjectionReport in projection_report."""
        report = GraphProjectionReport(output_dir="/tmp/test", nodes_projected=5)
        result = BuildResult(
            tenant_id="test",
            projection_report=report,
        )
        assert result.projection_report is not None
        assert result.projection_report.output_dir == "/tmp/test"  # type: ignore[union-attr]
        assert result.projection_report.nodes_projected == 5  # type: ignore[union-attr]

    def test_build_result_other_fields_unchanged(self) -> None:
        """Adding projection_report does not break other BuildResult fields."""
        result = BuildResult(
            tenant_id="test",
            node_count=10,
            edge_count=5,
            errors=[],
        )
        assert result.node_count == 10
        assert result.edge_count == 5
        assert result.errors == []


# ---------------------------------------------------------------------------
# Tests: graphindex __init__.py exports
# ---------------------------------------------------------------------------


class TestGraphIndexPackageExports:
    """Tests that projection symbols are exported from graphindex package."""

    def test_project_graph_sidecars_exported(self) -> None:
        """project_graph_sidecars is accessible from parrot.knowledge.graphindex."""
        from parrot.knowledge.graphindex import project_graph_sidecars

        assert callable(project_graph_sidecars)

    def test_project_node_sidecar_exported(self) -> None:
        """project_node_sidecar is accessible from parrot.knowledge.graphindex."""
        from parrot.knowledge.graphindex import project_node_sidecar

        assert callable(project_node_sidecar)

    def test_project_report_frontmatter_exported(self) -> None:
        """project_report_frontmatter is accessible from parrot.knowledge.graphindex."""
        from parrot.knowledge.graphindex import project_report_frontmatter

        assert callable(project_report_frontmatter)

    def test_node_to_frontmatter_dict_exported(self) -> None:
        """node_to_frontmatter_dict is accessible from parrot.knowledge.graphindex."""
        from parrot.knowledge.graphindex import node_to_frontmatter_dict

        assert callable(node_to_frontmatter_dict)

    def test_graph_projection_report_exported(self) -> None:
        """GraphProjectionReport is accessible from parrot.knowledge.graphindex."""
        from parrot.knowledge.graphindex import GraphProjectionReport as GPR

        report = GPR(output_dir="/tmp")
        assert report.nodes_projected == 0


# ---------------------------------------------------------------------------
# Tests: Analytics generate_report() tenant_id parameter backward compat
# ---------------------------------------------------------------------------


class TestGenerateReportBackwardCompat:
    """Verify generate_report() remains callable with old signature."""

    def test_positional_args_still_work(self, tmp_path: Path) -> None:
        """generate_report(analytics, output_dir) still works (no breaking change)."""
        analytics = AnalyticsResult()
        path = generate_report(analytics, tmp_path)
        assert path.exists()

    def test_llm_polish_still_accepted(self, tmp_path: Path) -> None:
        """generate_report(analytics, output_dir, llm_polish=True) still accepted."""
        analytics = AnalyticsResult()
        path = generate_report(analytics, tmp_path, llm_polish=True)
        assert path.exists()
