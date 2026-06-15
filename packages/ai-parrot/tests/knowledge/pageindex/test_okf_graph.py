"""Unit tests for OKF knowledge graph module (TASK-1555).

Tests verify:
- parse_markdown_links extracts links from body text.
- parse_markdown_links skips links inside fenced code blocks.
- KnowledgeGraph builds correct adjacency from relates_to edges.
- neighbors() returns correct edges, filterable by rel.
- trace() follows multi-hop typed chains.
- broken_links() reports edges to non-existent concept_ids.
- concepts() returns all known concept_ids.
- Graph is built from both relates_to and prose markdown links.
- Broken links are tolerated — no exception raised.
"""

import pytest
from parrot.knowledge.pageindex.okf.graph import (
    KnowledgeGraph,
    parse_markdown_links,
)


class TestParseMarkdownLinks:
    """Tests for the prose-link extractor."""

    def test_extracts_relative_links(self):
        """Relative link targets are extracted."""
        body = "See [control](/controls/nist-ir-4) for details."
        links = parse_markdown_links(body)
        assert "controls/nist-ir-4" in links

    def test_skips_fenced_code_blocks(self):
        """Links inside fenced code blocks are ignored."""
        body = "text\n```\n[link](/inside-code)\n```\n[real](/outside)"
        links = parse_markdown_links(body)
        assert "outside" in links
        assert "inside-code" not in links

    def test_extracts_multiple_links(self):
        """Multiple links in the same body all extracted."""
        body = "[a](/one) and [b](/two)"
        links = parse_markdown_links(body)
        assert len(links) == 2
        assert "one" in links
        assert "two" in links

    def test_strips_leading_slash(self):
        """Leading slash stripped from all link targets."""
        body = "[x](/section/one)"
        links = parse_markdown_links(body)
        assert "section/one" in links
        assert "/section/one" not in links

    def test_skips_http_links(self):
        """External HTTP links are ignored."""
        body = "[ext](https://example.com) [internal](/local)"
        links = parse_markdown_links(body)
        assert not any(l.startswith("http") for l in links)
        assert "local" in links

    def test_skips_anchor_links(self):
        """Anchor-only links (#section) are ignored."""
        body = "[heading](#section) [page](/page)"
        links = parse_markdown_links(body)
        assert not any(l.startswith("#") for l in links)
        assert "page" in links

    def test_empty_body(self):
        """Empty body returns empty list."""
        assert parse_markdown_links("") == []

    def test_no_links(self):
        """Body with no markdown links returns empty list."""
        body = "Just plain text without any links."
        assert parse_markdown_links(body) == []

    def test_deduplicates_links(self):
        """Duplicate link targets appear only once."""
        body = "[a](/one) and [b](/one) again."
        links = parse_markdown_links(body)
        assert links.count("one") == 1

    def test_multiple_code_blocks(self):
        """Multiple fenced code blocks all skipped."""
        body = "[a](/real)\n```\n[b](/fake1)\n```\n[c](/real2)\n```\n[d](/fake2)\n```"
        links = parse_markdown_links(body)
        assert "real" in links
        assert "real2" in links
        assert "fake1" not in links
        assert "fake2" not in links


@pytest.fixture
def tree_with_edges():
    """Tree with typed relates_to edges for graph tests."""
    return {
        "structure": [
            {
                "node_id": "0000",
                "concept_id": "safeguards/hipaa-164",
                "title": "HIPAA 164",
                "relates_to": [
                    {"concept": "controls/nist-ir-4", "rel": "maps_to"}
                ],
                "nodes": [],
            },
            {
                "node_id": "0001",
                "concept_id": "controls/nist-ir-4",
                "title": "NIST IR-4",
                "relates_to": [
                    {"concept": "evidence/ir-plan-v2", "rel": "satisfied_by"}
                ],
                "nodes": [],
            },
            {
                "node_id": "0002",
                "concept_id": "evidence/ir-plan-v2",
                "title": "IR Plan v2",
                "relates_to": [],
                "nodes": [],
            },
        ],
    }


class TestKnowledgeGraphBuild:
    """Tests for KnowledgeGraph construction."""

    def test_builds_from_relates_to(self, tree_with_edges):
        """Graph builds without error from relates_to edges."""
        g = KnowledgeGraph(tree_with_edges)
        assert len(g.concepts()) == 3

    def test_concepts_set(self, tree_with_edges):
        """All concept_ids from the tree are present."""
        g = KnowledgeGraph(tree_with_edges)
        assert "safeguards/hipaa-164" in g.concepts()
        assert "controls/nist-ir-4" in g.concepts()
        assert "evidence/ir-plan-v2" in g.concepts()

    def test_empty_tree(self):
        """Empty tree builds successfully."""
        g = KnowledgeGraph({"structure": []})
        assert len(g.concepts()) == 0
        assert g.broken_links() == []


