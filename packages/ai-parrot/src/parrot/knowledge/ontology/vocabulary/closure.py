"""Hierarchy closure, cycle detection and owl:inverseOf materialisation (FEAT-824).

Pure functions over picklable models; safe to run in a process pool.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Iterable, Sequence

from parrot.knowledge.ontology.vocabulary.contracts import ClosureRow, ParsedRelation

PARROT_NS = "urn:parrot:core:"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
OWL = "http://www.w3.org/2002/07/owl#"

FAMILY_PREDICATES: dict[str, str] = {
    "subclass": RDFS + "subClassOf",
    "subproperty": RDFS + "subPropertyOf",
    "broader": SKOS + "broader",
    "partof": PARROT_NS + "partOf",
}
OWL_INVERSE_OF = OWL + "inverseOf"


def materialise_inverses(relations: Sequence[ParsedRelation]) -> list[ParsedRelation]:
    """Relations implied by owl:inverseOf, each with inferred=True.

    Args:
        relations: Parsed relations; only asserted (``inferred=False``) ones are considered.

    Returns:
        Inferred relations sorted by (subject, predicate, object); already asserted ones are
        not repeated.
    """
    asserted = [r for r in relations if not r.inferred]
    inverses: dict[str, set[str]] = defaultdict(set)
    for rel in asserted:
        if rel.predicate == OWL_INVERSE_OF:
            inverses[rel.subject_iri].add(rel.object_iri)
            inverses[rel.object_iri].add(rel.subject_iri)
    existing = {(r.subject_iri, r.predicate, r.object_iri) for r in relations}
    out: dict[tuple[str, str, str], ParsedRelation] = {}
    for rel in asserted:
        if rel.predicate == OWL_INVERSE_OF:
            continue
        for inverse in inverses.get(rel.predicate, ()):
            key = (rel.object_iri, inverse, rel.subject_iri)
            if key in existing or key in out:
                continue
            out[key] = ParsedRelation(subject_iri=key[0], predicate=key[1], object_iri=key[2], inferred=True)
    return [out[k] for k in sorted(out)]


def _adjacency(relations: Sequence[ParsedRelation], family: str) -> dict[str, set[str]]:
    """Child -> parents adjacency for one family."""
    predicate = FAMILY_PREDICATES[family]
    adj: dict[str, set[str]] = defaultdict(set)
    for rel in relations:
        if rel.predicate == predicate:
            adj[rel.subject_iri].add(rel.object_iri)
    return adj


def find_cycle(relations: Sequence[ParsedRelation], family: str) -> list[str] | None:
    """One cycle in a hierarchy family as a list of IRIs (first IRI repeated at the end), or None."""
    adj = _adjacency(relations, family)
    nodes = sorted(set(adj) | {p for ps in adj.values() for p in ps})
    colour: dict[str, int] = {}  # absent = white, 1 = grey, 2 = black
    for start in nodes:
        if colour.get(start):
            continue
        path: list[str] = [start]
        colour[start] = 1
        stack = [iter(sorted(adj.get(start, ())))]
        while stack:
            nxt = next(stack[-1], None)
            if nxt is None:
                colour[path.pop()] = 2
                stack.pop()
                continue
            state = colour.get(nxt, 0)
            if state == 1:
                return path[path.index(nxt) :] + [nxt]
            if state == 0:
                colour[nxt] = 1
                path.append(nxt)
                stack.append(iter(sorted(adj.get(nxt, ()))))
    return None


def build_closure(relations: Sequence[ParsedRelation], iris: Iterable[str]) -> list[ClosureRow]:
    """Transitive closure per family over a DAG, including the depth-0 row of every IRI.

    Precondition: no family has a cycle (validation runs first).
    """
    iri_set = set(iris)
    rows: list[ClosureRow] = []
    for family in FAMILY_PREDICATES:
        adj = _adjacency(relations, family)
        nodes = iri_set | set(adj) | {p for ps in adj.values() for p in ps}
        for node in nodes:
            depths = {node: 0}
            queue = deque([node])
            while queue:
                cur = queue.popleft()
                for parent in adj.get(cur, ()):
                    if parent not in depths:
                        depths[parent] = depths[cur] + 1
                        queue.append(parent)
            for ancestor, depth in depths.items():
                rows.append(
                    ClosureRow(family=family, ancestor_iri=ancestor, descendant_iri=node, depth=depth)  # type: ignore[arg-type]
                )
    rows.sort(key=lambda r: (r.family, r.descendant_iri, r.ancestor_iri))
    return rows
