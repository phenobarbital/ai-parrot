"""Unit tests for vocabulary closure (FEAT-824)."""

import pickle

from parrot.knowledge.ontology.vocabulary.closure import (
    FAMILY_PREDICATES,
    OWL_INVERSE_OF,
    build_closure,
    find_cycle,
    materialise_inverses,
)
from parrot.knowledge.ontology.vocabulary.contracts import ParsedRelation

SUB = FAMILY_PREDICATES["subclass"]
BROADER = FAMILY_PREDICATES["broader"]


def _rel(s: str, p: str, o: str, inferred: bool = False) -> ParsedRelation:
    return ParsedRelation(subject_iri=s, predicate=p, object_iri=o, inferred=inferred)


def _depths(rows, family):
    return {(r.descendant_iri, r.ancestor_iri): r.depth for r in rows if r.family == family}


def test_closure_dag_and_reflexive():
    rels = [_rel("D", SUB, "B"), _rel("D", SUB, "C"), _rel("B", SUB, "A"), _rel("C", SUB, "A")]
    rows = build_closure(rels, ["A", "B", "C", "D", "Z"])
    d = _depths(rows, "subclass")
    assert d[("D", "A")] == 2
    assert sum(1 for r in rows if r.family == "subclass" and (r.descendant_iri, r.ancestor_iri) == ("D", "A")) == 1
    for iri in "ABCDZ":
        assert d[(iri, iri)] == 0
        for fam in FAMILY_PREDICATES:
            assert _depths(rows, fam)[(iri, iri)] == 0
    assert pickle.loads(pickle.dumps(rows)) == rows


def test_closure_shortest_depth():
    rels = [_rel("D", SUB, "A"), _rel("D", SUB, "B"), _rel("B", SUB, "A")]
    assert _depths(build_closure(rels, ["A", "B", "D"]), "subclass")[("D", "A")] == 1


def test_closure_families_are_separate():
    rows = build_closure([_rel("X", BROADER, "Y")], ["X", "Y"])
    assert ("X", "Y") in _depths(rows, "broader")
    assert ("X", "Y") not in _depths(rows, "subclass")


def test_closure_includes_out_of_set_ancestor():
    rows = build_closure([_rel("X", SUB, "Out")], ["X"])
    assert _depths(rows, "subclass")[("X", "Out")] == 1


def test_find_cycle_detects_and_returns_path():
    for family, pred in FAMILY_PREDICATES.items():
        rels = [_rel("A", pred, "B"), _rel("B", pred, "C"), _rel("C", pred, "A")]
        cycle = find_cycle(rels, family)
        assert cycle is not None
        assert cycle[0] == cycle[-1]
        assert set(cycle) == {"A", "B", "C"}


def test_find_cycle_none_on_dag():
    rels = [_rel("D", SUB, "B"), _rel("D", SUB, "C"), _rel("B", SUB, "A"), _rel("C", SUB, "A")]
    assert find_cycle(rels, "subclass") is None
    assert find_cycle([_rel("A", SUB, "A")], "subclass") == ["A", "A"]


def test_inverse_materialised_once():
    rels = [
        _rel("q", OWL_INVERSE_OF, "p"),
        _rel("s", "p", "o"),
        _rel("s2", "p", "o2"),
        _rel("o2", "q", "s2"),
    ]
    out = materialise_inverses(rels)
    assert [(r.subject_iri, r.predicate, r.object_iri, r.inferred) for r in out] == [("o", "q", "s", True)]
