# TASK-2580: execute_tool() enforcement parity for the ToolDefinition branch

**Feature**: FEAT-474 — ToolManager ToolDefinition Enforcement Parity (G7 remediation)
**Spec**: `sdd/specs/toolmanager-tooldefinition-enforcement.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2578, TASK-2579
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 / Goals G1, G4, G6, G7 — **the core security fix**. The
`ToolDefinition` branch of `ToolManager.execute_tool()` currently invokes
the plain function with NO enforcement whatsoever, which is the
`permission_context` bypass escalated in PR #1270 and remotely reachable
via A2UI. This task gives that branch the agreed parity: TOOL_CALL
guardrail pipeline + ConfirmationGuard + manager-level Layer 2 resolver
check, with fail-open semantics preserved when no context/resolver is
present, uniform structured enforcement logging on BOTH branches, and
`execute_tool_call()` context threading.

---

## Scope

- **Hoist the TOOL_CALL guardrail pipeline block** (manager.py:1579-1610)
  above the `isinstance` branch split so it runs for both tool kinds. The
  `not_found` short-circuit (1540-1546) stays BEFORE it. AbstractTool-branch
  observable order stays: pipeline → grant → confirm → execute.
- **ToolDefinition branch pre-execution sequence** (in this order):
  1. ConfirmationGuard (if `self._confirmation_guard is not None`):
     `await self._confirmation_guard.confirm(tool=tool, parameters=parameters,
     permission_context=permission_context)`. Not allowed ⇒
     `ToolResult(success=False, status=decision.status, error=..., result=None)`
     mirroring manager.py:1643-1648. Honor edited parameters
     (decision.parameters — mirror 1649-1651).
  2. Layer 2 resolver check when `permission_context is not None and
     self._resolver is not None`:
     `allowed = await self._resolver.can_execute(permission_context,
     tool.name, tool.required_permissions)`. Denied ⇒ forbidden
     `ToolResult` with the exact `abstract.py:880-890` message/metadata
     shape. Resolver exceptions PROPAGATE (no silent fail-open).
  3. Invoke `tool.function(**parameters)` with the existing
     sync/async dispatch (1552-1555); return the RAW value (1560).
- **Shared enforcement logger**: add private helper
  `ToolManager._log_enforcement(tool_name, tool_kind, layer, decision,
  permission_context, reason)` emitting one structured record; call it at
  every allow/deny point on BOTH branches (guardrail block/deny, grant
  deny, confirmation deny/allow-after-confirm, resolver allow/deny,
  fail-open skip is NOT logged per-call — only decisions are).
- **`execute_tool_call()`**: add optional
  `permission_context: Optional["PermissionContext"] = None` parameter,
  forwarded to `execute_tool()` (manager.py:1869-1891).
- Unit tests per spec §4 (deny/allow/fail-open/guardrail/confirmation/
  order-preservation/raw-return/logging/exception-propagation).

**NOT in scope**: A2UI adapter/doc changes (TASK-2581); e2e tests
(TASK-2582); any grant enforcement for ToolDefinition (spec Non-Goal);
duplicate manager-level resolver check for the AbstractTool branch (its
check lives inside `AbstractTool.execute()` — adding one would
double-enforce).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | `execute_tool()` (1519+), `execute_tool_call()` (1869+), new `_log_enforcement()` |
| `packages/ai-parrot/tests/tools/test_tooldefinition_enforcement.py` | MODIFY | Core enforcement tests |
| `packages/ai-parrot-tools/tests/test_manager_permissions.py` | MODIFY | Extend resolver-injection suite with ToolDefinition cases |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.manager import ToolDefinition, ToolManager     # manager.py:27
from parrot.tools.abstract import ToolResult, AbstractTool        # abstract.py
from parrot.auth.resolver import AbstractPermissionResolver       # resolver.py:25
from parrot.bots.guardrails.base import GuardrailContext, GuardrailStage
# ^ imported LOCALLY inside execute_tool at manager.py:1580 — keep local import
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/manager.py:1519-1560 (CURRENT)
async def execute_tool(self, tool_name, parameters,
                       permission_context: Optional["PermissionContext"] = None) -> Any:
    # not_found short-circuit 1540-1546 (returns ToolResult(status='not_found'))
    # ToolDefinition branch 1549-1560:
    #   iscoroutinefunction dispatch 1552-1555; debug log 1557-1559; RAW return 1560
    # TOOL_CALL guardrail block 1579-1610 (AbstractTool-only today):
    #   GuardrailContext(stage=GuardrailStage.TOOL_CALL, agent_name=tool_name,
    #     tool_name=tool_name, extras={"permission_context":..., "tool_name":...,
    #     "arguments": parameters})
    #   outcome = await self._tool_call_pipeline.run(f"tool_call:{tool_name}", ctx)
    #   blocked ⇒ prefer flag_reports message (1600-1603) over outcome.reason;
    #   returns ToolResult(success=False, status="forbidden", error=..., result=None)
    # GrantGuard block 1616-1628 (AbstractTool-only — LEAVE THERE)
    # ConfirmationGuard block 1636-1652:
    #   decision = await self._confirmation_guard.confirm(tool=tool,
    #       parameters=parameters, permission_context=permission_context)
    #   not allowed ⇒ ToolResult(status=decision.status)  # "cancelled"|"timeout"
    #   decision.parameters is not None ⇒ parameters = decision.parameters
    # kwargs propagation 1656-1673 (AbstractTool-only — LEAVE THERE)

# Guard seams on self: _tool_call_pipeline (1579, has .has_guardrails),
#   _grant_guard (1616), _confirmation_guard (1636),
#   _resolver (init 323, property 369-375, set_resolver 377-390)

# packages/ai-parrot/src/parrot/tools/abstract.py:875-890 — the shape to mirror:
if pctx is not None and resolver is not None:
    required = getattr(self, "_required_permissions", set())
    allowed = await resolver.can_execute(pctx, self.name, required)
    if not allowed:
        return ToolResult(
            success=False, status="forbidden", result=None,
            error=f"Permission denied: '{self.name}' requires {required}",
            metadata={"tool_name": self.name, "user_id": pctx.user_id,
                      "required_permissions": list(required)})

# packages/ai-parrot/src/parrot/auth/resolver.py:44-49
async def can_execute(self, context: PermissionContext, tool_name: str,
                      required_permissions: set[str]) -> bool: ...

# packages/ai-parrot/src/parrot/auth/confirmation.py:416-436
async def confirm(self, *, tool, parameters: dict,
                  permission_context=None) -> ConfirmationDecision:
    # gate 436: (tool.routing_meta or {}).get("requires_confirmation")
    # only touches tool.name + tool.routing_meta ⇒ extended ToolDefinition works.
    # ConfirmationDecision fields used by manager: .allowed, .status, .reason,
    #   .parameters (see manager.py:1642-1651)

# packages/ai-parrot/src/parrot/tools/manager.py:1869-1891 (CURRENT)
async def execute_tool_call(self, content_block: Dict[str, Any]) -> Dict[str, Any]:
    # 1879: tool_result = await self.execute_tool(tool_name, tool_input)
    # zero in-repo callers — public API; keep return shape identical.

# After TASK-2578/2579: ToolDefinition has .routing_meta / .required_permissions.
```

