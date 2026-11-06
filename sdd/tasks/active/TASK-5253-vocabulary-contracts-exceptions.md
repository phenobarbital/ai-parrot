# TASK-5253: Vocabulary data models, Protocols and exceptions

**Feature**: FEAT-824 — Ontology backend: PostgreSQL OntologyStore + SurrealDB programme
**Spec**: `sdd/specs/ontology-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec Module 3, first half. Creates the `parrot.knowledge.ontology.vocabulary` package's types:
the Pydantic models of spec §2 "Data Models", the `OntologyStore` and `OntologyPublisher`
Protocols, `EmbedFn`, and the `VocabularyError` hierarchy. Every later Phase 2 task imports
these. The package root `__init__.py`, settings and registry are TASK-5254.

---

## Scope

- `vocabulary/exceptions.py` — `VocabularyError(OntologyError)`, `OntologyNotFound`,
  `OntologyVersionNotFound`, `OntologyValidationError(issues)`, `PublishConflict`.
- `vocabulary/contracts.py` — type aliases `ConceptKind`, `ClosureFamily`, `LabelKind`; models
  `ConceptRef`, `Resolution`, `StoreStatus`, `ParsedConcept`, `ParsedLabel`, `ParsedRelation`,
  `ParsedStatement`, `OntologyContent`, `ClosureRow`, `VersionContent`, `PublishDiff`,
  `PublishResult`, `ValidationIssue`; `EmbedFn`; Protocols `OntologyStore`, `OntologyPublisher`.
- `packages/ai-parrot/tests/knowledge/ontology/vocabulary/__init__.py` (empty) and
  `test_vocabulary_contracts.py`.

**NOT in scope**: `vocabulary/__init__.py` (TASK-5254 writes it — until then the package is a
namespace-free directory with no `__init__.py`; see Steps), settings, registry, any I/O.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/exceptions.py` | CREATE | exception hierarchy |
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/contracts.py` | CREATE | models + Protocols |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/__init__.py` | CREATE | empty test package marker |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_contracts.py` | CREATE | model + Protocol tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.ontology.exceptions import OntologyError   # verified: parrot/knowledge/ontology/exceptions.py:4
from pydantic import BaseModel, Field                             # pydantic v2, core dependency
```

### Existing Signatures to Use
```python
# parrot/knowledge/ontology/exceptions.py:4
class OntologyError(Exception): ...
```

### Does NOT Exist
- ~~`parrot.knowledge.ontology.vocabulary`~~ — created by this task and TASK-5254.
- ~~`OntologyStore` / `OntologyPublisher` / `resolve()` / `expand()` / `canonical()` anywhere~~ —
  `parrot/knowledge/ontology/contracts.py` holds only the instance-graph contracts; do not edit it.
