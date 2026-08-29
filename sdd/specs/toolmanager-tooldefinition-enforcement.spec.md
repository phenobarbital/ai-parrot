---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: ToolManager ToolDefinition Enforcement Parity (G7 remediation)

**Feature ID**: FEAT-474
**Date**: 2026-08-29
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: 0.29.0
**Brainstorm**: `sdd/proposals/toolmanager-tooldefinition-enforcement.brainstorm.md` (Recommended Option A)

---

## 1. Motivation & Business Requirements

> Remediation for the security escalation flagged in the PR #1270 body
> (FEAT-469 — A2UI Agent Functions).

### Problem Statement

`ToolManager.execute_tool()` bypasses `permission_context` **entirely** for
the `ToolDefinition` (`@tool`-decorated function) path
(`packages/ai-parrot/src/parrot/tools/manager.py:1549-1560`): the branch
calls `tool.function(**parameters)` directly, skipping every enforcement
layer that the `AbstractTool` branch runs — the TOOL_CALL guardrail pipeline
(FEAT-406, PBAC), GrantGuard (FEAT-211), ConfirmationGuard (FEAT-235), and
the Layer 2 `resolver.can_execute()` check performed inside
`AbstractTool.execute()` (`abstract.py:875-890`).

This was a pre-existing internal gap, but **FEAT-469 made it remotely
reachable**: every non-hidden ToolManager tool is renderer-invocable via the
A2UI RPC surface, where the session user's `PermissionContext` is *the only
authorization barrier* (spec G7). For `@tool` functions that barrier is
currently decorative. The gap is logged per-call in
`ToolManagerExecutor.call()` (`outputs/a2ui/runtime/adapters.py:73-80`) and
documented as a known limitation in `docs/outputs/a2ui-agent-functions.md` §4.

A compensating fix (excluding `ToolDefinition` tools from A2UI dispatch) was
attempted and reverted during FEAT-469: it contradicted G7's resolved Open
Question ("every ToolManager tool is invocable, no opt-in") and broke
`test_e2e_http_call_agent_function`. **A ToolManager-level fix has no such
conflict** — G7/AC-G7 demand that every invocation pass `permission_context`
to `execute_tool` and that a denied tool produce `error{code:"FORBIDDEN"}`
(`sdd/specs/a2ui-agent-functions.spec.md:64-65, 392`). Enforcing inside the
manager *fulfills* G7; only the exclusion approach contradicted it.

A second, latent defect compounds it: `@tool(requires_confirmation=True,
confirm_template=..., confirm_window_seconds=..., allow_edit=...)` is an
advertised FEAT-235 API whose docstring promises HITL confirmation "via
ConfirmationGuard in ToolManager" (`decorators.py:80-92`) — but registration
drops `routing_meta` when converting the function to `ToolDefinition`
(`manager.py:783-788`, and a second site at `interfaces/tools.py:77-82`),
and the `ToolDefinition` branch never calls the guard. The documented API is
silently inert end-to-end.

### Goals

- G1. **Enforcement parity**: the `ToolDefinition`/`@tool` execution path in
  `ToolManager.execute_tool()` runs the TOOL_CALL guardrail pipeline,
  ConfirmationGuard, and a manager-level Layer 2 resolver check; denials
  return `ToolResult(status="forbidden")` (or `cancelled`/`timeout` for
  confirmation) exactly like the `AbstractTool` branch.
- G2. **Honor the FEAT-235 API**: preserve `routing_meta` on
  `ToolDefinition` at every construction site so
  `@tool(requires_confirmation=True)` actually triggers HITL confirmation
  (including `confirm_template`, `confirm_window_seconds`, `allow_edit`, and
  fail-closed no-HITL-channel behaviour).
- G3. **Declarable permissions on `@tool`**: new `required_permissions`
  parameter on the `@tool` decorator and field on `ToolDefinition` (default
  empty set), passed to `resolver.can_execute()`.
- G4. **Fail-open without context preserved**: no `permission_context` OR no
  resolver ⇒ no Layer 2 check, byte-for-byte mirroring
  `AbstractTool.execute()`'s gate (`abstract.py:875`). Zero breakage for
  internal callers.
- G5. **Grant residual made loud**: GrantGuard stays `AbstractTool`-only;
  registering a `ToolDefinition` whose `routing_meta` carries a truthy
  `requires_grant` logs a `WARNING` that grant policies are inert on this
  path; documentation states the convention (anything needing grants must be
  an `AbstractTool`).
- G6. **Uniform enforcement audit**: one shared structured-logging helper
  emits identical records (tool name, tool kind, user_id, layer, decision,
  reason) for allow/deny on both branches.
- G7. **`execute_tool_call()` context threading**: optional
  `permission_context` parameter, forwarded to `execute_tool()`; fail-open
  default preserved.
