# TASK-1910: QA repair loop — state, models, and topology

**Feature**: FEAT-377 — Graph Engineering Hardening
**Spec**: `sdd/specs/graphindex-as-engineering-devloop.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1906
**Assigned-to**: unassigned

---

## Context

Module 3 item 1, topology half (spec §3). Today `qa failed →
failure_handler` is terminal — the single highest-ROI gap (G1). This task
adds the bounded retry edge in BOTH topology forms plus the state/model
plumbing. Node behavior (feedback injection, worktree reuse) is TASK-1911.

---

## Scope

- `models.py`: add `attempt: int = 1` to `QAReport` (CEL predicates can only
  see fields ON the report — the engine's `cel_evaluator` coerces the node
  result via `model_dump()`).
- `session_state.py`: add `QaAttemptRecorded` action
  (`type: Literal["qa_attempt_recorded"]`, `attempt: int`, `qa_notes: str = ""`)
  to the `DevLoopAction` discriminated union (lines 406-417) and a branch in
  `reduce()` (line 560) persisting the counter into the state tree.
- New config `DEV_LOOP_QA_MAX_RETRIES` (default `2`), declared wherever the
  other `DEV_LOOP_*` keys live (grep `DEV_LOOP_GATE_TTL_DEPLOYMENT` for the
  mechanism).
- `definition.py`: replace the single `_CEL_QA_FAILED` edge with two, where
  `N` is interpolated from config at `build_dev_loop_definition()` time:
  - `qa → development`, predicate
    `"result.passed == false && result.attempt < N"`
  - `qa → failure_handler`, predicate
    `"result.passed == false && result.attempt >= N"`
  Keep `_CEL_QA_PASSED` edge unchanged.
- `flow.py` (lines 343-345): mirror with Python predicates
  (`_qa_retry` / `_qa_exhausted` closures over the configured N).
- Extend the definition↔flow parity test for the new edge.
- **Cycle check**: the back-edge introduces a cycle in the declared graph.
  The dev-loop executes in explicit-edge mode (OR-join), which supports it,
  but run the definition validation/materialization path
  (`test_declarative_flow.py`) — if the validator rejects cycles, scope an
  exemption to `on_condition` back-edges (spec §7 Known Risks).

**NOT in scope**: QA node stamping `attempt`, development-node feedback
redispatch, worktree reuse, e2e tests (all TASK-1911); escalation model
(TASK-1912).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` | MODIFY | `QAReport.attempt` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py` | MODIFY | `QaAttemptRecorded` + reducer branch |
| `packages/ai-parrot/src/parrot/flows/dev_loop/definition.py` | MODIFY | retry/exhaustion CEL edges |
| `packages/ai-parrot/src/parrot/flows/dev_loop/flow.py` | MODIFY | mirrored Python-predicate edges |
| `packages/ai-parrot/tests/flows/dev_loop/test_declarative_flow.py` | MODIFY | parity + cycle validation |
| `packages/ai-parrot/tests/flows/dev_loop/test_session_state.py` | MODIFY | reducer branch test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.models import QAReport
from parrot.flows.dev_loop.session_state import ActionEnvelope, reduce
from parrot.bots.flows.flow.definition import EdgeDefinition, FlowDefinition, NodeDefinition
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/definition.py:47-50
_CEL_QA_PASSED = "result.passed == true"
_CEL_QA_FAILED = "result.passed == false"
# Edge pattern (105-108) — `from` is a keyword, use dict unpack:
EdgeDefinition(**{"from": QA}, to=HANDOFF, condition="on_condition", predicate=_CEL_QA_PASSED)
# Node-id constants at top of definition.py: QA = "qa", DEVELOPMENT = "development",
# FAILURE = "failure_handler", HANDOFF = "deployment_handoff"

# packages/ai-parrot/src/parrot/flows/dev_loop/flow.py:343-345 (rewire these)
flow.add_edge("qa", "deployment_handoff", predicate=_qa_passed)
flow.add_edge("qa", "failure_handler", predicate=_qa_failed)

# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:249-256
def add_edge(self, from_: str, to: str, *, condition: str = "always",
             predicate: Optional[Union[str, Callable[[Any], bool]]] = None) -> FlowEdge:
# predicate auto-promotes condition to "on_condition" (lines 284-285)

# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
# DevLoopAction = Annotated[Union[...], Field(discriminator="type")]  # lines 406-417
# def reduce(state, action) -> DevLoopSessionState:  # line 560, flat `if t == "...":`
#   unknown action → no-op return at line 689
# NO register function exists — extend the union AND add a reduce branch.

# packages/ai-parrot/src/parrot/flows/dev_loop/models.py:487-511
class QAReport(BaseModel):
    passed: bool; criterion_results: List[CriterionResult]
    lint_passed: bool; lint_output: str = ""; notes: str = ""
    code_review_passed: bool = True; code_review_findings: List[str] = []
```

