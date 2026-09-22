# TASK-3630: PlanToolNode — thread the tool name + extension hooks (no behaviour change)

**Feature**: FEAT-590 — Tool-Call Delegate
**Spec**: `sdd/specs/tool-call-delegate.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3626
**Assigned-to**: unassigned

---

## Context

Spec Module 5, part 1, and design-research S2 (confirmed). `DelegateToolNode`
(TASK-3631) must reuse `PlanToolNode`'s whole dispatch/retry/receipt/storage
pipeline rather than duplicate it. Today that pipeline reads
`self.plan_node.tool` in 8 places, but a delegate picks the tool **per call**,
and fan-out runs calls concurrently on a *frozen* node. So the tool name has
to travel as a parameter, never as instance state.

This task is a pure refactor. It threads `tool` through the private helpers
and adds four overridable hooks that are inert for `PlanToolNode`. Every
existing test must pass **unmodified** (AC11).

---

## Scope

- `_Attempt` gains a `tool: str` field.
- Thread the tool name through the private helpers:
  - `_call_with_retry(args, *, index=None, tool=None)` resolves `tool_name = tool or self.plan_node.tool`
  - `_dispatch(args, *, tool)`
  - `_begin_attempt(..., tool)`
  - `_refuse_unknown_retry(..., tool)`
  - `_store(..., tool)`
- Every `self.plan_node.tool` read (8, at node.py:213, 473, 476, 679, 713, 727, 756, 854) uses the threaded name or a hook.
- Add four hooks with PlanToolNode defaults:
  - `_template_source()` → `self.plan_node.args`
  - `_action_label()` → `self.plan_node.tool`
  - `async _invoke(prior, bodies, *, item=None, index=None) -> _Attempt` → resolve args + `_call_with_retry(args, index=index, tool=self.plan_node.tool)`
  - `_is_escalation(exc) -> bool` → `False`
- `_run_single` and `_run_fan_out` call `_template_source()` and `_invoke`. When `_is_escalation(exc)` is true:
  - fan-out records `escalate: …` into `errors` even under `on_item_error="skip"`, and counts it into `ArtifactRef.escalated`
  - a single node returns `ArtifactRef(status="error", errors=[…], escalated=1)` without raising
- `PlanGuard.evaluate(..., extra: Optional[Mapping[str, Any]] = None)` merges `extra` into the activation. This is used by TASK-3631's `accept_when`.
- Add regression tests proving no behaviour change, and the hooks' effect through a test-only subclass.

**NOT in scope**: `DelegateToolNode` itself (TASK-3631). Any behaviour change for `PlanToolNode`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/plan/node.py` | MODIFY | Threaded tool name + hooks |
| `packages/ai-parrot/src/parrot/bots/flows/plan/guards.py` | MODIFY | `evaluate(..., extra=None)` |
| `packages/ai-parrot/tests/bots/flows/plan/test_node_hooks.py` | CREATE | Hook tests via a test subclass |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.plan.models import ArtifactRef, PlanNode   # ArtifactRef.escalated from TASK-3626
from parrot.bots.flows.plan.node import PlanToolNode, ToolExecutionError, _Attempt  # node.py:108,90,887
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/plan/node.py
class PlanToolNode(_BaseNode):                                                     # line 108, frozen
    async def execute(self, ctx, deps=None, **kwargs) -> ArtifactRef:              # line 179; line 213: await self.run_pre_actions(prompt=self.plan_node.tool, **kwargs)
    async def _run_single(self, prior) -> ArtifactRef:                             # line 230  <-- anchor
        # bodies = await self._artifact_bodies(self.plan_node.args); args = self._resolve_args(...); attempt = await self._call_with_retry(args)
    async def _run_fan_out(self, prior) -> ArtifactRef:                            # line 250
        # bodies = await self._artifact_bodies(self.plan_node.args)               # line ~289
        # args = self._resolve_args(self.plan_node.args, prior, bodies, item=item, index=index)   <-- anchor line 303
        # async def guarded(index, item): try run_item except: on_item_error fail/collect/skip   # lines ~317-324
    async def _store(self, key, payload, *, index, producer_call_id=None)          # line 443; reads plan_node.tool at 473, 476
    async def _call_with_retry(self, args, *, index=None) -> "_Attempt"            # line 645  <-- anchor; reads tool at 679, 713
    async def _dispatch(self, args) -> Any                                         # line 717  <-- anchor; reads tool at 727
    def _begin_attempt(self, session, *, attempt, index)                           # line 735; reads tool at 756
    def _refuse_unknown_retry(self, session, receipt, exc)                         # line 836; reads tool at 854
class _Attempt(NamedTuple): payload: Any; producer_call_id: Optional[str]; degraded: bool   # line 887
MAX_RECORDED_ERRORS = 20; _MAX_ERROR_CHARS = 300                                  # lines 84-85
# packages/ai-parrot/src/parrot/bots/flows/plan/guards.py
class PlanGuard:
    def evaluate(self, artifacts, statuses=None, errors: int = 0) -> bool          # line 95
        activation: Dict[str, Any] = {                                             # line 117  <-- anchor
            "artifacts": ..., "status": ..., "errors": errors}
        return bool(self._evaluator(None, None, **activation))                    # line 122
