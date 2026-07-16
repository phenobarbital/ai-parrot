---
type: Wiki Overview
title: 'TASK-1405: ToolManager Grant Guard Integration'
id: doc:sdd-tasks-completed-task-1405-toolmanager-grant-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the most critical integration point. The `ToolManager.execute_tool()`
relates_to:
- concept: mod:parrot.auth.grants
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot.tools.manager
  rel: mentions
---

# TASK-1405: ToolManager Grant Guard Integration

**Feature**: FEAT-211 — Tool Grants & Bounded Approval Windows
**Spec**: `sdd/specs/FEAT-211-tool-grants-bounded-approval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1404
**Assigned-to**: unassigned

---

## Context

> Spec Module 3: ToolManager integration.

This is the most critical integration point. The `ToolManager.execute_tool()`
method is the central dispatch through which **all** agent tool calls flow.
This task adds the grant guard check at the correct insertion point: inside the
`isinstance(tool, AbstractTool)` branch, **before** the dispatch to
`tool.execute()`.

The change is **additive**: without a `GrantGuard` configured, `execute_tool`
behaves identically to today (zero regression). With a guard set, tools
marked `requires_grant` are gated before execution.

---

## Scope

- Modify `packages/ai-parrot/src/parrot/tools/manager.py`:
  - Add `set_grant_guard(guard)` setter (mirror of `set_resolver()` at line 285).
  - Add optional `get_grant_guard()` getter.
  - In `execute_tool()` (line 1126), inside the `isinstance(tool, AbstractTool)`
    branch (line 1169), insert the grant guard check **before** the dispatch to
    `tool.execute()` (line 1178).
- Write integration tests in `packages/ai-parrot/tests/tools/test_grants.py`
  (append to existing file from TASK-1403/1404).

**NOT in scope**:
- Grant models / GrantStore (TASK-1403)
- GrantGuard implementation (TASK-1404)
- Auth exports wiring (TASK-1406)
- Modifying `AbstractTool.execute()` — gating is in `ToolManager` only

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | Add set_grant_guard(), guard check in execute_tool() |
| `packages/ai-parrot/tests/tools/test_grants.py` | MODIFY | Add integration tests for ToolManager gating |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.

### Verified Imports
```python
# For type hints in manager.py:
from parrot.auth.grants import GrantGuard       # created by TASK-1404
from parrot.tools.abstract import AbstractTool, ToolResult  # verified: tools/abstract.py:81,46

# For tests:
from parrot.tools.manager import ToolManager    # verified: tools/manager.py:203
from parrot.auth.grants import (
    GrantGuard, GrantConfig, InMemoryGrantStore, GuardDecision,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/manager.py:203
class ToolManager(MCPToolManagerMixin):
    # Init sets self._resolver = None (among other things)
    # self._tools: Dict[str, Union[ToolDefinition, AbstractTool]]

    # LINE 285 — injection pattern to MIRROR:
    def set_resolver(self, resolver: "AbstractPermissionResolver") -> None:
        self._resolver = resolver
        self.logger.debug("Permission resolver set: %s", resolver.__class__.__name__)

    # LINE 1126 — method to MODIFY (additive):
    async def execute_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        permission_context: Optional["PermissionContext"] = None,
    ) -> Any:
        # ...
        # LINE 1154: tool = self._tools[tool_name]
        # LINE 1156: if isinstance(tool, ToolDefinition): ...  # simple functions — NO gating
        # LINE 1169: elif isinstance(tool, AbstractTool):      # ← INSERT GUARD HERE
        #   LINE 1172: exec_kwargs = dict(parameters)
        #   LINE 1173-1176: propagate _permission_context, _resolver
        #   LINE 1178: result = await tool.execute(**exec_kwargs)  # ← AFTER guard
        #   LINE 1183: if result.status == 'forbidden': return result

# packages/ai-parrot/src/parrot/tools/abstract.py:46
class ToolResult(BaseModel):
    success: bool = True
    status: str = "success"    # includes "forbidden"
    result: Any = None
    error: str | None = None
    # ...
```

### Does NOT Exist
- ~~`ToolManager._grant_guard`~~ — does not exist yet. This task adds it.
- ~~`ToolManager.set_grant_guard()`~~ — does not exist yet.
- ~~Guard check in `execute_tool`~~ — no grant-related logic exists there.
- ~~`AbstractTool.requires_grant`~~ — NOT an attribute. The flag lives in
  `tool.routing_meta["requires_grant"]` (dict key).
- ~~Modifying `AbstractTool.execute()`~~ — spec explicitly forbids this (G6).

---

## Implementation Notes

### Insertion Point (exact)

The guard check goes inside the `elif isinstance(tool, AbstractTool):` branch
(line 1169), right after the branch test and **before** `exec_kwargs`
construction (line 1172):

```python
# LINE 1169:
elif isinstance(tool, AbstractTool):
    # === NEW: Grant guard check (FEAT-211) ===
    if self._grant_guard is not None:
        decision = await self._grant_guard.authorize(
            tool=tool,
            parameters=parameters,
            permission_context=permission_context,
        )
        if not decision.allowed:
            return ToolResult(
                success=False,
                status='forbidden',
                error=f"Grant denied: {decision.reason}",
                result=None,
            )
    # === END grant guard ===

    # Existing code continues unchanged:
    exec_kwargs = dict(parameters)
    ...
```

### Setter Pattern (mirror set_resolver)
```python
def set_grant_guard(self, guard: "GrantGuard") -> None:
    """Set the grant guard for tool-level approval gating.

    When set, tools with routing_meta["requires_grant"] = True will
    require an active grant or HITL approval before execution.
    """
    self._grant_guard = guard
    self.logger.debug("Grant guard set: %s", guard.__class__.__name__)
