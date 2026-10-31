# TASK-5083: Roost callers bind the call's PermissionContext and catch GrantDenied

**Feature**: FEAT-786 — fixgroup-0a1d456b8ed9
**Spec**: `sdd/specs/fixgroup-0a1d456b8ed9.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: none
**Assigned-to**: agent:sdd-fix
**Discovered-from**: `issue:562a840c56ef`

---

## Context

Spec §1–2. After the fail-closed `RoostEndpoint` (PR #1867), `AgentTool._execute_roost` and
`AgentSwarmToolkit._ask_via_roost` let `GrantDenied` escape and never publish the tool call's
`PermissionContext` to `_pctx_var`, so the endpoint refuses every call outside paths that bind it.

## Scope

- `agent.py`: in `_execute_roost`, bind `self._current_pctx` on `_pctx_var` around `caller.query`
  (only when not `None`; `reset` in `finally`); catch `GrantDenied` → `f"Error: grant denied: {exc}"`.
- `swarm_toolkit.py`: module-level `_CALL_PCTX: ContextVar` captured in an `_pre_execute` override
  (call `super()._pre_execute` first); `_ask_via_roost` binds it the same way; `GrantDenied` →
  `{"status": "refused", "detail": f"grant denied: {exc}"}`.
- Tests in the two Validation Contract files (spec §4 table).

**NOT in scope**: spec §1 Non-Goals.

## Files to Modify

| File | Action |
|---|---|
| `packages/ai-parrot/src/parrot/tools/agent.py` | MODIFY |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py` | MODIFY |
| `packages/ai-parrot/tests/roost/test_agent_tool_roost.py` | MODIFY |
| `packages/ai-parrot-integrations/tests/test_matrix_roost_ask_agent.py` | MODIFY |

## Codebase Contract

See spec §6 (verified against `ebcde58da6`).

## Acceptance Criteria

See spec §5.

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src pytest -q \
  packages/ai-parrot/tests/roost/test_agent_tool_roost.py \
  packages/ai-parrot-integrations/tests/test_matrix_roost_ask_agent.py \
  packages/ai-parrot-integrations/tests/test_matrix_swarm_toolkit.py
```

## Completion Note

(pending)
