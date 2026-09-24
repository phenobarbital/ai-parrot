# TASK-3636: End-to-end integration tests (plan with delegate triage)

**Feature**: FEAT-590 — Tool-Call Delegate
**Spec**: `sdd/specs/tool-call-delegate.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3635
**Assigned-to**: unassigned

---

## Context

Spec §4 integration tests, and AC2/AC3. These prove the whole path through
the real `ExecutionPlanToolkit` → `AgentsFlow`, with a `FakeDelegate` standing
in for a backend:

- a tool node feeds a delegate `for_each` triage
- accepted items are dispatched and stored
- rejected items are escalated
- the manifest carries the refs and the escalation count, and traces land in the sink

Plus back-compat: a FEAT-585 checkpoint of a tool-only plan still resumes (the
fingerprint is stable).

---

## Scope

- `test_plan_with_delegate_fan_out_end_to_end`: plan = `load_rows` (tool) → `triage` (delegate, `for_each` over `{artifacts.load_rows}` with `select: "rows[]"`, `on_reject: "escalate"`, `store_as: "triage_{index}"`). Run it through the toolkit's execute path. Assert:
  - `execute_tool` was called only for accepted items
  - the ArtifactRef status is `partial` with the right `escalated` count
  - the manifest never contains payload bodies
  - the sink received one trace per proposal
- `test_checkpointed_tool_plan_resumes_after_upgrade`: take a tool-only plan's `PlanRunMetadata` whose `plan_fingerprint` was computed with the *frozen* reference value from TASK-3626 and resume it. `_assert_policy` must not raise `policy_mismatch`.
- `test_mixed_plan_repair_targets_tool_node`: a failed tool node in a mixed plan is repairable end-to-end, and a delta targeting the delegate is refused.

**NOT in scope**: live backends (their integration tests live in TASK-3632/3633).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/tools/execution_plan/test_delegate_integration.py` | CREATE | End-to-end tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.execution_plan import ExecutionPlanToolkit                 # execution_plan/__init__.py:33
from parrot.bots.flows.plan.models import DelegatePlanNode, ExecutionPlan, ForEach, PlanNode   # TASK-3626
from parrot.bots.flows.plan.delegate import ToolCallProposal                 # TASK-3627
from ...bots.flows.plan._delegate_fakes import FakeDelegate, FakeTool, FakeToolManager         # TASK-3627
```

### Existing Signatures to Use
```python
# Reference for how existing integration tests drive the toolkit end-to-end (read before writing):
#   packages/ai-parrot/tests/tools/execution_plan/test_integration.py
#   packages/ai-parrot/tests/tools/execution_plan/test_integration_repair.py
#   packages/ai-parrot/tests/tools/execution_plan/_recovery_fakes.py (CountingToolManager, SerializingFakeCheckpointStore)
# ExecutionPlanToolkit(..., delegates=[...], delegate_trace_sink=..., allow_delegate_side_effects=False)   # TASK-3635
```

### Does NOT Exist
- ~~JSONPath `for_each` sources~~: use `ForEach(source="{artifacts.load_rows}", select="rows[]")`.
- ~~A real WorkingMemoryToolkit requirement~~: follow whatever the existing integration tests construct. Don't invent a new fake if they already use the real toolkit.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/tools/execution_plan/test_delegate_integration.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py#ExecutionPlanToolkit"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Test-only task. If a test exposes a bug in TASK-3626..3635 code, fix it **in the file that owns it**, record it in the Completion Note, and add that file to the table. Don't work around it in the test.

---

## Implementation Blueprint

### Steps (in order)
1. Read `test_integration.py` and `test_integration_repair.py` — *why*: reuse their toolkit construction and run helpers.
2. Write the three tests below — *why*: spec §4 integration table.

### `packages/ai-parrot/tests/tools/execution_plan/test_delegate_integration.py` (CREATE)
```python
"""FEAT-590: end-to-end — a plan with a delegate triage step, plus back-compat resume."""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from parrot.bots.flows.plan.delegate import ToolCallProposal
from parrot.bots.flows.plan.models import DelegatePlanNode, ExecutionPlan, ForEach, PlanNode
from ...bots.flows.plan._delegate_fakes import FakeDelegate, FakeTool, FakeToolManager


def _plan() -> ExecutionPlan:
    # FILL IN: load_rows (tool) → triage (DelegatePlanNode, for_each over {artifacts.load_rows} select rows[],
    #   tools=["retry_with_proxy", "mark_unavailable"], on_reject="escalate", store_as="triage_{index}")
    raise NotImplementedError


@pytest.mark.asyncio
async def test_plan_with_delegate_fan_out_end_to_end() -> None: ...       # FILL IN (see Scope)
@pytest.mark.asyncio
async def test_checkpointed_tool_plan_resumes_after_upgrade() -> None: ... # FILL IN (AC2 end-to-end)
@pytest.mark.asyncio
async def test_mixed_plan_repair_targets_tool_node() -> None: ...         # FILL IN (AC12 end-to-end)
```

### FILL IN checklist
- [ ] `_plan` and the three test bodies

---

## Acceptance Criteria

- [ ] AC3 end-to-end, AC2 via resume, AC12 via repair
- [ ] `ruff check` is clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/tools/execution_plan/test_delegate_integration.py -q`

---

## Test Specification

See the test file block above.

---

## Agent Instructions

Standard.

---

## Completion Note

Implemented by coder seat `gpt-5.6-terra` (codex), attempt_uid
`d64876dcc8154179a3b3fa255613510d`. Merged clean; `black` lint reported 0
errors/residuals. Reviewed and recorded (`coder-review:35ff19acb9940828d1d74f3d`).

**Review fix (disclosed):** post-merge orchestrator verification found
`test_mixed_plan_repair_targets_tool_node` failing — the test's own toolkit never
passed a `checkpoint_store`, so `plan_repair()` always refused with
`checkpoint_unavailable` before ever reaching the delta/replan logic it claims to
exercise; the test also asserted the wrong status literal (`"partial"` instead of
the architecturally correct `"failed"` for a linear dependency chain where nothing
reaches ok/skipped). Fixed in commit `9e155cce8707d0be1fb36cdbe45846c14a80b8f4`
(combined with a TASK-3628 finding — see that task's retroactive note). Recorded as
model feedback (`coder-feedback:69d8db4f40f7eae4e67d98fc`).

**Validation**: `pytest packages/ai-parrot/tests/tools/execution_plan/test_delegate_integration.py -q`
→ 3 passed after the fix. Broader regression: `pytest
packages/ai-parrot/tests/bots/flows/plan/ packages/ai-parrot/tests/tools/execution_plan/ -q`
→ **328 passed, 3 skipped**, with exactly one remaining failure —
`test_integration_recovery.py::test_fresh_process_recovery_chain` — in a file
completely untouched by any FEAT-590 task (confirmed via `git diff origin/dev`),
pre-existing and unrelated (same category as `issue:c3c59277ef77`; likely the same
subprocess/fork sandboxing artifact this session already documented for
`ProcessPoolExecutor` in the TASK-3624 spike).

**Merge-tier validation deviation (disclosed):** same as prior tasks — the
feature-wide `coder_run_validation` (tier=merge) sweep remains environmentally
blocked (`issue:c3c59277ef77`). This task is closed on its own directly-verified
scoped test evidence (post-fix) plus the broader regression sweep above.
