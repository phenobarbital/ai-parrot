---
type: Wiki Overview
title: 'TASK-1087: Concept Catalog Pydantic Models'
id: doc:sdd-tasks-completed-task-1087-concept-catalog-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic v2 row models for the concept catalog tables. These are used by
  the service, worker, seed, reconcile, and HTTP modules. See spec §2 Data Models
  and §3 Module 3.
relates_to:
- concept: mod:parrot.knowledge.ontology.concept_catalog
  rel: mentions
- concept: mod:parrot.knowledge.ontology.concept_catalog.models
  rel: mentions
---

# TASK-1087: Concept Catalog Pydantic Models

**Feature**: FEAT-159 — Topic-Authority Ontology Curation
**Spec**: `sdd/specs/topic-authority-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Pydantic v2 row models for the concept catalog tables. These are used by the service, worker, seed, reconcile, and HTTP modules. See spec §2 Data Models and §3 Module 3.

---

## Scope

- Create the `concept_catalog` sub-package with `__init__.py`.
- Create `ConceptRow`, `IsaEdgeRow`, `CascadeAlert` Pydantic v2 models.
- All models use `ConfigDict(extra="forbid")`.

**NOT in scope**: Service logic, worker logic, Postgres queries.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/__init__.py` | CREATE | Package init, re-export models |
| `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/models.py` | CREATE | ConceptRow, IsaEdgeRow, CascadeAlert |
| `tests/knowledge/ontology/concept_catalog/__init__.py` | CREATE | Test package init |
| `tests/knowledge/ontology/concept_catalog/test_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from pydantic import BaseModel, Field, ConfigDict  # already a dependency
from uuid import UUID
from datetime import datetime
from typing import Literal
```

### Existing Signatures to Use

```python
# No existing signatures needed — these are new models.
# Follow Pydantic v2 pattern used across the project.
```

### Does NOT Exist

- ~~`parrot.knowledge.ontology.concept_catalog`~~ — package does not exist; this task creates it.
- ~~`ConceptRow`~~ — does not exist; this task creates it.
- ~~`IsaEdgeRow`~~ — does not exist; this task creates it.
- ~~`CascadeAlert`~~ — does not exist; this task creates it.

---

## Implementation Notes

### Pattern to Follow

```python
# Follow the Pydantic v2 pattern used in schema.py:
from pydantic import BaseModel, Field, ConfigDict

class ConceptRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: str
    slug: str
    label: str
    synonyms: list[str] = Field(default_factory=list)
    description: str | None = None
    domain: str | None = None
    state: Literal["proposed","pending_review","approved","rejected","deprecated"]
    asserted_by: str
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    rationale: str | None = None
    effective_from: datetime
    effective_to: datetime | None = None
```

### Key Constraints

- `state` field uses `Literal` with the 5-state enum — matches Postgres CHECK constraint.
- `IsaEdgeRow.parent_tier` is `Literal["framework","tenant"]`.
- `IsaEdgeRow.parent_ref` is `str` — holds either a framework concept name or a tenant UUID as text.
- `CascadeAlert.affected_edge_ids` is `list[UUID]` — operational `topic_authority.id` values.
- Google-style docstrings on all classes.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py` — Pydantic v2 patterns with `ConfigDict`.
- Spec §2 "Pydantic / domain types" — exact field definitions.

---

## Acceptance Criteria

- [ ] `ConceptRow` model with all fields from spec §2.
- [ ] `IsaEdgeRow` model with all fields from spec §2.
- [ ] `CascadeAlert` model with all fields from spec §2.
- [ ] All models use `ConfigDict(extra="forbid")`.
- [ ] All tests pass: `pytest tests/knowledge/ontology/concept_catalog/test_models.py -v`
- [ ] Imports work: `from parrot.knowledge.ontology.concept_catalog.models import ConceptRow, IsaEdgeRow, CascadeAlert`

---

## Test Specification

```python
# tests/knowledge/ontology/concept_catalog/test_models.py
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from parrot.knowledge.ontology.concept_catalog.models import ConceptRow, IsaEdgeRow, CascadeAlert


class TestConceptRow:
    def test_valid_construction(self):
        row = ConceptRow(
            id=uuid4(), tenant_id="tenant-a", slug="sales_comp",
            label="Sales Compensation", state="proposed",
            asserted_by="user@example.com", effective_from=datetime.now(timezone.utc),
        )
        assert row.state == "proposed"

    def test_rejects_invalid_state(self):
        with pytest.raises(Exception):
            ConceptRow(
                id=uuid4(), tenant_id="t", slug="s", label="L",
                state="invalid", asserted_by="u",
                effective_from=datetime.now(timezone.utc),
            )

    def test_extra_fields_forbidden(self):
        with pytest.raises(Exception):
            ConceptRow(
                id=uuid4(), tenant_id="t", slug="s", label="L",
                state="proposed", asserted_by="u",
                effective_from=datetime.now(timezone.utc),
                unknown_field="boom",
            )


class TestIsaEdgeRow:
    def test_valid_construction(self):
        row = IsaEdgeRow(
            id=uuid4(), tenant_id="t", child_id=uuid4(),
            parent_tier="framework", parent_ref="Employee",
            state="proposed", asserted_by="user",
        )
        assert row.parent_tier == "framework"

    def test_rejects_invalid_parent_tier(self):
        with pytest.raises(Exception):
            IsaEdgeRow(
                id=uuid4(), tenant_id="t", child_id=uuid4(),
                parent_tier="invalid", parent_ref="x",
                state="proposed", asserted_by="u",
            )


class TestCascadeAlert:
    def test_valid_construction(self):
        alert = CascadeAlert(
            tenant_id="t", concept_id=uuid4(), concept_slug="sales",
            affected_edge_ids=[uuid4(), uuid4()],
            notified_at=datetime.now(timezone.utc),
        )
        assert len(alert.affected_edge_ids) == 2
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §2 Data Models for exact field definitions
2. **Create** the `concept_catalog` package directory with `__init__.py`
3. **Implement** models following Pydantic v2 `ConfigDict(extra="forbid")` pattern
4. **Run tests**: `pytest tests/knowledge/ontology/concept_catalog/test_models.py -v`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
