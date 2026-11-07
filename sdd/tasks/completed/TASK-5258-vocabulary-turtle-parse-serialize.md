# TASK-5258: Turtle ⇄ OntologyContent, canonical form and checksum (`turtle.py`, part 1)

**Feature**: FEAT-824 — Ontology backend: PostgreSQL OntologyStore + SurrealDB programme
**Spec**: `sdd/specs/ontology-backend.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5252, TASK-5255, TASK-5257
**Assigned-to**: unassigned

---

## Context

Spec Module 5 (Turtle half, part 1). Maps RDF Turtle to the row model (`OntologyContent`) and
back, defines the canonical form (sorted N-Triples of the **asserted** graph) and its SHA-256
checksum — the equality `checksum(export(as_of=v)) == version.checksum` is the temporal-fidelity
gate. Validation and diff are TASK-5259 (same file, later).

**Environment precondition:** `rdflib` must be installed in the shared venv (host step requested
by TASK-5252's Completion Note). Check `python -c "import rdflib"`; if it fails, stop and report —
do not install into the shared environment from a worktree.

---

## Scope

- `vocabulary/turtle.py` with `PARROT_NS` (re-exported from `closure.py`), `parse_turtle`,
  `canonical_ntriples`, `content_checksum`, `serialize`, `statement_object_hash` (spec lines 772–793).
- Mapping rules (spec line 776–779):
  - `rdf:type` of a subject decides `kind`: `owl:Class`/`rdfs:Class` → `class`; `owl:ObjectProperty`
    → `object_property`; `owl:DatatypeProperty` → `datatype_property`; `owl:NamedIndividual` (or a
    type that is a class defined in the graph) → `individual`; `skos:ConceptScheme` →
    `concept_scheme`; `skos:Concept` → `skos_concept`.
  - **Defined subjects** = subjects with one of those types; only they become `ParsedConcept`s.
  - `skos:prefLabel`/`rdfs:label` → label `pref` (rdfs:label only when no skos:prefLabel in that
    lang); `skos:altLabel` → `alt`; `skos:hiddenLabel` → `hidden`. Literal without lang →
    `default_lang`. `ParsedConcept.pref_label` = the pref label in `default_lang` (else first sorted).
  - `skos:definition` → `definition`; `owl:deprecated true` → `deprecated`; `dcterms:isReplacedBy`
    → `replaced_by`. These triples are attributes, not statements.
  - Any other triple with an IRI object → `ParsedRelation` (including `rdf:type` to non-kind
    classes, `rdfs:subClassOf`, `owl:inverseOf`, `skos:inScheme`); literal objects → `ParsedStatement`
    with object `{"value", "datatype", "lang"}` (absent keys omitted).
  - Any blank node (subject or object) → `OntologyValidationError([ValidationIssue(code="BLANK_NODE_UNSUPPORTED", …)])`.
- `canonical_ntriples` rebuilds an rdflib graph from the content (labels, attributes,
  `rdf:type` for each kind, relations with `inferred=False`, statements), serialises N-Triples,
  sorts lines, joins with `\n`, UTF-8.
- `serialize(content, "turtle"|"jsonld")`.
- `test_turtle.py`.

**NOT in scope**: `validate_content`, `diff_content`, SHACL shapes (TASK-5259).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/turtle.py` | CREATE | parse / canonical / serialize |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_turtle.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.ontology.vocabulary.contracts import (   # TASK-5253
    OntologyContent, ParsedConcept, ParsedLabel, ParsedRelation, ParsedStatement, ValidationIssue)