- G8. **Close the FEAT-469 escalation formally**: e2e test proving a denied
  `@tool` invocation through the real A2UI HTTP surface returns
  `error{code:"FORBIDDEN"}` (AC-G7 of FEAT-469 true for every tool kind);
  remove the known-limitation doc bullet and the adapter's per-call warning;
  amend `a2ui-agent-functions.spec.md` to record G7 as satisfied.

### Non-Goals (explicitly out of scope)

- Grants (FEAT-211) for `@tool` functions — no `requires_grant` API exists on
  the decorator and none is added; the residual is documented + warned (G5).
- `AuditLedger` wiring into `execute_tool()` — explicitly deferred
  (brainstorm Round 2 decision: structured logs only).
- Normalizing `@tool` functions into `AbstractTool` wrappers (brainstorm
  Option B) or extracting a `ToolEnforcementPipeline` chokepoint (Option C) —
  both rejected for this remediation as refactors of battle-tested code;
  either may be a follow-up brainstorm.
- Enforcement at the A2UI boundary only (brainstorm Option D) — rejected;
  same shape as the fix already reverted in FEAT-469.
- Changing the raw-return contract of successful `ToolDefinition` calls.
- Any per-surface allowlist or per-tool A2UI opt-in (rejected in FEAT-469's
  own Non-Goals; unchanged here).

---

## 2. Architectural Design

### Overview

Brainstorm Option A — **in-place branch parity inside `execute_tool()`**,
reusing the existing, battle-tested guard implementations unchanged:

1. **Hoist the TOOL_CALL guardrail pipeline block**
   (`manager.py:1579-1610`) above the `ToolDefinition`/`AbstractTool` branch
   split so it runs for both tool kinds. Its `GuardrailContext` only carries
   `tool_name`/`arguments`/`permission_context` — nothing
   tool-instance-specific — so the block moves verbatim. Ordering semantics
   on the `AbstractTool` branch are unchanged (pipeline → grant → confirm →
   execute).
2. **Extend `ToolDefinition`** with `routing_meta: Dict[str, Any]` (default
   `{}`) and `required_permissions: Set[str]` (default `set()`), migrating
   the class from manual `__slots__` to `@dataclass(slots=True)` (defaulted
   fields conflict with manual `__slots__` — see §7 Gotchas). Populate both
   fields at all four in-repo construction sites (`manager.py:783, 794, 802`
   and `interfaces/tools.py:77`).
3. **Extend the `@tool` decorator** with `required_permissions:
   Optional[Set[str]] = None`; store it in `func._tool_metadata` alongside
   the already-built `routing_meta`.
4. **New pre-execution sequence on the `ToolDefinition` branch**:
   a. ConfirmationGuard (if configured) — `confirm()` duck-types on `.name`
      + `.routing_meta` (verified `confirmation.py:436`), so it works on the
      extended `ToolDefinition` as-is. Denied ⇒
      `ToolResult(status=cancelled|timeout)`; edited parameters honored.
   b. Layer 2 resolver check at manager level (plain functions cannot
      receive `_permission_context`/`_resolver` kwargs): when both
      `permission_context` and `self._resolver` are present,
      `await self._resolver.can_execute(pctx, tool.name,
      tool.required_permissions)`. Denied ⇒
      `ToolResult(status="forbidden")` with the same message/metadata shape
      as `abstract.py:880-890`.
   c. Invoke `tool.function(**parameters)` (sync/async detection unchanged)
      and return the **raw** result (unchanged contract — A2UI's
      `_normalize()` and the client loop depend on it).
5. **Registration warning** (G5): after constructing/accepting a
   `ToolDefinition`, if `routing_meta.get("requires_grant")` is truthy, log
   a `WARNING` naming the tool and stating grants are not enforced on this
   path.
6. **Shared enforcement logger**: private helper on `ToolManager` (e.g.
   `_log_enforcement(tool_name, tool_kind, layer, decision, pctx, reason)`)
   called from every allow/deny point on both branches.
7. **`execute_tool_call(content_block, permission_context=None)`** threads
   the new optional parameter into `execute_tool()` (no in-repo callers —
   public-API hardening only).
8. **A2UI closure**: delete the known-gap `WARNING` block in
   `ToolManagerExecutor.call()`; replace the §4 known-limitation bullet in
   `docs/outputs/a2ui-agent-functions.md` with a uniform-enforcement
   statement; amend `sdd/specs/a2ui-agent-functions.spec.md` risks noting the
   manager-level fix satisfies G7 (formally resolving the PR #1270
   escalation); add the FORBIDDEN-path e2e beside
   `test_e2e_http_call_agent_function`.

Resolved-decision summary applied throughout (from brainstorm §Open
Questions, all `[x]`): feature on `dev`; parity = guardrails + confirmation +
resolver (grants excluded); fail-open without pctx; `required_permissions`
declarable on `@tool`; grant residual = document + registration warn;
`execute_tool_call` in scope; audit = structured logs only (no AuditLedger);
extras = e2e FORBIDDEN test, docs cleanup, spec amendment, uniform audit.

