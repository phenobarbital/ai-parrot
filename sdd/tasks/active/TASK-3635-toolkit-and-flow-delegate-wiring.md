# TASK-3635: Toolkit + build_plan_flow delegate wiring

**Feature**: FEAT-590 — Tool-Call Delegate
**Spec**: `sdd/specs/tool-call-delegate.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3628, TASK-3629, TASK-3631, TASK-3634
**Assigned-to**: unassigned

---

## Context

Spec Module 8, and design-research S3 (confirmed): the delegate chain must
reach **every** factory path. That's fresh runs, `plan_resume` and
`plan_repair` child flows, since all three rebuild through `build_plan_flow`.
The toolkit, not a node, owns the delegates' lifecycle (`aclose`).

This task connects all the pieces:
- `ExecutionPlanToolkit` constructor kwargs → validation (`validate_with_allowlist`, `validate_delta`)
- → `build_plan_flow` (the `"delegate"` node factory)
- → `PlanPlanner` (delegate rules)
- plus `_assert_policy` over `tool_names()` and `cleanup()` → `aclose()`

---

## Scope

- `build_plan_flow(..., delegates=(), delegate_trace_sink=None, allow_delegate_side_effects=False)`. When `delegates` is non-empty: `ensure_delegate_node_registered(DelegateToolNode)`, and `node_factories["delegate"] = make_delegate_node_factory(...)` with the same run bindings as the tool factory.
- `ExecutionPlanToolkit.__init__(..., delegates=None, delegate_trace_sink=None, allow_delegate_side_effects=False, **kwargs)`. Store `self._delegates: tuple`.
- Forward the delegate kwargs at every call site:
  - `build_plan_flow` (toolkit.py:337, 593, 1072)
  - `validate_with_allowlist` (1241, 1257, 1268)
  - `validate_delta` (732, 742)
- `PlanPlanner` construction (727, 1249) passes `delegate_safe_tools` (the allowlist-scoped `delegate_safe` tool names) and `delegate_max_tools` when delegates are configured, `None` otherwise.
- `_assert_policy` (581) uses the union of `node.tool_names()`.
- `cleanup()` (251) awaits `aclose()` on every delegate, logging and continuing on errors, before the existing teardown.
- Tests.

**NOT in scope**: the end-to-end run with fan-out/escalation/resume (TASK-3636); docs (TASK-3638).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/execution_plan/checkpoint.py` | MODIFY | Delegate factory in `build_plan_flow` |
| `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` | MODIFY | Kwargs, forwarding, `_assert_policy`, `cleanup` |
| `packages/ai-parrot/tests/tools/execution_plan/test_delegate_wiring.py` | CREATE | Wiring tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.plan import ensure_delegate_node_registered           # TASK-3628
from parrot.bots.flows.plan.delegate import DelegateToolNode, make_delegate_node_factory   # TASK-3631 (lazy __getattr__)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/execution_plan/checkpoint.py
def build_plan_flow(plan, *, run, tool_manager, working_memory, agent_registry, permission_context,
                    step_mapping, store, durable_store) -> PlanFlow                  # line 76
    # ensure_tool_node_registered(PlanToolNode)   line 89
    # factory = make_tool_node_factory(tool_manager, working_memory, permission_context=..., plan_run_id=run.run_id, step_mapping=dict(step_mapping))  line 92-98
    # node_factories={"tool": factory},            <-- anchor line 103
# packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py
class ExecutionPlanToolkit(AbstractToolkit):                                          # line 83
    def __init__(self, *, tool_manager, working_memory, planner_llm=None, plans_dir=None, allowed_tools=None,
                 soft_timeout=60.0, permission_context=None, on_node_event=None, max_completed_runs=50,
                 plan_step_mapping=None, recovery=None, checkpoint_store=None, durable_store=None,
                 task_memory_runtime: Optional["TaskMemoryRuntime"] = None,          <-- anchor line 136
                 scope=None, **kwargs) -> None                                        # line 120
    async def cleanup(self) -> None                                                   # line 251: await self._memory_binding.close(); await super().cleanup()
    def _assert_policy(self, run) -> None                                             # line 578; `needed = {node.tool for node in run.metadata.plan.nodes}` line 581
    # build_plan_flow(...) calls: lines 337, 593, 1072
    # validate_delta(delta, run=run, tool_manager=self._tool_manager, allowed_tools=allowed): lines 732, 742
    # PlanPlanner(self.planner_llm, build_catalog(self._tool_manager, self.allowed_tools)): line 727
    # PlanPlanner(self.planner_llm, catalog): line 1249
    # validate_with_allowlist(plan, self._tool_manager, self.allowed_tools): lines 1241, 1257, 1268
