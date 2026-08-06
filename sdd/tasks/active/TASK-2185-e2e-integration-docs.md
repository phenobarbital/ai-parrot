# TASK-2185: End-to-end integration tests + documentation

**Feature**: FEAT-419 — ExecutionPlanToolkit — deterministic tool-call DAGs for a BasicAgent
**Spec**: `sdd/specs/execution-plan-tool.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2179, TASK-2180, TASK-2181, TASK-2182, TASK-2183, TASK-2184
**Assigned-to**: unassigned

---

## Context

Proof that the whole design holds on a real `BasicAgent`: zero LLM tokens
during execution, payloads only in WorkingMemory, resumability, allowlist
enforcement, and the `AgentCrew.add_tool_node()` regression. Plus user
docs. Implements spec §3 Module 6 and closes the spec's §5 checklist.

---

## Scope

- Integration tests at
  `packages/ai-parrot/tests/tools/execution_plan/test_integration.py`:
  - `test_basicagent_end_to_end_zero_tokens_in_loop`: a real `BasicAgent`
    wired with `ExecutionPlanToolkit` (fake tool fleet, canned planner
    double, real in-memory WM). Assert: planner double called ≤2×; ZERO
    LLM-client calls between validation success and manifest; every
    payload only in WM; the serialized manifest of the example plan is
    <2 KB; the agent's class body is unchanged (no monkeypatching of
    `BasicAgent`).
  - `test_300_item_fanout_resumable`: `for_each` over 300 items with an
    injected crash mid-run; re-issue the same plan; assert only missing
    keys were re-executed (`skip_existing`) and the final manifest is
    complete.
  - `test_no_payload_in_flowcontext_results`: every `ctx.results` value is
    an `ArtifactRef`, never a body.
  - `test_agentcrew_add_tool_node_regression`: after
    `ensure_tool_node_registered(PlanToolNode)` has run,
    `AgentCrew.add_tool_node()` still behaves as before (crew `ToolNode`,
    not `PlanToolNode`).
  - Allowlist e2e: a plan naming a registered-but-not-allowlisted tool
    never executes anything.
- Documentation in `docs/` (place alongside existing feature docs; check
  `docs/` layout first): what the toolkit does, wiring example
  (constructor + the four tools), the plan file + `{params.<name>}`
  contract, the soft-timeout/`run_id` flow, failure semantics
  (partial = data), and the v1 caveats: WorkingMemory is in-RAM (no
  guardrail — cost visible via `bytes_stored`), run registry lost on
  restart, recovery = re-issue + `skip_existing`. Do NOT promise
  `plan_resume`.

**NOT in scope**: new toolkit behavior — if a test exposes a defect, fix
belongs to the owning task's module but lands here as a follow-up commit
with a note; persistent WM backend docs (separate future feature).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/tools/execution_plan/test_integration.py` | CREATE | E2E suite |
| `docs/execution-plan-toolkit.md` (or the repo's feature-docs convention) | CREATE | Usage documentation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.execution_plan import ExecutionPlanToolkit  # TASK-2180/2184
from parrot.bots.flows.plan import ArtifactRef, ExecutionPlan, PlanToolNode
# BasicAgent import — verify the real path (parrot/bots/agent.py defines it;
#   check how tests elsewhere import it) before writing the test.
# AgentCrew — parrot/bots/flows/crew/crew.py (moved there in FEAT-143).
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/crew/tool_node.py:168
class ToolNode(Node):  # crew's own tool node — the regression subject;
#   AgentCrew.add_tool_node() must keep using THIS class, untouched by the
#   NODE_REGISTRY["tool"] = PlanToolNode registration.

# packages/ai-parrot/src/parrot/tools/working_memory/internals.py:458
class WorkingMemoryCatalog:  # in-RAM dict — the docs caveat anchor.

# spec §5 Acceptance Criteria — this task's checklist mirrors it; read it.
```

### Does NOT Exist
- ~~`plan_resume`~~ — must NOT appear in docs or tests as a capability.
- ~~persistent WM backend~~ — document as explicit v1 limitation.
- `BasicAgent._inject_answer_memory_into_toolkits()` (bots/agent.py:145)
  does NOT match wrapped toolkits — the wiring example in docs must show
  explicit constructor injection of the shared `WorkingMemoryToolkit`,
  never rely on auto-injection.
- ~~network/provider access in tests~~ — all LLM surfaces are doubles.

---

## Implementation Notes

### Key Constraints
- The zero-token assertion is the feature's headline claim — implement it
  as a hard call-count assertion on the client double(s), not a log grep.
- The 300-item test must stay fast: fake tools are in-process async
  functions (no sleeps beyond what the crash-injection needs).
- Docs follow the existing docs/ tone; include one complete copy-pasteable
  wiring snippet and the daily_security_sweep example plan file reference
  (`examples/plans/daily_security_sweep.json` from TASK-2181).

### References in Codebase
- `packages/ai-parrot/tests/` — existing integration-test conventions
  (fixtures, markers, asyncio mode) — mirror them.
- `sdd/specs/execution-plan-tool.spec.md` §4/§5 — the authoritative test
  matrix and completion checklist.

---

## Acceptance Criteria

- [ ] All five integration tests implemented and passing:
  `pytest packages/ai-parrot/tests/tools/execution_plan/test_integration.py -v`
- [ ] Zero-token claim asserted by call counts (planner ≤2; execution
  window = 0)
- [ ] Manifest size assertion (<2 KB for the example plan) green
- [ ] `AgentCrew.add_tool_node()` regression green
- [ ] Full feature suite green:
  `pytest packages/ai-parrot/tests/bots/flows/plan/ packages/ai-parrot/tests/tools/execution_plan/ -v`
- [ ] Docs page created; covers wiring, both modes, failure semantics, and
  ALL v1 caveats (RAM, restart, no plan_resume)
- [ ] Every unchecked item in spec §5 Acceptance Criteria is now
  verifiable and checked off in the spec (update the spec checkboxes in
  the same commit)

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/execution_plan/test_integration.py
class TestEndToEnd:
    async def test_basicagent_end_to_end_zero_tokens_in_loop(...): ...
    async def test_300_item_fanout_resumable(...): ...
    async def test_no_payload_in_flowcontext_results(...): ...
    async def test_agentcrew_add_tool_node_regression(...): ...
    async def test_allowlist_blocks_before_execution(...): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2179…2184 all in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm the real `BasicAgent` and
   `AgentCrew` import paths before writing tests
4. **Update status** in `sdd/tasks/index/execution-plan-tool.json` → `"in-progress"`
5. **Implement**, 6. **Verify**, 7. **Move this file** to
   `sdd/tasks/completed/`, 8. **Update index** → `"done"`, 9. **Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
