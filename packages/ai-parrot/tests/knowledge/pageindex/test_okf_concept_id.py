"""Unit tests for OKF concept_id module (TASK-1553).

Tests verify:
- derive_concept_id produces deterministic kebab-case slugs.
- derive_concept_id scopes correctly under parent_path.
- dedup_concept_ids resolves collisions with stable numeric suffixes.
- assign_concept_ids walks a tree depth-first and writes concept_id on all nodes.
- Running assign_concept_ids twice yields identical results (idempotency).
"""

import pytest
from parrot.knowledge.pageindex.okf.concept_id import (
    assign_concept_ids,
    dedup_concept_ids,
    derive_concept_id,
)


class TestDeriveConceptId:
    """Tests for the deterministic slug function."""

    def test_simple_title(self):
        """Plain English title maps to kebab-case slug."""
        assert derive_concept_id("AWS Incident Response") == "aws-incident-response"

    def test_with_parent_path(self):
        """Title under parent path gets fully-scoped id."""
        result = derive_concept_id("IR-4", "controls/nist-800-53")
        assert result == "controls/nist-800-53/ir-4"

    def test_special_characters_stripped(self):
        """Non-ASCII and punctuation are normalised/removed."""
        result = derive_concept_id("HIPAA §164.312(a)(1)")
        # Must be non-empty and ASCII-safe
        assert result
        assert result.isascii()
        # No unescaped special chars — only letters, digits, hyphens, slashes
        import re

        assert re.match(r"^[a-z0-9][a-z0-9/-]*$", result), (
            f"Unexpected slug: {result!r}"
        )

    def test_empty_title(self):
        """Empty title falls back to 'untitled'."""
        assert derive_concept_id("") == "untitled"

    def test_whitespace_only_title(self):
        """Whitespace-only title falls back to 'untitled'."""
        assert derive_concept_id("   ") == "untitled"

    def test_deterministic(self):
        """Same inputs always produce same output."""
        a = derive_concept_id("Some Title", "parent")
        b = derive_concept_id("Some Title", "parent")
        assert a == b

    def test_parent_path_trailing_slash_normalised(self):
        """Trailing slash in parent_path is stripped before joining."""
        a = derive_concept_id("Child", "section/")
        b = derive_concept_id("Child", "section")
        assert a == b

    def test_no_parent_path(self):
        """Without parent_path no slash prefix is added."""
        result = derive_concept_id("Overview")
        assert "/" not in result

    def test_nested_parent_path(self):
        """Deep parent paths are preserved exactly."""
        result = derive_concept_id("Step 1", "guides/aws/incident")
        assert result == "guides/aws/incident/step-1"

    def test_numbers_preserved(self):
        """Digits are preserved in slugs."""
        result = derive_concept_id("NIST 800-53")
        assert "800" in result
        assert "53" in result

    def test_unicode_normalisation(self):
        """Unicode characters are normalised to ASCII equivalents."""
        result = derive_concept_id("Résumé Control")
        # 'e' from 'é' via NFKD normalisation
        assert result  # non-empty
        assert result.isascii()

    def test_long_title_truncated(self):
        """Very long titles are truncated at ~80 chars."""
        long_title = "A" * 200
        result = derive_concept_id(long_title)
        assert len(result) <= 80


