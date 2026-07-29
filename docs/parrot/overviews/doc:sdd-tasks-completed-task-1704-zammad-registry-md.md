---
type: Wiki Overview
title: 'TASK-1704: Register ZammadToolkit in TOOL_REGISTRY'
id: doc:sdd-tasks-completed-task-1704-zammad-registry-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The toolkit must be discoverable at runtime via `TOOL_REGISTRY` so that
relates_to:
- concept: mod:parrot_tools.jiratoolkit
  rel: mentions
- concept: mod:parrot_tools.workday.tool
  rel: mentions
- concept: mod:parrot_tools.zammad
  rel: mentions
- concept: mod:parrot_tools.zipcode
  rel: mentions
---

# TASK-1704: Register ZammadToolkit in TOOL_REGISTRY

**Feature**: FEAT-218 — Zammad Interface & Toolkit
**Spec**: `sdd/specs/zammad-interface-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1703
**Assigned-to**: unassigned

---

## Context

The toolkit must be discoverable at runtime via `TOOL_REGISTRY` so that
`ToolManager.register_toolkit("zammad")` resolves to `ZammadToolkit`.

Implements: Spec §3 Module 4 (Registry & Exports).

---

## Scope

- Add `"zammad": "parrot_tools.zammad.ZammadToolkit"` entry to `TOOL_REGISTRY` in
  `packages/ai-parrot-tools/src/parrot_tools/__init__.py`

**NOT in scope**: ZammadInterface, ZammadToolkit implementation, tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | Add entry to TOOL_REGISTRY dict |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# No new imports needed — just a dict entry
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/__init__.py
TOOL_REGISTRY: dict[str, str] = {                    # line 12
    "zipcode": "parrot_tools.zipcode.ZipcodeAPIToolkit",  # line 14 — pattern
    "jira": "parrot_tools.jiratoolkit.JiraToolkit",       # line 56 — pattern
    "workday": "parrot_tools.workday.tool.WorkdayToolkit", # line 24 — pattern
}
```

### Does NOT Exist
- ~~`AbstractToolkit.register()`~~ — no such method; TOOL_REGISTRY is a plain dict
- ~~`@register_toolkit("zammad")`~~ — no such decorator; use dict entry

---

## Implementation Notes

### Pattern to Follow
Add one line to the `TOOL_REGISTRY` dict:
```python
"zammad": "parrot_tools.zammad.ZammadToolkit",
```

Place it alphabetically near other entries, or at the end of the dict.

### Key Constraints
- The import path must match the actual module: `parrot_tools.zammad.ZammadToolkit`
- Entry must be a string (lazy import), not a direct import

---

## Acceptance Criteria

- [ ] `TOOL_REGISTRY["zammad"]` resolves to `"parrot_tools.zammad.ZammadToolkit"`
- [ ] `ToolkitRegistry.get("zammad")` returns `ZammadToolkit` class
- [ ] No linting errors

---

## Test Specification

```python
def test_zammad_in_registry():
    from parrot_tools import TOOL_REGISTRY
    assert "zammad" in TOOL_REGISTRY
    assert TOOL_REGISTRY["zammad"] == "parrot_tools.zammad.ZammadToolkit"
```

---

## Agent Instructions

When you pick up this task:

1. **Read** `packages/ai-parrot-tools/src/parrot_tools/__init__.py` to find the `TOOL_REGISTRY` dict
2. **Add** the `"zammad"` entry following the existing pattern
3. **Verify** TASK-1703 is complete (ZammadToolkit exists at the expected path)
4. **Commit** and update status

---

## Completion Note

Added `"zammad": "parrot_tools.zammad.ZammadToolkit"` to `TOOL_REGISTRY` in
`parrot_tools/__init__.py`, placed next to the `"odoo"` entry. Verified via
import that `TOOL_REGISTRY["zammad"] == "parrot_tools.zammad.ZammadToolkit"`.
Pre-existing `ruff` F401 findings on line 10 (`__title__`/`__description__`
unused) are unrelated to this change and predate this task.