### Component Diagram

```
caller (A2UI ToolManagerExecutor / A2A / MCP / client LLM loop / direct)
   │  execute_tool(name, params, permission_context=?)
   ▼
ToolManager.execute_tool()
   ├─ lookup ── not found ──────────────────────────► ToolResult(not_found)
   ├─ TOOL_CALL guardrail pipeline  (BOTH kinds; hoisted)  ─► forbidden
   ├─ isinstance ToolDefinition?
   │    ├─ ConfirmationGuard.confirm(tool, params, pctx)   ─► cancelled/timeout
   │    ├─ resolver.can_execute(pctx, name, required_perms)─► forbidden
   │    │    (only when pctx AND resolver present — fail-open otherwise)
   │    └─ tool.function(**params)  → RAW return value
   └─ isinstance AbstractTool?  (unchanged order)
        ├─ GrantGuard.authorize(...)                       ─► forbidden
        ├─ ConfirmationGuard.confirm(...)                  ─► cancelled/timeout
        └─ tool.execute(_permission_context, _resolver, …) → ToolResult
              └─ Layer 2 check inside execute()            ─► forbidden

every ─► decision point calls ToolManager._log_enforcement(...)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.tools.manager.ToolManager.execute_tool()` | modifies | guardrail hoist + ToolDefinition guard sequence + shared logging (manager.py:1519+) |
| `parrot.tools.manager.ToolDefinition` | modifies | new `routing_meta`/`required_permissions` fields; `@dataclass(slots=True)` migration (manager.py:26-34) |
| `parrot.tools.manager.ToolManager.register_tool()/add_tool()` | modifies | metadata copy at 783-788/794-799/802-807; inert-grant warning |
| `parrot.tools.manager.ToolManager.execute_tool_call()` | extends | optional `permission_context` param (manager.py:1869) |
| `parrot.tools.decorators.tool` | extends | `required_permissions` parameter; metadata dict carries it (decorators.py:55-146) |
| `parrot.interfaces.tools` (registration path) | modifies | 5th ToolDefinition construction site copies routing_meta/required_permissions (interfaces/tools.py:77-82) |
| `parrot.auth.confirmation.ConfirmationGuard` | uses (unchanged) | duck-types on `.name`/`.routing_meta`; type hint loosened or docstring-noted (see §8) |
| `parrot.auth.resolver.AbstractPermissionResolver` | uses (unchanged) | `can_execute(pctx, name, required)` contract (resolver.py:44-63) |
| `parrot.auth.grants.GrantGuard` | unchanged | explicitly out of scope for ToolDefinition; referenced by the warning |
| `parrot.outputs.a2ui.runtime.adapters.ToolManagerExecutor` | modifies | remove known-gap WARNING (adapters.py:73-80) |
| `docs/outputs/a2ui-agent-functions.md` §4 | modifies | limitation bullet → uniform-enforcement statement |
| `sdd/specs/a2ui-agent-functions.spec.md` | modifies | risk amendment: G7 satisfied by manager-level enforcement |
| `parrot.clients.base` LLM loop | unchanged | already threads `_permission_context` (base.py:1494-1496) — verified |

### Data Models

```python
# Extended ToolDefinition (manager.py) — slots generated by the dataclass
# machinery so defaulted fields are legal (manual __slots__ + defaults raise
# ValueError at class creation; see §7 Gotchas).
@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: Dict[str, Any]
    function: Callable
    routing_meta: Dict[str, Any] = field(default_factory=dict)
    required_permissions: Set[str] = field(default_factory=set)
```

No new Pydantic models — `ToolResult`, `GuardrailContext`,
`ConfirmationDecision`, `GuardDecision` are reused as-is.

### New Public Interfaces

```python
# parrot/tools/decorators.py — extended decorator signature (additive)
def tool(
    _func: Optional[Callable] = None,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    schema: Optional[Dict[str, Any]] = None,
    auto_register: bool = False,
    requires_confirmation: bool = False,
    confirm_template: Optional[str] = None,
    confirm_window_seconds: int = 0,
    allow_edit: bool = False,
    required_permissions: Optional[Set[str]] = None,   # NEW (FEAT-474)
): ...

# parrot/tools/manager.py — extended wrapper signature (additive)
async def execute_tool_call(
    self,
    content_block: Dict[str, Any],
    permission_context: Optional["PermissionContext"] = None,  # NEW (FEAT-474)
) -> Dict[str, Any]: ...
```

`execute_tool()`'s public signature is unchanged.

---

## 3. Module Breakdown

### Module 1: ToolDefinition model + decorator extension
- **Path**: `packages/ai-parrot/src/parrot/tools/manager.py` (class only),
  `packages/ai-parrot/src/parrot/tools/decorators.py`