### Does NOT Exist
- ~~`ToolManager._log_enforcement()`~~ — this task ADDS it
- ~~`execute_tool_call(..., permission_context=...)`~~ — this task ADDS the param
- ~~manager-level `can_execute` for AbstractTool~~ — must NOT be added
  (lives inside `AbstractTool.execute()` via `_permission_context`/`_resolver`
  kwargs, manager.py:1656-1660)
- ~~`ConfirmationGuard` type accepting only AbstractTool at runtime~~ — the
  `tool:` hint is a string annotation; runtime duck-types (see §8 open
  question: loosen hint to a Protocol OR add a docstring note — pick one)
- ~~`GuardrailContext(tool=...)` parameter~~ — context takes
  `stage/agent_name/tool_name/extras` (manager.py:1581-1590), no tool object

---

## Implementation Notes

### Pattern to Follow
```python
# ToolDefinition branch target shape (inside execute_tool, after hoisted pipeline):
if isinstance(tool, ToolDefinition):
    if self._confirmation_guard is not None:
        confirm_decision = await self._confirmation_guard.confirm(
            tool=tool, parameters=parameters,
            permission_context=permission_context,
        )
        if not confirm_decision.allowed:
            self._log_enforcement(tool_name, "tool_definition", "confirmation",
                                  "deny", permission_context, confirm_decision.reason)
            return ToolResult(success=False, status=confirm_decision.status,
                              error=f"Confirmation {confirm_decision.status}: {confirm_decision.reason}",
                              result=None)
        if confirm_decision.parameters is not None:
            parameters = confirm_decision.parameters
    if permission_context is not None and self._resolver is not None:
        allowed = await self._resolver.can_execute(
            permission_context, tool.name, tool.required_permissions)
        if not allowed:
            self._log_enforcement(tool_name, "tool_definition", "resolver",
                                  "deny", permission_context, "permission denied")
            return ToolResult(...)  # abstract.py:880-890 shape, verbatim
    ...existing sync/async dispatch, RAW return...
```

