---
type: Wiki Overview
title: 'TASK-1152: Extractor Reverse-Mappings for New Field Types'
id: doc:sdd-tasks-completed-task-1152-extractor-reverse-mappings-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 2, Module 14. Adds reverse-mapping entries for the 10 new `FieldType`
---

# TASK-1152: Extractor Reverse-Mappings for New Field Types

**Feature**: FEAT-167 — FormDesigner New Field Types
**Spec**: `sdd/specs/formdesigner-new-fields.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1147, TASK-1148, TASK-1149
**Assigned-to**: unassigned

---

## Context

Phase 2, Module 14. Adds reverse-mapping entries for the 10 new `FieldType`
values into `extractors/jsonschema.py` and `extractors/yaml.py`. Enables
round-trip: YAML/JSON Schema → `FormSchema` → YAML/JSON Schema for new types.

---

## Scope

- Add `_FORMAT_MAP` entries in `extractors/jsonschema.py` for new types
  (e.g. `"signature"` → `FieldType.SIGNATURE`)
- Add `_YAML_TYPE_MAP` entries in `extractors/yaml.py` for new types
- Add `options_source.http_method` and `options_source.auth_ref` extraction
  in the JSON Schema extractor where `OptionsSource` is built
- Do NOT modify existing mappings

**NOT in scope**: Renderer changes, validator changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py` | MODIFY | Add format → FieldType mappings for 10 new types |
| `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/yaml.py` | MODIFY | Add yaml key → FieldType mappings for 10 new types |
| `packages/parrot-formdesigner/tests/unit/test_extractors.py` | MODIFY | Add roundtrip tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# extractors/jsonschema.py current imports (verified):
from __future__ import annotations
import logging
from typing import Any
from ..core.constraints import FieldConstraints
from ..core.options import FieldOption
from ..core.schema import FormField, FormSchema, FormSection
from ..core.types import FieldType

# _FORMAT_MAP (line 31):
_FORMAT_MAP: dict[str, FieldType] = {
    "email": FieldType.EMAIL,
    "uri": FieldType.URL,
    "url": FieldType.URL,
    "date": FieldType.DATE,
    "date-time": FieldType.DATETIME,
    "time": FieldType.TIME,
    "password": FieldType.PASSWORD,
    "color": FieldType.COLOR,
    "phone": FieldType.PHONE,
    # ... (read full file for complete list)
}

# _TYPE_MAP (line 21):
_TYPE_MAP: dict[str, FieldType] = {
    "string": FieldType.TEXT,
    "number": FieldType.NUMBER,
    "integer": FieldType.INTEGER,
    "boolean": FieldType.BOOLEAN,
    "array": FieldType.ARRAY,
    "object": FieldType.GROUP,
}
```

### Does NOT Exist
- ~~`_FORMAT_MAP["signature"]`~~ — THIS task adds it
- ~~`_FORMAT_MAP["nps"]`~~ — THIS task adds it
- ~~`OptionsSource.http_method` in extractor~~ — this task handles extraction

---

## Implementation Notes

### JSON Schema Format → FieldType Mappings
```python
# Add to _FORMAT_MAP in extractors/jsonschema.py:
"signature": FieldType.SIGNATURE,
"dynamic-select": FieldType.DYNAMIC_SELECT,
"dynamic_select": FieldType.DYNAMIC_SELECT,  # underscore variant
"transfer-list": FieldType.TRANSFER_LIST,
"transfer_list": FieldType.TRANSFER_LIST,
"remote-response": FieldType.REMOTE_RESPONSE,
"remote_response": FieldType.REMOTE_RESPONSE,
"availability": FieldType.AVAILABILITY,
"location": FieldType.LOCATION,
"tags": FieldType.TAGS,
"nps": FieldType.NPS,
"likert": FieldType.LIKERT,
"ranking": FieldType.RANKING,
```

### YAML Type → FieldType Mappings
Read `extractors/yaml.py` to understand its mapping structure, then add:
```python
# In yaml extractor's type map:
"signature": FieldType.SIGNATURE,
"dynamic_select": FieldType.DYNAMIC_SELECT,
"transfer_list": FieldType.TRANSFER_LIST,
"remote_response": FieldType.REMOTE_RESPONSE,
"availability": FieldType.AVAILABILITY,
"location": FieldType.LOCATION,
"tags": FieldType.TAGS,
"nps": FieldType.NPS,
"likert": FieldType.LIKERT,
"ranking": FieldType.RANKING,
```

### OptionsSource http_method / auth_ref Extraction
Find where `OptionsSource` is constructed in the JSON Schema extractor
and add extraction of the new fields:
```python
options_source = OptionsSource(
    source_type=...,
    source_ref=...,
    value_field=prop.get("x-value-field", "value"),
    label_field=prop.get("x-label-field", "label"),
    cache_ttl_seconds=prop.get("x-cache-ttl"),
    http_method=prop.get("x-http-method", "GET"),   # NEW
    auth_ref=prop.get("x-auth-ref"),                 # NEW
)
```

---

## Acceptance Criteria

- [ ] `_FORMAT_MAP["signature"] == FieldType.SIGNATURE`
- [ ] All 10 new types have entries in both extractors
- [ ] Existing extractor tests pass unchanged
- [ ] `test_extractor_yaml_signature_roundtrip` passes
- [ ] `test_extractor_jsonschema_dynamic_select_roundtrip` passes
- [ ] `ruff check packages/parrot-formdesigner/` passes

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_extractors.py
# Add to existing test file:

def test_extractor_yaml_signature_roundtrip():
    """YAML key 'signature' extracts to FieldType.SIGNATURE."""
    from parrot_formdesigner.extractors.yaml import extract_form_from_yaml  # verify API
    yaml_content = """
    form_id: test_sig
    title: Test
    sections:
      - section_id: s1
        fields:
          - field_id: sig
            type: signature
            label: Your Signature
    """
    form = extract_form_from_yaml(yaml_content)
    assert form.sections[0].fields[0].field_type == FieldType.SIGNATURE


def test_extractor_jsonschema_dynamic_select_roundtrip():
    """JSON Schema with format 'dynamic_select' + options_source → FieldType.DYNAMIC_SELECT."""
    # Use the JSON Schema extractor API — read extractors/jsonschema.py to verify method names
    pass
```

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
