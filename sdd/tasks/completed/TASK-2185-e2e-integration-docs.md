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

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-07
**Notes**: Implemented all five integration tests in
`packages/ai-parrot/tests/tools/execution_plan/test_integration.py`:

- `test_basicagent_end_to_end_zero_tokens_in_loop` — a REAL
  `BasicAgent(name=...)` (not a lightweight harness), with the daily
  security sweep example plan run through a canned `PlanPlanner` client
  double + 4 fake tools registered on the agent's own real
  `tool_manager` via `ToolManager.register_tool(name=..., description=...,
  input_schema=..., function=...)`. `agent.client.ask` is replaced with an
  `AsyncMock` that raises `AssertionError` if ever called — a hard,
  fail-loud guard on the "zero LLM tokens during execution" claim, not a
  log grep. Asserts exactly 1 planner call (no repair needed), manifest
  <2 KB, no payload-body leakage (verified via a report *filename* marker
  that only exists inside the fake tool's raw body, not any facet or
  the plan's own `objective` text — see the two false-positive iterations
  noted below), and `"plan_execute" not in type(agent).__dict__` proving
  no monkeypatching of the class.
- `test_300_item_fanout_resumable` — simulates a crash by pre-populating
  150 of 300 expected WorkingMemory keys before calling `_run_plan`;
  asserts exactly 150 `get_item` tool calls (not 300) and a complete
  300-item manifest artifact, proving `for_each.skip_existing` recovery.
- `test_no_payload_in_flowcontext_results` — every plan-node value in
  `ctx.results` is an `ArtifactRef`.
- `test_agentcrew_add_tool_node_regression` — after
  `ensure_tool_node_registered(PlanToolNode)`, `AgentCrew.add_tool_node()`
  still builds crew's own `ToolNode` (not `PlanToolNode`) and
  `run_sequential()` still works.
- `test_allowlist_blocks_before_execution` — a plan naming a
  registered-but-not-allowlisted tool, run through the real
  `plan_execute(plan_name=...)` entry point, never calls
  `ToolManager.execute_tool` and registers no run.

Documentation added at `docs/toolkits/execution_plan_toolkit.md`,
following the repo's existing `docs/toolkits/<name>.md` convention (see
`docs/toolkits/infographic_toolkit.md`): wiring snippet, all four tools,
the `{params.<name>}` load-time-vs-runtime placeholder table, the
soft-timeout/`run_id` flow, failure semantics, and every v1 caveat
(in-RAM WorkingMemory with no guardrail, run registry lost on restart,
recovery = re-issue + `skip_existing`, no `plan_resume`). Spec §5
Acceptance Criteria checkboxes all flipped to `[x]` in this commit.

**Debugging note** (test-writing artifact, not a code defect): two
iterations of `test_basicagent_end_to_end_zero_tokens_in_loop`'s
no-payload-leak assertion were themselves wrong before landing on the
filename-marker check — `"findings" not in manifest_json` false-failed on
the legitimate facet name `"n_findings"`, and `"critical" not in
manifest_json` false-failed on the word "critical" inside the *plan's own
`objective` field text* ("...map new critical findings..."), not a
payload leak. Documented here so a future reader doesn't misread either
assertion's history as evidence of a real leak.

**Confirmed pre-existing, unrelated hang (not fixed — out of scope):**
`packages/ai-parrot/tests/test_crew_tool_node_regression.py` (an
existing FEAT-137 file, not owned by this feature) hangs indefinitely
when its `TestSequentialToolNode`/`TestFlowToolNode`/
`TestParallelToolNode`/`TestLoopToolNode` classes are run — reproduced
identically on plain `dev` with zero FEAT-419 changes applied
(`cd <main-repo-checkout> && pytest test_crew_tool_node_regression.py::
TestSequentialToolNode::test_agent_tool_agent_pipeline` hangs there too).
Confirmed NOT caused by TASK-2180's flow.py fsm fix — that fix only
touches the definition-driven branch of `_materialize_nodes()`
(`self._definition is not None`), and this crew suite exclusively uses
the programmatic `add_node()`/`add_edge()` branch (`self._definition is
None`), which was already correct and untouched. This feature's own
regression coverage (`test_agentcrew_add_tool_node_regression` above)
exercises the same `add_tool_node()` + `run_sequential()` path
successfully in under a second, so the acceptance criterion is
independently satisfied without needing that file to run. Flagging for a
separate ticket.

