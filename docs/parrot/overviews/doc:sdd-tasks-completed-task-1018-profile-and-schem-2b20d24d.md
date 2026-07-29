---
type: Wiki Overview
title: 'TASK-1018: Odoo Profile & Schema Catalog'
id: doc:sdd-tasks-completed-task-1018-profile-and-schema-catalog-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Agents need a comprehensive environment snapshot (`get_odoo_profile`) and
  a way to
---

# TASK-1018: Odoo Profile & Schema Catalog

**Feature**: FEAT-147 — Evaluate Odoo MCP Toolkit
**Spec**: `sdd/specs/evaluate-odoo-mcp-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1013, TASK-1015
**Assigned-to**: unassigned

---

## Context

Agents need a comprehensive environment snapshot (`get_odoo_profile`) and a way to
browse available models (`schema_catalog`). These complement the existing `server_info`
and `list_models` with richer data.

Implements spec §3 Module 5: Profile & Schema Catalog.

---

## Scope

- Add `get_odoo_profile` async method: returns server version, user context
  (`res.users` context_get), transport info, database, and installed modules
  (bounded by `module_limit`)
- Add `schema_catalog` async method: queries `ir.model` with optional substring
  filter (`query`), explicit model list (`models`), optional field metadata
  (`include_fields`), and a limit cap
- Decorate both with `@tool_schema`
- Return `OdooProfileResult` and `SchemaCatalogResult` envelopes

**NOT in scope**: `inspect_model_relationships`, `diagnose_access`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | MODIFY | Add `get_odoo_profile`, `schema_catalog` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .models.inputs import GetOdooProfileInput, SchemaCatalogInput  # TASK-1013
from .models.envelopes import OdooProfileResult, SchemaCatalogResult  # TASK-1013

# Existing:
from .models.envelopes import ServerInfoResult  # envelopes.py:154
```

### Existing Signatures to Use
```python
# toolkit.py:228
async def _execute(self, model, method, args=None, kwargs=None) -> Any:

# toolkit.py:282
async def server_info(self) -> ServerInfoResult:

# toolkit.py:327
async def fields_get(self, model, attributes=None) -> dict[str, Any]:

# TASK-1015 adds:
async def _get_fields_metadata(self, model: str) -> dict:
```

### Does NOT Exist
- ~~`OdooToolkit.get_odoo_profile()`~~ — must be created
- ~~`OdooToolkit.schema_catalog()`~~ — must be created
- ~~`OdooToolkit._schema_cache`~~ — no cache exists; implement if needed

---

## Implementation Notes

### get_odoo_profile
1. Call `server_info()` for version/transport
2. Call `_execute("res.users", "context_get", [])` for user context
3. Call `_execute("ir.module.module", "search_read", [domain], {fields, limit})`
   with `domain=[("state", "=", "installed")]` for installed modules
4. Assemble into `OdooProfileResult`

### schema_catalog
1. Build domain for `ir.model`:
   - If `query`: `[("model", "ilike", query)]`
   - If `models` list: `[("model", "in", models)]`
   - Otherwise: `[]` (all models)
2. Call `_execute("ir.model", "search_read", [domain], {fields: ["model", "name", "info"], limit})`
3. If `include_fields=True`, call `fields_get` for each model (use `_get_fields_metadata`)
4. Return `SchemaCatalogResult`

### Key Constraints
- `module_limit` capped at 500
- `schema_catalog` limit capped at 500
- Both methods are read-only

---

## Acceptance Criteria

- [ ] `get_odoo_profile()` returns version, user_context, transport, modules
- [ ] `get_odoo_profile(include_modules=False)` skips module query
- [ ] `schema_catalog(query="sale")` filters models containing "sale"
- [ ] `schema_catalog(include_fields=True)` includes field metadata
- [ ] `schema_catalog(limit=5)` returns at most 5 models

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_get_odoo_profile(odoo_toolkit):
    # Mock _execute for context_get and module search_read
    result = await tk.get_odoo_profile()
    assert isinstance(result, OdooProfileResult)
    assert result.server_version

@pytest.mark.asyncio
async def test_schema_catalog_with_query(odoo_toolkit):
    # Mock _execute for ir.model search_read
    result = await tk.schema_catalog(query="sale")
    assert isinstance(result, SchemaCatalogResult)
```

---

## Completion Note

*(Agent fills this in when done)*