```

### Does NOT Exist
- ~~`PlanToolNode._invoke` / `_template_source` / `_action_label` / `_is_escalation`~~: added here.
- ~~`_Attempt.tool`~~: added here. Every `_Attempt(...)` construction must pass it (the only one is in `_call_with_retry`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/flows/plan/node.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/flows/plan/guards.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/bots/flows/plan/test_node_hooks.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/node.py#PlanToolNode",
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/node.py#PlanToolNode._call_with_retry",
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/node.py#PlanToolNode._dispatch",
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/node.py#PlanToolNode._store",
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/node.py#_Attempt",
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/guards.py#PlanGuard.evaluate"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Byte-identical behaviour for `PlanToolNode`:** same `execute_tool` calls, same working-memory descriptions/metadata, same error messages, same receipts.
- Run the full existing `test_node.py` and the execution_plan integration tests before and after the change.
- Escalation recording: cap at `MAX_RECORDED_ERRORS` like other errors, but **always** increment the `escalated` counter, even past the cap. The count is the truth.
- A fan-out with escalations reports `status="partial"`. If every item escalated and nothing stored, keep the existing rule (`items and not stored` → `"error"`).

---

## Implementation Blueprint

### Steps (in order)
1. Add `tool: str` to `_Attempt`; thread `tool` through the helpers — *why*: concurrent fan-out on a frozen node.
2. Add the four hooks with PlanToolNode defaults — *why*: TASK-3631 overrides only these.
3. Rewire `_run_single` / `_run_fan_out` / `execute` to use the hooks — *why*: one pipeline for both node kinds.
4. Add `extra` to `PlanGuard.evaluate` — *why*: `accept_when` sees `ctx.proposal.*` (spec M5).
5. Write the hook tests; run the existing suites unmodified.

### `packages/ai-parrot/src/parrot/bots/flows/plan/node.py` (MODIFY) — hooks
```python
# INSERT in PlanToolNode, before `# ── Single call ──` (i.e. after execute(), ~line 227):
    # ── Extension hooks (FEAT-590) — inert for PlanToolNode ──────────────

    def _template_source(self) -> Any:
        """The structure whose ``{artifacts.<id>}`` bodies are pre-read."""
        return self.plan_node.args

    def _action_label(self) -> str:
        """Label passed to pre-actions."""
        return self.plan_node.tool

    async def _invoke(
        self,
        prior: Mapping[str, ArtifactRef],
        bodies: Mapping[str, Any],
        *,
        item: Any = None,
        index: Optional[int] = None,
    ) -> "_Attempt":
        """Resolve arguments and dispatch once (with retries) — one logical call."""
        args = self._resolve_args(self.plan_node.args, prior, bodies, item=item, index=index)
        return await self._call_with_retry(args, index=index, tool=self.plan_node.tool)

    def _is_escalation(self, exc: BaseException) -> bool:
        """Whether ``exc`` is an escalation that must always be recorded."""
        return False
```
**Why**: `_resolve_args` stays unchanged and is reused by the delegate for `instruction`/`facts`.

### `packages/ai-parrot/src/parrot/bots/flows/plan/node.py` (MODIFY) — call sites
```python
# line 213: await self.run_pre_actions(prompt=self._action_label(), **kwargs)
# occurrences: 1 (verified: grep -c '    async def _run_single(self, prior: Mapping\[str, ArtifactRef\]) -> ArtifactRef:' node.py)
# _run_single body (230-248) becomes:
        bodies = await self._artifact_bodies(self._template_source())
        try:
            attempt = await self._invoke(prior, bodies)
        except Exception as exc:  # noqa: BLE001 - escalations become a ref, everything else re-raises
            if not self._is_escalation(exc):
                raise
            return ArtifactRef(node_id=self.node_id, status="error",
                               errors=[str(exc)[:_MAX_ERROR_CHARS]], escalated=1)
        key = self.plan_node.store_as
        stored = await self._store(key, attempt.payload, index=None,
                                   producer_call_id=attempt.producer_call_id, tool=attempt.tool)
        # ... remainder unchanged (ArtifactRef(... status="ok" ...))
# _run_fan_out: `bodies = await self._artifact_bodies(self.plan_node.args)` → self._template_source()
# occurrences: 1 (verified: grep -c 'args = self._resolve_args(self.plan_node.args, prior, bodies, item=item, index=index)' node.py)
# REPLACE lines 303-304 (`args = ...` + `attempt = await self._call_with_retry(args, index=index)`) with:
                attempt = await self._invoke(prior, bodies, item=item, index=index)
