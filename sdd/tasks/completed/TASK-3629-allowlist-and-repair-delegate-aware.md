# TASK-3629: Delegate-aware allowlist and repair

**Feature**: FEAT-590 — Tool-Call Delegate
**Spec**: `sdd/specs/tool-call-delegate.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3626, TASK-3628
**Assigned-to**: unassigned

---

## Context

Spec Module 4, part 2. The toolkit's allowlist and FEAT-585's `plan_repair`
both read `node.tool`, which delegate nodes don't have. This task switches
them to `tool_names()` (TASK-3626). It also makes `plan_repair` refuse a delta
that targets a delegate node (AC12), and threads the delegate chain through
`validate_delta` → `validate_with_allowlist`.

That last change matters because `validate_delta` re-validates the **merged**
plan. Without the chain, repairing *any* plan that contains a delegate node
would fail with `no_delegate_configured`, even when the delta only touches a
tool node.

---

## Scope

- `check_allowlist`: iterate `node.tool_names()` and emit one `tool_not_allowed` per disallowed name.
- `validate_with_allowlist(..., delegates=None, allow_delegate_side_effects=False)`: forward both to `validate_plan`.
- `validate_delta(..., delegates=None, allow_delegate_side_effects=False)`:
  - `delta_delegate_not_repairable` when the original node is a `DelegatePlanNode`
  - `delta_tool_not_allowed` stays as-is (`PlanDelta` nodes are always `PlanNode`)
  - forward the kwargs to `validate_with_allowlist`
- Write tests.

**NOT in scope**: passing these kwargs from the toolkit (TASK-3635); `toolkit._assert_policy` (TASK-3635); changing `PlanDelta` (it stays `List[PlanNode]`, a spec non-goal).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/execution_plan/catalog.py` | MODIFY | `tool_names()` allowlist + kwargs |
| `packages/ai-parrot/src/parrot/tools/execution_plan/repair.py` | MODIFY | Refuse delegate targets + forward kwargs |
| `packages/ai-parrot/tests/tools/execution_plan/test_delegate_allowlist_repair.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.plan import DelegatePlanNode, ExecutionPlan, PlanNode   # DelegatePlanNode exported by TASK-3626
from parrot.tools.execution_plan.catalog import check_allowlist, validate_with_allowlist   # catalog.py:113,145
from parrot.tools.execution_plan.repair import validate_delta                             # repair.py:88
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/execution_plan/catalog.py
def check_allowlist(plan, allowed_tools: Optional[Sequence[str]]) -> List[ValidationIssue]   # line 113
    #   for node in plan.nodes:
    #       if node.tool not in allowed_set:      <-- anchor (line 133), message at 138
def validate_with_allowlist(plan, tool_manager, allowed_tools=None, *, check_guards: bool = True) -> ValidationReport  # line 145
    #   report = validate_plan(plan, tool_manager, check_guards=check_guards)   # line 164
# packages/ai-parrot/src/parrot/tools/execution_plan/repair.py
from parrot.bots.flows.plan import ExecutionPlan, PlanNode                    # line 16
def validate_delta(delta: PlanDelta, *, run: PlanRun, tool_manager: Any, allowed_tools: Sequence[str]) -> ValidationReport  # line 88
    #   original: Dict[str, PlanNode] = {node.id: node for node in plan.nodes}   # line 113 → annotate Dict[str, Any]
    #   original_node = original[node.id]                                       <-- anchor (line 130)
    #   return validate_with_allowlist(merged, tool_manager, effective_allowlist)  # line 180
def _for_each_identity_changed(original_node: PlanNode, replacement: PlanNode) -> bool   # line 183
```

### Does NOT Exist
- ~~`PlanDelta` accepting `DelegatePlanNode`~~: it doesn't, by design.
- ~~`delta_delegate_not_repairable`~~: new code, added here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/execution_plan/catalog.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/tools/execution_plan/repair.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/execution_plan/test_delegate_allowlist_repair.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/catalog.py#check_allowlist",
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/catalog.py#validate_with_allowlist",
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/repair.py#validate_delta"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Tool-only plans must yield the same issues and messages as before, and the existing `test_delta_validation.py` / `test_catalog.py` must pass unmodified.
- In `validate_delta`, after appending `delta_delegate_not_repairable`, `continue` to the next delta node. The other identity checks assume a `PlanNode` original.

---

## Implementation Blueprint

### Steps (in order)
1. Update `check_allowlist` and `validate_with_allowlist` — *why*: allowlist coverage for delegate tools.
2. Update `validate_delta` — *why*: AC12, and so a merged plan that contains a delegate still validates.
3. Write tests.

