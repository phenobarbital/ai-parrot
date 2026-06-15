"""Tests for parrot.knowledge.pageindex.tree_ops splice / delete / reindex helpers."""
from __future__ import annotations

import pytest

from parrot.knowledge.pageindex.tree_ops import (
    delete_node,
    make_folder_node,
    reindex_node_ids,
    splice_subtree,
)
from parrot.knowledge.pageindex.utils import find_node_by_id, get_nodes


def _sample_tree() -> dict:
    tree = {
        "doc_name": "demo",
        "structure": [
            {"title": "A", "nodes": [{"title": "A.1"}, {"title": "A.2"}]},
            {"title": "B"},
        ],
    }
    reindex_node_ids(tree)
    return tree


def test_reindex_assigns_contiguous_4digit_ids():
    tree = _sample_tree()
    ids = [n["node_id"] for n in get_nodes(tree["structure"])]
    assert ids == ["0000", "0001", "0002", "0003"]
    assert all(len(nid) == 4 for nid in ids)


def test_splice_at_root_appends_to_top_level():
    tree = _sample_tree()
    new_ids = splice_subtree(tree, {"structure": [{"title": "C"}]})
    titles = [n["title"] for n in tree["structure"]]
    assert titles == ["A", "B", "C"]
    assert len(new_ids) == 1


def test_splice_under_parent_renumbers_all_ids():
    tree = _sample_tree()
    parent_id = tree["structure"][0]["node_id"]
    splice_subtree(tree, {"structure": [{"title": "A.3"}]}, parent_node_id=parent_id)
    a_node = find_node_by_id(tree["structure"], parent_id)
    assert [c["title"] for c in a_node["nodes"]] == ["A.1", "A.2", "A.3"]
    ids = [n["node_id"] for n in get_nodes(tree["structure"])]
    assert ids == ["0000", "0001", "0002", "0003", "0004"]


def test_splice_unknown_parent_raises():
    tree = _sample_tree()
    with pytest.raises(KeyError):
        splice_subtree(tree, {"structure": [{"title": "x"}]}, parent_node_id="9999")


def test_splice_accepts_bare_node_dict():
    tree = _sample_tree()
    folder = make_folder_node("docs")
    splice_subtree(tree, folder)
    assert folder["node_id"] is not None
    assert tree["structure"][-1] is folder
    assert folder["title"] == "docs"


def test_delete_removes_descendants():
    tree = _sample_tree()
    a_id = tree["structure"][0]["node_id"]
    assert delete_node(tree, a_id) is True
    titles = [n["title"] for n in get_nodes(tree["structure"])]
    assert titles == ["B"]
    # After deletion + reindex, the sole remaining node should occupy "0000"
    assert tree["structure"][0]["node_id"] == "0000"
    # The original A.1 / A.2 titles are gone
    assert not any(t.startswith("A") for t in titles)


def test_delete_missing_returns_false():
    tree = _sample_tree()
    assert delete_node(tree, "9999") is False


def test_delete_nested_node():
    tree = _sample_tree()
    a1_node = tree["structure"][0]["nodes"][0]
    a1_id = a1_node["node_id"]
    assert delete_node(tree, a1_id) is True
    remaining = [c["title"] for c in tree["structure"][0]["nodes"]]
    assert remaining == ["A.2"]


# ---- OKF concept_id preservation tests (FEAT-238 / TASK-1559) -------


def _sample_okf_tree() -> dict:
    """Build a sample tree with concept_ids pre-assigned."""
    tree = {
        "doc_name": "demo",
        "structure": [
            {
                "title": "A",
                "concept_id": "section/a",
                "nodes": [
                    {"title": "A.1", "concept_id": "section/a/a-1"},
                    {"title": "A.2", "concept_id": "section/a/a-2"},
                ],
            },
            {"title": "B", "concept_id": "section/b"},
        ],
    }
    reindex_node_ids(tree)
    return tree


def test_reindex_preserves_concept_id():
    """reindex_node_ids must NOT touch concept_id on any node."""
    tree = _sample_okf_tree()
    # Record original concept_ids
    nodes_before = get_nodes(tree["structure"])
    cids_before = {n["node_id"]: n.get("concept_id") for n in nodes_before}

    # Run reindex again — changes nothing meaningful, but concept_ids must survive.
    reindex_node_ids(tree)

    nodes_after = get_nodes(tree["structure"])
    cids_after = {n["node_id"]: n.get("concept_id") for n in nodes_after}
    assert cids_before == cids_after, (
        "reindex_node_ids must not modify concept_id values"
    )


def test_reindex_preserves_concept_id_with_structure_change():
    """concept_id survives renumbering caused by a prior splice."""
    tree = _sample_okf_tree()
    # Splice a new node — this triggers reindex internally.
    splice_subtree(tree, {"title": "C"})
    # A and B nodes should still have their original concept_ids.
    a_node = next(n for n in get_nodes(tree["structure"]) if n["title"] == "A")
    b_node = next(n for n in get_nodes(tree["structure"]) if n["title"] == "B")
    assert a_node["concept_id"] == "section/a"
    assert b_node["concept_id"] == "section/b"


def test_splice_assigns_concept_id_to_new_nodes():
    """splice_subtree assigns concept_id to newly spliced nodes without one."""
    tree = _sample_okf_tree()
    new_node = {"title": "D", "summary": "New node"}  # no concept_id
    splice_subtree(tree, new_node)
    # After splice, the new node should have received a concept_id.
    d_node = next(n for n in get_nodes(tree["structure"]) if n["title"] == "D")
    assert d_node.get("concept_id") is not None, (
        "splice_subtree should assign concept_id to nodes without one"
    )


def test_delete_preserves_sibling_concept_id():
    """Deleting a node does not alter concept_ids on sibling nodes."""
    tree = _sample_okf_tree()
    b_id = tree["structure"][1]["node_id"]  # node B
    delete_node(tree, b_id)
    # Node A (sibling of B) must still have its concept_id.
    a_node = tree["structure"][0]
    assert a_node["concept_id"] == "section/a"
    # Children of A must also retain their concept_ids.
    a1 = a_node["nodes"][0]
    a2 = a_node["nodes"][1]
    assert a1["concept_id"] == "section/a/a-1"
    assert a2["concept_id"] == "section/a/a-2"
