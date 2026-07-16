---
type: Wiki Overview
title: 'TASK-1164: `_BUILTIN_METADATA[FieldType.REST]` registration'
id: doc:sdd-tasks-completed-task-1164-builtin-metadata-rest-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Registers the new field type with the form-designer UI metadata
---

# TASK-1164: `_BUILTIN_METADATA[FieldType.REST]` registration

**Feature**: FEAT-170 — FormDesigner `FieldType.REST`
**Spec**: `sdd/specs/new-formdesigner-field-rest.spec.md` (Module 5)
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1163
**Assigned-to**: unassigned

---

## Context

Registers the new field type with the form-designer UI metadata
registry (controls panel label, category, icon, render hint). Spec
§8 Q1 fixed category as `"advanced"` (peer of `REMOTE_RESPONSE`).

---

## Scope

- Add one entry to `_BUILTIN_METADATA` in
  `controls/builtin.py` for `FieldType.REST`:
  - `label="REST"`
  - `description="Upload content to a REST endpoint or callback; the API response becomes the field answer."`
  - `category="advanced"`
  - `icon="rest"`
  - `render_hint="upload"`
  - `supports_constraints=True`
  - `is_container=False`
  - `snippet={...}` — minimal valid stub (just enough to call
    `register_field_control` — the full snippet lives in
    `tools/field_helpers` and is added by TASK-1165).
- Test asserting `_BUILTIN_METADATA[FieldType.REST]["category"] == "advanced"`.

**NOT in scope**: the full field-schema snippet (TASK-1165).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/controls/builtin.py` | MODIFY | +1 entry |
| `packages/parrot-formdesigner/tests/unit/controls/test_builtin.py` | MODIFY or CREATE | Assert REST entry |

---

## Codebase Contract (Anti-Hallucination)

### Verified Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/controls/builtin.py:26
_BUILTIN_METADATA: dict[FieldType, dict[str, Any]] = {
    # 30 existing entries.
}
def _seed() -> None: ...     # line 301; called on import (line 322)

# packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py:67
_REGISTRY: dict[str, FieldControlMetadata] = {}
def register_field_control(
    field_type, *, label, description, category, icon, snippet,
    render_hint, supports_constraints, is_container=False,
) -> None: ...

# Existing REMOTE_RESPONSE entry (the precedent) — find it in
# _BUILTIN_METADATA and mirror its shape, swapping in REST values.
```

### Does NOT Exist

- ~~`_BUILTIN_METADATA[FieldType.REST]`~~ — added by this task.

---

## Acceptance Criteria

- [ ] `_BUILTIN_METADATA[FieldType.REST]["category"] == "advanced"`.
- [ ] `_seed()` runs without error after registration.
- [ ] `register_field_control` is called with the seven required kwargs.
- [ ] `ruff check` clean.

---

## Test Specification

```python
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.controls.builtin import _BUILTIN_METADATA

def test_rest_metadata_present():
    entry = _BUILTIN_METADATA[FieldType.REST]
    assert entry["category"] == "advanced"
    assert entry["label"] == "REST"
    assert entry["render_hint"] == "upload"
    assert entry["supports_constraints"] is True
```

---

## Completion Note

*(Agent fills this in when done)*
