---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-integrations]
tags: [roost, auth, pbac, tools, matrix, ledger-fix]
---

# Feature Specification: fixgroup-0a1d456b8ed9

**Feature ID**: FEAT-786
**Date**: 2026-11-01
**Author**: Jesus Lara (with Claude Opus 5.5, via /sdd-fix)
**Status**: approved
**Target version**: 1.2.6

> **Source**: work-ledger group `fixgroup:0a1d456b8ed9`, routed to the SDD lane by
> `wikitoolkit ledger plan-fix` (major severity). Resolves `issue:562a840c56ef`, a follow-up to
> `issue:59d1cb0c9814` (fail-closed `RoostEndpoint`, merged in PR #1867, commit `572db7599`).

---

## 1. Motivation & Business Requirements

### Problem Statement

`RoostEndpoint` now fails closed: `query(receiver=)` raises `GrantDenied` for a receiver outside the
caller's grant, and a serving `_run_tool` answers `failure(POLICY)` when no caller authority resolves.
The caller authority comes from the endpoint's constructor `permission_context=` or, failing that, the
request-scoped `parrot.auth.context._pctx_var` (`RoostEndpoint._caller_authority`).

Two in-tree callers were not adapted:

1. `AgentTool._execute_roost` (`parrot/tools/agent.py`) catches only `RoostFailure`. `GrantDenied` is a
   plain `Exception` (`roost/grant.py`), so a denied query escapes the handler that turns Roost errors
   into a returned error string.
2. Neither `AgentTool` nor `AgentSwarmToolkit._ask_via_roost`
   (`parrot/integrations/matrix/crew/swarm_toolkit.py`) publishes the tool call's `PermissionContext` to
   `_pctx_var`. `ToolManager` hands that context to the tool (`_permission_context`), but outside the
   few paths that bind `_pctx_var` themselves (MCP agent mount, msagentsdk, DatasetManager) the endpoint
   resolves no authority and the call is refused.
3. `AgentSwarmToolkit._ask_via_roost` also catches only `RoostFailure`.

Both Roost paths are opt-in (nothing in-tree sets `AgentTool.roost_caller`/`agent.roost_endpoint`, and
`MatrixCrewTransport` builds the toolkit without `endpoint=`), so this affects deployments that enable
them, not the default wiring.

### Goals
- A denied grant becomes the caller's normal error result in both callers (error string for `AgentTool`,
  `{"status": "refused", ...}` for the swarm toolkit), never an escaping exception.
- The tool call's own `PermissionContext` reaches the endpoint for the duration of the `query`, bound
  with `ContextVar.set`/`reset` so it never leaks into later work in the same task and concurrent calls
  never see each other's context.
- An already-bound `_pctx_var` (e.g. from the MCP mount) is left untouched when the call has no context.

### Non-Goals (explicitly out of scope)
- Constructor `permission_context=` wiring (a service identity) for endpoints — a policy decision.
- Changing `RoostEndpoint`, `ToolkitTool` or `AbstractTool` (core lifecycle machinery).
- Wiring Roost into `MatrixCrewTransport` by default.

---

## 2. Architectural Design

### Overview
- `AgentTool._execute_roost`: read the call's context from `self._current_pctx` (stored by
  `AbstractTool.execute` before `_execute`), bind it on `_pctx_var` around `caller.query(...)` when it is
  not `None`, reset afterwards; catch `GrantDenied` next to `RoostFailure` → `"Error: grant denied: <name>"`.
- `AgentSwarmToolkit`: override `_pre_execute(tool_name, /, **kwargs)` to capture
  `kwargs["_permission_context"]` (always injected by `ToolkitTool`, even when `None`) in a module-level,
  task-local `ContextVar`; `_ask_via_roost` binds it on `_pctx_var` around `query` the same way, and maps
  `GrantDenied` to `{"status": "refused", "detail": "grant denied: <name>"}`.

### Integration Points
| Existing component | Integration type | Notes |
|---|---|---|
| `parrot.auth.context._pctx_var` | set/reset | read by `RoostEndpoint._caller_authority` |
| `AbstractTool._current_pctx` | read | set at `abstract.py` `execute()` before `_execute` |
| `AbstractToolkit._pre_execute` | override | receives `_permission_context` from `ToolkitTool._execute` |

### Data Models / New Public Interfaces
None.

---

## 3. Module Breakdown

### Module 1: Roost callers bind the call's authority and catch GrantDenied
- **Paths**: `packages/ai-parrot/src/parrot/tools/agent.py`,
  `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py`
- **Depends on**: nothing.

---

## 4. Test Specification

### Unit Tests
| Test | Expectation |
|---|---|
| `AgentTool` query raises `GrantDenied` | returns an error string, no working-memory write |
| `AgentTool` with `_current_pctx` set | `_pctx_var.get()` inside `query` is that context; reset afterwards |
| `AgentTool` with no context, ambient `_pctx_var` bound | ambient value seen inside `query`, unchanged after |
| swarm `query` raises `GrantDenied` | `{"status": "refused", ...}` |
| swarm `_pre_execute` captured context | visible on `_pctx_var` inside `query`; reset afterwards |
| two concurrent swarm calls with different contexts | each `query` sees its own context |

### Validation Contract

tests:
- packages/ai-parrot/tests/roost/test_agent_tool_roost.py
- packages/ai-parrot-integrations/tests/test_matrix_roost_ask_agent.py
markers: none

---

## 5. Acceptance Criteria

- [ ] Both test files pass; existing Roost and swarm-toolkit tests still pass.
- [ ] `GrantDenied` never escapes `AgentTool._execute_roost` or `AgentSwarmToolkit._ask_via_roost`.
- [ ] `_pctx_var` is bound only for the duration of `query` and only when the call carries a context.
- [ ] `ruff check` clean on changed files.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.auth.context import _pctx_var                 # packages/ai-parrot/src/parrot/auth/context.py:33
from parrot.roost.grant import GrantDenied                # packages/ai-parrot/src/parrot/roost/grant.py:14
from parrot.roost.endpoint import RoostEndpoint, RoostFailure  # endpoint.py (agent.py:17 imports both)
```

### Existing Signatures
```python
# parrot/tools/abstract.py
self._current_pctx = pctx                                  # :965, inside execute(), before _execute
# parrot/tools/toolkit.py
async def _pre_execute(self, tool_name: str, /, **kwargs) -> None   # :491
# parrot/roost/endpoint.py
def _caller_authority(self) -> tuple[Any, Optional[str]]  # constructor override, else _pctx_var.get()
async def query(self, question, *, receiver, timeout=None, expected_schema=None, hops=0) -> Any  # raises GrantDenied
```

### Does NOT Exist (Anti-Hallucination)
- ~~`RoostEndpoint.query(..., permission_context=)`~~ — authority comes only from the constructor or `_pctx_var`.
- ~~`GrantDenied` subclassing `RoostFailure`~~ — it is a plain `Exception`.

### Edit Sites (Blueprint Anchors)

Verified against: `ebcde58da6`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/tools/agent.py` | MODIFY | `answer = await caller.query(question, receiver=target.address())` | `:307` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py` | MODIFY | `result = await self._endpoint.query(` | `:135` | 1 |

---

## 7. Implementation Notes & Constraints

- `_current_pctx` is an unlocked instance attribute (documented accepted race in `abstract.py`); it is the
  only per-call context `AgentTool._execute` can reach without changing `AbstractTool`.
- Run tests from the worktree with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`.

---

## 8. Open Questions

None.