```

### Key Constraints
- `self._grant_guard` must be initialized to `None` in `__init__`.
- The guard check MUST be inside the `isinstance(tool, AbstractTool)` branch ONLY.
  `ToolDefinition` (simple function wrappers) are NOT gated — they have no
  `routing_meta`.
- If guard is None (not configured), the existing flow is **completely unchanged**.
- The `ToolResult` for denial reuses the existing `status='forbidden'` pattern
  (lines 1183-1184 already handle this status downstream).
- Import `GrantGuard` with `TYPE_CHECKING` to avoid circular imports:
  ```python
  from typing import TYPE_CHECKING
  if TYPE_CHECKING:
      from parrot.auth.grants import GrantGuard
  ```

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/manager.py:285` — `set_resolver()` pattern to mirror
- `packages/ai-parrot/src/parrot/tools/manager.py:1169-1194` — `execute_tool` AbstractTool branch
- `packages/ai-parrot/src/parrot/tools/abstract.py:46` — `ToolResult` model

---

## Acceptance Criteria

- [ ] `ToolManager.set_grant_guard(guard)` sets the guard.
- [ ] `execute_tool` with guard + `requires_grant` tool: approved → executes normally.
- [ ] `execute_tool` with guard + `requires_grant` tool: denied → returns `ToolResult(status="forbidden")`.
- [ ] `execute_tool` with guard + non-gated tool → executes normally (no guard check).
- [ ] `execute_tool` WITHOUT guard → all tools execute as today (zero regression).
- [ ] Second call within window does NOT re-request HITL approval.
- [ ] `ToolDefinition` tools are never gated (no `routing_meta`).
- [ ] `self._grant_guard = None` in `__init__`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/test_grants.py -v -k "toolmanager"`.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/manager.py`.
- [ ] Existing tool tests still pass: `pytest packages/ai-parrot/tests/tools/ -v`.

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_grants.py (append to existing)
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.tools.manager import ToolManager
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.auth.grants import (
    GrantGuard, GrantConfig, InMemoryGrantStore, GuardDecision,
)


def _make_abstract_tool(name="pulumi_apply", requires_grant=True):
    """Create a mock AbstractTool with routing_meta."""
    tool = MagicMock(spec=AbstractTool)
    tool.name = name
    tool.routing_meta = {"requires_grant": requires_grant}
    tool.execute = AsyncMock(return_value=ToolResult(
        success=True, status="success", result="deployed",
    ))
    return tool


@pytest.mark.asyncio
class TestToolManagerGrantIntegration:
    async def test_no_guard_unaffected(self):
        """Without guard configured, all tools execute normally (zero regression)."""
        tm = ToolManager()
        tool = _make_abstract_tool(requires_grant=True)
        tm.register_tool(tool)
        # No guard set — requires_grant is ignored
        result = await tm.execute_tool("pulumi_apply", {})
        # Tool should execute (result depends on ToolManager internals,
        # but it should NOT return forbidden)
        assert result != ToolResult(status="forbidden")

    async def test_gates_requires_grant_approved(self):
        """Guard approves → tool executes normally."""
        tm = ToolManager()
        store = InMemoryGrantStore()
        hm = MagicMock()
        # Pre-approve
        await store.grant("user-1", "tool:pulumi_apply",
                          granted_by="admin", window_seconds=900)
        guard = GrantGuard(store, human_manager=hm)
        tm.set_grant_guard(guard)

        tool = _make_abstract_tool()
        tm.register_tool(tool)

        pctx = MagicMock()
        pctx.user_id = "user-1"
        result = await tm.execute_tool("pulumi_apply", {}, permission_context=pctx)
        # Should have executed the tool (not forbidden)
        tool.execute.assert_called_once()

    async def test_denied_returns_forbidden(self):
        """Guard denies → execute_tool returns ToolResult(status='forbidden')."""
        tm = ToolManager()
        store = InMemoryGrantStore()
        guard = GrantGuard(store, human_manager=None)  # no HITL → fail-closed
        tm.set_grant_guard(guard)

        tool = _make_abstract_tool()
        tm.register_tool(tool)

        pctx = MagicMock()
        pctx.user_id = "user-1"
        result = await tm.execute_tool("pulumi_apply", {}, permission_context=pctx)
        assert isinstance(result, ToolResult)
        assert result.status == "forbidden"
        tool.execute.assert_not_called()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-211-tool-grants-bounded-approval.spec.md` for full context
2. **Check dependencies** — verify TASK-1403 and TASK-1404 are completed
3. **Verify the Codebase Contract** — before writing ANY code:
   - Read `packages/ai-parrot/src/parrot/tools/manager.py` around lines 285 and 1126-1194
   - Confirm `set_resolver()` pattern at line 285
   - Confirm `isinstance(tool, AbstractTool)` branch at line 1169
   - Confirm `GrantGuard` exists in `parrot.auth.grants`
4. **Update status** in `sdd/tasks/index/tool-grants-bounded-approval.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met — including running existing tool tests
7. **Move this file** to `sdd/tasks/completed/TASK-1405-toolmanager-grant-integration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-06-01
**Notes**: Added `self._grant_guard = None` in `ToolManager.__init__`, added
`set_grant_guard()`/`get_grant_guard()` methods (mirror of `set_resolver()`),
and inserted the guard check in `execute_tool()` inside the
`isinstance(tool, AbstractTool)` branch before `exec_kwargs = dict(parameters)`.
TYPE_CHECKING import added for `GrantGuard`. Integration tests updated to use
`spec=AbstractTool` for correct mock dispatch. 4/4 integration tests pass.

**Deviations from spec**: None. The `get_grant_guard()` getter was added as
specified in the task.