# and pass tool=attempt.tool to the self._store(...) call that follows.
# guarded(): FILL IN — before the on_item_error branches:
#     if self._is_escalation(exc): escalated += 1 (nonlocal counter); append f"[{index}] {msg}" if under cap; return
# ArtifactRef(...) at the end: add escalated=escalated; status stays "ok" if not errors else "partial" (+ existing "error" rule)
```

### `packages/ai-parrot/src/parrot/bots/flows/plan/node.py` (MODIFY) — threaded tool name
```python
# occurrences: 1 (verified: grep -c '    async def _call_with_retry(self, args: Dict\[str, Any\], \*, index: Optional\[int\] = None) -> "_Attempt":' node.py)
    async def _call_with_retry(
        self, args: Dict[str, Any], *, index: Optional[int] = None, tool: Optional[str] = None
    ) -> "_Attempt":
        # docstring: add "tool: Tool to dispatch; defaults to plan_node.tool (PlanToolNode)."
        tool_name = tool or self.plan_node.tool
        # FILL IN: replace self.plan_node.tool at 679/713 with tool_name; pass tool=tool_name to
        #   self._begin_attempt(...), self._dispatch(args, tool=tool_name), self._refuse_unknown_retry(..., tool=tool_name);
        #   return _Attempt(payload=..., producer_call_id=..., degraded=..., tool=tool_name)
# occurrences: 1 (verified: grep -c '    async def _dispatch(self, args: Dict\[str, Any\]) -> Any:' node.py)
    async def _dispatch(self, args: Dict[str, Any], *, tool: str) -> Any:
        coro = self.tool_manager.execute_tool(tool, args, permission_context=self.permission_context)
        return await asyncio.wait_for(coro, self.plan_node.timeout) if self.plan_node.timeout else await coro
# _begin_attempt(self, session, *, attempt, index, tool: str): line 756 → `tool,`
# _refuse_unknown_retry(self, session, receipt, exc, *, tool: str): line 854 → {tool!r}
# _store(..., producer_call_id=None, tool: Optional[str] = None): lines 473/476 → name = tool or self.plan_node.tool
# _Attempt: add `tool: str` as the LAST field (+ docstring "tool: Tool actually dispatched.")
```
**Why**: after this, `grep -n 'self.plan_node.tool' node.py` should hit only the hook defaults and the `or` fallbacks. `DelegatePlanNode` has no `.tool`, and TASK-3631 overrides every hook that would reach one.

### `packages/ai-parrot/src/parrot/bots/flows/plan/guards.py` (MODIFY)
```python
# evaluate signature (line 95): add `extra: Optional[Mapping[str, Any]] = None` after `errors`
# occurrences: 1 (verified: grep -c '        activation: Dict\[str, Any\] = {' guards.py)
# AFTER the activation dict literal (lines 117-121):
        if extra:
            activation.update(extra)
# docstring: "extra: Additional activation keys (e.g. ``proposal`` for delegate accept_when)."
```

### `packages/ai-parrot/tests/bots/flows/plan/test_node_hooks.py` (CREATE)
```python
"""FEAT-590: PlanToolNode extension hooks — inert by default, effective in a subclass."""
from __future__ import annotations

import pytest

from parrot.bots.flows.plan.models import ArtifactRef, ForEach, PlanNode
from parrot.bots.flows.plan.node import PlanToolNode, ToolExecutionError
from .test_node import _Ctx, _ToolManager, _WorkingMemory  # reuse the existing fakes


class _Escalate(ToolExecutionError):
    pass


class _EscalatingNode(PlanToolNode):
    def _is_escalation(self, exc: BaseException) -> bool:
        return isinstance(exc, _Escalate)


@pytest.mark.asyncio
async def test_attempt_records_dispatched_tool() -> None: ...           # FILL IN
@pytest.mark.asyncio
async def test_fanout_escalations_recorded_even_with_skip() -> None: ... # FILL IN: escalated count + 'partial'
@pytest.mark.asyncio
async def test_single_escalation_returns_error_ref() -> None: ...       # FILL IN: not raised
def test_guard_extra_activation() -> None: ...                          # FILL IN: compile_guard("ctx.proposal.name == 'a'") with extra
```

### FILL IN checklist
- [ ] `_call_with_retry` threaded name at every read
- [ ] `guarded()` escalation branch + counter; bounded by spec §2 "Escalation"
- [ ] Hook tests. Make `_invoke` raise `_Escalate` via a `_ToolManager` payload callable that raises

---

## Acceptance Criteria

- [ ] AC11: `test_node.py`, `test_plan.py` and the execution_plan integration tests pass **unmodified**
- [ ] Hooks are inert for `PlanToolNode` and effective in a subclass
- [ ] `ruff check` is clean on changed files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/flows/plan/test_node_hooks.py -q`
- `pytest packages/ai-parrot/tests/bots/flows/plan/test_node.py -q`
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_integration.py -q`
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_checkpointed_execution.py -q`

---

## Test Specification

See the test file block above.

---

## Agent Instructions

Standard. Run `test_node.py` BEFORE editing to record the baseline.

---

## Completion Note

*(Agent fills this in when done)*
