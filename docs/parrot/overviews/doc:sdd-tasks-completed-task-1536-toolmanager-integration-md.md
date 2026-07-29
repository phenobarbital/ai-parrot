---
type: Wiki Overview
title: 'TASK-1536: ToolManager integration (dispatch gate)'
id: doc:sdd-tasks-completed-task-1536-toolmanager-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §2 Integration Points + §3 Module 3. Wires `ConfirmationGuard` into
relates_to:
- concept: mod:parrot.tools.abstract
  rel: mentions
---

# TASK-1536: ToolManager integration (dispatch gate)

**Feature**: FEAT-235 — HITL Tool-Call Confirmation
**Spec**: `sdd/specs/hitl-confirmation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1534
**Assigned-to**: unassigned

---

## Context

Spec §2 Integration Points + §3 Module 3. Wires `ConfirmationGuard` into
`ToolManager` symmetrically to the existing `GrantGuard` (FEAT-211), invoking it in
`execute_tool()` **after** the grant check and **before** `tool.execute()`. Dispatch
order is locked **grant → confirm**. The no-guard path must be unchanged.

---

## Scope

- In `parrot/tools/manager.py`:
  - Add `self._confirmation_guard: Optional["ConfirmationGuard"] = None` in
    `__init__` (next to `self._grant_guard`, manager.py:250).
  - Add `def set_confirmation_guard(self, guard) -> None` and a
    `@property confirmation_guard` (mirror `set_grant_guard`:307 / `grant_guard`:324).
  - In the `elif isinstance(tool, AbstractTool):` branch of `execute_tool()`
    (manager.py:1200), AFTER the grant block (ends ~1218) and BEFORE building
    `exec_kwargs` (1222), add a purely-additive block:
    ```python
    if self._confirmation_guard is not None:
        decision = await self._confirmation_guard.confirm(
            tool=tool, parameters=parameters,
            permission_context=permission_context,
        )
        if not decision.allowed:
            return ToolResult(
                success=False, status=decision.status,   # "cancelled" | "timeout"
                error=f"Confirmation {decision.status}: {decision.reason}",
                result=None,
            )
        if decision.parameters is not None:
            parameters = decision.parameters   # use edited/re-validated params
    ```
  - Ensure the subsequent `exec_kwargs = dict(parameters)` (1222) picks up the
    (possibly edited) `parameters`.
- Tests in `packages/ai-parrot/tests/test_toolmanager_confirmation.py`.

**NOT in scope**: guard internals (TASK-1534/1535); decorator/spawn (TASK-1537);
exports/docs (TASK-1538). Do NOT alter the grant block.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | setter/property + confirm block in `execute_tool()` |
| `packages/ai-parrot/tests/test_toolmanager_confirmation.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# at top of manager.py, alongside the TYPE_CHECKING GrantGuard import (manager.py:18):
from ..auth.confirmation import ConfirmationGuard   # mirror the GrantGuard import style
from parrot.tools.abstract import ToolResult        # tools/abstract.py:46 (already in scope)
```

### Existing Signatures to Use
```python
# parrot/tools/manager.py
# __init__:
self._grant_guard: Optional["GrantGuard"] = None         # line 250  (add confirmation peer here)
# wiring to mirror:
def set_grant_guard(self, guard: "GrantGuard") -> None:   # line 307
@property
def grant_guard(self) -> Optional[GrantGuard]:            # line 324
# dispatch block (insert confirm AFTER this, before exec_kwargs):
elif isinstance(tool, AbstractTool):                      # line 1200
    if self._grant_guard is not None:                     # line 1205
        decision = await self._grant_guard.authorize(...)  # line 1206
        if not decision.allowed:
            return ToolResult(success=False, status="forbidden", ...)  # line 1212
    # === insert confirmation block here ===
    exec_kwargs = dict(parameters)                        # line 1222
    result = await tool.execute(**exec_kwargs)            # line 1228
    if isinstance(result, ToolResult):
        if result.status == 'forbidden':                  # line 1233 (returned directly)
            return result

# parrot/auth/confirmation.py (from TASK-1534)
class ConfirmationDecision(BaseModel):
    allowed: bool; status: str; reason: str; parameters: Optional[Dict[str, Any]]
class ConfirmationGuard:
    async def confirm(self, *, tool, parameters, permission_context=None) -> ConfirmationDecision: ...
```

### Does NOT Exist
- ~~`ToolManager.confirmation_guard` / `set_confirmation_guard`~~ — this task ADDS them.
  Only `grant_guard` / `set_grant_guard` exist today (manager.py:307,324).
- ~~A confirmation hook anywhere else in `execute_tool()`~~ — the ONLY insertion
  point is the `isinstance(tool, AbstractTool)` branch at manager.py:1200, after grant.
- Do NOT confuse with the OTHER `isinstance(tool, AbstractTool)` branches at
  manager.py:421 and 601 — those are not the execution dispatch.

---

## Implementation Notes

### Key Constraints
- Purely additive: when `self._confirmation_guard is None`, behavior is identical to
  today (assert this with a regression test).
- Order MUST be grant → confirm.
- Reuse the existing special-casing of `forbidden` results; the confirm path returns
  `cancelled`/`timeout`, which flow back as normal `ToolResult`s to the caller/LLM.
- `HumanInteractionInterrupt` raised by SUSPEND propagates out of `confirm()` —
  do NOT catch it in `execute_tool()`; let it bubble (matches existing suspend flow).

### References in Codebase
- `parrot/tools/manager.py:307-330, 1200-1234` — wiring + dispatch.
- `parrot/auth/grants.py` — sibling guard semantics.

---

## Acceptance Criteria

- [ ] `ToolManager.set_confirmation_guard()` + `confirmation_guard` property exist and mirror the grant equivalents.
- [ ] With a guard set, a `requires_confirmation` tool that is approved executes normally.
- [ ] Rejected → `ToolResult(success=False, status="cancelled")` returned; no execution.
- [ ] Timeout → `ToolResult(success=False, status="timeout")`.
- [ ] Edited params from the decision are passed to `tool.execute()`.
- [ ] No guard set → dispatch identical to current behavior (regression test).
- [ ] grant → confirm order verified when a tool requires both.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_toolmanager_confirmation.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/tools/manager.py`

---

## Test Specification
```python
# packages/ai-parrot/tests/test_toolmanager_confirmation.py
# - build a ToolManager, register a confirming AbstractTool
# - set_confirmation_guard(guard with a stubbed manager that approves/rejects)
# - assert execute path: approve → real result; reject → status=="cancelled"
# - assert no-guard regression: same tool runs without prompting
```

---

## Agent Instructions
1. Read spec §2/§6. 2. `read` manager.py around 250/307/1200 to confirm line context.
3. Index → `in-progress`. 4. Implement (additive only) + verify. 5. Move to completed, index → `done`, note.

---

## Completion Note
**Completed by**: SDD Worker (Claude Sonnet 4.6)
**Date**: 2026-06-12
**Notes**: Added _confirmation_guard attribute, set_confirmation_guard()/confirmation_guard
property, and confirmation block in execute_tool() after the grant block and before
exec_kwargs. Grant→confirm ordering verified. No-guard regression tested. All 8 tests pass.
**Deviations from spec**: none