### Does NOT Exist
- ~~`qa_attempts` / `qa_retries` / `QaAttemptRecorded`~~ — nothing like this exists; this task creates it
- ~~`DEV_LOOP_QA_MAX_RETRIES`~~ — not in code/config; this task declares it
- ~~`register_reducer()` or a reducer registry~~ — reducers are a flat if-match in `reduce()`
- ~~`QAReport.attempt`~~ — this task adds it
- ~~a `qa → development` edge in either topology form~~ — this task adds both

### MAJOR scope expansion discovered during implementation (2026-07-26)

**The task's Known Risk ("verify the materialization/validation path
tolerates the cycle... if the validator rejects cycles, scope the
exemption to `on_condition` back-edges") undersold the actual gap.**
Hands-on testing (see Completion Note) proved TWO problems, not one, both
in shared core engine files NOT in this task's file list:

1. `FlowDefinition._validate_acyclic`
   (`packages/ai-parrot/src/parrot/bots/flows/flow/definition.py`) DOES
   reject the new `qa → development` edge with `ValueError: Cycle
   detected` — confirmed by constructing `build_dev_loop_definition()`
   under pytest before the fix. Exactly the risk the task anticipated;
   fixed by exempting `on_condition` edges from the check.
2. **Not anticipated by the task**: even after (1), `AgentsFlow.run_flow`'s
   explicit-edge OR-join scheduler (`bots/flows/flow/flow.py`) DEADLOCKS
   on the very first run — "development" never dispatches at all, because
   the OR-join gate waits for ALL incoming edges to resolve before a
   node's FIRST dispatch, including the back-edge from "qa", which cannot
   resolve until "development" has already run once. Proven with a
   minimal `StubNode` reproduction before any fix (`_ran(ctx) == []`).
   This is a genuine execution-semantics gap, not a validation one — the
   task's claim "explicit-edge mode supports [cycles]" was true only for
   validation-time tolerance, not for actual node re-entry.

Both are shared, high-blast-radius engine files used by every flow in the
codebase, not just dev_loop. Fixing them was unavoidable — without it,
Module 3's entire objective (and TASK-1911's e2e tests) would be
impossible, since no later task's file list touches the engine either.
See the Completion Note for the exact design and the regression coverage
added to de-risk it (full `packages/ai-parrot/tests/bots/` suite: same
64 pre-existing unrelated failures before and after, zero new ones).

---

## Implementation Notes

### Pattern to Follow
```python
# CEL interpolation at build time (definition.py):
max_retries = int(<config>("DEV_LOOP_QA_MAX_RETRIES", 2))
cel_retry = f"result.passed == false && result.attempt < {max_retries}"
cel_exhausted = f"result.passed == false && result.attempt >= {max_retries}"
```

### Key Constraints
- FEAT-322 event sourcing: NEVER mutate state; new action + pure reducer
  branch only. State tree types are frozen models — follow the existing
  branch style in `reduce()`.
- FEAT-250 parity: declaration and imperative wiring must match
  edge-for-edge; the parity test in `test_declarative_flow.py` asserts it.
- `build_dev_loop_definition(revision=...)` — decide whether the revision
  graph also gets a retry edge: NO (spec scopes repair to the main loop;
  revision QA failure keeps routing to failure_handler).

### References in Codebase
- `packages/ai-parrot/tests/flows/dev_loop/test_declarative_flow.py` — parity test to extend
- `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py:71-79` — config-attr lookup mechanism to copy for the new key

---

## Acceptance Criteria

