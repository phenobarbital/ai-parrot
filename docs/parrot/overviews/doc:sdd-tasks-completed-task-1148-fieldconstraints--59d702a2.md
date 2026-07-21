---
type: Wiki Overview
title: 'TASK-1148: FieldConstraints — Scale Fields'
id: doc:sdd-tasks-completed-task-1148-fieldconstraints-scale-fields-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 2, Module 10. Extends `FieldConstraints` in `core/constraints.py` with
---

# TASK-1148: FieldConstraints — Scale Fields

**Feature**: FEAT-167 — FormDesigner New Field Types
**Spec**: `sdd/specs/formdesigner-new-fields.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1146
**Assigned-to**: unassigned

---

## Context

Phase 2, Module 10. Extends `FieldConstraints` in `core/constraints.py` with
four new fields for NPS/LIKERT/RANKING scale configuration. Adds `field_validator`
enforcing `scale_max > scale_min` and `anchor_labels` keys within bounds.

---

## Scope

- Add `scale_min: int | None = None` with `ge=0` to `FieldConstraints`
- Add `scale_max: int | None = None` with validator enforcing `> scale_min`
- Add `scale_step: int | None = None` (default 1 when `scale_max` is set)
- Add `anchor_labels: dict[int, LocalizedString] | None = None`
- Add `field_validator` enforcing `scale_max > scale_min` when both set
- Add `field_validator` enforcing all `anchor_labels` keys within `[scale_min, scale_max]`

**NOT in scope**: Validator branches for new field types (TASK-1150).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py` | MODIFY | Add scale_* fields and validators |
| `packages/parrot-formdesigner/tests/unit/test_core_models.py` | MODIFY | Add scale constraint tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# core/constraints.py current imports (verified):
import re
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .types import LocalizedString
```

### Existing Signatures to Use
```python
# core/constraints.py:17 (verified):
class FieldConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")   # line 35
    min_length: int | None = Field(default=None, ge=0, ...)  # line 37
    max_length: int | None = Field(default=None, ge=0, ...)  # line 38
    min_value: float | None = None              # line 39
    max_value: float | None = None              # line 40
    step: float | None = None                   # line 41
    pattern: str | None = None                  # line 42
    pattern_message: LocalizedString | None = None  # line 43
    min_items: int | None = Field(default=None, ge=0, ...)  # line 44
    max_items: int | None = Field(default=None, ge=0, ...)  # line 45
    allowed_mime_types: list[str] | None = None # line 46
    max_file_size_bytes: int | None = Field(default=None, ge=0, ...)  # line 47
    # Existing field_validator for "pattern" at line 51
```

### Does NOT Exist
- ~~`FieldConstraints.scale_min`~~ — THIS task adds it
- ~~`FieldConstraints.scale_max`~~ — THIS task adds it
- ~~`FieldConstraints.scale_step`~~ — THIS task adds it
- ~~`FieldConstraints.anchor_labels`~~ — THIS task adds it

---

## Implementation Notes

```python
# Add after max_file_size_bytes in FieldConstraints:

    # Phase 2 — scale fields for NPS / LIKERT / RANKING (FEAT-167)
    scale_min: int | None = Field(default=None, ge=0, description="Scale minimum (>= 0)")
    scale_max: int | None = Field(default=None, description="Scale maximum (must be > scale_min)")
    scale_step: int | None = Field(default=None, ge=1, description="Scale step increment (>= 1)")
    anchor_labels: dict[int, LocalizedString] | None = Field(
        default=None, description="Label for specific scale points"
    )

    @field_validator("scale_max")
    @classmethod
    def _validate_scale_max(cls, v: int | None, info) -> int | None:
        """Enforce scale_max > scale_min when both are set."""
        scale_min = info.data.get("scale_min")
        if v is not None and scale_min is not None and v <= scale_min:
            raise ValueError(
                f"scale_max ({v}) must be greater than scale_min ({scale_min})"
            )
        return v

    @field_validator("anchor_labels")
    @classmethod
    def _validate_anchor_labels(cls, v: dict | None, info) -> dict | None:
        """Enforce anchor_labels keys are within [scale_min, scale_max]."""
        if v is None:
            return v
        scale_min = info.data.get("scale_min", 0) or 0
        scale_max = info.data.get("scale_max")
        if scale_max is not None:
            for key in v:
                if not (scale_min <= key <= scale_max):
                    raise ValueError(
                        f"anchor_labels key {key} is outside [{scale_min}, {scale_max}]"
                    )
        return v
```

Note: `model_config = ConfigDict(extra="forbid")` is already set — new fields
must be valid Pydantic field definitions.

---

## Acceptance Criteria

- [ ] `FieldConstraints.scale_min`, `scale_max`, `scale_step`, `anchor_labels` exist
- [ ] `FieldConstraints(scale_min=0, scale_max=10)` instantiates successfully
- [ ] `FieldConstraints(scale_min=5, scale_max=3)` raises `ValidationError`
- [ ] Anchor label keys outside `[scale_min, scale_max]` raise `ValidationError`
- [ ] All existing `FieldConstraints` tests pass unchanged
- [ ] `test_field_constraints_scale_validator_rejects_inverted_range` passes
- [ ] `test_field_constraints_anchor_labels_in_bounds` passes
- [ ] `ruff check packages/parrot-formdesigner/` passes

---

## Test Specification

```python
import pytest
from pydantic import ValidationError
from parrot_formdesigner.core.constraints import FieldConstraints


def test_field_constraints_scale_validator_rejects_inverted_range():
    """scale_max < scale_min raises ValidationError."""
    with pytest.raises(ValidationError, match="scale_max"):
        FieldConstraints(scale_min=5, scale_max=3)


def test_field_constraints_scale_equal_raises():
    """scale_max == scale_min raises ValidationError."""
    with pytest.raises(ValidationError):
        FieldConstraints(scale_min=5, scale_max=5)


def test_field_constraints_anchor_labels_in_bounds():
    """Anchor label keys outside [scale_min, scale_max] raise."""
    with pytest.raises(ValidationError, match="anchor_labels"):
        FieldConstraints(scale_min=0, scale_max=10, anchor_labels={11: "Extreme"})


def test_field_constraints_anchor_labels_valid():
    """Anchor labels within bounds are accepted."""
    fc = FieldConstraints(
        scale_min=0, scale_max=10,
        anchor_labels={0: "Not at all", 5: "Neutral", 10: "Extremely likely"}
    )
    assert len(fc.anchor_labels) == 3


def test_field_constraints_scale_none_is_ok():
    """scale_* fields default to None — existing usage unchanged."""
    fc = FieldConstraints()
    assert fc.scale_min is None
    assert fc.scale_max is None
```

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
