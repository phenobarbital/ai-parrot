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

### Contract resolution (found during implementation, 2026-07-26)
- `_ensure_worktree_safe` DOES exist (`nodes/research.py:924`), but it is
  irrelevant to this task: it verifies a worktree isn't stale junk when
  **ResearchNode** first creates/discovers it (relaxation for re-running
  against an already-known incident), called exactly once per flow run.
  The repair-loop retry edge is `qa -> development` — it never re-enters
  `ResearchNode` — so worktree reuse across attempts falls out for free:
  `shared["research_output"]` (and its `worktree_path`) is set once and
  read unchanged by every `DevelopmentNode.execute()` re-entry. No call to
  `_ensure_worktree_safe` (or any other helper) was needed in
  `development.py`.

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

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-26
**Notes**:
- `nodes/base.py`: added `condense_qa_failure(report, max_chars=2000) ->
  str` — a shared helper (imports `QAReport` from `models.py`; verified no
  circular import) composing failed-criterion names + `stderr_tail`/
  `stdout_tail` (last 300 chars) + lint tail + notes + code-review
  findings, budget-capped. Used by both `qa.py` (attempt-recorded notes)
  and `development.py` (redispatch feedback) so both surfaces describe a
  failure identically, per the task's "do not add a new field" note.
- `nodes/qa.py`: after the final report is assembled, stamps
  `report.attempt = shared.get("qa_attempt", 1)` (development owns the
  counter; QA only reads it — defaults to 1 before development ever
  runs). When the (now-stamped) report fails AND
  `attempt < DEV_LOOP_QA_MAX_RETRIES` (a retry WILL occur), emits
  `session_host.apply(QaAttemptRecorded(attempt=..., qa_notes=
  condense_qa_failure(report)))` when a host is present (mirrors the
  existing `review_escalation` gate-opening call one method below, which
  already calls `session_host` methods directly from within this node —
  established precedent, not a new pattern).
- `nodes/development.py`: new `_with_repair_feedback(shared, research)`
  called at the top of `execute()`. Detects re-entry via a failing
  `QAReport` already in `shared["qa_report"]` (set by `QANode` on the
  previous pass through the retry edge); when found, increments
  `shared["qa_attempt"]` (this node's counter — `QANode` only reads it)
  and returns a `research.model_copy(update={"log_excerpts": [...,
  <condensed feedback>]})` — reusing the existing `ResearchOutput
  .log_excerpts` free-text field rather than adding a new one (out of
  this task's file scope; `models.py` isn't listed). Both `_execute_single`
  (`brief=research`) and `_execute_pool` (`research=research` → wrapped
  into every `TaskScopedBrief` by `agent_pool.py`) receive the identical
  augmented object automatically since only the local variable changes,
  not a new parameter — covers both dispatch paths per the acceptance
  criterion. `research.worktree_path` (and every other field) is
  byte-identical across the copy, so path/cwd logic downstream is
  unaffected.
- `nodes/failure_handler.py`: `_build_comment` gained a `shared` parameter
  and a new `_attempt_trail(shared)` static method that replays
  `session_host.replay_since(0)`, filters `action.type ==
  "run/qaAttemptRecorded"` (TASK-1910's naming-corrected literal), and
  renders one `"attempt N: <qa_notes>"` line per retry — appended to the
  `qa_failed` comment as "Repair-loop attempt trail:". Degrades to an
  empty string (no trail section) when no `session_host` is present
  (legacy construction) — escalation must never fail on a missing host.
- `tests/integration/test_repair_loop.py` (new): drives the REAL
  `DevLoopRunner.run()` / `build_dev_loop_flow()` stack (mocked
  dispatcher/Jira, harness style copied from `test_runner.py` +
  `test_pool_e2e.py` — no shared fixtures existed to reuse across
  directories, so `brief`/`mock_jira`/`patch_handoff`/
  `patch_worktree_base`/`_build_flow` are duplicated locally, matching
  this test suite's existing per-file-fixture convention).
  - `test_repair_loop_e2e`: QA fails attempt 1 (with a `CriterionResult`
    carrying a distinctive `stderr_tail`) → development redispatches with
    that text verifiably present in `log_excerpts` → QA passes attempt 2
    → flow reaches `close` with `final_report.attempt == 2`; verifies
    attempt 1's brief carries NO feedback (nothing to redispatch from yet).
  - `test_repair_loop_exhaustion_e2e`: QA fails every attempt up to
    `DEV_LOOP_QA_MAX_RETRIES` → `failure_handler`; the Jira comment
    contains exactly `N-1` attempt-trail lines (the N-th, exhausting
    failure never dispatches a retry, so `QANode` never emits a
    `QaAttemptRecorded` for it — verified by asserting `f"attempt {n}:"`
    is absent from the trail).
- Fixed an unrelated regression discovered by the full suite:
  `test_repointing.py::test_devloop_{development,qa}_uses_canonical_node`
  string-match the literal source substring `"parrot.flows.dev_loop.nodes
  .base import DevLoopNode"` on one line — my initial multi-line `import
  (...)` block broke that exact-substring check. Fixed by keeping the
  `nodes.base` import single-line in both files (well under the 120-col
  limit) rather than touching the string-matching test itself.
- `pytest packages/ai-parrot/tests/flows/dev_loop/ -m "not live"` (minus
  the pre-existing `hypothesis`-missing file): 664 passed, 1 skipped,
  same one pre-existing unrelated test-order-dependent failure noted in
  every prior task this session.
- `ruff check` clean on every touched file.

**Deviations from spec**: none beyond the two documented, non-behavioral
corrections above (worktree-helper contract resolution; single-line
import to satisfy an unrelated pre-existing string-match test).