# catalog.validate_with_allowlist(..., *, delegates=None, allow_delegate_side_effects=False)   # TASK-3629
# repair.validate_delta(..., delegates=None, allow_delegate_side_effects=False)              # TASK-3629
# planner.PlanPlanner(llm, catalog, *, delegate_safe_tools=None, delegate_max_tools=5)       # TASK-3634
```

### Does NOT Exist
- ~~`ExecutionPlanToolkit.delegates` public attribute~~: store it privately as `self._delegates`.
- ~~A delegate registry~~: the chain is a plain ordered tuple, and `[0]` is primary.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/execution_plan/checkpoint.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/execution_plan/test_delegate_wiring.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/checkpoint.py#build_plan_flow",
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py#ExecutionPlanToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py#ExecutionPlanToolkit._assert_policy",
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py#ExecutionPlanToolkit.cleanup"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- A toolkit without delegates behaves exactly as today. The existing `tests/tools/execution_plan/` suites pass unmodified.
- Use two small private helpers so the eight call sites stay one-liners and cannot drift:
  - `_validation_kwargs()` → `{"delegates": self._delegates, "allow_delegate_side_effects": ...}`
  - `_flow_delegate_kwargs()` → adds `delegate_trace_sink`
- Line numbers above were verified at `cc6caa6da`. Re-grep each call site before editing; FEAT-585 follow-ups may shift them.
- The trace sink is passed to nodes only. Nothing about traces goes into `run_metadata`, checkpoints or the manifest (AC10, design-research S9).

---

## Implementation Blueprint

### Steps (in order)
1. Extend `build_plan_flow` — *why*: one place feeds fresh, resumed and child flows.
2. Add the toolkit kwargs and helpers; update all eight call sites plus the planner construction — *why*: S3 (every path).
3. `_assert_policy` → `tool_names()`; `cleanup` → `aclose` — *why*: a delegate node has no `.tool`; the toolkit owns the lifecycle.
4. Write the tests.

### `packages/ai-parrot/src/parrot/tools/execution_plan/checkpoint.py` (MODIFY)
```python
# signature (line 76): add keyword-only
#     delegates: Sequence[Any] = (), delegate_trace_sink: Optional[Any] = None, allow_delegate_side_effects: bool = False,
# (add Sequence to the typing import at line 10)
# occurrences: 1 (verified: grep -c '        node_factories={"tool": factory},' checkpoint.py)
# BEFORE `flow = PlanFlow.from_definition(` build the factories dict, then use it at line 103:
    node_factories: Dict[str, Any] = {"tool": factory}
    if delegates:
        from parrot.bots.flows.plan import ensure_delegate_node_registered  # noqa: PLC0415
        from parrot.bots.flows.plan.delegate import DelegateToolNode, make_delegate_node_factory  # noqa: PLC0415

        ensure_delegate_node_registered(DelegateToolNode)
        node_factories["delegate"] = make_delegate_node_factory(
            tool_manager,
            working_memory,
            delegates,
            trace_sink=delegate_trace_sink,
            allow_delegate_side_effects=allow_delegate_side_effects,
            permission_context=permission_context,
            plan_run_id=run.run_id,
            step_mapping=dict(step_mapping),
        )
# ... PlanFlow.from_definition(..., node_factories=node_factories, ...)
```
**Why**: the imports are lazy so a toolkit without delegates never imports the delegate node module.

### `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        task_memory_runtime: Optional\["TaskMemoryRuntime"\] = None,' toolkit.py)
# AFTER — insert below that line (toolkit.py:136):
        delegates: Optional[Sequence[Any]] = None,
        delegate_trace_sink: Optional[Any] = None,
        allow_delegate_side_effects: bool = False,
