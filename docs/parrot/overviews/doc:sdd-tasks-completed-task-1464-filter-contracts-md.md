---
type: Wiki Overview
title: 'TASK-1464: Filter Contracts (Pydantic models)'
id: doc:sdd-tasks-completed-task-1464-filter-contracts-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 1** of the spec. All other modules consume these models,
  so
relates_to:
- concept: mod:parrot.tools.dataset_manager.filtering
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.spatial.contracts
  rel: mentions
---

# TASK-1464: Filter Contracts (Pydantic models)

**Feature**: FEAT-225 — DatasetManager Common-Field Filtering
**Spec**: `sdd/specs/datasetmanager-filtering.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of the spec. All other modules consume these models, so
this is the foundation task. Models are I/O-free Pydantic v2, mirroring the style
of the existing `spatial/contracts.py`.

---

## Scope

- Create the `parrot/tools/dataset_manager/filtering/` package (`__init__.py`).
- Implement `filtering/contracts.py` with:
  - `FilterKind = Literal["categorical","numeric","temporal","text","spatial"]`
  - `FilterOp = Literal["eq","ne","in","not_in","range","radius"]`
  - `ValuesSource(BaseModel)` — `query_slug`, `column`, `dataset` (all optional).
  - `FilterDefinition(BaseModel)` — `name`, `columns: List[str]` (min_length=1),
    `kind`, `ops: List[FilterOp]` (min_length=1), `required: bool = False`,
    `values_source: Optional[ValuesSource]`, `label`, `description`.
  - `FilterCondition(BaseModel)` — `op: FilterOp`, `value: Any = None`.
  - `FilterResult(BaseModel)` — `applied: List[str]`, `skipped: List[str]`.
- Add op⇄kind validation (Pydantic `model_validator`):
  - `radius` ⇒ `kind == "spatial"`.
  - `range` ⇒ `kind in {"numeric","temporal"}`.
  - `eq/ne/in/not_in` valid for `categorical`/`numeric`/`temporal`/`text`.
- Export the public names from `filtering/__init__.py`.
- Unit tests for validation and round-trip serialization.

**NOT in scope**: storing definitions on the manager (TASK-1465), any execution
logic, SQL/pandas, spatial bridging.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/filtering/__init__.py` | CREATE | Package init + exports |
| `packages/ai-parrot/src/parrot/tools/dataset_manager/filtering/contracts.py` | CREATE | Pydantic models + validators |
| `packages/ai-parrot/tests/unit/test_filter_contracts.py` | CREATE | Validation + serialization tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Style reference (do NOT import from here; replicate the pattern):
from parrot.tools.dataset_manager.spatial.contracts import DatasetSpatialProfile  # spatial/contracts.py:111
# Standard:
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/spatial/contracts.py
# Pattern reference — I/O-free Pydantic v2 with field_validator / model_validator,
# no `from __future__ import annotations` (so Tuple[...] resolves at class-def time).
class DatasetSpatialProfile(BaseModel):  # line 111
    @model_validator(mode="after")
    def _validate_geometry_source(self) -> "DatasetSpatialProfile": ...  # line 214
_ALLOWED_COLUMN_FORMATS: frozenset = frozenset({...})  # line 20 — validation precedent
```

### Does NOT Exist
- ~~`parrot.tools.dataset_manager.filtering`~~ — this task creates the package.
- ~~`FilterDefinition` / `FilterCondition` / `FilterResult` / `ValuesSource`~~ — created here.
- ~~text operators `like`/`contains`/`startswith` in `FilterOp`~~ — deferred (spec Non-Goals).

---

## Implementation Notes

### Pattern to Follow
Replicate the validator style of `spatial/contracts.py` (`field_validator`/
`model_validator(mode="after")`, descriptive `ValueError` messages). Omit
`from __future__ import annotations` to keep Pydantic v2 happy with literal
annotations (as that file documents).

### Key Constraints
- Pydantic v2 models; no I/O, no DB, no pandas in this module.
- Clear `ValueError` messages naming the offending field/op.
- `FilterDefinition.columns` carries `[lat, lng]` (or single geom col) for spatial.

---

## Acceptance Criteria

- [ ] `from parrot.tools.dataset_manager.filtering import FilterDefinition, FilterCondition, FilterResult, ValuesSource` works.
- [ ] `radius` op rejected unless `kind="spatial"`; `range` rejected unless numeric/temporal.
- [ ] Models round-trip via `.model_dump()` / re-construct.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/test_filter_contracts.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/dataset_manager/filtering/`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_filter_contracts.py
import pytest
from parrot.tools.dataset_manager.filtering import (
    FilterDefinition, FilterCondition, FilterResult, ValuesSource,
)


def test_categorical_definition_ok():
    d = FilterDefinition(name="region", columns=["region"], kind="categorical",
                         ops=["eq", "ne", "in"])
    assert d.required is False


def test_radius_requires_spatial_kind():
    with pytest.raises(ValueError):
        FilterDefinition(name="geo", columns=["lat", "lng"], kind="categorical",
                         ops=["radius"])


def test_range_requires_numeric_or_temporal():
    with pytest.raises(ValueError):
        FilterDefinition(name="r", columns=["region"], kind="categorical",
                         ops=["range"])


def test_roundtrip_serialization():
    d = FilterDefinition(name="geo", columns=["lat", "lng"], kind="spatial",
                         ops=["radius"])
    assert FilterDefinition(**d.model_dump()) == d
```

---

## Agent Instructions

Follow the standard SDD agent loop (verify contract, implement, test, move file
to `sdd/tasks/completed/`, update the per-spec index to `done`, fill the
completion note).

---

## Completion Note

Implemented as specified. Created `filtering/__init__.py` (package + exports) and
`filtering/contracts.py` with all four models: `ValuesSource`, `FilterDefinition`,
`FilterCondition`, `FilterResult`. The `model_validator` in `FilterDefinition`
enforces op-kind rules: `radius` requires `kind=spatial`, `range` requires
`kind in {numeric, temporal}`, and `kind=spatial` restricts ops to `radius` only.
28 unit tests pass. No linting errors.
