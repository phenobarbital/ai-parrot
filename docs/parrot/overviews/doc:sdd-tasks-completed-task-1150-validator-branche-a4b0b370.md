---
type: Wiki Overview
title: 'TASK-1150: Validator Branches for New Field Types (excl. REMOTE_RESPONSE)'
id: doc:sdd-tasks-completed-task-1150-validator-branches-new-types-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 2, Module 12a. Extends `FormValidator` in `services/validators.py`
---

# TASK-1150: Validator Branches for New Field Types (excl. REMOTE_RESPONSE)

**Feature**: FEAT-167 — FormDesigner New Field Types
**Spec**: `sdd/specs/formdesigner-new-fields.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1147, TASK-1148, TASK-1149
**Assigned-to**: unassigned

---

## Context

Phase 2, Module 12a. Extends `FormValidator` in `services/validators.py`
with one validation branch per new FieldType, covering 9 of the 10 new
types. `REMOTE_RESPONSE` is deferred to TASK-1159 (Module 21) which
depends on Phase 3 services. Implements the data shapes from spec §7.

---

## Scope

Add validation branches for:
- `SIGNATURE` — validates `{"svg": str, "png": str}` dict + MIME types
- `DYNAMIC_SELECT` — same as `SELECT` (value is a string)
- `TRANSFER_LIST` — same as `MULTI_SELECT` (value is `list[str]`)
- `AVAILABILITY` — `list[{"start": datetime, "end": datetime}]`, rejects overlapping slots
- `LOCATION` — ISO 3166 alpha-2 string, validated against `pycountry`
- `TAGS` — accepts `str` (comma-separated) or `list[str]`, coerces to `list[str]`
- `NPS` — `int 0..10`, enforces `scale_min=0`, `scale_max=10`
- `LIKERT` — `int scale_min..scale_max`, requires `constraints.scale_*`
- `RANKING` — `int 0..scale_max`, defaults `scale_max=5` if absent

**NOT in scope**: `REMOTE_RESPONSE` (TASK-1159), pycountry wrapper (TASK-1154
must be completed first for LOCATION validation).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` | MODIFY | Add 9 new validator branches |
| `packages/parrot-formdesigner/tests/unit/test_renderers.py` | MODIFY | Add validator unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# services/validators.py current imports (verified):
import logging
import re
from typing import Any, Callable
from pydantic import BaseModel
from ..core.schema import FormField, FormSchema, FormSection
from ..core.types import FieldType, LocalizedString

# After TASK-1147 (new FieldType values available):
# FieldType.SIGNATURE, DYNAMIC_SELECT, TRANSFER_LIST, etc. now exist

# For LOCATION validation (after TASK-1154):
# from ..core._location_data import is_valid_iso_country_code
# NOTE: TASK-1154 may not be complete when this task runs.
# If pycountry/_location_data.py is not yet available, skip the
# pycountry validation and add a TODO comment — do not import blindly.
```

### Existing Signatures to Use
```python
# services/validators.py — FormValidator current state
# Read the full file to understand the existing validate_field() method
# structure, then add new branches following the same pattern.

