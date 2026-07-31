---
type: Wiki Overview
title: 'TASK-1085: Ontology Exception Types Extension'
id: doc:sdd-tasks-completed-task-1085-ontology-exception-types-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Four new exception types are needed by the concept catalog service, schema
  overlay service, and merger extension. They must inherit from the existing `OntologyError`
  base class. See spec §3 Module 2.
relates_to:
- concept: mod:parrot.knowledge.ontology.exceptions
  rel: mentions
---

# TASK-1085: Ontology Exception Types Extension

**Feature**: FEAT-159 — Topic-Authority Ontology Curation
**Spec**: `sdd/specs/topic-authority-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Four new exception types are needed by the concept catalog service, schema overlay service, and merger extension. They must inherit from the existing `OntologyError` base class. See spec §3 Module 2.

---

## Scope

- Add `FrameworkOverrideError`, `CycleError`, `SynonymConflictError`, `DryRunFailedError` to the existing exceptions module.
- `DryRunFailedError` accepts a `DryRunReport` in its constructor.
- Write unit tests verifying inheritance and constructor behavior.

**NOT in scope**: Service logic, merger logic, HTTP error mapping.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/exceptions.py` | MODIFY | Add 4 new exception classes |
| `tests/knowledge/ontology/test_exceptions.py` | CREATE | Unit tests for new exceptions |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot/src/parrot/knowledge/ontology/exceptions.py (existing)
from parrot.knowledge.ontology.exceptions import OntologyError  # exceptions.py:4
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/ontology/exceptions.py
class OntologyError(Exception):  # line 4
    """Base exception for all ontology-related errors."""
    ...

class OntologyMergeError(OntologyError):  # line 8
    ...

class OntologyIntegrityError(OntologyError):  # line 18
    ...

class AQLValidationError(OntologyError):  # line 27
    ...

class UnknownDataSourceError(OntologyError):  # line 38
    ...

class DataSourceValidationError(OntologyError):  # line 42
    ...
```

### Does NOT Exist

- ~~`FrameworkOverrideError`~~ — does not exist; this task creates it.
- ~~`CycleError`~~ — does not exist; this task creates it.
- ~~`SynonymConflictError`~~ — does not exist; this task creates it.
- ~~`DryRunFailedError`~~ — does not exist; this task creates it.
- ~~`DryRunReport` in exceptions module~~ — `DryRunReport` is defined in `schema_overlay/models.py` (TASK-1093); use a forward reference or TYPE_CHECKING import.

---

## Implementation Notes

### Pattern to Follow

```python
# Follow the existing pattern in exceptions.py:
class OntologyMergeError(OntologyError):  # line 8
    """Raised when ontology merge fails due to conflicts or invalid configuration."""

    def __init__(self, message: str, conflicts: list[str] | None = None):
        self.conflicts = conflicts or []
        super().__init__(message)
```

### Key Constraints

- All 4 exceptions inherit from `OntologyError`.
- `DryRunFailedError` must store the `DryRunReport` as an attribute. Since `DryRunReport` is defined in TASK-1093 (schema_overlay models), use `TYPE_CHECKING` import or `Any` type hint to avoid circular dependency.
- `CycleError` should store the cycle path for debugging.
- `SynonymConflictError` should store the conflicting synonym and the existing concept slug.
- `FrameworkOverrideError` should store the entity/relation/pattern name that was attempted to be overridden.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/ontology/exceptions.py` — extend this file.

---

## Acceptance Criteria

- [ ] `FrameworkOverrideError` exists and inherits from `OntologyError`.
- [ ] `CycleError` exists, inherits from `OntologyError`, stores cycle path.
- [ ] `SynonymConflictError` exists, inherits from `OntologyError`, stores conflicting synonym and slug.
- [ ] `DryRunFailedError` exists, inherits from `OntologyError`, stores report.
- [ ] All tests pass: `pytest tests/knowledge/ontology/test_exceptions.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/ontology/exceptions.py`
- [ ] Imports work: `from parrot.knowledge.ontology.exceptions import FrameworkOverrideError, CycleError, SynonymConflictError, DryRunFailedError`

---

## Test Specification

```python
# tests/knowledge/ontology/test_exceptions.py
import pytest
from parrot.knowledge.ontology.exceptions import (
    OntologyError,
    FrameworkOverrideError,
    CycleError,
    SynonymConflictError,
    DryRunFailedError,
)


class TestFrameworkOverrideError:
    def test_inherits_ontology_error(self):
        err = FrameworkOverrideError("cannot override Employee")
        assert isinstance(err, OntologyError)

    def test_stores_entity_name(self):
        err = FrameworkOverrideError("msg", entity_name="Employee")
        assert err.entity_name == "Employee"


class TestCycleError:
    def test_inherits_ontology_error(self):
        err = CycleError("cycle detected")
        assert isinstance(err, OntologyError)

    def test_stores_cycle_path(self):
        err = CycleError("cycle", cycle_path=["A", "B", "A"])
        assert err.cycle_path == ["A", "B", "A"]


class TestSynonymConflictError:
    def test_inherits_ontology_error(self):
        err = SynonymConflictError("conflict")
        assert isinstance(err, OntologyError)

    def test_stores_conflict_details(self):
        err = SynonymConflictError("msg", synonym="commissions", existing_slug="sales_comp")
        assert err.synonym == "commissions"
        assert err.existing_slug == "sales_comp"


class TestDryRunFailedError:
    def test_inherits_ontology_error(self):
        err = DryRunFailedError("dry run failed", report={"ok": False})
        assert isinstance(err, OntologyError)

    def test_stores_report(self):
        report = {"ok": False, "checks": [], "error": "bad AQL"}
        err = DryRunFailedError("failed", report=report)
        assert err.report == report
```

---

## Agent Instructions

When you pick up this task:

1. **Read** `packages/ai-parrot/src/parrot/knowledge/ontology/exceptions.py` to see current exception patterns
2. **Add** the four new exception classes following the existing style
3. **Run tests**: `pytest tests/knowledge/ontology/test_exceptions.py -v`
4. **Verify imports** work from the package

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