class TestDedupConceptIds:
    """Tests for slug collision resolution."""

    def test_no_collisions(self):
        """Nodes with distinct concept_ids are untouched."""
        nodes = [
            {"concept_id": "a", "title": "A"},
            {"concept_id": "b", "title": "B"},
        ]
        dedup_concept_ids(nodes)
        assert nodes[0]["concept_id"] == "a"
        assert nodes[1]["concept_id"] == "b"

    def test_collision_suffixes(self):
        """Duplicates receive -2, -3, ... suffixes; first keeps bare slug."""
        nodes = [
            {"concept_id": "overview", "title": "Overview"},
            {"concept_id": "overview", "title": "Overview"},
            {"concept_id": "overview", "title": "Overview"},
        ]
        dedup_concept_ids(nodes)
        assert nodes[0]["concept_id"] == "overview"
        assert nodes[1]["concept_id"] == "overview-2"
        assert nodes[2]["concept_id"] == "overview-3"

    def test_stable_across_runs(self):
        """Running dedup twice on the same input yields identical results."""
        nodes_a = [
            {"concept_id": "x", "title": "X"},
            {"concept_id": "x", "title": "X"},
        ]
        nodes_b = [
            {"concept_id": "x", "title": "X"},
            {"concept_id": "x", "title": "X"},
        ]
        dedup_concept_ids(nodes_a)
        dedup_concept_ids(nodes_b)
        assert [n["concept_id"] for n in nodes_a] == [n["concept_id"] for n in nodes_b]

    def test_mixed_collisions(self):
        """Only the colliding slugs get suffixes; others are preserved."""
        nodes = [
            {"concept_id": "intro", "title": "Intro"},
            {"concept_id": "overview", "title": "Overview"},
            {"concept_id": "overview", "title": "Overview"},
            {"concept_id": "intro", "title": "Intro"},
        ]
        dedup_concept_ids(nodes)
        assert nodes[0]["concept_id"] == "intro"
        assert nodes[1]["concept_id"] == "overview"
        assert nodes[2]["concept_id"] == "overview-2"
        assert nodes[3]["concept_id"] == "intro-2"

    def test_single_node_unchanged(self):
        """Single node list is not modified."""
        nodes = [{"concept_id": "only", "title": "Only"}]
        dedup_concept_ids(nodes)
        assert nodes[0]["concept_id"] == "only"


class TestAssignConceptIds:
    """Tests for the full tree assignment function."""

    def test_assigns_to_all_nodes(self):
        """All nodes (root and children) receive a concept_id."""
        tree = {
            "structure": [
                {
                    "title": "Root",
                    "node_id": "0000",
                    "nodes": [
                        {"title": "Child", "node_id": "0001", "nodes": []},
                    ],
                },
            ]
        }
        assign_concept_ids(tree)
        root = tree["structure"][0]
        assert "concept_id" in root
        assert "concept_id" in root["nodes"][0]

    def test_idempotent(self):
        """Running assign_concept_ids twice yields identical concept_ids."""
        tree = {
            "structure": [
                {"title": "Root", "node_id": "0000", "nodes": []},
            ]
        }
        assign_concept_ids(tree)
        first = tree["structure"][0]["concept_id"]
        assign_concept_ids(tree)
        assert tree["structure"][0]["concept_id"] == first

    def test_child_scoped_under_parent(self):
        """Child concept_id includes parent slug as prefix."""
        tree = {
            "structure": [
                {
                    "title": "Controls",
                    "node_id": "0000",
                    "nodes": [
                        {"title": "IR-4", "node_id": "0001", "nodes": []},
                    ],
                }
            ]
        }
        assign_concept_ids(tree)
        parent = tree["structure"][0]
        child = parent["nodes"][0]
        assert child["concept_id"].startswith(parent["concept_id"] + "/")

    def test_sibling_collision_resolved(self):
        """Two siblings with the same title get distinct concept_ids."""
        tree = {
            "structure": [
                {"title": "Overview", "node_id": "0000", "nodes": []},
                {"title": "Overview", "node_id": "0001", "nodes": []},
            ]
        }
        assign_concept_ids(tree)
        ids = [n["concept_id"] for n in tree["structure"]]
        assert len(set(ids)) == 2, f"Expected distinct ids, got: {ids}"
        assert ids[0] == "overview"
        assert ids[1] == "overview-2"

    def test_empty_structure(self):
        """Tree with no nodes does not raise."""
        tree = {"structure": []}
        assign_concept_ids(tree)  # should not raise

    def test_missing_structure_key(self):
        """Tree dict without 'structure' key does not raise."""
        tree = {}
        assign_concept_ids(tree)  # should not raise

    def test_deep_nesting(self):
        """Multiple levels of nesting are all assigned concept_ids."""
        tree = {
            "structure": [
                {
                    "title": "L1",
                    "node_id": "0000",
                    "nodes": [
                        {
                            "title": "L2",
                            "node_id": "0001",
                            "nodes": [
                                {"title": "L3", "node_id": "0002", "nodes": []},
                            ],
                        }
                    ],
                }
            ]
        }
        assign_concept_ids(tree)
        l1 = tree["structure"][0]
        l2 = l1["nodes"][0]
        l3 = l2["nodes"][0]
        assert "concept_id" in l1
        assert "concept_id" in l2
        assert "concept_id" in l3
        # Hierarchy encoded in slash-separated path
        assert l3["concept_id"].startswith(l2["concept_id"] + "/")
        assert l2["concept_id"].startswith(l1["concept_id"] + "/")
