---
type: Wiki Overview
title: 'TASK-1093: Schema Overlay Pydantic Models'
id: doc:sdd-tasks-completed-task-1093-schema-overlay-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic v2 row models for the schema overlay tables. Used by the schema
  overlay service, validator, worker, and HTTP modules. See spec §2 Data Models and
  §3 Module 9.
relates_to:
- concept: mod:parrot.knowledge.ontology.schema_overlay
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema_overlay.models
  rel: mentions
---

# TASK-1093: Schema Overlay Pydantic Models

**Feature**: FEAT-159 — Topic-Authority Ontology Curation
**Spec**: `sdd/specs/topic-authority-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Pydantic v2 row models for the schema overlay tables. Used by the schema overlay service, validator, worker, and HTTP modules. See spec §2 Data Models and §3 Module 9.

---

## Scope

- Create the `schema_overlay` sub-package with `__init__.py`.
- Create `SchemaOverlayRow` and `DryRunReport` Pydantic v2 models.
- All models use `ConfigDict(extra="forbid")`.

**NOT in scope**: Service logic, validator logic, dry-run execution.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/schema_overlay/__init__.py` | CREATE | Package init |
| `packages/ai-parrot/src/parrot/knowledge/ontology/schema_overlay/models.py` | CREATE | SchemaOverlayRow, DryRunReport |
| `tests/knowledge/ontology/schema_overlay/__init__.py` | CREATE | Test package init |
| `tests/knowledge/ontology/schema_overlay/test_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from pydantic import BaseModel, Field, ConfigDict  # already a dependency
from uuid import UUID
from datetime import datetime
from typing import Literal, Any
```

### Existing Signatures to Use

```python
# No existing signatures needed — these are new models.
```

### Does NOT Exist

- ~~`parrot.knowledge.ontology.schema_overlay`~~ — package does not exist; this task creates it.
- ~~`SchemaOverlayRow`~~ — does not exist; this task creates it.
- ~~`DryRunReport`~~ — does not exist; this task creates it.

---

## Implementation Notes

### Pattern to Follow

```python
class SchemaOverlayRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: str
    overlay_kind: Literal["entity_type","relation_type","traversal_pattern"]
    name: str
    definition: dict[str, Any]
    state: Literal["proposed","pending_review","approved","rejected","deprecated"]
    asserted_by: str
    reviewed_by: str | None = None
    rationale: str | None = None
    dry_run_report: dict[str, Any] | None = None

class DryRunReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    checks: list[dict[str, Any]]
    error: str | None = None
    duration_ms: int
```

### Key Constraints

- `overlay_kind` uses `Literal` with 3 allowed values matching the Postgres CHECK constraint.
- `definition` is a free-form dict (serialized `EntityDef`/`RelationDef`/`TraversalPattern`).
- `dry_run_report` stores the last dry-run outcome as JSONB.
- `DryRunReport.checks` is a list of check results: `{check_name: str, passed: bool, details: str}`.

### References in Codebase

- Spec §2 "Pydantic / domain types" — exact field definitions.
- `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py` — Pydantic v2 pattern.

---

## Acceptance Criteria

- [ ] `SchemaOverlayRow` model with all fields from spec §2.
- [ ] `DryRunReport` model with all fields from spec §2.
- [ ] All models use `ConfigDict(extra="forbid")`.
- [ ] All tests pass: `pytest tests/knowledge/ontology/schema_overlay/test_models.py -v`
- [ ] Imports work: `from parrot.knowledge.ontology.schema_overlay.models import SchemaOverlayRow, DryRunReport`

---

## Test Specification

```python
# tests/knowledge/ontology/schema_overlay/test_models.py
import pytest
from uuid import uuid4
from parrot.knowledge.ontology.schema_overlay.models import SchemaOverlayRow, DryRunReport


class TestSchemaOverlayRow:
    def test_valid_construction(self):
        row = SchemaOverlayRow(
            id=uuid4(), tenant_id="t", overlay_kind="entity_type",
            name="Project", definition={"collection": "projects"},
            state="proposed", asserted_by="admin",
        )
        assert row.overlay_kind == "entity_type"

    def test_rejects_invalid_overlay_kind(self):
        with pytest.raises(Exception):
            SchemaOverlayRow(
                id=uuid4(), tenant_id="t", overlay_kind="invalid",
                name="X", definition={}, state="proposed", asserted_by="a",
            )

    def test_extra_fields_forbidden(self):
        with pytest.raises(Exception):
            SchemaOverlayRow(
                id=uuid4(), tenant_id="t", overlay_kind="entity_type",
                name="X", definition={}, state="proposed", asserted_by="a",
                extra="boom",
            )


class TestDryRunReport:
    def test_valid_success(self):
        report = DryRunReport(ok=True, checks=[], duration_ms=42)
        assert report.ok

    def test_valid_failure(self):
        report = DryRunReport(
            ok=False,
            checks=[{"check_name": "aql_validation", "passed": False, "details": "syntax error"}],
            error="AQL validation failed",
            duration_ms=100,
        )
        assert not report.ok
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §2 Data Models for exact field definitions
2. **Create** the `schema_overlay` package directory with `__init__.py`
3. **Implement** models following Pydantic v2 `ConfigDict(extra="forbid")` pattern
4. **Run tests**: `pytest tests/knowledge/ontology/schema_overlay/test_models.py -v`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
