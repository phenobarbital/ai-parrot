# TASK-5259: Validation rules, SHACL shapes and content diff (`turtle.py`, part 2)

**Feature**: FEAT-824 — Ontology backend: PostgreSQL OntologyStore + SurrealDB programme
**Spec**: `sdd/specs/ontology-backend.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5258, TASK-5257
**Assigned-to**: unassigned

---

## Context

Spec Module 5 (part 2) and spec §2 "Parrot validation rules". A publication is rejected — and
nothing is written — when the candidate fails SHACL or any parrot rule. `diff_content` computes the
row-level difference the publisher writes and the publication outbox carries. Adds two functions
to `turtle.py` (created by TASK-5258) and the bundled shapes file.

**Environment precondition:** `pyshacl` and `rdflib` installed in the shared venv (host step after
TASK-5252). If `python -c "import pyshacl"` fails, stop and report.

---

## Scope

- Append to `turtle.py`: `validate_content(content, *, previous_iris=frozenset(), shapes=None)` and
  `diff_content(base, candidate)` (spec lines 780–791).
- Issue codes (spec §2; `ValidationIssue.code`):
  - `IRI_OUTSIDE_BASE` — a defined subject (concept) not starting with `content.base_iri`;
  - `IRI_REMOVED` — an IRI in `previous_iris` absent from `content.concepts` (deprecation keeps it present);
  - `HIERARCHY_CYCLE` — `find_cycle` non-None for any of the four families (one issue per family, path in message);
  - `MISSING_PREF_LABEL` — a concept of kind `class` or `skos_concept` with no `pref` label;
  - `SHACL` — one issue per SHACL result (focus node → `subject`);
  - (`BLANK_NODE_UNSUPPORTED` is raised by `parse_turtle`, not here.)
- `shapes/parrot-core.shacl.ttl` — minimal shapes: `skos:Concept` must have ≥ 1 `skos:prefLabel`
  literal; `skos:broader` / `rdfs:subClassOf` objects must be IRIs; `owl:deprecated` is `xsd:boolean`.
  Extra caller shapes (`shapes` bytes) are validated **in addition**.
- `diff_content`: `added_iris` (in candidate, not base), `changed_iris` (present in both with any
  differing attribute, label set or statement set), `deprecated` (newly deprecated → `replaced_by`),
  `relations_added` / `relations_closed` (asserted relations only); `base=None` → everything added.
  "Nothing to publish" = all fields empty/zero.
- `test_validation.py` with one failing inline-Turtle fixture per rule code + diff tests.

**NOT in scope**: deciding `previous_iris` (the publisher passes the base version's IRIs); writing rows.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/turtle.py` | MODIFY | add `validate_content`, `diff_content` |
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/shapes/parrot-core.shacl.ttl` | CREATE | bundled shapes |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_validation.py` | CREATE | per-code tests + diff |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.ontology.vocabulary.closure import FAMILY_PREDICATES, find_cycle   # TASK-5257
from parrot.knowledge.ontology.vocabulary.contracts import PublishDiff, ValidationIssue  # TASK-5253
import pyshacl   # inside validate_content only
from importlib import resources   # read the bundled shapes file
```

### Existing Signatures to Use
```python
# TASK-5258 — turtle.py
def parse_turtle(turtle: bytes, *, base_iri: str, default_lang: str) -> OntologyContent
def _to_graph(content: OntologyContent) -> rdflib.Graph     # asserted graph — feed it to pyshacl
# TASK-5257 — closure.py
def find_cycle(relations: Sequence[ParsedRelation], family: str) -> list[str] | None
FAMILY_PREDICATES: dict[str, str]   # keys: subclass, subproperty, broader, partof
```

### Does NOT Exist
- ~~`shapes/` package data declared in pyproject~~ — check how `packages/ai-parrot/pyproject.toml`
  includes non-Python package files (setuptools `package-data` / include patterns) and confirm a
  `.ttl` under `parrot/knowledge/ontology/vocabulary/shapes/` ships in the wheel; if it would not,
  note it in the Completion Note (do not edit pyproject here — TASK-5252 owns it).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/turtle.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/shapes/parrot-core.shacl.ttl", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_validation.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Write the shapes file — *why*: SHACL is one of the two validation layers (spec §2).
2. Append `validate_content` — collect **every** issue, never stop at the first (spec signature docstring).
3. Append `diff_content`.
4. Tests.

### `.../vocabulary/turtle.py` (MODIFY)
```python
# occurrences: 1 (verified at implementation: grep -c '^def _to_graph' turtle.py)
# AFTER — append at end of file, below `def _to_graph(` and its body (TASK-5258)