- ~~`parrot.ontology`~~, ~~`parrot.knowledge.stores`~~ — never use these package names.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/exceptions.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/contracts.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_contracts.py", "action": "CREATE"}
  ],
  "contract_symbols": ["sym:packages/ai-parrot/src/parrot/knowledge/ontology/exceptions.py#OntologyError"]
}
```

---

## Implementation Notes

### Key Constraints
- `contracts.py` imports only stdlib + pydantic — never `asyncpg`, `rdflib`, `numpy` (import
  ceilings, spec §7). `exceptions.py` imports `ValidationIssue` from `contracts.py`; `contracts.py`
  must not import `exceptions.py` (no cycle).
- Models must be picklable (they cross the publisher's process pool): plain fields only.
- Signatures are fixed by spec Module 3 (lines 659–701) and field lists by spec §2 (lines 352–444):
  copy them verbatim, adding Google-style docstrings.
- Python package import needs `vocabulary/__init__.py`; to let this task's test import
  `parrot.knowledge.ontology.vocabulary.contracts` before TASK-5254 lands, rely on PEP 420
  implicit namespace resolution (no `__init__.py`) — do **not** create `__init__.py` here.

---

## Implementation Blueprint

### Steps (in order)
1. Write `contracts.py`: aliases + models copied from spec §2 lines 352–444, then `EmbedFn` and the
   two Protocols from spec lines 660–701 — *why*: fixed contract, every later task imports it.
2. Write `exceptions.py` — *why*: typed errors let callers degrade to vector-only (spec §7).
3. Write the tests; run ruff and pytest.

### `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/contracts.py` (CREATE)
```python
"""Data models and read/write contracts of the ontology vocabulary store (FEAT-824).

Pure types: no driver imports, so importing this module is cheap and the models are picklable.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Literal, Protocol, Sequence, runtime_checkable

from pydantic import BaseModel, Field

ConceptKind = Literal["class", "object_property", "datatype_property", "individual", "concept_scheme", "skos_concept"]
ClosureFamily = Literal["subclass", "subproperty", "broader", "partof"]
LabelKind = Literal["pref", "alt", "hidden"]


class ConceptRef(BaseModel):
    """A concept as read at one published version."""

    iri: str
    ontology_id: str
    kind: ConceptKind
    pref_label: str | None = None
    definition: str | None = None
    deprecated: bool = False
    replaced_by: str | None = None
    version: int


# FILL IN: Resolution, StoreStatus, ParsedConcept, ParsedLabel, ParsedRelation, ParsedStatement,
#          OntologyContent, ClosureRow, VersionContent, PublishDiff, PublishResult, ValidationIssue —
#          fields verbatim from spec §2 lines 368-444, each with a one-line docstring.

EmbedFn = Callable[[Sequence[str]], Awaitable[list[list[float]]]]


@runtime_checkable
class OntologyStore(Protocol):
    """Read contract of the ontology vocabulary. Every call reads one published version."""

    async def version(self, ontology_id: str) -> int:
        """Current published version; 0 when registered but never published. Raises OntologyNotFound."""
        ...

    # FILL IN: status, get, resolve, expand, neighbors, canonical, export, close —
    #          signatures and docstrings verbatim from spec lines 668-692.


@runtime_checkable
class OntologyPublisher(Protocol):
    """Write contract; implemented only by the PostgreSQL backend."""

    # FILL IN: ensure_ontology, publish, publish_content — verbatim from spec lines 697-701.
```
**Why this shape**: the spec fixes every name and field; `@runtime_checkable` lets the
conformance suite assert `isinstance(store, OntologyStore)`.

### `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/exceptions.py` (CREATE)
```python
"""Typed errors of the ontology vocabulary store (FEAT-824)."""
from __future__ import annotations

from typing import Sequence

from parrot.knowledge.ontology.exceptions import OntologyError  # verified: parrot/knowledge/ontology/exceptions.py:4
from parrot.knowledge.ontology.vocabulary.contracts import ValidationIssue


class VocabularyError(OntologyError):
    """Base class for vocabulary-store errors."""


class OntologyNotFound(VocabularyError):
    """The ontology_id is not registered."""


class OntologyVersionNotFound(VocabularyError):
    """as_of names a version that was never published, or one a snapshot does not hold."""


class OntologyValidationError(VocabularyError):
    """Publication rejected; ``issues`` holds every ValidationIssue."""

    def __init__(self, issues: Sequence[ValidationIssue]) -> None:
        self.issues = list(issues)
        # FILL IN: message summarising the issue codes (e.g. "3 issues: IRI_REMOVED, ...").
        super().__init__("FILL IN")


class PublishConflict(VocabularyError):
    """The base version kept moving; bounded retries were exhausted."""
```

### `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_contracts.py` (CREATE)
```python
"""Models and Protocols of the vocabulary store (FEAT-824 TASK-5253)."""
from __future__ import annotations

import pickle

from parrot.knowledge.ontology.exceptions import OntologyError
from parrot.knowledge.ontology.vocabulary import contracts as c
from parrot.knowledge.ontology.vocabulary import exceptions as e


def test_models_roundtrip() -> None:
    """Every model validates, serialises with model_dump/model_validate, and pickles."""
    # FILL IN: one instance per model; assert model_validate(model_dump()) == instance and pickle round-trip.


def test_validation_error_carries_issues() -> None:
    err = e.OntologyValidationError([c.ValidationIssue(code="IRI_REMOVED", message="x")])
    assert isinstance(err, OntologyError) and err.issues[0].code == "IRI_REMOVED"


def test_protocols_are_runtime_checkable() -> None:
    # FILL IN: a minimal class implementing every OntologyStore method passes isinstance.
    ...
```

### FILL IN checklist
- [ ] remaining twelve models — verbatim fields from spec §2.
- [ ] remaining Protocol methods — verbatim from spec Module 3.
- [ ] `OntologyValidationError` message.
- [ ] test bodies.

---

## Acceptance Criteria

- [ ] All models and both Protocols exist with the spec's exact names and fields.
- [ ] Importing `contracts.py` loads neither `asyncpg`, `rdflib` nor `numpy`.
- [ ] `ruff check` passes on the new files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_contracts.py -q`
- `pytest packages/ai-parrot/tests/knowledge/ontology/test_exceptions.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug ontology-backend --feature-id FEAT-824`).
2. Verify the Codebase Contract; mark `in-progress`; implement from the blueprint.
3. Run the Validation Commands (prefix `PYTHONPATH=packages/ai-parrot/src` inside the worktree).
4. Commit only the files listed above; close with `parrot sdd task close TASK-5253 ontology-backend verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