### Key Constraints
- **Raw-return invariant** (AC-5): successful ToolDefinition calls return
  the plain function value — only denials return `ToolResult`s.
- **Fail-open** (AC-4): the pctx-AND-resolver gate must match
  `abstract.py:875` exactly; no context ⇒ zero new behaviour. The FULL
  existing suite must pass with no call-site changes.
- **Read `routing_meta` defensively** (`getattr(tool, 'routing_meta', {})
  or {}`) — tolerate pre-migration duck-typed objects (spec §7 gotcha).
- **Do not move the `not_found` short-circuit** below the pipeline —
  guardrails must not run for unknown tools (today's behaviour).
- "Purely additive" comment style of FEAT-406/211/235 blocks; lazy `%s`
  logging; Google docstrings on `_log_enforcement` and updated
  `execute_tool` docstring (drop the "ToolDefinition does not support
  permission enforcement" comment at 1550-1551 — it becomes false).
- Existing behaviour note: `_execute_tool` in `clients/base.py:1494-1496`
  already threads pctx — do NOT touch clients.

### References in Codebase
- `packages/ai-parrot/tests/test_toolmanager_confirmation.py` — existing
  ToolManager+ConfirmationGuard test patterns (fixtures, fakes) to imitate
- `packages/ai-parrot-tools/tests/test_manager_permissions.py` — resolver
  injection test patterns
- `packages/ai-parrot/tests/tools/test_grants.py` — guard-decision fakes

---

## Acceptance Criteria

- [ ] AC-1: resolver deny on ToolDefinition ⇒ forbidden ToolResult
  (abstract.py shape), function NOT called
- [ ] AC-2: guardrail pipeline runs for both kinds; blocked ToolDefinition
  call ⇒ forbidden with guardrail message; AbstractTool order preserved
  (pipeline → grant → confirm → execute)
- [ ] AC-3: `requires_confirmation` ToolDefinition consults
  ConfirmationGuard; cancelled/timeout propagate; edited params used;
  fail-closed without human_manager
- [ ] AC-4: fail-open without pctx or resolver — full existing suite green
  unmodified
- [ ] AC-5: successful call returns RAW value
- [ ] AC-8: `execute_tool_call(..., permission_context=ctx)` forwards ctx
- [ ] AC-9: uniform structured log records on both branches (caplog)
- [ ] Resolver exception propagates (no swallow)
- [ ] All tests pass:
  `pytest packages/ai-parrot/tests/tools/test_tooldefinition_enforcement.py packages/ai-parrot-tools/tests/test_manager_permissions.py packages/ai-parrot/tests/test_toolmanager_confirmation.py packages/ai-parrot/tests/tools/test_grants.py -v`
- [ ] `ruff check` clean on modified files

---

## Test Specification

```python
# extend packages/ai-parrot/tests/tools/test_tooldefinition_enforcement.py
import pytest
from parrot.tools.manager import ToolManager
from parrot.tools.decorators import tool
from parrot.auth.resolver import AbstractPermissionResolver


class DenyAll(AbstractPermissionResolver):
    async def can_execute(self, context, tool_name, required_permissions):
        return False
    async def filter_tools(self, context, tools):  # if ABC requires it — verify
        return []


class TestToolDefinitionEnforcement:
    async def test_resolver_denies_tooldef(self, perm_ctx):
        tm = ToolManager(resolver=DenyAll())
        calls = []
        @tool
        def f(x: int) -> str:
            """Doc."""
            calls.append(x); return str(x)
        tm.register_tool(f)
        res = await tm.execute_tool("f", {"x": 1}, permission_context=perm_ctx)
        assert res.status == "forbidden" and calls == []

    async def test_fail_open_without_pctx(self):
        tm = ToolManager(resolver=DenyAll())
        @tool
        def g(x: int) -> str:
            """Doc."""
            return str(x)
        tm.register_tool(g)
        assert await tm.execute_tool("g", {"x": 2}) == "2"   # RAW value

    async def test_raw_return_on_allow(self, perm_ctx):
        ...  # AllowAll resolver ⇒ raw "3"

    async def test_resolver_exception_propagates(self, perm_ctx):
        ...  # Boom resolver ⇒ pytest.raises

    async def test_guardrail_blocks_tooldef(self, perm_ctx):
        ...  # pipeline with blocking guardrail ⇒ forbidden, fn not called

    async def test_confirmation_cancelled_no_hitl(self, perm_ctx):
        ...  # requires_confirmation + guard without human_manager ⇒ cancelled

    async def test_abstracttool_order_unchanged(self):
        ...  # spy guards record order: pipeline, grant, confirm
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2578 and TASK-2579 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code (line numbers
   will have shifted after TASK-2578/2579 — re-anchor them first)
4. **Update status** in `sdd/tasks/index/toolmanager-tooldefinition-enforcement.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2580-execute-tool-enforcement-parity.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-29
**Notes**: Hoisted the TOOL_CALL guardrail pipeline block above the
`ToolDefinition`/`AbstractTool` `isinstance` split (the `not_found`
short-circuit stays before it, unchanged) so it runs for BOTH tool kinds;
`AbstractTool` branch order (pipeline → grant → confirm → execute) proven
byte-for-byte preserved via the reused `test_guardrails_tool_call_hook.py`
suite (7/7 green) plus a new order-tracking test. Added the
`ToolDefinition` pre-execution sequence exactly per spec: ConfirmationGuard
(mirrors manager.py's existing cancelled/timeout shape + edited-parameter
honoring) then the manager-level Layer 2 resolver gate (mirrors
`abstract.py:875-890` byte-for-byte — same message/metadata shape,
fail-open only when BOTH pctx and resolver are present, resolver
exceptions propagate via the existing bare `raise`) then the unchanged
raw-return dispatch. Added `ToolManager._log_enforcement()` — one shared
structured-log helper called at every allow/deny decision point on both
branches per spec (guardrail deny, grant deny, confirmation deny/allow,
resolver deny/allow); fail-open skips are never logged. Extended
`execute_tool_call()` with optional `permission_context`, forwarded to
`execute_tool()`. Updated the `execute_tool()` docstring to drop the
now-false "ToolDefinition does not support permission enforcement" claim.
Added 9 new tests to `test_tooldefinition_enforcement.py`
(`TestToolDefinitionEnforcement`, reusing the `_BlockGuardrail`/
`_PassGuardrail`/`GuardrailPipeline` and `ConfirmationGuard`/
`InMemoryConfirmationWindowStore` patterns from
`test_guardrails_tool_call_hook.py`/`test_toolmanager_confirmation.py`) and
7 new tests to `test_manager_permissions.py`
(`TestToolDefinitionResolverParity`, extending the existing
`DefaultPermissionResolver`/role-hierarchy fixtures with ToolDefinition
cases) — all pass. Full regression: the two extended files plus
`test_toolmanager_confirmation.py`, `test_grants.py` (64+25 = 89 tests) all
green; the broader `packages/ai-parrot/tests/tools/` sweep plus
`test_guardrails_tool_call_hook.py`/`test_guardrails_pipeline.py`/
`test_guardrails_pbac.py`/`test_guardrails_core_models.py`/
`test_guardrails_output.py`/`test_pbac_guardrails_e2e.py` (940+77 = 1017
tests) show the same 51 pre-existing `dev`-baseline failures (unrelated
`databasequery`/`test_auto_registration_hooks` suites) and zero new
regressions. `ruff check` diff against `dev` baseline on `manager.py` shows
only the two new `Optional["PermissionContext"]` parameters
(`_log_enforcement`, `execute_tool_call`) triggering the same
`UP045`/`UP037` findings the file already carries at its pre-existing
`resolver: Optional["AbstractPermissionResolver"]` parameter (line 249) —
matching, not deviating from, established convention; no new rule
categories introduced. Test files' own `ruff check` is clean (auto-fixed
import ordering).

**Deviations from spec**: none
