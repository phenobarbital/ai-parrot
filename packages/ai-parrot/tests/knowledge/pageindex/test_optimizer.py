"""Unit tests for parrot.knowledge.pageindex.optimizer (FEAT-846 M1)."""

import pytest

from parrot.knowledge.pageindex.optimizer import (
    OptimizeReport,
    OptimizerSettings,
    assign_ownership,
    normalize,
    optimizable_roots,
    owned_tokens,
    repair_ownership,
)
from parrot.knowledge.pageindex.segments import DocumentRevision, render_body, revision_id, segment_text


@pytest.fixture(autouse=True)
def _stub_tokens(monkeypatch):
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.utils.count_tokens", lambda text, model="gpt-4o": max(1, len(text) // 4)
    )


@pytest.fixture
def revision() -> DocumentRevision:
    segments = segment_text("# Parent\n\nlead\n\n# First\n\nsmall\n\n# Second\n\ntail", ["Document"])
    return DocumentRevision(
        doc_id="doc",
        revision=revision_id(segments),
        source={"name": "document.md", "kind": "markdown"},
        created_at="2026-01-01T00:00:00Z",
        segments=segments,
    )


def test_owned_tokens_and_scope(revision: DocumentRevision) -> None:
    root = {
        "node_id": "root",
        "nodes": [
            {"node_id": "missing", "doc_id": "missing", "revision": "none", "span": [0, 1], "owned": [[0, 1]]},
            {
                "node_id": "doc",
                "doc_id": "doc",
                "revision": revision.revision,
                "span": [0, 5],
                "owned": [[0, 2], [3, 5]],
            },
            {
                "node_id": "locked",
                "doc_id": "doc",
                "revision": revision.revision,
                "locked": True,
                "span": [0, 1],
                "owned": [[0, 1]],
            },
        ],
    }
    scoped = optimizable_roots(root, {("doc", revision.revision): revision})
    assert scoped == [root["nodes"][1]]
    assert owned_tokens(scoped[0], revision) == sum(
        segment.tokens for segment in revision.segments[:2] + revision.segments[3:5]
    )
    assert optimizable_roots(root, {("doc", revision.revision): revision}, node_id="doc") == [root["nodes"][1]]


def test_repair_gaps_and_reject_overlaps(revision: DocumentRevision) -> None:
    parent = {"node_id": "parent", "span": [0, 5], "owned": [[0, 1], [4, 5]]}
    child = {"node_id": "child", "span": [1, 4], "owned": []}
    report = OptimizeReport()
    assert repair_ownership([parent, child], revision, report) == []
    assert child["owned"] == [[1, 4]]
    assert report.repaired_gaps == 1

    overlap = {"node_id": "overlap", "span": [4, 5], "owned": [[4, 5]]}
    original = list(parent["owned"])
    problems = repair_ownership([parent, overlap], revision, report)
    assert problems and problems[0].startswith("overlap")
    assert parent["owned"] == original


def test_normalize_duplicates_empty_and_tiny(revision: DocumentRevision) -> None:
    children = [
        {"title": "First", "concept_id": "first", "span": [0, 2], "owned": [[0, 2]]},
        {"title": "Duplicate", "concept_id": "duplicate", "span": [0, 2], "owned": [[0, 2]]},
        {"title": "Empty", "span": [2, 2], "owned": []},
        {"title": "Tiny", "concept_id": "tiny", "span": [2, 3], "owned": [[2, 3]]},
        {"title": "Tail", "concept_id": "tail", "span": [3, 5], "owned": [[3, 5]]},
        {"title": "Separate", "span": [8, 9], "owned": [[4, 5]]},
    ]
    report = OptimizeReport()
    normalize(children, revision, OptimizerSettings(min_leaf_tokens=100), report)
    assert [child["title"] for child in children] == ["Tail", "Separate"]
    tail = children[0]
    assert tail["aliases"] == ["tiny", "first", "duplicate"]
    assert {item["label"] for item in tail["key_items"]} >= {"Duplicate", "First", "Tiny"}
    assert {action.reason for action in report.merged} == {"duplicate_span", "under_minimum"}


def test_assign_ownership_residuals(revision: DocumentRevision) -> None:
    parent = {
        "title": "Parent",
        "span": [0, 5],
        "owned": [[0, 5]],
        "nodes": [
            {"title": "First", "span": [1, 2], "owned": [[1, 2]]},
            {"title": "Second", "span": [3, 4], "owned": [[3, 4]]},
        ],
    }
    assign_ownership(parent)
    assert parent["owned"] == [[0, 1], [2, 3], [4, 5]]
    body = render_body(revision, parent, parent["nodes"])
    assert "<!-- continues in: First -->" in body
    assert "<!-- continues in: Second -->" in body
