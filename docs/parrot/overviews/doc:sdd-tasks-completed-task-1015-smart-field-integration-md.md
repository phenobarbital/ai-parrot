---
type: Wiki Overview
title: 'TASK-1015: Wire Smart Field Selection into search_records & get_record'
id: doc:sdd-tasks-completed-task-1015-smart-field-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: With `select_smart_fields` implemented (TASK-1014), this task wires it into
  the
---

# TASK-1015: Wire Smart Field Selection into search_records & get_record

**Feature**: FEAT-147 — Evaluate Odoo MCP Toolkit
**Spec**: `sdd/specs/evaluate-odoo-mcp-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1013, TASK-1014
**Assigned-to**: unassigned

---

## Context

With `select_smart_fields` implemented (TASK-1014), this task wires it into the
existing `search_records` and `get_record` methods so they auto-select fields when
the caller omits `fields`. Also adds a per-model `fields_get` cache to avoid
redundant RPC calls.

Implements spec §3 Module 2: Smart Field Integration.

---

## Scope

- Add `_fields_cache: dict[str, dict]` attribute to `OdooToolkit.__init__`
- Add private `async def _get_fields_metadata(self, model: str) -> dict` that
  checks cache, calls `fields_get` on miss, and caches the result
- Modify `search_records`: when `fields is None`, call `_get_fields_metadata` →
  `select_smart_fields`, pass result as `fields`, set `FieldSelectionMetadata.field_selection_method = "auto"`
- Modify `get_record`: same smart-field fallback
- Update `FieldSelectionMetadata` reporting in both methods

**NOT in scope**: New toolkit methods, the smart_fields module itself (TASK-1014).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | MODIFY | Add `_fields_cache`, `_get_fields_metadata`, modify `search_records` and `get_record` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# New import to add at top of toolkit.py:
from .smart_fields import select_smart_fields  # created in TASK-1014

# Existing (already imported in toolkit.py):
from .models.envelopes import FieldSelectionMetadata  # envelopes.py:14
from .models.envelopes import SearchResult            # envelopes.py:52
from .models.envelopes import RecordResult            # envelopes.py:63
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py
class OdooToolkit(AbstractToolkit):                        # line 127
    def __init__(self, ...):                               # line 148
        self._auth_lock = asyncio.Lock()                   # line 185
        self.logger = logging.getLogger("OdooToolkit")     # line 186

    async def fields_get(self, model, attributes=None) -> dict:  # line 327
    async def search_records(self, model, domain=None, fields=None, limit=100, offset=0, order=None) -> SearchResult:  # line 341
    async def get_record(self, model, record_id, fields=None) -> RecordResult:  # line 368

# envelopes.py:14
class FieldSelectionMetadata(BaseModel):
    fields_returned: int
    field_selection_method: str    # "requested" | "all" | "auto" (NEW value)
    total_fields_available: Optional[int]
    note: Optional[str]
```

### Does NOT Exist
- ~~`OdooToolkit._fields_cache`~~ — must be added in `__init__`
- ~~`OdooToolkit._get_fields_metadata()`~~ — must be created
- ~~`OdooToolkit._smart_fields_enabled`~~ — no such flag; smart fields are always on when `fields is None`

---

## Implementation Notes

### Pattern for `_get_fields_metadata`
```python
async def _get_fields_metadata(self, model: str) -> dict[str, Any]:
    if model not in self._fields_cache:
        self._fields_cache[model] = await self.fields_get(model)
    return self._fields_cache[model]
```

### Modification to `search_records`
```python
# Before the _execute call, add:
auto_selected = False
if fields is None:
    meta = await self._get_fields_metadata(model)
    fields = select_smart_fields(meta)
    auto_selected = True

# In the return, update metadata:
# field_selection_method = "auto" if auto_selected else ("requested" if original_fields else "all")
```

### Key Constraints
- Do NOT change the method signatures (keep `fields: Optional[list[str]] = None`)
- The cache is per-toolkit-instance (dict on `self`), no TTL needed
- `FieldSelectionMetadata` gains a new `field_selection_method` value: `"auto"`
- The `total_fields_available` field should be set to `len(meta)` when auto-selecting

---

## Acceptance Criteria

- [ ] `search_records(model="res.partner")` without `fields` uses smart selection
- [ ] `search_records(model="res.partner", fields=["name"])` uses explicit fields
- [ ] `get_record(model="res.partner", record_id=1)` without `fields` uses smart selection
- [ ] `metadata.field_selection_method == "auto"` when smart fields are used
- [ ] `metadata.total_fields_available` is set when auto-selecting
- [ ] `fields_get` is called only once per model (cache works)

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_search_records_auto_fields(odoo_toolkit_with_mock_transport):
    tk = odoo_toolkit_with_mock_transport
    tk._transport.execute_kw = AsyncMock(side_effect=[
        # fields_get call
        {"name": {"type": "char"}, "state": {"type": "selection"}, "image": {"type": "binary"}},
        # search_read call
        [{"id": 1, "name": "Test", "state": "draft"}],
        # search_count call
        1,
    ])
    result = await tk.search_records(model="res.partner")
    assert result.metadata is not None or result.fields is not None

@pytest.mark.asyncio
async def test_search_records_explicit_fields(odoo_toolkit_with_mock_transport):
    tk = odoo_toolkit_with_mock_transport
    tk._transport.execute_kw = AsyncMock(side_effect=[
        [{"id": 1, "name": "Test"}],
        1,
    ])
    result = await tk.search_records(model="res.partner", fields=["name"])
    # fields_get should NOT have been called
    assert result.fields == ["name"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read** `toolkit.py` lines 127-380 for full context
2. **Verify** TASK-1013 and TASK-1014 are done
3. **Modify** `__init__` to add `self._fields_cache = {}`
4. **Add** `_get_fields_metadata` private method
5. **Modify** `search_records` and `get_record` to use smart-field fallback
6. **Run tests**: `pytest packages/ai-parrot/tests/test_odoo_toolkit.py -v`

---

## Completion Note

*(Agent fills this in when done)*
