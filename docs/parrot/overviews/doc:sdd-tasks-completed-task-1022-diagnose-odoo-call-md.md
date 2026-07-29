---
type: Wiki Overview
title: 'TASK-1022: Diagnose Odoo Call (Phase 2)'
id: doc:sdd-tasks-completed-task-1022-diagnose-odoo-call-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Agents need to preview/debug a failing Odoo call without executing it. This
  method
relates_to:
- concept: mod:parrot_tools.odoo
  rel: mentions
---

# TASK-1022: Diagnose Odoo Call (Phase 2)

**Feature**: FEAT-147 — Evaluate Odoo MCP Toolkit
**Spec**: `sdd/specs/evaluate-odoo-mcp-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1013, TASK-1015
**Assigned-to**: unassigned

---

## Context

Agents need to preview/debug a failing Odoo call without executing it. This method
validates model names, classifies method safety, checks transport compatibility, and
flags Odoo 20 deprecation warnings.

Implements spec §3 Module 10: Call Diagnostics.

---

## Scope

- Add `diagnose_odoo_call` method to `OdooToolkit` (synchronous — no Odoo call)
- Define constants: `READ_ONLY_METHODS`, `DESTRUCTIVE_METHODS`
- Implement model name validation (regex: `^[a-z][a-z0-9_.]*$`)
- Classify method safety: read_only / destructive / side_effect / unknown
- Check transport compatibility: warn if JSON-2 method not in known mapping
- Flag Odoo 20 deprecation: warn about XML-RPC removal if `target_version >= "20"`
- Decorate with `@tool_schema(DiagnoseOdooCallInput)`
- Return `OdooCallDiagnosisResult` envelope

**NOT in scope**: Actually executing the call, `generate_json2_payload`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | MODIFY | Add `diagnose_odoo_call`, constants |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .models.inputs import DiagnoseOdooCallInput       # TASK-1013
from .models.envelopes import OdooCallDiagnosisResult  # TASK-1013
import re  # stdlib
```

### Does NOT Exist
- ~~`OdooToolkit.diagnose_odoo_call()`~~ — must be created
- ~~`parrot_tools.odoo.diagnostics`~~ — no such module; logic goes in toolkit.py

---

## Implementation Notes

### Constants
```python
READ_ONLY_METHODS = frozenset({
    "search", "search_count", "search_read", "read",
    "fields_get", "name_get", "name_search", "context_get",
})
DESTRUCTIVE_METHODS = frozenset({"create", "write", "unlink"})
_MODEL_NAME_RE = re.compile(r"^[a-z][a-z0-9_.]*$")
```

### Method Safety Classification
```python
if method in READ_ONLY_METHODS:
    safety = "read_only"
elif method in DESTRUCTIVE_METHODS:
    safety = "destructive"
elif method.startswith("action_") or method.startswith("button_"):
    safety = "side_effect"
else:
    safety = "unknown"
```

### Transport Compatibility
- If `transport == "json2"` and method has no known JSON-2 arg mapping → warning
- If `target_version >= "20"` and `transport in ("xmlrpc", "jsonrpc")` → deprecation warning

### Key Constraints
- Pure function — no Odoo network call
- Method is synchronous (not async)
- `observed_error` is optional; when provided, included in diagnosis for context

---

## Acceptance Criteria

- [ ] `diagnose_odoo_call(model="res.partner", method="search_read")` → safety="read_only"
- [ ] `diagnose_odoo_call(model="res.partner", method="unlink")` → safety="destructive"
- [ ] Invalid model name (e.g., `"DROP TABLE"`) → warning in result
- [ ] `target_version="20"`, `transport="xmlrpc"` → deprecation warning
- [ ] Returns `OdooCallDiagnosisResult` envelope

---

## Test Specification

```python
def test_diagnose_call_read_only():
    result = tk.diagnose_odoo_call(model="res.partner", method="search_read")
    assert result.method_safety == "read_only"

def test_diagnose_call_destructive():
    result = tk.diagnose_odoo_call(model="res.partner", method="unlink")
    assert result.method_safety == "destructive"

def test_diagnose_call_bad_model():
    result = tk.diagnose_odoo_call(model="DROP TABLE", method="search_read")
    assert len(result.warnings) > 0

def test_diagnose_call_odoo20_deprecation():
    result = tk.diagnose_odoo_call(
        model="res.partner", method="read",
        transport="xmlrpc", target_version="20",
    )
    assert any("deprecat" in w.lower() for w in result.warnings)
```

---

## Completion Note

*(Agent fills this in when done)*
