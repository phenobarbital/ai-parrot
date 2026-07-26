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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
