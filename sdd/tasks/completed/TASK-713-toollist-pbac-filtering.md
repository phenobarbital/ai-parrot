# TASK-713: ToolList PBAC Filtering

**Feature**: policy-rules-abstractbot
**Spec**: `sdd/specs/policy-rules-abstractbot.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-712
**Assigned-to**: unassigned

---

## Context

> Adds PBAC-based filtering to the ToolList handler so users only see tools they're
> authorized to access via `tool:list` action. Implements Spec Module 7.

---

## Scope

- Modify `ToolList.get()` (bots.py:1015):
  1. After `discover_all()`, collect all tool names.
  2. Get evaluator from `self.request.app.get('abac')`.
  3. If evaluator exists, build EvalContext (reuse the `_build_eval_context` helper added
     in TASK-712 — extract it to a shared utility or duplicate the pattern).
  4. Call `evaluator.filter_resources(ctx, ResourceType.TOOL, tool_names, "tool:list")`.
  5. Filter the tools dict to only include allowed tool names.
  6. If no evaluator → return all tools (fail-open).
- Write unit tests.

**NOT in scope**: Per-agent tool filtering, tool execution filtering, ChatbotHandler.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/bots.py` | MODIFY | Add PBAC filtering to ToolList.get() |
| `tests/handlers/test_toollist_pbac.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Same navigator-auth imports as TASK-712 (module-level guards already added)
# ResourceType.TOOL for tool filtering
```

### Existing Signatures to Use
```python
# parrot/handlers/bots.py:1010-1041
@user_session()
class ToolList(BaseView):
    async def get(self):
        try:
            raw = discover_all()
            tools = {}
            for name, value in raw.items():
                if isinstance(value, str):
                    tools[name] = {"tool_name": name, "module_path": value}
                else:
                    tools[name] = {
                        "tool_name": getattr(value, "name", name),
                        "module_path": f"{value.__module__}.{value.__qualname__}",
                        "description": getattr(value, "description", value.__doc__ or ""),
                    }
            return self.json_response({"tools": tools})
```

### Does NOT Exist
- ~~`ToolList._build_eval_context()`~~ — does not exist; use pattern from TASK-712
- ~~`ToolManager.filter_by_policy()`~~ — does not exist
- ~~`discover_all_filtered()`~~ — does not exist

---

## Implementation Notes

### Key Constraints
- ToolList inherits from `BaseView`, not `AbstractModel` — it has `self.request` available.
- Build eval context inline or extract a shared helper from TASK-712's work.
- Filter AFTER `discover_all()` but BEFORE building the response dict (avoid unnecessary processing).
- Fail-open: return all tools if PDP not available.

---

## Acceptance Criteria

- [ ] `ToolList.get()` filters tools via `evaluator.filter_resources()` when PDP available
- [ ] Returns all tools when PDP absent (fail-open)
- [ ] Tests pass: `pytest tests/handlers/test_toollist_pbac.py -v`

---

## Test Specification

```python
# tests/handlers/test_toollist_pbac.py
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestToolListPBAC:
    async def test_get_filters_denied_tools(self):
        """get() excludes tools denied by PBAC."""

    async def test_get_no_pbac_returns_all(self):
        """get() returns all tools when PDP absent."""

    async def test_get_empty_tools(self):
        """get() handles empty tool list gracefully."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/policy-rules-abstractbot.spec.md`
2. **Check dependencies** — verify TASK-712 is done
3. **Verify** `ToolList.get()` is still at bots.py:1015
4. **Implement** filtering
5. **Move** to `tasks/completed/` and update index

---

## Completion Note

*(Agent fills this in when done)*