- **Responsibility**: `@dataclass(slots=True)` migration; `routing_meta` +
  `required_permissions` fields with safe defaults; `@tool` gains
  `required_permissions` and stores it in `_tool_metadata`; decorator
  docstring updated to reflect real behaviour.
- **Depends on**: nothing (foundation).

### Module 2: Registration metadata preservation + inert-grant warning
- **Path**: `packages/ai-parrot/src/parrot/tools/manager.py`
  (`register_tool`/`add_tool` internals, lines 739-818),
  `packages/ai-parrot/src/parrot/interfaces/tools.py` (lines 77-82)
- **Responsibility**: copy `routing_meta`/`required_permissions` from
  `_tool_metadata` at all construction sites; default them for dict/param
  constructions; `WARNING` when a registered `ToolDefinition` carries
  truthy `routing_meta["requires_grant"]` (G5).
- **Depends on**: Module 1.

### Module 3: execute_tool() enforcement parity
- **Path**: `packages/ai-parrot/src/parrot/tools/manager.py`
  (`execute_tool`, lines 1519+; `execute_tool_call`, line 1869)
- **Responsibility**: hoist the TOOL_CALL guardrail block above the branch
  split; ConfirmationGuard + manager-level Layer 2 resolver check on the
  `ToolDefinition` branch (fail-open gate: pctx AND resolver); denial
  `ToolResult`s mirroring `abstract.py:880-890`; edited-parameter honoring;
  raw-return preservation; `_log_enforcement()` shared helper wired into
  both branches; `execute_tool_call` optional `permission_context`.
- **Depends on**: Modules 1–2.

### Module 4: A2UI closure — adapter, docs, spec amendment
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/runtime/adapters.py`,
  `docs/outputs/a2ui-agent-functions.md`,
  `sdd/specs/a2ui-agent-functions.spec.md`
- **Responsibility**: remove the known-gap `WARNING` block in
  `ToolManagerExecutor.call()`; rewrite the §4 known-limitation bullet;
  amend the FEAT-469 spec's risk section recording that manager-level
  enforcement satisfies G7 (escalation closure).
- **Depends on**: Module 3.

### Module 5: E2E FORBIDDEN coverage + parity regression suite
- **Path**: `packages/ai-parrot-server/tests/integration/test_a2ui_e2e.py`
  (extend), `packages/ai-parrot-tools/tests/test_manager_permissions.py`
  (extend), plus decorator/registration unit tests near their modules
- **Responsibility**: e2e deny-path test through the real A2UI HTTP surface
  (`error{code:"FORBIDDEN"}`); branch-parity tests (both kinds deny
  identically under the same resolver/guardrail/confirmation config);
  fail-open regressions; raw-return regression; inert-grant warning test.
- **Depends on**: Modules 3–4.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_tooldefinition_defaults` | 1 | New fields default to `{}`/`set()`; keyword construction of the 4-field legacy shape still works |
| `test_tool_decorator_required_permissions` | 1 | `@tool(required_permissions={"x"})` lands in `_tool_metadata` |
| `test_registration_preserves_routing_meta` | 2 | `@tool(requires_confirmation=True)` → registered `ToolDefinition.routing_meta["requires_confirmation"] is True` (both manager and `interfaces/tools.py` paths) |
| `test_registration_warns_inert_grant` | 2 | `routing_meta["requires_grant"]=True` on a ToolDefinition logs the G5 warning |
| `test_tooldef_resolver_denies` | 3 | resolver returns False ⇒ `ToolResult(status="forbidden")`, function NOT called |
| `test_tooldef_resolver_allows` | 3 | resolver True ⇒ raw return value unchanged |
| `test_tooldef_fail_open_no_pctx` | 3 | no permission_context ⇒ no resolver call, function executes (current semantics preserved) |
| `test_tooldef_fail_open_no_resolver` | 3 | pctx but no resolver ⇒ function executes |
| `test_tooldef_guardrail_blocks` | 3 | TOOL_CALL pipeline block ⇒ forbidden, function NOT called |
| `test_tooldef_confirmation_flow` | 3 | requires_confirmation ⇒ ConfirmationGuard consulted; cancelled/timeout statuses propagate; edited params used |
| `test_abstracttool_branch_unchanged` | 3 | grant→confirm→execute order and results identical to pre-change behaviour |
| `test_execute_tool_call_threads_pctx` | 3 | `execute_tool_call(..., permission_context=ctx)` forwards ctx to `execute_tool` |
| `test_enforcement_log_uniform` | 3 | allow/deny on both branches emit the shared structured record (caplog) |
| `test_branch_parity_denial` | 5 | same resolver config denies a `@tool` function and an `AbstractTool` with identical status/error shape |
| `test_resolver_exception_propagates` | 3 | resolver raising ⇒ exception propagates (no silent fail-open) |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_http_call_agent_function` | EXISTING — allow path through A2UI HTTP surface; must keep passing untouched |
| `test_e2e_http_call_agent_function_forbidden` | NEW — role-gated `@tool` function denied ⇒ `error{code:"FORBIDDEN"}` in the A2UI envelope, function not executed, a2ui_audit line logged |

### Test Data / Fixtures

```python
@pytest.fixture
def deny_all_resolver():
    class DenyAll(AbstractPermissionResolver):
        async def can_execute(self, context, tool_name, required_permissions):
            return False
    return DenyAll()

