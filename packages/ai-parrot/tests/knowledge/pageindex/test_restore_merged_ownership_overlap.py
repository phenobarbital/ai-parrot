"""Regression: restoring merged ownership must never overlap a sibling (overlap seq N owned by A and B)."""
from parrot.knowledge.pageindex.toolkit import _original_spans, _restore_roots


def _leaf(concept_id: str, span: list[int], aliases: list[str] | None = None) -> dict:
    return {"concept_id": concept_id, "span": list(span), "owned": [list(span)], "aliases": aliases or []}


def _owners(nodes: list[dict]) -> dict[int, str]:
    owners: dict[int, str] = {}
    for node in nodes:
        for start, end in node["owned"]:
            for seq in range(start, end):
                assert seq not in owners, f"overlap seq {seq} owned by {owners[seq]} and {node['concept_id']}"
                owners[seq] = node["concept_id"]
    return owners


def test_alias_hull_crossing_sibling_is_not_restored() -> None:
    a = _leaf("a", [0, 10], aliases=["c"])
    b = _leaf("b", [10, 20])
    roots = [a, b]
    _restore_roots(roots, {"a": [0, 10], "b": [10, 20], "c": [20, 30]})
    assert a["span"] == [0, 10]
    _owners(roots)


def test_adjacent_alias_is_restored() -> None:
    a = _leaf("a", [0, 10], aliases=["c"])
    b = _leaf("b", [20, 30])
    roots = [a, b]
    _restore_roots(roots, {"c": [10, 20]})
    assert a["span"] == [0, 20]
    assert _owners(roots)[15] == "a"


def test_duplicate_concept_ids_are_ambiguous() -> None:
    nodes = [{"concept_id": "x", "span": [0, 5]}, {"concept_id": "x", "span": [3, 9]}, {"concept_id": "y", "span": [9, 12]}]
    assert _original_spans(nodes) == {"y": [9, 12]}


def test_nested_child_cannot_cross_parent_sibling() -> None:
    child = _leaf("p/c", [2, 6], aliases=["q"])
    parent = {"concept_id": "p", "span": [0, 8], "owned": [[0, 2], [6, 8]], "nodes": [child], "aliases": []}
    q = _leaf("q", [8, 14])
    roots = [parent, q]
    _restore_roots(roots, {"q": [8, 14]})
    assert child["span"] == [2, 6]
    _owners([parent, child, q])