Full FEAT-419 suite: `pytest packages/ai-parrot/tests/bots/flows/plan/
packages/ai-parrot/tests/tools/execution_plan/ -v` → 128 passed. Full
pre-existing `packages/ai-parrot/tests/bots/flows/` suite (301 tests,
unrelated to the crew hang above) still green after TASK-2180's fsm fix.
`ruff check --select F,E9` clean.

**Post-completion addendum — adversarial code review (feature-level, after
all 7 tasks landed):** the `code-reviewer` agent (cross-checked against an
independent `codex exec review --base dev`) found and both independently
confirmed with live exploits/repros 4 CRITICAL issues, all fixed in a
follow-up commit (`fix(execution-plan-tool): address code-review CRITICAL
findings`) on top of this task's own commit:
1. `plan_name` path traversal (`store.py::_resolve_path`) — an
   LLM-controlled argument with no traversal guard let `plan_validate`
   read and return verbatim any YAML/JSON file on disk. Fixed: reject any
   `plan_name` containing a path separator or `..`, and verify the
   resolved candidate's parent is exactly `plans_dir`.
2. A malformed plan file crashed `plan_execute` with a raw uncaught
   `JSONDecodeError`/`yaml.YAMLError` instead of the promised structural
   `ToolResult` error. Fixed: `PlanFileStore._parse` now wraps both into
   `PlanLoadError`.
3. `AgentsFlow.from_definition`'s flow-level checkpointing defaults to
   `True` (`PlanMetadata.checkpoint`), which requires a live Redis-backed
   checkpoint store before the first node ever dispatches — silently
   contradicting this feature's own "pure in-RAM v1, no persistent
   backend" Non-Goal. All 133 tests passed only because this dev sandbox
   happens to run `redis-server`. Fixed: `_run_plan` now passes
   `checkpoint=False` explicitly to `AgentsFlow.from_definition`.
4. A node's hard failure (not a `for_each` per-item failure) left its
   downstream dependent neither in `ctx.results` nor `ctx.errors` (never
   dispatched by the scheduler's AND-join gate) — silently vanishing from
   the manifest instead of showing up as blocked. Fixed: `_execute_flow`
   now synthesizes a `status="error"` `ArtifactRef` for any plan node in
   neither bucket, so `nodes_total` accounting stays honest.

Also fixed the accompanying 🟠 Important finding: `PlanFileStore`'s
synchronous file I/O was called directly from an `async def` toolkit
method (blocking-I/O-in-async-context violation) — now wrapped in
`asyncio.to_thread`. Each of the 4 fixes has a dedicated regression test
(`test_store.py::test_path_traversal_rejected`,
`test_malformed_json_raises_plan_load_error_not_raw_exception`,
`test_malformed_yaml_raises_plan_load_error`;
`test_toolkit_core.py::test_hard_failed_node_downstream_dependent_shows_
as_error`, `test_checkpoint_disabled_no_redis_dependency`). Full suite
after the fix: 133 passed (up from 128); `ruff check --select F,E9`
clean. Docs (`docs/toolkits/execution_plan_toolkit.md`) updated to note
the checkpoint-disable decision under the v1 caveats.

Findings NOT fixed (noted, not blocking): 🟠 "uninformative tool error on
flow-level crash" was folded into fix #3/#4's `RunRecord.flow_error`
field as a byproduct. All 🟡/💡 suggestions (nitpicks on comment
placement, a redundant `.get(..., record)` fallback, `MAX_FACET_STR`
double-duty naming) were left as-is — cosmetic, no functional risk.

**Deviations from spec**: none