@pytest.fixture
def perm_ctx():
    """Minimal PermissionContext with user_id for window keying / metadata."""
    ...

@pytest.fixture
def confirming_tool():
    @tool(requires_confirmation=True, confirm_window_seconds=0)
    def sensitive_op(x: int) -> str:
        """Do something sensitive."""
        return f"done {x}"
    return sensitive_op
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC-1: `execute_tool()` on a `ToolDefinition` with `permission_context`
  + resolver present calls `resolver.can_execute(pctx, name,
  required_permissions)`; a False result returns
  `ToolResult(status="forbidden")` with the `abstract.py:880-890`
  message/metadata shape and the function is NOT invoked.
- [ ] AC-2: TOOL_CALL guardrail pipeline runs for BOTH tool kinds; a blocked
  outcome on the `ToolDefinition` path returns forbidden with the
  guardrail's human-readable message; `AbstractTool` branch ordering
  (pipeline → grant → confirm → execute) is byte-for-byte preserved.
- [ ] AC-3: `@tool(requires_confirmation=True, ...)` triggers
  `ConfirmationGuard.confirm()` on the `ToolDefinition` path — including
  fail-closed cancellation with no HITL channel and edited-parameter
  honoring — proving the FEAT-235 documented API.
- [ ] AC-4: Without `permission_context` (or without a resolver), the
  `ToolDefinition` path executes exactly as today (fail-open) — the full
  existing test suite passes with no call-site changes.
- [ ] AC-5: A successful `ToolDefinition` call still returns the RAW
  function return value (not a `ToolResult`).
- [ ] AC-6: `@tool` accepts `required_permissions`; registration preserves
  `routing_meta` + `required_permissions` on ALL in-repo construction sites
  (manager.py:783/794/802, interfaces/tools.py:77).
- [ ] AC-7: Registering a `ToolDefinition` with truthy
  `routing_meta["requires_grant"]` logs a WARNING stating grants are inert
  on this path.
- [ ] AC-8: `execute_tool_call()` accepts and forwards optional
  `permission_context`.
- [ ] AC-9: Allow/deny decisions on both branches emit one uniform
  structured log record (tool name, tool kind, user_id, layer, decision,
  reason) via a shared helper.
- [ ] AC-10: New e2e test proves a denied `@tool` invocation through the
  A2UI HTTP surface yields `error{code:"FORBIDDEN"}`;
  `test_e2e_http_call_agent_function` (allow path) passes untouched.