### `packages/ai-parrot/src/parrot/tools/execution_plan/catalog.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        if node.tool not in allowed_set:' catalog.py)
# REPLACE the loop body at catalog.py:132-141 with:
    for node in plan.nodes:
        for tool_name in sorted(node.tool_names()):
            if tool_name not in allowed_set:
                issues.append(
                    ValidationIssue(
                        node.id,
                        "tool_not_allowed",
                        f"Tool {tool_name!r} is not in the allowed_tools list. "
                        f"Allowed: {sorted(allowed_set)}.",
                    )
                )
# validate_with_allowlist (line 145): add keyword-only `delegates: Optional[Sequence[Any]] = None,
#   allow_delegate_side_effects: bool = False` and forward both to validate_plan at line 164; document them.
```
**Why**: for a tool node, `tool_names()` is `{tool}`, so the message is unchanged.

### `packages/ai-parrot/src/parrot/tools/execution_plan/repair.py` (MODIFY)
```python
# line 16: from parrot.bots.flows.plan import DelegatePlanNode, ExecutionPlan, PlanNode
# validate_delta signature (line 88): add `delegates: Optional[Sequence[Any]] = None,
#   allow_delegate_side_effects: bool = False` (keyword-only; document them)
# occurrences: 1 (verified: grep -c '        original_node = original\[node.id\]' repair.py)
# AFTER — insert below `        original_node = original[node.id]` (repair.py:130):
        if isinstance(original_node, DelegatePlanNode):
            issues.append(
                ValidationIssue(
                    node_id=node.id,
                    code="delta_delegate_not_repairable",
                    message="delegate nodes are not repairable in v1; the delta may only replace tool nodes",
                )
            )
            continue
# line 180: return validate_with_allowlist(merged, tool_manager, effective_allowlist,
#               delegates=delegates, allow_delegate_side_effects=allow_delegate_side_effects)
```
**Why**: spec §1 non-goal and AC12. `continue` skips checks that dereference `.tool`. Check whether `Optional` is already imported in `repair.py` before adding it.

### `packages/ai-parrot/tests/tools/execution_plan/test_delegate_allowlist_repair.py` (CREATE)
```python
"""FEAT-590: allowlist + repair are delegate-aware."""
from __future__ import annotations

from parrot.bots.flows.plan.models import DelegatePlanNode, ExecutionPlan, PlanNode
from parrot.tools.execution_plan.catalog import check_allowlist


def test_allowlist_covers_delegate_tools() -> None: ...           # FILL IN: one issue per disallowed delegate tool
def test_allowlist_tool_only_unchanged() -> None: ...             # FILL IN
def test_delta_targeting_delegate_rejected() -> None: ...         # FILL IN: build a PlanRun like test_delta_validation.py does (reuse its helpers)
def test_delta_on_tool_node_in_mixed_plan_validates() -> None: ...  # FILL IN: pass delegates=[FakeDelegate([])] → no no_delegate_configured
```

### FILL IN checklist
- [ ] Test bodies. Reuse how `tests/tools/execution_plan/test_delta_validation.py` builds a `PlanRun` (read it first); `FakeDelegate` via `from ...bots.flows.plan._delegate_fakes import FakeDelegate` (TASK-3627)

---

## Acceptance Criteria

- [ ] AC12: `delta_delegate_not_repairable`
- [ ] Mixed-plan repair validates when `delegates` is forwarded
- [ ] The existing catalog and delta tests pass unmodified
- [ ] `ruff check` is clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/tools/execution_plan/test_delegate_allowlist_repair.py -q`
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_delta_validation.py -q`
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_catalog.py -q`

---

## Test Specification

See the test file block above.

---

## Agent Instructions

Standard.

---

## Completion Note

Implemented by coder seat `gpt-5.6-terra` (codex), attempt_uid
`d6f4aaac4ed6493f917dd9a10ec2c8e4`. Merged clean; `black` lint reported 0
errors/residuals. Reviewed and recorded (`coder-review:ed5c12740eb478610d1f61fe`,
no corrections needed).

**Validation**: re-verified directly by the orchestrator post-merge —
`pytest packages/ai-parrot/tests/tools/execution_plan/test_delegate_allowlist_repair.py
packages/ai-parrot/tests/tools/execution_plan/test_delta_validation.py
packages/ai-parrot/tests/tools/execution_plan/test_catalog.py -q` → 30 passed.

**Merge-tier validation deviation (disclosed):** same as prior tasks — the
feature-wide `coder_run_validation` (tier=merge) sweep remains environmentally
blocked (`issue:c3c59277ef77`). This task is closed on its own directly-verified
scoped test evidence.
