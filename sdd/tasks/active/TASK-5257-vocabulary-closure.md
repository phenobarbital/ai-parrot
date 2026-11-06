# TASK-5257: Hierarchy closure, cycle detection and inverse materialisation (`closure.py`)

**Feature**: FEAT-824 — Ontology backend: PostgreSQL OntologyStore + SurrealDB programme
**Spec**: `sdd/specs/ontology-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5253
**Assigned-to**: unassigned

---

## Context

Spec Module 5 (closure half). Pure, synchronous, picklable functions: the transitive closure per
hierarchy family over a DAG (with a depth-0 reflexive row for every IRI), cycle detection for the
`HIERARCHY_CYCLE` rule, and the relations implied by `owl:inverseOf` (marked `inferred=True` so
export leaves them out). Runs in the publisher's process pool — no I/O, no event loop, no rdflib.

---

## Scope

- `vocabulary/closure.py` with `PARROT_NS`, `RDFS`, `SKOS`, `OWL` namespace constants,
  `FAMILY_PREDICATES`, `materialise_inverses`, `find_cycle`, `build_closure` (spec lines 795–803).
- `PARROT_NS = "urn:parrot:core:"` is defined **here** and re-exported by `turtle.py` (TASK-5258),
  so the closure has no dependency on the Turtle module.
- `test_closure.py`.

**NOT in scope**: parsing Turtle (TASK-5258); validation rules (TASK-5259) — they call `find_cycle`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/closure.py` | CREATE | closure functions |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_closure.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.ontology.vocabulary.contracts import ClosureRow, ParsedRelation   # TASK-5253
```

### Existing Signatures to Use
```python
# TASK-5253 — contracts.py
class ParsedRelation(BaseModel): subject_iri: str; predicate: str; object_iri: str; inferred: bool = False
class ClosureRow(BaseModel): family: ClosureFamily; ancestor_iri: str; descendant_iri: str; depth: int
ClosureFamily = Literal["subclass", "subproperty", "broader", "partof"]
```

### Does NOT Exist
- ~~`parrot.knowledge.ontology.exceptions.CycleError` for this purpose~~ — it exists (exceptions.py:82)
  but belongs to the YAML ontology merger; `find_cycle` returns the cycle, it does not raise.
- ~~`networkx`~~ — do not add a graph library; plain dict/BFS.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/closure.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_closure.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Edge direction: for `s rdfs:subClassOf o`, `o` is the **ancestor** of `s`. `skos:broader` same
  (`s skos:broader o` → `o` ancestor). `partof`: `s parrot:partOf o` → `o` ancestor.
- With multiple paths, `depth` is the **shortest** path length.
- `build_closure` includes a depth-0 row `(family, iri, iri, 0)` for **every** IRI in `iris`, for
  every family — `expand` must always return its input (spec §2 "Read contract").
- Inferred inverse relations: for `p owl:inverseOf q` (either direction declared), every asserted
  `s p o` implies `o q s`; skip ones already asserted; never feed inferred rows back into inverse
  computation (no fixpoint over inferred).
- Deterministic output order (sort) — closure rows are compared across backends.

---

## Implementation Blueprint

### Steps (in order)
1. Constants and `FAMILY_PREDICATES` — *why*: shared by turtle, validation and publisher.
2. `materialise_inverses`, `find_cycle`, `build_closure` — *why*: spec Module 5.
3. Tests.

### `.../vocabulary/closure.py` (CREATE)
```python
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
    """Relations implied by owl:inverseOf, each with inferred=True (asserted ones are not repeated)."""
    # FILL IN: collect inverse pairs from relations whose predicate is OWL_INVERSE_OF (symmetric);
    #          for each asserted (inferred=False) s p o with p in the pairs, emit o q s unless asserted;
    #          return sorted by (subject, predicate, object).
    raise NotImplementedError


def find_cycle(relations: Sequence[ParsedRelation], family: str) -> list[str] | None:
    """One cycle in a hierarchy family as a list of IRIs (first IRI repeated at the end), or None."""
    # FILL IN: iterative DFS with white/grey/black colouring over edges whose predicate is
    #          FAMILY_PREDICATES[family]; deterministic start order (sorted IRIs).
    raise NotImplementedError


def build_closure(relations: Sequence[ParsedRelation], iris: Iterable[str]) -> list[ClosureRow]:
    """Transitive closure per family over a DAG, including the depth-0 row of every IRI.

    Precondition: no family has a cycle (validation runs first).
    """
    # FILL IN: per family, child→parents adjacency; BFS upward from each node giving shortest depth;
    #          nodes = iris ∪ every IRI appearing in that family's edges; add depth-0 rows;
    #          return rows sorted by (family, descendant_iri, ancestor_iri).
    raise NotImplementedError
```

### `.../vocabulary/test_closure.py` (CREATE) — required cases
```python
def test_closure_dag_and_reflexive(): ...        # D ⊂ B, D ⊂ C, B ⊂ A, C ⊂ A: D→A depth 2 once; every IRI has depth 0
def test_closure_families_are_separate(): ...    # a broader edge never appears under "subclass"
def test_closure_includes_out_of_set_ancestor(): ...  # parent IRI not in `iris` still appears as ancestor
def test_find_cycle_detects_and_returns_path(): ...
def test_find_cycle_none_on_dag(): ...
def test_inverse_materialised_once(): ...        # p inverseOf q; s p o → o q s inferred=True; asserted o q s not duplicated
```

### FILL IN checklist
- [ ] three function bodies.
- [ ] six test bodies.

---

## Acceptance Criteria

- [ ] `build_closure` is reflexive and correct on a DAG with multiple inheritance (shortest depth).
- [ ] `find_cycle` finds a cycle in each family and returns `None` on a DAG.
- [ ] Inferred inverses carry `inferred=True`.
- [ ] Module imports no rdflib/asyncpg/numpy; `ruff check` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_closure.py -q`

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5253 is `done`.
2. Mark `in-progress`; implement; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
3. Commit only the listed files; close with `parrot sdd task close TASK-5257 ontology-backend verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: `PARROT_NS` is defined in `closure.py` and re-exported by `turtle.py`
(spec Module 5 places it in `turtle.py`) so the closure has no dependency on the Turtle module.