- [ ] AC-11: The known-gap WARNING in `ToolManagerExecutor.call()` and the
  §4 known-limitation bullet in `docs/outputs/a2ui-agent-functions.md` are
  removed/replaced; `sdd/specs/a2ui-agent-functions.spec.md` is amended to
  record G7 satisfied (PR #1270 escalation closed).
- [ ] AC-12: No breaking changes to public API signatures (`execute_tool`
  unchanged; new decorator/`execute_tool_call` params optional; legacy
  4-field keyword construction of `ToolDefinition` still valid).
- [ ] All feature-owned unit + integration tests pass (`pytest`), plus a
  full-repo sanity pass showing zero new regressions outside this
  feature's file scope.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> All references re-verified on 2026-08-29 against `dev`.

### Verified Imports

```python
from parrot.tools.manager import ToolDefinition, ToolManager   # manager.py:27 (@dataclass at :26), class ToolManager ~:240
from parrot.tools.decorators import tool                        # decorators.py:55
from parrot.tools.abstract import ToolResult, AbstractTool      # abstract.py
from parrot.auth.resolver import AbstractPermissionResolver     # resolver.py:25
from parrot.auth.grants import GrantGuard                       # grants.py:338
from parrot.auth.confirmation import ConfirmationGuard          # confirmation.py:~397
from parrot.auth.permission import PermissionContext            # TYPE_CHECKING import at manager.py:20
from parrot.bots.guardrails.base import GuardrailContext, GuardrailStage  # imported locally inside execute_tool at manager.py:1580
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/tools/manager.py:26-34
@dataclass                                             # line 26 — NOTE: manual __slots__, no slots=True
class ToolDefinition:
    __slots__ = ('name', 'description', 'input_schema', 'function')  # line 30
    name: str
    description: str
    input_schema: Dict[str, Any]
    function: Callable

# packages/ai-parrot/src/parrot/tools/manager.py:1519-1524
async def execute_tool(
    self,
    tool_name: str,
    parameters: Dict[str, Any],
    permission_context: Optional["PermissionContext"] = None,
) -> Any: ...
# ToolDefinition branch: 1549-1560 — direct tool.function(**parameters);
#   iscoroutinefunction dispatch at 1552-1555; raw return at 1560.
# TOOL_CALL guardrail block (AbstractTool-only today): 1579-1610 —
#   GuardrailContext(stage=GuardrailStage.TOOL_CALL, agent_name=tool_name,
#   tool_name=tool_name, extras={permission_context, tool_name, arguments});
#   blocked ⇒ ToolResult(success=False, status="forbidden", error=..., result=None)
#   with flag_reports message preference at 1600-1603.
# GrantGuard block: 1616-1628. ConfirmationGuard block: 1636-1652
#   (statuses "cancelled"|"timeout" at 1645; edited params honored 1649-1651).
# kwargs propagation to AbstractTool.execute: 1656-1660
#   ('_permission_context', '_resolver'); broker kwargs 1662-1673.

# packages/ai-parrot/src/parrot/tools/manager.py:1869-1891
async def execute_tool_call(self, content_block: Dict[str, Any]) -> Dict[str, Any]:
    # calls self.execute_tool(tool_name, tool_input) at 1879 — NO permission_context.
    # Zero in-repo callers (public API only) — verified by grep 2026-08-29.

# packages/ai-parrot/src/parrot/tools/manager.py — registration internals
# register_tool(): @tool-function → ToolDefinition at 783-788 (copies ONLY
#   name/description/schema/function from tool._tool_metadata — routing_meta
#   and any other keys DROPPED). dict path 794-799. explicit-params path 802-807.
# add_tool(): accepts ToolDefinition/AbstractTool at 690-718.
# ToolManager._resolver: Optional[AbstractPermissionResolver] (init line 323,
#   property 369-375, set_resolver 377-390).
# Guard seams: self._tool_call_pipeline (1579), self._grant_guard (1616),
#   self._confirmation_guard (1636).

# packages/ai-parrot/src/parrot/tools/decorators.py:55-66
def tool(_func=None, *, name=None, description=None, schema=None,
         auto_register=False, requires_confirmation=False,
         confirm_template=None, confirm_window_seconds=0, allow_edit=False):
    # confirmation routing_meta built at 126-133:
    #   {"requires_confirmation", "confirm_window_seconds", "allow_edit",
    #    optional "confirm_template"}
    # func._tool_metadata stored at 135-146 with keys:
    #   name, description, schema, function, auto_register, routing_meta
    # func._is_tool = True; wrapper preserves both attrs.

# packages/ai-parrot/src/parrot/tools/abstract.py:837-890 (AbstractTool.execute)
pctx = kwargs.pop("_permission_context", None)      # line 860
resolver = kwargs.pop("_resolver", None)            # line 861
if pctx is not None and resolver is not None:       # line 875 — fail-open gate
    required = getattr(self, "_required_permissions", set())   # line 876
    allowed = await resolver.can_execute(pctx, self.name, required)  # line 877
    # denial (lines 880-890): ToolResult(success=False, status="forbidden",
    #   result=None,
    #   error=f"Permission denied: '{self.name}' requires {required}",
    #   metadata={"tool_name":..., "user_id": pctx.user_id,
    #             "required_permissions": list(required)})

# packages/ai-parrot/src/parrot/auth/resolver.py:25,44-49
class AbstractPermissionResolver(ABC):
    async def can_execute(self, context: PermissionContext, tool_name: str,
                          required_permissions: set[str]) -> bool: ...
    # empty set = unrestricted (docstring, line 58)

# packages/ai-parrot/src/parrot/auth/confirmation.py:416-436
class ConfirmationGuard:
    async def confirm(self, *, tool: "AbstractTool", parameters: dict,
                      permission_context: Optional["PermissionContext"] = None,
                      ) -> ConfirmationDecision: ...
    # gate at 436: `if not (tool.routing_meta or {}).get("requires_confirmation")`
    # also reads tool.routing_meta["confirm_window_seconds"] (fallback to
    # config default with try/int guard) and tool.name → duck-type
    # compatible with extended ToolDefinition. Fail-closed without
    # human_manager (docstring line 17 + lifecycle step 3).

# packages/ai-parrot/src/parrot/auth/grants.py:338,379-399
class GrantGuard:
    async def authorize(self, *, tool: "AbstractTool", parameters: dict,
                        permission_context: Optional["PermissionContext"] = None,
                        ) -> GuardDecision: ...
    # gate: `if not tool.routing_meta.get("requires_grant")` → allow

# packages/ai-parrot/src/parrot/outputs/a2ui/runtime/adapters.py:44-110
class ToolManagerExecutor:
    def __init__(self, tool_manager: ToolManager) -> None: ...
    async def call(self, name: str, args: dict[str, Any],
                   ctx: A2UICallContext) -> ToolResult: ...
    # known-gap WARNING for ToolDefinition at ~73-80 (REMOVE in Module 4);
    # execute_tool(..., permission_context=ctx.permission_context) at ~82;
    # a2ui_audit INFO line ~88-95 (KEEP); _normalize() wraps raw returns
    # into ToolResult(success=True, status="success", result=raw).

# packages/ai-parrot/src/parrot/interfaces/tools.py:73-84
# 5th ToolDefinition construction site: @tool-decorated function →
#   ToolDefinition(name=metadata['name'], description=..., input_schema=
#   metadata['schema'], function=metadata['function']) — routing_meta DROPPED
#   here too; must copy in Module 2.

# packages/ai-parrot/src/parrot/clients/base.py:1454,1494-1496
async def _execute_tool(...):   # client LLM loop — NOT execute_tool_call
    perm_ctx = getattr(self, '_permission_context', None)          # 1494
    ...execute_tool(tool_name, merged, permission_context=perm_ctx)  # 1496
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| Hoisted guardrail block | `self._tool_call_pipeline.run()` | existing call, moved above branch split | manager.py:1579-1610 |
| ToolDefinition confirm step | `ConfirmationGuard.confirm(tool=, parameters=, permission_context=)` | duck-typed `.name`/`.routing_meta` | confirmation.py:416-436 |
| ToolDefinition Layer 2 step | `self._resolver.can_execute(pctx, tool.name, tool.required_permissions)` | manager-level await | resolver.py:44-49, gate mirror abstract.py:875 |
| `_log_enforcement()` helper | both branches' allow/deny points | `self.logger` structured record | new — pattern per manager.py logging style |
| Registration metadata copy | `tool._tool_metadata['routing_meta']` | dict copy at construction | decorators.py:135-146 → manager.py:783-788, interfaces/tools.py:77-82 |
| FORBIDDEN e2e | A2UI HTTP surface | existing harness | packages/ai-parrot-server/tests/integration/test_a2ui_e2e.py::test_e2e_http_call_agent_function |

### Does NOT Exist (Anti-Hallucination)

- ~~`ToolDefinition.routing_meta` / `ToolDefinition.required_permissions`~~ —
  do NOT exist yet; Module 1 adds them (`__slots__` currently only 4 fields).
- ~~`@tool(required_permissions=...)`~~ — decorator has NO such parameter
  today; Module 1 adds it.
- ~~`@tool(requires_grant=...)`~~ — never existed; NOT added by this feature
  either (grants stay AbstractTool-only).
- ~~Callers of `ToolManager.execute_tool_call()`~~ — none in-repo; the live
  LLM loop is `clients/base.py:_execute_tool` (a different method).
- ~~`AuditLedger` wiring inside `execute_tool()`~~ —
  `parrot/security/audit_ledger.py` and `parrot/auth/audit.py` exist but are
  NOT wired here and deliberately stay unwired (structured logs only).
- ~~Manager-level Layer 2 check for `AbstractTool`s~~ — for that branch the
  check happens INSIDE `AbstractTool.execute()` via
  `_permission_context`/`_resolver` kwargs; do NOT add a duplicate
  manager-level check for AbstractTool (double enforcement).
- ~~`ToolManager._log_enforcement()`~~ — does not exist yet; Module 3 adds it.
- ~~Positional `ToolDefinition(...)` constructions in-repo~~ — grep found
  none (all four sites use keyword args); external plugins unverified (§8).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Mirror `abstract.py:875-890` **exactly** for the manager-level Layer 2
  gate and the forbidden `ToolResult` shape (message
  `f"Permission denied: '{name}' requires {required}"`, metadata keys
  `tool_name`/`user_id`/`required_permissions`).
- Mirror `manager.py:1636-1652` for the ToolDefinition confirmation step
  (statuses `cancelled`/`timeout`; edited-parameter replacement).
- Keep guard blocks "purely additive" in the established FEAT-406/211/235
  comment style: without a configured guard/resolver the path is unchanged.
- async/await throughout; `self.logger` (never print); Google docstrings +
  strict typing on every new/modified signature.
- Follow the existing structured-log conventions of `manager.py` (lazy `%s`
  formatting) for `_log_enforcement()`.

### Known Risks / Gotchas

- **`@dataclass` + manual `__slots__` + defaulted fields is a landmine**:
  adding `routing_meta: Dict = field(default_factory=dict)` to the current
  class raises `ValueError: 'routing_meta' in __slots__ conflicts with class
  variable` at import time. Migrate to `@dataclass(slots=True)` and DELETE
  the manual `__slots__` line (legal on the `>=3.11` floor —
  pyproject.toml:11). Keyword-compat is preserved; equality/repr semantics
  unchanged.
- **Raw-return invariant**: only *denials* introduce `ToolResult`s on the
  ToolDefinition branch. `ToolManagerExecutor._normalize()` and
  `clients/base.py` stringification depend on successful calls returning the
  raw value.
- **Resolver exceptions must propagate** (matching the AbstractTool path) —
  a broken resolver must not silently fail open.
- **ConfirmationGuard without HITL channel is fail-closed** (`cancelled`
  immediately) — a `@tool(requires_confirmation=True)` function in a
  deployment with no `human_manager` goes from silently-executing (today's
  broken behaviour) to always-cancelled (correct per FEAT-235). This is an
  intended behaviour change; call it out in the changelog/docs.
- **Hoisting the guardrail block** must not change AbstractTool-branch
  observable order: pipeline still runs before GrantGuard. Moving the block
  above the `isinstance` split preserves this naturally, but the
  `not_found` short-circuit must stay BEFORE the pipeline (don't run
  guardrails for unknown tools — today's behaviour).
- **`manager.py` is high-traffic** (FEAT-380/396/406 all touched it
  recently): check for in-flight worktrees touching
  `parrot/tools/manager.py` before creating this feature's worktree.
- **Legacy/duck-typed ToolDefinitions**: read `routing_meta` defensively
  (`getattr(tool, 'routing_meta', {}) or {}`) at every consumption site to
  tolerate objects constructed before the migration (e.g., pickled state).
- **Deny-path e2e** needs a role-gated resolver/PBAC config in the test
  harness; reuse the FEAT-469 e2e fixtures (`build_principal_context`
  defaults roles to empty `frozenset()` — deny-by-default direction already
  documented in docs §4).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | No new dependencies; pytest / pytest-asyncio (already in dev deps) for tests |

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks sequential in one
  worktree (`git worktree add -b feat-474-toolmanager-tooldefinition-enforcement
  .claude/worktrees/feat-474-toolmanager-tooldefinition-enforcement HEAD`
  from `dev`).
- **Rationale**: nearly everything funnels through `manager.py` (Modules
  1–3 stack on the same file); a security fix concentrated in one hot
  method benefits from a single review narrative. Only Module 4's doc/spec
  edits are independent, not worth a second worktree.
- **Cross-feature dependencies**: none to merge first — FEAT-469 (PR #1270)
  and FEAT-470 are already merged to `dev`. Verify no in-flight worktree is
  touching `parrot/tools/manager.py` at start.

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

Resolved in the brainstorm (`sdd/proposals/toolmanager-tooldefinition-enforcement.brainstorm.md`) — carried forward, do not re-open:

- [x] Feature or hotfix? — *Resolved in brainstorm*: feature on `dev` (A2UI surface is dev-only; fix must land before any release cut carries A2UI to main).
- [x] Enforcement parity scope for the ToolDefinition path? — *Resolved in brainstorm*: resolver + TOOL_CALL guardrails + ConfirmationGuard ("honor the API" upgrade after discovering the inert FEAT-235 `requires_confirmation`); GrantGuard stays AbstractTool-only.
- [x] Behaviour without permission_context? — *Resolved in brainstorm*: keep fail-open (mirror `abstract.py:875`'s pctx-AND-resolver gate).
- [x] Source of required_permissions for @tool functions? — *Resolved in brainstorm*: add `required_permissions` to `@tool` and `ToolDefinition` (default empty set).
- [x] Grant/confirmation residual on @tool? — *Resolved in brainstorm*: document + registration-time warning for grant-requiring ToolDefinitions; confirmation is honored (no longer residual).
- [x] `execute_tool_call()` in scope? — *Resolved in brainstorm*: yes — optional `permission_context` parameter threaded through; fail-open default preserved.
- [x] Audit depth? — *Resolved in brainstorm*: uniform structured logs via a shared helper on both branches; NO AuditLedger wiring (deferred).
- [x] Extras? — *Resolved in brainstorm*: e2e FORBIDDEN test via the A2UI HTTP surface; remove known-limitation docs + adapter warning; amend a2ui-agent-functions spec recording G7 satisfied; uniform audit of both paths.

Still open:

- [ ] Should `ConfirmationGuard.confirm()` / `GrantGuard.authorize()` type
  hints be loosened to a `Protocol` (`.name` + `.routing_meta`) instead of
  `"AbstractTool"`, or is a docstring note enough? Decide during Module 3
  implementation; either satisfies mypy since the hints are strings. —
  *Owner: implementer*
- [ ] Do external plugins construct `ToolDefinition` positionally? In-repo
  grep found only keyword construction (4 sites), and `@dataclass(slots=True)`
  with trailing defaulted fields keeps positional 4-arg construction valid
  anyway — verify against the plugins repo before release notes claim full
  compat. — *Owner: Jesus*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-29 | Jesus Lara (with Claude) | Initial draft from brainstorm (Option A) |
