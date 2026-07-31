---
type: Wiki Overview
title: 'TASK-1149: OptionsSource Extensions'
id: doc:sdd-tasks-completed-task-1149-optionssource-extensions-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 2, Module 11. Extends `OptionsSource` in `core/options.py` with
---

# TASK-1149: OptionsSource Extensions

**Feature**: FEAT-167 — FormDesigner New Field Types
**Spec**: `sdd/specs/formdesigner-new-fields.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1146
**Assigned-to**: unassigned

---

## Context

Phase 2, Module 11. Extends `OptionsSource` in `core/options.py` with
`http_method` and `auth_ref` fields needed by `DYNAMIC_SELECT` and the
`OptionsLoader` service (Phase 3). Existing schemas without these fields
deserialize unchanged.

---

## Scope

- Add `http_method: Literal["GET", "POST"] = "GET"` to `OptionsSource`
- Add `auth_ref: str | None = None` to `OptionsSource`
- Keep existing `value_field` / `label_field` names unchanged
- Do NOT rename `value_field` → `value_column` or `label_field` → `label_column`

**NOT in scope**: OptionsLoader service (TASK-1156), auth context (TASK-1155).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/options.py` | MODIFY | Add http_method and auth_ref |
| `packages/parrot-formdesigner/tests/unit/test_core_models.py` | MODIFY | Add OptionsSource tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# core/options.py current imports (verified):
from pydantic import BaseModel
from .types import LocalizedString

# Add for http_method:
from typing import Literal
```

### Existing Signatures to Use
```python
# core/options.py:30 — OptionsSource current state (verified):
class OptionsSource(BaseModel):
    source_type: str          # line 41
    source_ref: str           # line 42
    value_field: str = "value"    # line 43 — KEEP THIS NAME
    label_field: str = "label"    # line 44 — KEEP THIS NAME
    cache_ttl_seconds: int | None = None  # line 45
    # ADD: http_method and auth_ref
```

### Does NOT Exist
- ~~`OptionsSource.http_method`~~ — THIS task adds it
- ~~`OptionsSource.auth_ref`~~ — THIS task adds it
- ~~`OptionsSource.value_column`~~ — MUST NOT be introduced (use `value_field`)
- ~~`OptionsSource.label_column`~~ — MUST NOT be introduced (use `label_field`)
- ~~`OptionsLoader`~~ — TASK-1156

---

## Implementation Notes

```python
from typing import Literal
from pydantic import BaseModel
from .types import LocalizedString


class OptionsSource(BaseModel):
    """Dynamic options source configuration for fetching options at runtime.

    Attributes:
        source_type: Type of source (e.g., "tool", "endpoint", "query").
        source_ref: Reference to the source (tool name, URL, query name).
        value_field: Field in the source response to use as option value.
        label_field: Field in the source response to use as option label.
        cache_ttl_seconds: How long to cache the fetched options. None = no cache.
        http_method: HTTP verb for endpoint sources. Defaults to "GET".
        auth_ref: Reference to an AuthContext auth entry for authenticated endpoints.
    """
    source_type: str
    source_ref: str
    value_field: str = "value"     # Keep existing name
    label_field: str = "label"     # Keep existing name
    cache_ttl_seconds: int | None = None
    # Phase 2 additions (FEAT-167)
    http_method: Literal["GET", "POST"] = "GET"
    auth_ref: str | None = None
```

Backwards compatibility: `http_method` and `auth_ref` have defaults, so all
existing `OptionsSource(source_type=..., source_ref=...)` instantiations
continue working.

---

## Acceptance Criteria

- [ ] `OptionsSource.http_method` defaults to `"GET"`
- [ ] `OptionsSource.auth_ref` defaults to `None`
- [ ] `OptionsSource(source_type="endpoint", source_ref="http://x")` still works
- [ ] `value_field` and `label_field` names are unchanged
- [ ] `test_options_source_http_method_default_get` passes
- [ ] `test_options_source_auth_ref_optional` passes
- [ ] All existing tests using `OptionsSource` pass unchanged
- [ ] `ruff check packages/parrot-formdesigner/` passes

---

## Test Specification

```python
from parrot_formdesigner.core.options import OptionsSource


def test_options_source_http_method_default_get():
    """New OptionsSource defaults http_method to GET."""
    src = OptionsSource(source_type="endpoint", source_ref="https://api.test/users")
    assert src.http_method == "GET"


def test_options_source_auth_ref_optional():
    """auth_ref is optional; legacy schemas without it deserialize unchanged."""
    src = OptionsSource(source_type="endpoint", source_ref="https://api.test/users")
    assert src.auth_ref is None


def test_options_source_with_post_and_auth():
    """OptionsSource accepts POST method and auth_ref."""
    src = OptionsSource(
        source_type="endpoint",
        source_ref="https://api.test/users",
        http_method="POST",
        auth_ref="MY_API_KEY",
    )
    assert src.http_method == "POST"
    assert src.auth_ref == "MY_API_KEY"


def test_options_source_value_label_field_names_unchanged():
    """value_field and label_field names are preserved."""
    src = OptionsSource(
        source_type="endpoint",
        source_ref="https://api.test/users",
        value_field="id",
        label_field="full_name",
    )
    assert src.value_field == "id"
    assert src.label_field == "full_name"
```

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