def validate_content(content: OntologyContent, *, previous_iris: frozenset[str] = frozenset(),
                     shapes: bytes | None = None) -> list[ValidationIssue]:
    """Bundled SHACL shapes, optional extra shapes, and the parrot rules. Empty list means valid."""
    from parrot.knowledge.ontology.vocabulary.closure import FAMILY_PREDICATES, find_cycle

    issues: list[ValidationIssue] = []
    # FILL IN: IRI_OUTSIDE_BASE, IRI_REMOVED, HIERARCHY_CYCLE (all four families), MISSING_PREF_LABEL;
    #          then SHACL: pyshacl.validate(_to_graph(content), shacl_graph=bundled [+ extra], inference="none")
    #          → one SHACL issue per result; return issues sorted by (code, subject or "").
    return issues


def diff_content(base: OntologyContent | None, candidate: OntologyContent) -> PublishDiff:
    """Row-level difference; an all-empty diff means 'nothing to publish'."""
    # FILL IN: per Scope; compare concepts by iri (attributes + labels + statements per subject);
    #          relations as sets of (s, p, o) with inferred=False; sorted lists.
    raise NotImplementedError
```
Add `PublishDiff` to the existing `contracts` import line of `turtle.py`.

### `.../vocabulary/test_validation.py` (CREATE) — required cases
```python
BASE = "https://ontology.parrot.dev/t/"
PREFIXES = "@prefix ex: <https://ontology.parrot.dev/t/> . @prefix owl: <http://www.w3.org/2002/07/owl#> . ..."

def test_valid_golden_has_no_issues(golden_v1, golden_base_iri): ...
def test_rule_iri_outside_base(): ...
def test_rule_iri_removed(): ...                  # previous_iris has ex:Gone, content lacks it
def test_rule_iri_deprecated_is_not_removed(): ...  # ex:Gone present with owl:deprecated true → no IRI_REMOVED
def test_rule_hierarchy_cycle(): ...              # A ⊂ B ⊂ A
def test_rule_missing_pref_label(): ...
def test_rule_shacl_extra_shapes(): ...           # caller shape violated → SHACL issue
def test_rules_report_every_issue(): ...          # one document with two violations → two issues
def test_diff_v1_v2(golden_v1, golden_v2, golden_base_iri): ...   # deprecated map, changed and added IRIs, relations_closed ≥ 1
def test_diff_identical_is_empty(golden_v1, golden_base_iri): ...
```

### FILL IN checklist
- [ ] shapes file.
- [ ] `validate_content`, `diff_content` bodies.
- [ ] test bodies (one inline failing fixture per code).

---

## Acceptance Criteria

- [ ] Each rule code of spec §2 is produced by a minimal failing document and only by it.
- [ ] Every issue in a document is reported, not just the first.
- [ ] `diff_content(v1, v1)` is empty; `diff_content(v1, v2)` reports the v2 changes listed in
      TASK-5255's Completion Note.
- [ ] `ruff check` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_validation.py -q`

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5258 and TASK-5257 are `done`; check the pyshacl precondition.
2. Mark `in-progress`; implement; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
3. Commit only the listed files; close with `parrot sdd task close TASK-5259 ontology-backend verified`.

---

## Completion Note

Seat: gpt-5.6-terra · Backend: codex · Attempts: 1 · Duration: 282s. Merge-tier validation green (28 passed).

**Completed by**: sdd-worker (coder: gpt-5.6-terra)
**Date**: 2026-11-07
**Notes**:

**Deviations from spec**: none