from parrot.knowledge.ontology.vocabulary.exceptions import OntologyValidationError   # TASK-5253
from parrot.knowledge.ontology.vocabulary.closure import PARROT_NS, OWL, RDFS, SKOS   # TASK-5257
import rdflib   # declared by TASK-5252's extra; import INSIDE functions (process-pool + import ceilings)
```

### Existing Signatures to Use
```python
# TASK-5255 conftest: golden_v1 / golden_v2 / golden_v3 -> bytes ; golden_base_iri -> str
# TASK-5253: OntologyValidationError(issues: Sequence[ValidationIssue]); .issues
```

### Does NOT Exist
- ~~Turtle/SKOS/IRI handling anywhere in `parrot.knowledge.ontology`~~ — this is the first.
- ~~`rdflib.Graph` crossing the process boundary~~ — only Pydantic models leave these functions.
- ~~`validate_content` / `diff_content` in this task~~ — TASK-5259.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/turtle.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_turtle.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Confirm `import rdflib` works (precondition).
2. Write `parse_turtle` per the mapping rules — *why*: the row model is the store's source of truth.
3. Write `statement_object_hash`, `canonical_ntriples`, `content_checksum`, `serialize`.
4. Tests, including parse → canonical → parse round trip on the golden files.

### `.../vocabulary/turtle.py` (CREATE)
```python
"""Turtle ⇄ OntologyContent mapping, canonical form and checksum (FEAT-824).

Pure, synchronous functions; rdflib is imported inside them.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Mapping

from parrot.knowledge.ontology.vocabulary.closure import OWL, PARROT_NS, RDFS, SKOS  # noqa: F401 — PARROT_NS re-exported
from parrot.knowledge.ontology.vocabulary.contracts import (
    OntologyContent, ParsedConcept, ParsedLabel, ParsedRelation, ParsedStatement, ValidationIssue,
)
from parrot.knowledge.ontology.vocabulary.exceptions import OntologyValidationError

DCTERMS = "http://purl.org/dc/terms/"
KIND_BY_TYPE: dict[str, str] = {
    OWL + "Class": "class", RDFS + "Class": "class",
    OWL + "ObjectProperty": "object_property", OWL + "DatatypeProperty": "datatype_property",
    OWL + "NamedIndividual": "individual",
    SKOS + "ConceptScheme": "concept_scheme", SKOS + "Concept": "skos_concept",
}


def parse_turtle(turtle: bytes, *, base_iri: str, default_lang: str) -> OntologyContent:
    """Parse Turtle into rows (mapping rules in TASK-5258 Scope).

    Raises:
        OntologyValidationError: BLANK_NODE_UNSUPPORTED on any blank node; SYNTAX on a parse error.
    """
    import rdflib

    # FILL IN: Graph().parse(data=turtle, format="turtle"); blank-node scan; kinds; labels;
    #          attributes; relations; statements; deterministic ordering of every list.
    raise NotImplementedError


def statement_object_hash(obj: Mapping[str, Any]) -> str:
    """sha256 of the canonical JSON of a statement object (value, datatype, lang | iri)."""
    return hashlib.sha256(json.dumps(dict(obj), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def canonical_ntriples(content: OntologyContent) -> bytes:
    """Sorted N-Triples of the asserted graph (inferred relations excluded)."""
    # FILL IN: build graph via _to_graph(content); serialize(format="nt"); split lines, drop blanks,
    #          sort, "\n".join + "\n"; encode utf-8.
    raise NotImplementedError


def content_checksum(content: OntologyContent) -> str:
    """sha256 hex digest of canonical_ntriples(content)."""
    return hashlib.sha256(canonical_ntriples(content)).hexdigest()


def serialize(content: OntologyContent, fmt: Literal["turtle", "jsonld"]) -> bytes:
    """Serialise the asserted graph."""
    # FILL IN: _to_graph(content).serialize(format="turtle" | "json-ld") → bytes; bind common prefixes.
    raise NotImplementedError


def _to_graph(content: OntologyContent) -> "rdflib.Graph":
    """Rebuild the asserted graph from rows (inverse of parse_turtle)."""
    # FILL IN: rdf:type per concept kind (first matching IRI of KIND_BY_TYPE for the kind), labels with
    #          lang, definition/deprecated/isReplacedBy, relations with inferred=False, statements.
    raise NotImplementedError
```
**Why this shape**: spec Module 5 signatures; `_to_graph` is the single inverse used by both the
canonical form and `serialize`, so export and checksum can never disagree.

### `.../vocabulary/test_turtle.py` (CREATE) — required cases
```python
def test_parse_kinds_labels_relations(golden_v1, golden_base_iri): ...   # expected kinds, pref/alt labels, a subClassOf relation, a datatyped statement
def test_blank_node_rejected(): ...              # "_:b a owl:Class ." → OntologyValidationError, code BLANK_NODE_UNSUPPORTED
def test_checksum_ignores_formatting(golden_base_iri): ...  # same graph, two formattings / prefix choices → same checksum
def test_roundtrip_preserves_checksum(golden_v1, golden_base_iri): ...   # parse(serialize(parse(v1))) has the same checksum
def test_statement_object_hash_distinguishes_lang(): ...   # {"value":"a","lang":"es"} ≠ {"value":"a","lang":"en"}
def test_inferred_relations_not_in_canonical(golden_base_iri): ...  # add an inferred relation → canonical bytes unchanged
```

### FILL IN checklist
- [ ] `parse_turtle`, `canonical_ntriples`, `serialize`, `_to_graph` bodies.
- [ ] test bodies.

---

## Acceptance Criteria

- [ ] Golden v1 parses into the expected kinds, labels, relations and statements.
- [ ] A blank node is rejected with `BLANK_NODE_UNSUPPORTED`.
- [ ] Two formattings of one graph share a checksum; parse → serialize → parse preserves it.
- [ ] `ruff check` passes; rdflib imported only inside functions.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_turtle.py -q`

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5252, TASK-5255 and TASK-5257 are `done`; check the rdflib precondition.
2. Mark `in-progress`; implement; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
3. Commit only the listed files; close with `parrot sdd task close TASK-5258 ontology-backend verified`.

---

## Completion Note

Seat: gpt-5.6-sol · Backend: codex · Attempts: 1 · Duration: 263s. Merge-tier validation green. Orchestrator lint fix: rdflib TYPE_CHECKING import (F821) in turtle.py.

**Completed by**: sdd-worker (coder: gpt-5.6-sol)
**Date**: 2026-11-07
**Notes**:

**Deviations from spec**: none