class TestKnowledgeGraphNeighbors:
    """Tests for neighbors() method."""

    def test_neighbors_returns_edges(self, tree_with_edges):
        """neighbors() returns all outgoing edges for a concept."""
        g = KnowledgeGraph(tree_with_edges)
        n = g.neighbors("safeguards/hipaa-164")
        assert any(e["concept"] == "controls/nist-ir-4" for e in n)

    def test_neighbors_filtered_by_rel(self, tree_with_edges):
        """neighbors() filtered by rel returns only matching edges."""
        g = KnowledgeGraph(tree_with_edges)
        n = g.neighbors("safeguards/hipaa-164", rel="maps_to")
        assert len(n) == 1
        assert n[0]["concept"] == "controls/nist-ir-4"

    def test_neighbors_unknown_concept(self, tree_with_edges):
        """Unknown concept_id returns empty list — no exception."""
        g = KnowledgeGraph(tree_with_edges)
        assert g.neighbors("nonexistent") == []

    def test_neighbors_no_outgoing_edges(self, tree_with_edges):
        """Concept with no outgoing edges returns empty list."""
        g = KnowledgeGraph(tree_with_edges)
        n = g.neighbors("evidence/ir-plan-v2")
        assert n == []

    def test_neighbors_wrong_rel_filter_returns_empty(self, tree_with_edges):
        """Filtering by non-matching rel returns empty list."""
        g = KnowledgeGraph(tree_with_edges)
        n = g.neighbors("safeguards/hipaa-164", rel="satisfied_by")
        assert n == []


class TestKnowledgeGraphTrace:
    """Tests for trace() multi-hop traversal."""

    def test_trace_multi_hop(self, tree_with_edges):
        """trace() follows a two-hop chain correctly."""
        g = KnowledgeGraph(tree_with_edges)
        paths = g.trace("safeguards/hipaa-164", ["maps_to", "satisfied_by"])
        assert any("evidence/ir-plan-v2" in path for path in paths)

    def test_trace_single_hop(self, tree_with_edges):
        """trace() with a single rel works."""
        g = KnowledgeGraph(tree_with_edges)
        paths = g.trace("safeguards/hipaa-164", ["maps_to"])
        assert any("controls/nist-ir-4" in path for path in paths)

    def test_trace_empty_chain(self, tree_with_edges):
        """trace() with empty rel_chain returns [[concept_id]]."""
        g = KnowledgeGraph(tree_with_edges)
        paths = g.trace("safeguards/hipaa-164", [])
        assert paths == [["safeguards/hipaa-164"]]

    def test_trace_no_match(self, tree_with_edges):
        """trace() returns [] when no edges match the chain."""
        g = KnowledgeGraph(tree_with_edges)
        paths = g.trace("safeguards/hipaa-164", ["supersedes"])
        assert paths == []

    def test_trace_path_includes_start(self, tree_with_edges):
        """All paths include the starting concept_id."""
        g = KnowledgeGraph(tree_with_edges)
        paths = g.trace("safeguards/hipaa-164", ["maps_to", "satisfied_by"])
        for path in paths:
            assert path[0] == "safeguards/hipaa-164"


class TestBrokenLinks:
    """Tests for broken link tolerance."""

    def test_broken_links_collected(self):
        """Edge to unknown target is collected in broken_links()."""
        tree = {
            "structure": [
                {
                    "node_id": "0000",
                    "concept_id": "a",
                    "title": "A",
                    "relates_to": [{"concept": "nonexistent", "rel": "references"}],
                    "nodes": [],
                },
            ],
        }
        g = KnowledgeGraph(tree)
        broken = g.broken_links()
        assert len(broken) == 1
        assert broken[0]["concept"] == "nonexistent"

    def test_broken_links_do_not_raise(self):
        """Broken links are tolerated — no exception raised."""
        tree = {
            "structure": [
                {
                    "node_id": "0000",
                    "concept_id": "a",
                    "title": "A",
                    "relates_to": [{"concept": "b"}, {"concept": "c"}],
                    "nodes": [],
                },
            ],
        }
        g = KnowledgeGraph(tree)  # must not raise
        assert len(g.broken_links()) == 2

    def test_no_broken_links(self, tree_with_edges):
        """Well-formed tree with no broken links."""
        g = KnowledgeGraph(tree_with_edges)
        assert g.broken_links() == []


class TestProseLinks:
    """Tests for prose-link edge addition via add_prose_links."""

    def test_prose_links_added(self):
        """Markdown links from body are added as references edges."""
        tree = {
            "structure": [
                {
                    "node_id": "0000",
                    "concept_id": "a",
                    "title": "A",
                    "relates_to": [],
                    "nodes": [],
                },
                {
                    "node_id": "0001",
                    "concept_id": "b",
                    "title": "B",
                    "relates_to": [],
                    "nodes": [],
                },
            ],
        }
        g = KnowledgeGraph(tree)
        g.add_prose_links("a", "See [B](/b) for more.")
        neighbors = g.neighbors("a")
        assert any(e["concept"] == "b" for e in neighbors)

    def test_prose_links_are_references(self):
        """Prose-link edges have rel=references."""
        tree = {
            "structure": [
                {"node_id": "0000", "concept_id": "src", "title": "S", "relates_to": [], "nodes": []},
                {"node_id": "0001", "concept_id": "tgt", "title": "T", "relates_to": [], "nodes": []},
            ],
        }
        g = KnowledgeGraph(tree)
        g.add_prose_links("src", "[T](/tgt)")
        edges = g.neighbors("src", rel="references")
        assert any(e["concept"] == "tgt" for e in edges)

    def test_prose_links_broken_tolerated(self):
        """Prose links to unknown concepts are tolerated."""
        tree = {
            "structure": [
                {"node_id": "0000", "concept_id": "a", "title": "A", "relates_to": [], "nodes": []},
            ],
        }
        g = KnowledgeGraph(tree)
        g.add_prose_links("a", "[Unknown](/missing-concept)")  # must not raise
        assert any(b["concept"] == "missing-concept" for b in g.broken_links())
