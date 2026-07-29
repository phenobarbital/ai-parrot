---
type: Wiki Overview
title: 'TASK-1014: Smart Field Selection Module'
id: doc:sdd-tasks-completed-task-1014-smart-field-selection-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: When agents omit `fields` in `search_records` or `get_record`, the toolkit
  returns
relates_to:
- concept: mod:parrot_tools.odoo
  rel: mentions
- concept: mod:parrot_tools.odoo.smart_fields
  rel: mentions
---

# TASK-1014: Smart Field Selection Module

**Feature**: FEAT-147 — Evaluate Odoo MCP Toolkit
**Spec**: `sdd/specs/evaluate-odoo-mcp-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1013
**Assigned-to**: unassigned

---

## Context

When agents omit `fields` in `search_records` or `get_record`, the toolkit returns
every field — flooding LLM context with binary blobs, HTML, and audit columns. This
task creates the scoring heuristic that selects the top N most useful fields.

Implements spec §3 Module 1: Smart Field Selection.

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/odoo/smart_fields.py` (new file)
- Implement `select_smart_fields(fields_metadata: dict, max_fields: int = 15, always_include: list[str] | None = None) -> list[str]`
- Implement private `_smart_field_score(field_name: str, field_meta: dict) -> float`
- Define constants: `TECHNICAL_FIELD_NAMES`, `HIGH_VALUE_PATTERNS`, `SKIP_FIELD_TYPES`

**NOT in scope**: Wiring into `search_records`/`get_record` (TASK-1015), toolkit
methods, tests for toolkit integration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/smart_fields.py` | CREATE | Smart field selection logic |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# This module is pure — no imports from parrot or parrot_tools needed.
# Only stdlib:
from __future__ import annotations
from typing import Any
```

### Existing Signatures to Use
```python
# The function receives fields_get() output, which has this shape per field:
# {
#     "name": {"type": "char", "string": "Name", "required": True, "readonly": False, ...},
#     "image_1920": {"type": "binary", "string": "Image", ...},
#     ...
# }
# Keys: field name → dict with at minimum "type" and "string"
```

### Does NOT Exist
- ~~`parrot_tools.odoo.smart_fields`~~ — this is what we are creating
- ~~`parrot_tools.odoo.utils`~~ — no utils module exists

---

## Implementation Notes

### Algorithm (from spec §7)

1. Always include `id` and `display_name` (don't count against max).
2. Skip fields with `type` in `{"binary", "html"}` entirely.
3. Penalise technical fields: `create_uid`, `write_uid`, `create_date`, `write_date`,
   `__last_update`, any field starting with `message_`.
4. Score by type: `char`/`selection`/`many2one` → 10; `float`/`integer`/`monetary` → 7;
   `date`/`datetime` → 5; `text` → 3; `one2many`/`many2many` → 4; others → 1.
5. Boost fields matching high-value patterns: `name`, `state`, `status`, `date`,
   `amount`, `email`, `phone`, `partner_id`, `user_id` → +5 bonus.
6. Sort by score descending, take top `max_fields`.
7. Return sorted field name list.

### Key Constraints
- Pure function — no async, no Odoo calls, no side effects.
- Must handle empty `fields_metadata` gracefully (return `["id", "display_name"]`).
- `always_include` parameter: if provided, these fields are always included
  (like `id`/`display_name`) and don't count against the cap.

---

## Acceptance Criteria

- [ ] `select_smart_fields(metadata)` returns ≤ 15 fields by default
- [ ] `id` and `display_name` always present in output
- [ ] Binary and HTML fields never appear in output
- [ ] `name`, `state`, `amount_total` rank higher than `create_uid`, `write_date`
- [ ] Empty metadata returns `["id", "display_name"]`
- [ ] `always_include=["custom_field"]` adds it regardless of score

---

## Test Specification

```python
# packages/ai-parrot/tests/test_odoo_smart_fields.py
from parrot_tools.odoo.smart_fields import select_smart_fields


def test_max_cap():
    meta = {f"field_{i}": {"type": "char", "string": f"F{i}"} for i in range(50)}
    meta["id"] = {"type": "integer", "string": "ID"}
    meta["display_name"] = {"type": "char", "string": "Display Name"}
    result = select_smart_fields(meta, max_fields=15)
    assert len(result) <= 17  # 15 + id + display_name

def test_always_includes_id_and_display_name():
    meta = {"name": {"type": "char", "string": "Name"}}
    result = select_smart_fields(meta)
    assert "id" in result
    assert "display_name" in result

def test_skips_binary_and_html():
    meta = {
        "name": {"type": "char", "string": "Name"},
        "image": {"type": "binary", "string": "Image"},
        "notes": {"type": "html", "string": "Notes"},
    }
    result = select_smart_fields(meta)
    assert "image" not in result
    assert "notes" not in result

def test_score_ranking():
    meta = {
        "name": {"type": "char", "string": "Name"},
        "state": {"type": "selection", "string": "Status"},
        "create_uid": {"type": "many2one", "string": "Created by"},
        "write_date": {"type": "datetime", "string": "Last Updated"},
    }
    result = select_smart_fields(meta, max_fields=2)
    assert result.index("name") < result.index("create_uid") or "create_uid" not in result

def test_empty_metadata():
    result = select_smart_fields({})
    assert result == ["id", "display_name"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §3 Module 1 and §7 "Smart Field Selection Algorithm"
2. **Check dependencies** — TASK-1013 must be done (but this task doesn't import from it)
3. **Create** `smart_fields.py` as a new file
4. **Run tests**: `pytest packages/ai-parrot/tests/test_odoo_smart_fields.py -v`
5. **Update status** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