# FieldConstraints (after TASK-1148):
# constraints.scale_min: int | None
# constraints.scale_max: int | None
# constraints.scale_step: int | None
# constraints.anchor_labels: dict[int, LocalizedString] | None
# constraints.allowed_mime_types: list[str] | None
```

### Does NOT Exist
- ~~`RemoteResponseResolver`~~ — TASK-1157 (do not add REMOTE_RESPONSE here)
- ~~`AuthContext`~~ — TASK-1155
- ~~`pycountry` import~~ — only safe after TASK-1154 is done; guard with try/except

---

## Implementation Notes

### Data Shape Rules (from spec §7)

| FieldType | Submitted shape | Validation rule |
|---|---|---|
| `SIGNATURE` | `{"svg": str, "png": str}` | dict with both keys; MIME types validated against `constraints.allowed_mime_types` |
| `DYNAMIC_SELECT` | `str` | same as SELECT (string match against options values) |
| `TRANSFER_LIST` | `list[str]` | same as MULTI_SELECT |
| `AVAILABILITY` | `list[{"start": datetime, "end": datetime}]` | discrete slots; reject overlapping unless `meta.allow_overlap=True` |
| `LOCATION` | `str` ISO alpha-2 | check against pycountry; "XX" fails, "ES"/"VE"/"US" pass |
| `TAGS` | `list[str]` | accept `"a,b,c"` → coerce to `["a","b","c"]`; `["a","b","c"]` unchanged |
| `NPS` | `int 0..10` | enforce within range; "5" → 5 (coerce); -1 and 11 fail |
| `LIKERT` | `int scale_min..scale_max` | requires `constraints.scale_*` |
| `RANKING` | `int 0..scale_max` | default `scale_max=5` if absent |

### pycountry Guard
```python
try:
    import pycountry
    _HAS_PYCOUNTRY = True
except ImportError:
    _HAS_PYCOUNTRY = False

def _validate_location(value: str) -> bool:
    if not _HAS_PYCOUNTRY:
        return True  # skip if not installed
    return pycountry.countries.get(alpha_2=value.upper()) is not None
```

---

## Acceptance Criteria

- [ ] `SIGNATURE` validator rejects bare strings, accepts `{"svg": "...", "png": "..."}`
- [ ] `NPS` validator coerces `"5"` → `5`, rejects `-1` and `11`
- [ ] `LIKERT` enforces `constraints.scale_min..scale_max`
- [ ] `RANKING` defaults to `scale_max=5` when constraints absent
- [ ] `TAGS` accepts `"a,b,c"` and coerces to `["a", "b", "c"]`
- [ ] `AVAILABILITY` rejects overlapping slots unless `meta.allow_overlap=True`
- [ ] `LOCATION` rejects unknown ISO codes (when pycountry available)
- [ ] All existing validator tests pass unchanged
- [ ] Tests for each new type pass
- [ ] `ruff check packages/parrot-formdesigner/` passes

---

## Test Specification

```python
import pytest
from pydantic import ValidationError
from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.constraints import FieldConstraints


# These tests assume FormValidator.validate_field(field, value) or similar
# Read the current validator structure first to use the correct API

def test_validator_signature_accepts_svg_png_dict():
    """SIGNATURE accepts {"svg": "...", "png": "..."} and rejects bare strings."""
    # Use FormValidator with a SIGNATURE field
    field = FormField(
        field_id="sig", field_type=FieldType.SIGNATURE, label="Sig",
        constraints=FieldConstraints(allowed_mime_types=["image/svg+xml", "image/png"])
    )
    # valid: dict with svg and png
    valid_value = {"svg": "<svg/>", "png": "data:image/png;base64,abc"}
    # invalid: bare string
    invalid_value = "<svg/>"
    # ... assert validation passes/fails accordingly


def test_validator_nps_clamps_to_0_10():
    """NPS coerces string '5' → 5, rejects 11 and -1."""
    field = FormField(
        field_id="nps", field_type=FieldType.NPS, label="NPS",
        constraints=FieldConstraints(scale_min=0, scale_max=10)
    )
    # Test with your validator's API


def test_validator_tags_returns_list_of_strings():
    """TAGS accepts 'a,b,c' and ['a','b','c'], both yield ['a','b','c']."""
    pass  # Implement using FormValidator API


def test_validator_availability_rejects_overlapping_slots():
    """Two overlapping slots raise unless meta.allow_overlap=True."""
    pass


def test_validator_location_rejects_unknown_iso_code():
    """LOCATION with 'XX' raises; 'ES', 'VE', 'US' pass."""
    pass
```

Note: Read `services/validators.py` fully before implementing to use the
correct `FormValidator` API (method names, return types, error model).

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
