"""Unit tests for OKF knowledge base lint engine (TASK-1566).

Tests verify:
- Orphan detection (zero inbound edges)
- Broken link audit (from KnowledgeGraph.broken_links())
- Missing concept pages (known concept without sidecar in content_store)
- Stale claims (timestamp older than stale_days)
- Empty graph returns zero findings
"""

from datetime import datetime, timedelta, timezone

import pytest

from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.okf.graph import KnowledgeGraph
from parrot.knowledge.pageindex.okf.lint import (
    LintFinding,
    LintReport,
    lint_knowledge_base,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_timestamp(days_ago: int) -> str:
    """Return an ISO-8601 timestamp ``days_ago`` days before now."""
    ts = datetime.now(tz=timezone.utc) - timedelta(days=days_ago)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def content_store(tmp_path):
    """An empty NodeContentStore backed by tmp_path."""
    return NodeContentStore(tmp_path)


@pytest.fixture
def tree_two_nodes():
    """Minimal tree: two concepts, one references the other."""
    return {
        "tree_name": "test",
        "structure": [
            {
                "node_id": "0001",
                "concept_id": "policy-a",
                "type": "Policy",
                "title": "Policy A",
                "summary": "",
                "timestamp": "2026-01-01T00:00:00Z",
                "relates_to": [{"concept": "control-b", "rel": "references"}],
                "nodes": [],
            },
            {
                "node_id": "0002",
                "concept_id": "control-b",
                "type": "Control",
                "title": "Control B",
                "summary": "",
                "timestamp": "2026-01-01T00:00:00Z",
                "relates_to": [],
                "nodes": [],
            },
        ],
    }


@pytest.fixture
def tree_broken_link():
    """Tree where policy-x references nonexistent-concept."""
    return {
        "tree_name": "test",
        "structure": [
            {
                "node_id": "0001",
                "concept_id": "policy-x",
                "type": "Policy",
                "title": "Policy X",
                "summary": "",
                "timestamp": "2026-01-01T00:00:00Z",
                "relates_to": [{"concept": "nonexistent-concept", "rel": "references"}],
                "nodes": [],
            },
        ],
    }


@pytest.fixture
def tree_stale():
    """Tree with one very old node (200 days ago)."""
    old_ts = _make_timestamp(200)
    return {
        "tree_name": "test",
        "structure": [
            {
                "node_id": "0001",
                "concept_id": "old-policy",
                "type": "Policy",
                "title": "Old Policy",
                "summary": "",
                "timestamp": old_ts,
                "relates_to": [],
                "nodes": [],
            },
        ],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLintOrphans:
    """Orphan detection: concepts with zero inbound edges."""

    def test_lint_finds_orphans(self, tree_two_nodes, content_store):
        """control-b has an inbound edge from policy-a; policy-a has none → orphan."""
        graph = KnowledgeGraph(tree_two_nodes)
        report = lint_knowledge_base(graph, tree_two_nodes, content_store)
        orphan_ids = {f.concept_id for f in report.orphans}
        # policy-a has zero inbound edges
        assert "policy-a" in orphan_ids
        # control-b is referenced by policy-a → not an orphan
        assert "control-b" not in orphan_ids

    def test_lint_finds_orphan_kind(self, tree_two_nodes, content_store):
        """Orphan findings have kind='orphan' and severity='warning'."""
        graph = KnowledgeGraph(tree_two_nodes)
        report = lint_knowledge_base(graph, tree_two_nodes, content_store)
        for finding in report.orphans:
            assert finding.kind == "orphan"
            assert finding.severity == "warning"

    def test_no_orphans_when_all_referenced(self, content_store):
        """If every concept is referenced, no orphans are reported."""
        tree = {
            "tree_name": "test",
            "structure": [
                {
                    "node_id": "0001",
                    "concept_id": "a",
                    "type": "Policy",
                    "title": "A",
                    "summary": "",
                    "relates_to": [{"concept": "b", "rel": "references"}],
                    "nodes": [],
                },
                {
                    "node_id": "0002",
                    "concept_id": "b",
                    "type": "Control",
                    "title": "B",
                    "summary": "",
                    "relates_to": [{"concept": "a", "rel": "references"}],
                    "nodes": [],
                },
            ],
        }
        graph = KnowledgeGraph(tree)
        report = lint_knowledge_base(graph, tree, content_store)
        assert report.orphans == []


class TestLintBrokenLinks:
    """Broken link audit: edges targeting unknown concept_ids."""

    def test_lint_finds_broken_links(self, tree_broken_link, content_store):
        """Edge to nonexistent-concept surfaces as a broken_link finding."""
        graph = KnowledgeGraph(tree_broken_link)
        report = lint_knowledge_base(graph, tree_broken_link, content_store)
        assert len(report.broken_links) >= 1
        targets = {f.detail for f in report.broken_links}
        assert any("nonexistent-concept" in d for d in targets)

    def test_broken_link_severity_is_error(self, tree_broken_link, content_store):
        """Broken links are reported with severity='error'."""
        graph = KnowledgeGraph(tree_broken_link)
        report = lint_knowledge_base(graph, tree_broken_link, content_store)
        for finding in report.broken_links:
            assert finding.kind == "broken_link"
            assert finding.severity == "error"

    def test_no_broken_links_in_clean_tree(self, tree_two_nodes, content_store):
        """Clean tree with valid references has zero broken links."""
        graph = KnowledgeGraph(tree_two_nodes)
        report = lint_knowledge_base(graph, tree_two_nodes, content_store)
        assert report.broken_links == []


class TestLintMissingConcepts:
    """Missing concept pages: concepts with no sidecar body."""

    def test_lint_finds_missing_concepts(self, tree_two_nodes, content_store):
        """Both concepts have no sidecars → both are missing_concept findings."""
        graph = KnowledgeGraph(tree_two_nodes)
        report = lint_knowledge_base(graph, tree_two_nodes, content_store)
        missing_ids = {f.concept_id for f in report.missing_concepts}
        assert "policy-a" in missing_ids
        assert "control-b" in missing_ids

    def test_no_missing_when_sidecar_exists(self, tree_two_nodes, content_store):
        """When a sidecar is present, the concept is NOT flagged as missing."""
        graph = KnowledgeGraph(tree_two_nodes)
        # Pre-seed a sidecar for policy-a
        content_store.save("test", "policy-a", "# Policy A\n\nBody text.")
        report = lint_knowledge_base(graph, tree_two_nodes, content_store)
        missing_ids = {f.concept_id for f in report.missing_concepts}
        assert "policy-a" not in missing_ids
        # control-b still has no sidecar
        assert "control-b" in missing_ids


class TestLintStaleClaims:
    """Stale claims: timestamp older than stale_days."""

    def test_lint_finds_stale_claims(self, tree_stale, content_store):
        """Node with timestamp 200 days ago is stale at threshold 90."""
        graph = KnowledgeGraph(tree_stale)
        report = lint_knowledge_base(
            graph, tree_stale, content_store, stale_days=90
        )
        stale_ids = {f.concept_id for f in report.stale_claims}
        assert "old-policy" in stale_ids

    def test_recent_node_not_stale(self, content_store):
        """Node with timestamp 10 days ago is not stale at threshold 90."""
        recent_ts = _make_timestamp(10)
        tree = {
            "tree_name": "test",
            "structure": [
                {
                    "node_id": "0001",
                    "concept_id": "recent-policy",
                    "type": "Policy",
                    "title": "Recent Policy",
                    "summary": "",
                    "timestamp": recent_ts,
                    "relates_to": [],
                    "nodes": [],
                },
            ],
        }
        graph = KnowledgeGraph(tree)
        report = lint_knowledge_base(graph, tree, content_store, stale_days=90)
        stale_ids = {f.concept_id for f in report.stale_claims}
        assert "recent-policy" not in stale_ids

    def test_stale_severity_is_warning(self, tree_stale, content_store):
        """Stale findings have kind='stale' and severity='warning'."""
        graph = KnowledgeGraph(tree_stale)
        report = lint_knowledge_base(graph, tree_stale, content_store)
        for finding in report.stale_claims:
            assert finding.kind == "stale"
            assert finding.severity == "warning"


class TestLintEmptyGraph:
    """Edge case: empty graph produces zero findings."""

    def test_lint_empty_graph(self, content_store):
        """Empty tree returns a LintReport with zero findings."""
        tree = {"tree_name": "empty", "structure": []}
        graph = KnowledgeGraph(tree)
        report = lint_knowledge_base(graph, tree, content_store)
        assert report.total_concepts == 0
        assert report.total_findings == 0
        assert report.orphans == []
        assert report.broken_links == []
        assert report.missing_concepts == []
        assert report.stale_claims == []


class TestLintTotals:
    """total_findings correctly sums all categories."""

    def test_total_findings_counts_all(self, content_store):
        """total_findings equals sum of all finding lists."""
        tree = {
            "tree_name": "test",
            "structure": [
                {
                    "node_id": "0001",
                    "concept_id": "a",
                    "type": "Policy",
                    "title": "A",
                    "summary": "",
                    "timestamp": "2020-01-01T00:00:00Z",  # stale
                    "relates_to": [{"concept": "ghost", "rel": "references"}],  # broken
                    "nodes": [],
                },
            ],
        }
        graph = KnowledgeGraph(tree)
        report = lint_knowledge_base(graph, tree, content_store, stale_days=90)
        expected = (
            len(report.orphans)
            + len(report.broken_links)
            + len(report.missing_concepts)
            + len(report.stale_claims)
        )
        assert report.total_findings == expected

    def test_lint_report_is_pydantic_model(self, content_store):
        """LintReport can be serialised to dict via model_dump()."""
        tree = {"tree_name": "test", "structure": []}
        graph = KnowledgeGraph(tree)
        report = lint_knowledge_base(graph, tree, content_store)
        d = report.model_dump()
        assert "orphans" in d
        assert "broken_links" in d
        assert "missing_concepts" in d
        assert "stale_claims" in d
        assert "total_findings" in d
        assert "total_concepts" in d


class TestLintNoTreeName:
    """Edge case: tree dict with no name keys uses safe fallback."""

    def test_lint_no_tree_name_does_not_crash(self, content_store):
        """lint_knowledge_base must not raise when tree has no name key."""
        tree = {
            # Intentionally omit tree_name, doc_name, name
            "structure": [
                {
                    "node_id": "0001",
                    "concept_id": "policy-x",
                    "type": "Policy",
                    "title": "Policy X",
                    "summary": "",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "relates_to": [],
                    "nodes": [],
                },
            ],
        }
        graph = KnowledgeGraph(tree)
        # Must not raise ValueError from NodeContentStore validation
        report = lint_knowledge_base(graph, tree, content_store)
        assert report.total_concepts == 1
        # All concepts should be flagged as missing (no sidecar under "_unknown")
        missing_ids = {f.concept_id for f in report.missing_concepts}
        assert "policy-x" in missing_ids

    def test_lint_no_tree_name_report_tree_name_is_unknown(self, content_store):
        """LintReport.tree_name is '_unknown' when no name key is present."""
        tree = {"structure": []}
        graph = KnowledgeGraph(tree)
        report = lint_knowledge_base(graph, tree, content_store)
        assert report.tree_name == "_unknown"
