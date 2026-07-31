---
type: Wiki Overview
title: 'TASK-1019: Model Introspection & Diagnostics (inspect_model_relationships,
  diagnose_access, health_check)'
id: doc:sdd-tasks-completed-task-1019-introspection-and-diagnostics-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Agents need to understand model schemas (which fields are relational, which
  are
---

# TASK-1019: Model Introspection & Diagnostics (inspect_model_relationships, diagnose_access, health_check)

**Feature**: FEAT-147 — Evaluate Odoo MCP Toolkit
**Spec**: `sdd/specs/evaluate-odoo-mcp-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1013, TASK-1015
**Assigned-to**: unassigned

---

## Context

Agents need to understand model schemas (which fields are relational, which are
required) and diagnose access issues without guessing. This task adds three
introspection/diagnostic tools.

Implements spec §3 Module 6: Model Introspection & Diagnostics.

---

## Scope

- Add `inspect_model_relationships` async method: calls `fields_get` and partitions
  fields by relation type (many2one, one2many, many2many), lists required fields,
  and provides create/write hints
- Add `diagnose_access` async method: queries `ir.model.access` for ACL rows and
  `ir.rule` for record rules applying to the given model/operation, reports user
  groups, and produces a human-readable diagnosis string
- Add `health_check` method (synchronous): reports toolkit version, transport,
  connection status, and tool count without making any Odoo network call
- Decorate each with `@tool_schema`
- Return `ModelRelationshipsResult`, `AccessDiagnosisResult`, `HealthCheckResult`

**NOT in scope**: `get_odoo_profile`, `schema_catalog` (TASK-1018).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | MODIFY | Add three methods |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .models.inputs import (
    InspectModelRelationshipsInput, DiagnoseAccessInput,
)  # TASK-1013
from .models.envelopes import (
    ModelRelationshipsResult, AccessDiagnosisResult, HealthCheckResult,
)  # TASK-1013
```

### Existing Signatures to Use
```python
# toolkit.py:228
async def _execute(self, model, method, args=None, kwargs=None) -> Any:

# toolkit.py:327
async def fields_get(self, model, attributes=None) -> dict[str, Any]:

# TASK-1015 adds:
async def _get_fields_metadata(self, model: str) -> dict:
```

### Does NOT Exist
- ~~`OdooToolkit.inspect_model_relationships()`~~ — must be created
- ~~`OdooToolkit.diagnose_access()`~~ — must be created
- ~~`OdooToolkit.health_check()`~~ — must be created

---

## Implementation Notes

### inspect_model_relationships
1. Call `_get_fields_metadata(model)` to get all field definitions
2. Partition fields by `type`:
   - `"many2one"` → `many2one` list (include `relation`, `required`, `string`)
   - `"one2many"` → `one2many` list (include `relation`, `relation_field`)
   - `"many2many"` → `many2many` list (include `relation`)
3. Required fields: filter where `required=True`
4. Create hints: list fields that are `required` and not `readonly`

### diagnose_access
1. Query `ir.model.access` for the model:
   `_execute("ir.model.access", "search_read", [[("model_id.model", "=", model)]], {fields: [...]})`
2. Check ACL for the given operation (map `"read"` → `"perm_read"`, etc.)
3. Query `ir.rule` for record rules:
   `_execute("ir.rule", "search_read", [[("model_id.model", "=", model)]], {fields: [...]})`
4. Query current user's groups:
   `_execute("res.users", "read", [[transport.uid]], {fields: ["groups_id"]})`
5. Produce diagnosis: "acl_allowed", "acl_denied_likely", "record_rule_filter_likely", etc.
6. **Handle AccessError gracefully**: non-admin users may not be able to read `ir.rule`.
   Catch `OdooRPCError` and report "unable to read record rules" in diagnosis.

### health_check
Synchronous method. Reports:
- `toolkit_version`: hardcode or read from package metadata
- `transport`: `self.protocol`
- `connected`: `self._transport is not None and self._transport.uid is not None`
- `write_permissions`: list of `@requires_permission` values on write methods
- `tool_count`: `len(self.get_tools())`

### Key Constraints
- All three methods are read-only
- `diagnose_access` must not use `sudo` or impersonation
- `health_check` must not make any Odoo network call

---

## Acceptance Criteria

- [ ] `inspect_model_relationships("res.partner")` groups fields correctly
- [ ] Lists required fields and create hints
- [ ] `diagnose_access("res.partner", "read")` queries ACL and rules
- [ ] Returns human-readable diagnosis string
- [ ] Handles `OdooRPCError` on `ir.rule` gracefully
- [ ] `health_check()` returns result without Odoo call

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_inspect_relationships(odoo_toolkit):
    # Mock _get_fields_metadata to return diverse field types
    result = await tk.inspect_model_relationships(model="res.partner")
    assert isinstance(result, ModelRelationshipsResult)
    assert len(result.many2one) > 0

@pytest.mark.asyncio
async def test_diagnose_access_allowed(odoo_toolkit):
    # Mock ir.model.access query returning perm_read=True
    result = await tk.diagnose_access(model="res.partner", operation="read")
    assert result.acl_allowed is True

def test_health_check(odoo_toolkit):
    result = tk.health_check()
    assert isinstance(result, HealthCheckResult)
    assert result.transport in ("auto", "json2", "jsonrpc", "xmlrpc")
```

---

## Completion Note

*(Agent fills this in when done)*