# docstring Args: delegates ("ordered ToolCallDelegate chain; [0] primary. Owned: closed by cleanup()"),
#   delegate_trace_sink ("opt-in DelegateTraceSink; never persisted in checkpoints"),
#   allow_delegate_side_effects ("host policy; plan text alone can never grant side effects").
# body, after `self.plan_step_mapping = ...`:
        self._delegates: tuple = tuple(delegates or ())
        self._delegate_trace_sink = delegate_trace_sink
        self._allow_delegate_side_effects = allow_delegate_side_effects

    def _validation_kwargs(self) -> Dict[str, Any]:
        """Delegate kwargs for validate_with_allowlist / validate_delta."""
        return {"delegates": self._delegates, "allow_delegate_side_effects": self._allow_delegate_side_effects}

    def _flow_delegate_kwargs(self) -> Dict[str, Any]:
        """Delegate kwargs for build_plan_flow."""
        return {**self._validation_kwargs(), "delegate_trace_sink": self._delegate_trace_sink}

    def _planner(self, catalog: Any) -> PlanPlanner:
        """Build the planner, enabling delegate rules only when delegates exist (AC13)."""
        # FILL IN: when self._delegates: safe = [n for n in (allowed names) if getattr(self._tool_manager.get_tool(n),
        #   "delegate_safe", False)]; PlanPlanner(self.planner_llm, catalog, delegate_safe_tools=safe,
        #   delegate_max_tools=self._delegates[0].max_tools); else PlanPlanner(self.planner_llm, catalog)
        raise NotImplementedError

# call sites: build_plan_flow(..., **self._flow_delegate_kwargs()) at 337/593/1072;
#   validate_with_allowlist(plan, self._tool_manager, self.allowed_tools, **self._validation_kwargs()) at 1241/1257/1268;
#   validate_delta(..., allowed_tools=allowed, **self._validation_kwargs()) at 732/742;
#   PlanPlanner(...) at 727/1249 → self._planner(<same catalog expression>)
# occurrences: 1 (verified: grep -c '        needed = {node.tool for node in run.metadata.plan.nodes}' toolkit.py)
# REPLACE line 581 with:
        needed = {name for node in run.metadata.plan.nodes for name in node.tool_names()}
# cleanup (line 251): FILL IN — before `await self._memory_binding.close()`:
#   for delegate in self._delegates: try await delegate.aclose() except Exception → self.logger.warning; continue
```

### `packages/ai-parrot/tests/tools/execution_plan/test_delegate_wiring.py` (CREATE)
```python
"""FEAT-590 M8: delegates reach every flow path; the toolkit owns their lifecycle."""
from __future__ import annotations

import pytest

from parrot.tools.execution_plan import ExecutionPlanToolkit
from parrot.tools.execution_plan.checkpoint import build_plan_flow
from ...bots.flows.plan._delegate_fakes import FakeDelegate, FakeTool, FakeToolManager


def test_build_plan_flow_registers_delegate_factory_only_with_delegates() -> None: ...  # FILL IN
def test_toolkit_threads_delegates_to_all_build_sites(monkeypatch) -> None: ...        # FILL IN: spy build_plan_flow; run, resume, child
def test_validation_receives_delegates(monkeypatch) -> None: ...                       # FILL IN
def test_planner_rules_enabled_only_with_delegates(monkeypatch) -> None: ...          # FILL IN: spy PlanPlanner kwargs
def test_assert_policy_covers_delegate_tools() -> None: ...                           # FILL IN
@pytest.mark.asyncio
async def test_cleanup_closes_delegates_and_tolerates_errors() -> None: ...           # FILL IN
@pytest.mark.asyncio
async def test_checkpoint_holds_no_traces() -> None: ...                              # FILL IN: checkpoint projection has no trace/proposal keys
```

### FILL IN checklist
- [ ] `_planner` safe-tool computation (allowlist-scoped)
- [ ] `cleanup` delegate closing
- [ ] All eight call sites + two planner sites updated (re-grep first)
- [ ] Tests. Build the toolkit the way `tests/tools/execution_plan/test_toolkit_core.py` does; the relative import of `_delegate_fakes` must collect (verify)

---

## Acceptance Criteria

- [ ] Fresh, resume and child flows get the `"delegate"` factory when delegates are configured (S3)
- [ ] `cleanup()` closes every delegate
- [ ] AC13 (toolkit half) and AC10 (no traces in checkpoints)
- [ ] The existing execution_plan suites pass unmodified; `ruff check` is clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/tools/execution_plan/test_delegate_wiring.py -q`
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_toolkit_core.py -q`
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_runtime_repair.py -q`
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_checkpoint_resume.py -q`

---

## Test Specification

See the test file block above.

---

## Agent Instructions

Standard.

---

## Completion Note

*(Agent fills this in when done)*
