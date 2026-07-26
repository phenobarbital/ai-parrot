# TASK-1911: QA repair loop — node behavior, feedback redispatch, e2e

**Feature**: FEAT-377 — Graph Engineering Hardening
**Spec**: `sdd/specs/graphindex-as-engineering-devloop.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1910
**Assigned-to**: unassigned

---

## Context

Module 3 item 1, behavior half (spec §3). TASK-1910 gives the graph a
`qa → development` back-edge and the `attempt` counter; this task makes the
nodes use them: QA stamps the attempt, development re-entry carries the
prior `QAReport`'s failures as feedback into the redispatch brief, and the
worktree from attempt 1 is reused so committed progress survives.

---

## Scope

- `nodes/qa.py`: stamp `QAReport.attempt` from shared state (attempt counter
  key set by the development node or session state; 1 on first pass). Emit
  the `QaAttemptRecorded` action (from TASK-1910) when the report fails and
  a retry will occur.
- `nodes/development.py`: on re-entry (shared state contains a prior failed
  `QAReport`), append a condensed failure summary to the dispatch brief —
  failed `CriterionResult` names + `stderr_tail`/`stdout_tail`, lint tail,
  `notes`, `code_review_findings`. Increment the attempt counter in shared
  state.
- **Worktree reuse**: the retried development run MUST reuse the existing
  worktree so attempt 1's committed progress is preserved. Locate the
  worktree-provisioning path in the development/research nodes (the spec
  references `_ensure_worktree_safe` — *(unverified — grep for it before
  use; if it does not exist under that name, find the actual
  worktree-provisioning helper in `nodes/development.py` /
  `nodes/research.py` and use that)*).
- Integration tests with a stub dispatcher:
  - `test_repair_loop_e2e`: QA fails once → development re-runs with
    feedback in the brief → QA passes → flow reaches close, final
    `QAReport.attempt == 2`.
  - `test_repair_loop_exhaustion_e2e`: QA fails N times → failure_handler;
    the Jira escalation comment includes the attempt trail.

**NOT in scope**: topology/CEL/state models (TASK-1910); escalation model
(TASK-1912); stop rule (TASK-1913).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | MODIFY | stamp attempt, emit action |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` | MODIFY | feedback brief, counter, worktree reuse |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/failure_handler.py` | MODIFY | include attempt trail in escalation comment |
| `packages/ai-parrot/tests/flows/dev_loop/integration/test_repair_loop.py` | CREATE | both e2e tests + fixtures |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.models import QAReport, CriterionResult, WorkBrief
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py
# execute() spans ~113-249; code-review autofix re-runs deterministic criteria
# WITHIN the node at lines 187-196 (this is NOT the graph-level retry — keep it)

# packages/ai-parrot/src/parrot/flows/dev_loop/models.py:475 (CriterionResult)
class CriterionResult(BaseModel):
    name: str; kind: Literal["flowtask", "shell", "manual"]
    exit_code: int; duration_seconds: float
    stdout_tail: str; stderr_tail: str; passed: bool

# QAReport fields incl. attempt (added by TASK-1910): models.py:487-511
# QaAttemptRecorded action: session_state.py (added by TASK-1910)

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py
# _resolve_pool_config: line 139; _execute_pool: 235-240; single-agent path
# exists as fallback — feedback injection must cover BOTH paths' briefs.
```

### Does NOT Exist
- ~~`_ensure_worktree_safe`~~ — *(unverified)* referenced by the proposal but NOT verified by the signature harvest; grep before use and substitute the real worktree-provisioning helper if the name differs
- ~~a feedback field on `QAReport`~~ — compose the summary from `criterion_results` + `lint_output` + `notes` + `code_review_findings`; do not add a new field
- ~~automatic attempt increment in the engine~~ — the development node owns the counter

---

## Implementation Notes

### Key Constraints
- Shared-state key naming: follow existing `shared[...]` key conventions in
  the dev_loop nodes (grep `shared[` in `nodes/` for the style).
- The condensed feedback must be budget-capped (tail excerpts, not full
  logs) — the dispatch brief goes into an LLM prompt.
- Both dispatch paths (pool `_execute_pool` and single-agent fallback)
  receive the feedback.
- The failure_handler escalation comment gains one line per attempt
  (`attempt N: <failed criteria names>`), built from session state.

### References in Codebase
- `packages/ai-parrot/tests/flows/dev_loop/integration/test_pool_e2e.py` — e2e harness/fixture style (stub dispatchers, FEAT-323 TASK-1864)
- `packages/ai-parrot/tests/flows/dev_loop/integration/test_session_state_e2e.py` — gated-run e2e patterns

---

## Acceptance Criteria

- [ ] QA stamps `attempt` from shared state; first pass is 1
- [ ] Retried development brief contains failed-criterion names and log tails from the prior report
- [ ] Retry reuses the existing worktree (assert same path across attempts)
- [ ] `test_repair_loop_e2e` and `test_repair_loop_exhaustion_e2e` pass
- [ ] Escalation Jira comment includes the attempt trail
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/` clean

---

## Test Specification

```python
@pytest.fixture
def failing_then_passing_dispatcher():
    """Stub DevLoopCodeDispatcher: QA criteria fail on attempt 1, pass on 2."""

async def test_repair_loop_e2e(failing_then_passing_dispatcher):
    """One failure → feedback redispatch → pass → close; attempt == 2."""

async def test_repair_loop_exhaustion_e2e(always_failing_dispatcher):
    """N failures → failure_handler; escalation comment lists attempts."""
```

---

## Agent Instructions

1. **Read the spec** for full context
2. **Check dependencies** — TASK-1910 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code (especially the *(unverified)* worktree helper)
4. **Update status** in `sdd/tasks/index/graphindex-as-engineering-devloop.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill the Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