- [ ] `QAReport(passed=False, attempt=1)` routes to `development`; `attempt=N` routes to `failure_handler` (unit, both topology forms)
- [ ] `QaAttemptRecorded` replays through `reduce()`; unknown-action no-op preserved
- [ ] Parity test covers the new edges; definition validation tolerates the `on_condition` back-edge
- [ ] Default N=2 without config; honors `DEV_LOOP_QA_MAX_RETRIES`
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/` clean

---

## Test Specification

```python
def test_qa_retry_edge_routes_to_development(): ...
def test_qa_exhausted_edge_routes_to_failure(): ...
def test_definition_flow_parity_includes_retry_edge(): ...
def test_reduce_qa_attempt_recorded(): ...
def test_qa_report_attempt_default_is_1(): ...
```

---

## Agent Instructions

1. **Read the spec** for full context
2. **Check dependencies** — TASK-1906 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/graphindex-as-engineering-devloop.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill the Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-26
**Notes**:

**Core scope (as specified):**
- `models.py`: `QAReport.attempt: int = Field(default=1, ge=1, ...)`.
- `session_state.py`: `QaAttemptRecorded` action + `run/qaAttemptRecorded`
  reducer branch; `DevLoopSessionState` gained `qa_attempts: int = 0` /
  `qa_notes: str = ""` fields so the counter is replayable via
  `view=state`. **Naming deviation**: the spec's Data Models sketch names
  the action's `type` literal `"qa_attempt_recorded"`; every one of the
  other 21 actions in `DevLoopAction` follows a strict
  `"<namespace>/camelCase"` convention (`"run/jiraLinked"`,
  `"gate/opened"`, ...), so this uses `"run/qaAttemptRecorded"` instead —
  semantically identical, documented in the class docstring, no code
  parses the string structurally.
- `DEV_LOOP_QA_MAX_RETRIES` declared in `conf.py` (`config.getint(...,
  fallback=2)`), next to `DEV_LOOP_ACTIONS_RETENTION_DAYS` — read at
  `build_dev_loop_definition()` / `build_dev_loop_flow()` **call time**
  (not import time) via `parrot.conf`, matching the established
  `monkeypatch.setattr(conf, "DEV_LOOP_...", ...)` test pattern used
  throughout `tests/flows/dev_loop/`.
- `definition.py`: `_cel_qa_retry(n)` / `_cel_qa_exhausted(n)` replace the
  single `qa → failure_handler` (`_CEL_QA_FAILED`) edge with two —
  `qa → development` (retry) and `qa → failure_handler` (exhausted) — in
  `build_dev_loop_definition()` only; `_build_revision_definition()` is
  untouched per the task's explicit decision (no retry edge on the
  revision graph).
- `flow.py`: `_make_qa_retry(n)` / `_make_qa_exhausted(n)` closures mirror
  the CEL edges with Python callables in `build_dev_loop_flow()`.
  `_qa_failed` (used by `runner.py`'s **revision** flow) is untouched and
  documented as such.
- `test_declarative_flow.py`: `test_qa_report_attempt_default_is_1`,
  `test_qa_retry_edge_routes_to_development`,
  `test_qa_exhausted_edge_routes_to_failure` (predicate-level, both
  topology forms), `test_definition_flow_parity_includes_retry_edge`
  (edge-for-edge). Fixed `test_routing_qa_fail_goes_to_failure`'s stub
  (stamps the exhaustion attempt so a single "always fails" QA stub
  doesn't now infinite-loop through the real retry edge) and added two
  genuine end-to-end tests through the REAL `build_dev_loop_flow()`:
  `test_routing_qa_retry_then_pass_reaches_close` (fail once → retry →
  pass → close) and `test_routing_qa_exhausts_after_max_retries` (fails
  N times → failure_handler, bounded).
- `test_session_state.py`: `test_reduce_qa_attempt_recorded`,
  `test_reduce_qa_attempt_recorded_replays_latest_attempt`,
  `test_qa_attempt_recorded_unknown_action_still_no_op`.

**Unplanned but necessary engine work (see Codebase Contract "MAJOR scope
expansion" above for the discovery):**
- `packages/ai-parrot/src/parrot/bots/flows/flow/definition.py`:
  `_validate_acyclic` now skips `condition == "on_condition"` edges when
  building the Kahn's-algorithm graph — a CEL-gated back-edge is a
  deliberate bounded loop, not a structural bug. Unconditional cycles
  (`always`/`on_success`/`on_error`/`on_timeout`) still raise.
- `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` (the bigger
  fix): `run_flow`'s explicit-edge scheduler gained genuine cyclic
  re-entry support:
  - `_forward_in_edges[tgt]` = `incoming[tgt]` minus any edge identified
    as a cyclic back-edge (an `on_condition` edge whose target can
    already reach its own source via the full edge graph) — used instead
    of raw `incoming` for both the initial entry-node dispatch and the
    OR-join readiness gate, so a back-edge never blocks a node's FIRST
    dispatch.
  - `_resolve_retries()`: when a back-edge's source resolves and its
    predicate fires, every node on the cycle (target through source,
    inclusive — computed once via forward-reachability-from-target ∩
    backward-reachability-to-source over the full edge graph) is reset
    (`completed`/`failed`/`skipped`/`results`/`errors`/`tasks` cleared,
    FSM replaced with a fresh `AgentTaskMachine`, mirroring the existing
    same-node `max_retries` reset pattern a few lines above) and the
    target is re-dispatched. Checked once per completion event, ahead of
    the normal OR-join pass (which would otherwise act on now-stale
    state).
- Regression coverage added directly against the engine:
  `test_definition_cycle.py::TestOnConditionCycleExemption` (2 tests:
  on_condition back-edge allowed, unconditional cycle still rejected
  alongside an unrelated on_condition edge) and
  `test_explicit_edges.py::TestCycleValidation` (+3 tests: back-edge
  exempt from cycle check but never actually fires, unconditional cycle
  still raises, and — the load-bearing one —
  `test_back_edge_actually_retries_and_completes`: a counting node fails
  its predicate on attempt 1, retries, passes on attempt 2, reaches the
  terminal node, `_ran(ctx) == ["dev", "qa", "dev", "qa", "end"]`).
- Fixed two other pre-existing dev_loop tests that would have
  **infinite-looped** under the new real retry edge (both construct a
  fixed `QAReport(passed=False)` with the default `attempt=1`, which now
  retries forever against a dispatcher stub that never varies its
  answer): `test_flow.py::test_qa_fail_routes_to_failure_handler` (now
  stamps `attempt=DEV_LOOP_QA_MAX_RETRIES`; added a companion
  `test_qa_fail_below_retry_cap_routes_to_development`) and
  `test_runner.py::_dispatcher_returning` (the shared dispatcher-stub
  helper — stamps the same exhaustion attempt on a failing QAReport).
  Found these by bisecting a hung `pytest packages/ai-parrot/tests/flows/dev_loop/`
  run with `timeout`/per-file isolation — confirmed via `git stash` that
  neither test hung on the pre-TASK-1910 baseline.

**Validation:**
- `pytest packages/ai-parrot/tests/flows/dev_loop/ -m "not live"` (minus
  the pre-existing `hypothesis`-missing file): 662 passed, 1 skipped,
  same one pre-existing unrelated `test_lazy_import.py` failure noted in
  every prior task this session.
- `pytest packages/ai-parrot/tests/bots/flow/ packages/ai-parrot/tests/bots/flows/`:
  249 passed (was 246 before this task's engine tests).
- `pytest packages/ai-parrot/tests/bots/ -m "not live"`: 1010 passed, 64
  failed — **identical 64 failures on the pre-TASK-1910 baseline**
  (verified via `git stash`), all in unrelated files (prompts, RAG,
  vector-context, Porygon migration) — zero regressions from the engine
  change.
- `ruff check` clean on every touched file except two pre-existing,
  unrelated findings confirmed via `git stash` diff: `conf.py:450`
  (`E402`, a pre-existing import-order finding ~500 lines from this
  task's addition) and the graphindex `Any`/`TraversalPattern` unused
  imports already noted in TASK-1909's completion note.

**Deviations from spec**:
1. `QaAttemptRecorded.type` literal uses `"run/qaAttemptRecorded"` instead
   of the spec sketch's `"qa_attempt_recorded"` (naming-convention fix,
   see Codebase Contract).
2. Two shared core-engine files
   (`bots/flows/flow/definition.py`, `bots/flows/flow/flow.py`) were
   modified — not in this task's file list — because the repair loop is
   provably impossible without them (deadlock, demonstrated before the
   fix). Flagging prominently for review given the blast radius (every
   flow in the codebase uses this scheduler), despite the full
   `tests/bots/` suite showing zero regressions.
3. Two additional dev_loop test files
   (`test_flow.py`, `test_runner.py`) needed a one-line stub fix each to
   avoid a genuine infinite loop under the new topology — not architecture
   changes, just test fixtures catching up to real behavior change.
