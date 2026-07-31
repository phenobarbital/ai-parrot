---
type: Wiki Overview
title: 'TASK-1023: JSON-2 Payload Generator (Phase 2)'
id: doc:sdd-tasks-completed-task-1023-generate-json2-payload-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: When migrating from XML-RPC to Odoo 19+ JSON-2, agents need to preview the
relates_to:
- concept: mod:parrot_tools.odoo
  rel: mentions
---

# TASK-1023: JSON-2 Payload Generator (Phase 2)

**Feature**: FEAT-147 — Evaluate Odoo MCP Toolkit
**Spec**: `sdd/specs/evaluate-odoo-mcp-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1013
**Assigned-to**: unassigned

---

## Context

When migrating from XML-RPC to Odoo 19+ JSON-2, agents need to preview the
translated request. This tool converts positional args into the JSON-2 named-argument
endpoint, headers, and body.

Implements spec §3 Module 11: JSON-2 Payload Generator.

---

## Scope

- Add `generate_json2_payload` method to `OdooToolkit` (synchronous — no Odoo call)
- Define `JSON2_ARG_MAP` constant mapping ORM methods to named parameter lists
- Build endpoint path: `/json/2/{model}/{method}`
- Build headers: `Content-Type: application/json`, optionally `X-Odoo-Database`
- Map positional args to named body using `JSON2_ARG_MAP`
- Fall back to generic body for unknown methods
- Decorate with `@tool_schema(GenerateJson2PayloadInput)`
- Return `Json2PayloadResult` envelope

**NOT in scope**: Actually executing the call, `diagnose_odoo_call`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | MODIFY | Add `generate_json2_payload`, `JSON2_ARG_MAP` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .models.inputs import GenerateJson2PayloadInput  # TASK-1013
from .models.envelopes import Json2PayloadResult      # TASK-1013
```

### Existing Signatures to Use
```python
# toolkit.py:175 — config available for default base_url/database:
self.config = OdooConfig(url=..., database=..., ...)
```

### Does NOT Exist
- ~~`OdooToolkit.generate_json2_payload()`~~ — must be created
- ~~`parrot_tools.odoo.json2_utils`~~ — no such module

---

## Implementation Notes

### JSON2_ARG_MAP (from spec §7)
```python
JSON2_ARG_MAP = {
    "search_read": ["domain", "fields", "offset", "limit", "order"],
    "search":      ["domain", "offset", "limit", "order"],
    "search_count":["domain"],
    "read":        ["ids", "fields"],
    "create":      ["vals_list"],
    "write":       ["ids", "vals"],
    "unlink":      ["ids"],
    "fields_get":  ["allfields", "attributes"],
    "name_search": ["name", "args", "operator", "limit"],
}
```

### Endpoint Construction
```python
base = base_url or self.config.url
endpoint = f"/json/2/{model}/{method}"
full_url = f"{base.rstrip('/')}{endpoint}"
```

### Body Construction
```python
body = {}
if method in JSON2_ARG_MAP:
    param_names = JSON2_ARG_MAP[method]
    for i, name in enumerate(param_names):
        if args and i < len(args):
            body[name] = args[i]
    if kwargs:
        body.update(kwargs)
else:
    # Unknown method — pass args/kwargs directly
    body = {"args": args or [], "kwargs": kwargs or {}}
    notes.append(f"Method '{method}' not in known JSON-2 mapping; using generic body")
```

### Key Constraints
- Pure function — no network call
- Synchronous (not async)
- Default `base_url` from `self.config.url` if not provided
- Default `database` from `self.config.database` if not provided
- `X-Odoo-Database` header included by default

---

## Acceptance Criteria

- [ ] `generate_json2_payload("res.partner", "search_read", [[("active","=",True)]], {"limit": 5})`
      → endpoint `/json/2/res.partner/search_read`, body has `domain` and `limit` keys
- [ ] `generate_json2_payload("res.partner", "create", [{"name": "Test"}])`
      → body has `vals_list` key
- [ ] Unknown method → generic body with notes
- [ ] Headers include `Content-Type` and `X-Odoo-Database`

---

## Test Specification

```python
def test_json2_search_read():
    result = tk.generate_json2_payload(
        model="res.partner", method="search_read",
        args=[[("active", "=", True)]], kwargs={"limit": 5},
    )
    assert "/json/2/res.partner/search_read" in result.endpoint
    assert "domain" in result.body

def test_json2_create():
    result = tk.generate_json2_payload(
        model="res.partner", method="create",
        args=[[{"name": "Test"}]],
    )
    assert "vals_list" in result.body

def test_json2_unknown_method():
    result = tk.generate_json2_payload(
        model="res.partner", method="custom_action",
    )
    assert len(result.notes) > 0
```

---

## Completion Note

*(Agent fills this in when done)*
