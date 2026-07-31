---
type: Wiki Overview
title: 'TASK-1165: REST field-schema snippet in `tools/field_helpers`'
id: doc:sdd-tasks-completed-task-1165-field-helper-snippet-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Seeds an LLM-friendly example snippet for `FieldType.REST` in
---

# TASK-1165: REST field-schema snippet in `tools/field_helpers`

**Feature**: FEAT-170 — FormDesigner `FieldType.REST`
**Spec**: `sdd/specs/new-formdesigner-field-rest.spec.md` (Module 6)
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1163
**Assigned-to**: unassigned

---

## Context

Seeds an LLM-friendly example snippet for `FieldType.REST` in
`_FIELD_SCHEMA_SNIPPETS` so the form-builder agents can suggest the
new field without re-deriving it from JSON Schema. Uses the planogram
callback example from spec §1.

---

## Scope

- Add one entry under `_FIELD_SCHEMA_SNIPPETS[FieldType.REST.value]` in
  `tools/field_helpers.py`. Snippet shape (planogram callback mode):

  ```python
  {
      "field_id": "planogram_photo",
      "field_type": "rest",
      "label": "Subir foto para planogram compliance",
      "required": True,
      "constraints": {
          "allowed_mime_types": ["image/jpeg", "image/png"],
          "max_file_size_bytes": 10485760,  # 10 MiB
      },
      "meta": {
          "rest": {
              "mode": "callback",
              "callback_ref": "planogram_compliance",
              "response_path": "$.compliance_score",
              "display_template": "Compliance: {{ (answer * 100) | round }}/100",
              "persist_binary": True,
          }
      },
  }
  ```

- Unit test asserting the snippet round-trips: parses to a valid
  `FormField` with `mode="callback"`.

**NOT in scope**: the `RestFieldSpec` model itself (TASK-1162), the
`_BUILTIN_METADATA` registration (TASK-1164).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py` | MODIFY | +1 snippet |
| `packages/parrot-formdesigner/tests/unit/tools/test_field_helpers.py` | MODIFY or CREATE | Snippet round-trip |

---

## Codebase Contract (Anti-Hallucination)

### Verified Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py:236
def get_form_field_schema_snippets() -> dict[str, dict[str, Any]]: ...
# Backed by module-level _FIELD_SCHEMA_SNIPPETS dict.
```

### Does NOT Exist

- ~~`_FIELD_SCHEMA_SNIPPETS["rest"]`~~ — added by this task.

---

## Acceptance Criteria

- [ ] `get_form_field_schema_snippets()["rest"]` returns the planogram snippet.
- [ ] Snippet round-trips: `FormField.model_validate(snippet)` succeeds.
- [ ] The `meta.rest` dict parses via `RestFieldSpec.model_validate(snippet["meta"]["rest"])` and yields a `CallbackRestFieldSpec`.

---

## Test Specification

```python
from parrot_formdesigner.tools.field_helpers import get_form_field_schema_snippets
from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.services.rest_field_resolver import (
    RestFieldSpec, CallbackRestFieldSpec,
)

def test_rest_snippet_roundtrips():
    snippet = get_form_field_schema_snippets()["rest"]
    field = FormField.model_validate(snippet)
    assert field.field_type.value == "rest"
    spec = RestFieldSpec.model_validate(snippet["meta"]["rest"])
    assert isinstance(spec, CallbackRestFieldSpec)
    assert spec.callback_ref == "planogram_compliance"
```

---

## Completion Note

*(Agent fills this in when done)*
