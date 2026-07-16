---
type: Wiki Overview
title: 'TASK-1153: Controls Registry Seeding for New Field Types'
id: doc:sdd-tasks-completed-task-1153-controls-registry-seeding-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 2, Module 15. Adds `register_field_control()` calls for each of the
  10
---

# TASK-1153: Controls Registry Seeding for New Field Types

**Feature**: FEAT-167 — FormDesigner New Field Types
**Spec**: `sdd/specs/formdesigner-new-fields.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1147
**Assigned-to**: unassigned

---

## Context

Phase 2, Module 15. Adds `register_field_control()` calls for each of the 10
new `FieldType` values in `controls/builtin.py`. Categorization: `"media"` for
SIGNATURE; `"selection"` for DYNAMIC_SELECT, TRANSFER_LIST, LOCATION, TAGS;
`"advanced"` for REMOTE_RESPONSE, AVAILABILITY, NPS, LIKERT, RANKING.

---

## Scope

- Add `register_field_control()` call for each of the 10 new FieldType values
- Assign correct `category`, `icon`, `render_hint`, `supports_constraints`
- Add appropriate `snippet` (JSON Schema seed) for each type
- After this task, `len(get_controls()) == 30`

**NOT in scope**: Pycountry (TASK-1154), renderer implementations (TASK-1151).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/controls/builtin.py` | MODIFY | Add register_field_control() calls for 10 new types |
| `packages/parrot-formdesigner/tests/unit/test_controls_registry.py` | MODIFY | Add test_controls_registry_has_all_new_types |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# controls/builtin.py current imports (verified):
from __future__ import annotations
from typing import Any
from ..core.types import FieldType
from ..tools.field_helpers import get_form_field_schema_snippets
from .registry import register_field_control

# controls/registry.py:70 — register_field_control signature (verified):
def register_field_control(
    field_type: FieldType | str,
    *,
    label: str,
    description: str,
    category: str,        # "basic" | "selection" | "media" | "layout" | "advanced"
    icon: str,
    snippet: dict[str, Any],
    render_hint: str,
    supports_constraints: bool,
    is_container: bool = False,
) -> None: ...
# Idempotent — re-registration overwrites with a warning

# controls/registry.py — get_controls(), iter_controls() functions
from parrot_formdesigner.controls.registry import get_controls, iter_controls
```

### Does NOT Exist
- ~~`FieldType.SIGNATURE` etc.~~ in builtin.py until TASK-1147 completes — this
  task depends on TASK-1147 so they will exist

---

## Implementation Notes

### Categorization (from spec §3 Module 15)
| FieldType | category | render_hint |
|---|---|---|
| `SIGNATURE` | `"media"` | `"signature"` |
| `DYNAMIC_SELECT` | `"selection"` | `"select"` |
| `TRANSFER_LIST` | `"selection"` | `"transfer"` |
| `LOCATION` | `"selection"` | `"select"` |
| `TAGS` | `"selection"` | `"tags"` |
| `REMOTE_RESPONSE` | `"advanced"` | `"remote"` |
| `AVAILABILITY` | `"advanced"` | `"availability"` |
| `NPS` | `"advanced"` | `"nps"` |
| `LIKERT` | `"advanced"` | `"likert"` |
| `RANKING` | `"advanced"` | `"ranking"` |

### Example Registration
```python
register_field_control(
    FieldType.SIGNATURE,
    label="Signature",
    description="Capture a handwritten signature (SVG + PNG).",
    category="media",
    icon="signature",
    snippet={"type": "string", "format": "signature"},
    render_hint="signature",
    supports_constraints=True,
)

register_field_control(
    FieldType.NPS,
    label="NPS Score",
    description="Net Promoter Score 0–10.",
    category="advanced",
    icon="nps",
    snippet={"type": "integer", "format": "nps", "minimum": 0, "maximum": 10},
    render_hint="nps",
    supports_constraints=True,
)
```

Read the existing `_BUILTIN_METADATA` dict pattern in `builtin.py` and follow
the same style for consistency.

---

## Acceptance Criteria

- [ ] `register_field_control()` called for all 10 new FieldType values
- [ ] `len(get_controls()) == 30` after `builtin.py` is imported
- [ ] Each new type has correct `category` per spec
- [ ] `test_controls_registry_has_all_new_types` passes
- [ ] `ruff check packages/parrot-formdesigner/` passes

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_controls_registry.py
# Add to existing test file:

def test_controls_registry_has_all_new_types():
    """get_controls() returns 30 entries (20 existing + 10 new) after import."""
    import parrot_formdesigner.controls.builtin  # trigger side-effect registration
    from parrot_formdesigner.controls.registry import get_controls
    controls = get_controls()
    assert len(controls) == 30, f"Expected 30 controls, got {len(controls)}"

    # Spot-check new types are present
    control_types = {c.type for c in controls}
    assert "signature" in control_types
    assert "nps" in control_types
    assert "likert" in control_types
    assert "ranking" in control_types
    assert "dynamic_select" in control_types


def test_controls_new_type_categories():
    """New types have correct categories."""
    import parrot_formdesigner.controls.builtin
    from parrot_formdesigner.controls.registry import get_controls
    controls = {c.type: c for c in get_controls()}
    assert controls["signature"].category == "media"
    assert controls["dynamic_select"].category == "selection"
    assert controls["nps"].category == "advanced"
```

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
