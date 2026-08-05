# TASK-2132: `_close_host` must record `outcome="failed"` for a blocked handoff

**Feature**: FEAT-413 — devloop-handoff-blocked-outcome
**Spec**: `sdd/specs/devloop-handoff-blocked-outcome.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`FeatureHandoffNode`/`DeploymentHandoffNode` never raise on a blocked
handoff (failed `git push` or PR creation after retry) — by explicit,
intentional design they return `{"status": "blocked", "error": ...}`
instead. `AgentsFlow` only distinguishes `completed`/`failed` nodes by
whether the node *raised*, so a blocked handoff still lands in
`FlowResult.status == "completed"`. `DevLoopRunner._close_host` then
maps that straight through `_outcome_from_status` to
`outcome="succeeded"`, recording a "succeeded" run with no PR —
contradicting the "a successful run always has a PR" invariant assumed
across both `dev_loop` and `dev_flow` (FEAT-412). See spec §1 for the
full trace (discovered via FEAT-412's code review; reproduces
identically and independently on unmodified `dev`).

This is the spec's only task — implements spec §3 Modules 1 and 2
together (one file-pair change).

---

## Scope

- In `DevLoopRunner._close_host`, after the existing `handoff_resp`
  lookup, check whether `handoff_resp` is a dict with
  `handoff_resp.get("status") == "blocked"`. If so, force
  `outcome = "failed"` before constructing `RunClosed`, overriding
  whatever `_outcome_from_status(result.status)` computed.
- Add two new regression tests (blocked `deployment_handoff`, blocked
  `feature_handoff`) using the existing `_FakeFlow` harness from
  `test_run_bundle_export.py`, asserting `RunBundle.outcome == "failed"`
  and `pr_url == ""`.
- Confirm the existing succeeded-path test
  (`test_close_host_writes_bundle_and_report`) still passes unmodified.

**NOT in scope**:
- Any change to `FeatureHandoffNode` / `DeploymentHandoffNode` — their
  `execute()` contract (return a dict, never raise on blocked) is
  untouched.
- Any change to `bots/flows/core/result.py::determine_run_status` or
  `bots/flows/flow/flow.py`'s `completed`/`failed` bookkeeping — shared
  by every `AgentsFlow` consumer, out of scope for this task.
- `revision_handoff.py`'s blocked path — not read by `_close_host`'s
  `handoff_resp` lookup at all.
- Adding a third `Literal` value to `RunClosed.outcome` — it stays
  `["succeeded", "failed"]`; blocked maps to the existing `"failed"`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` | MODIFY | `_close_host` — force `outcome="failed"` when the handoff response is `{"status": "blocked", ...}` |
| `packages/ai-parrot/tests/flows/dev_loop/test_run_bundle_export.py` | MODIFY | Add the two blocked-outcome regression tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py — already imported, no new imports needed
from parrot.flows.dev_loop.session_state import RunClosed, SessionHost  # session_state.py:349

# packages/ai-parrot/tests/flows/dev_loop/test_run_bundle_export.py — already imported, no new imports needed
from parrot.flows.dev_loop import BugBrief, DevLoopRunner, RunBundle, ShellCriterion, build_run_bundle, render_markdown
from parrot.bots.flows.core.result import FlowResult
from parrot.bots.flows.core.types import FlowStatus
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py:446-454
@staticmethod
def _outcome_from_status(status: Any) -> str:
    # "completed" -> "succeeded"; "partial"/"failed" -> "failed"
    value = getattr(status, "value", status)
    return "succeeded" if value == "completed" else "failed"

# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py:1314-1355 (verbatim today)
def _close_host(
    self, host: SessionHost, result: FlowResult, ctx: FlowContext,
) -> None:
    run_id = host.state.run_id
    outcome = self._outcome_from_status(result.status)              # :1342
    jira_issue_key = str(ctx.shared_data.get("jira_issue_key", "") or "")
    handoff_resp = result.responses.get("deployment_handoff") or result.responses.get(
        "feature_handoff"
    )                                                                 # :1345-1347
    pr_url = ""
    if isinstance(handoff_resp, dict):
        pr_url = str(handoff_resp.get("pr_url", "") or "")            # :1349-1351
    # >>> INSERT THE NEW BLOCKED-OUTCOME CHECK HERE <<<
    host.apply(RunClosed(
        outcome=outcome, jira_issue_key=jira_issue_key, pr_url=pr_url,
    ))                                                                 # :1353-1355
    self._persist_terminal_snapshot(host)
    self._persist_run_bundle(host, ctx)
    self._schedule_actions_retention(run_id)
    self._apply_root_action(
        RunSummaryChanged(summary=self._run_summary_from_host(host))
    )
    self._discard_host(run_id)

# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py:349-353
class RunClosed(_ActionBase):
    type: Literal["run/closed"] = "run/closed"
    outcome: Literal["succeeded", "failed"]     # stays binary — do not extend
    jira_issue_key: str = ""
    pr_url: str = ""

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/feature_handoff.py:186-189 (blocked-return shape, unchanged)
#   return {"status": "blocked", "error": last_error or "unknown PR error"}
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py:142-143, 199 (blocked-return shape, unchanged)
#   return {"status": "blocked", "error": f"push: {exc}"}
#   return {"status": "blocked", "error": gate_error}

# packages/ai-parrot/tests/flows/dev_loop/test_run_bundle_export.py:47-64 (existing test harness, verbatim)
class _FakeFlow:
    def __init__(self, *, status: FlowStatus = FlowStatus.COMPLETED,
                 responses: Dict[str, Any] | None = None) -> None:
        self.status = status
        self.responses = responses or {}
    async def run_flow(self, ctx, **kwargs) -> FlowResult:
        return FlowResult(
            output=ctx.shared_data.get("run_id"),
            status=self.status,
            responses=dict(self.responses),
        )

# existing succeeded-path test to preserve verbatim (test_run_bundle_export.py:74-89):
#   flow = _FakeFlow(responses={"deployment_handoff": {"pr_url": "http://pr/1"}})
#   runner = DevLoopRunner(flow, max_concurrent_runs=2)
#   result = await runner.run(brief, run_id="run-bundle-export1")
#   assert result.status == FlowStatus.COMPLETED
#   bundle = RunBundle.model_validate(json.loads(bundle_path.read_text()))
#   assert bundle.outcome == "succeeded"
```

### Does NOT Exist
- ~~a `"blocked"` value in `RunClosed.outcome`'s `Literal`~~ — stays
  `["succeeded", "failed"]`.
- ~~raising from `FeatureHandoffNode`/`DeploymentHandoffNode` on the
  blocked path~~ — not part of this task; their `execute()` contract is
  unchanged.
- ~~a change to `determine_run_status` / `AgentsFlow`'s
  `completed`/`failed` bookkeeping~~
  (`bots/flows/core/result.py`, `bots/flows/flow/flow.py:1701/1717`) —
  out of scope.
- ~~`revision_handoff.py` changes~~ — out of scope; not read by
  `_close_host`'s `handoff_resp` lookup.

---

## Implementation Notes

### Pattern to Follow
```python
# Inside _close_host, right after the existing pr_url extraction:
if isinstance(handoff_resp, dict) and handoff_resp.get("status") == "blocked":
    outcome = "failed"
```
Keep this as a minimal, additive insertion — do not refactor the
surrounding method or reorder existing lines.

### Key Constraints
- `handoff_resp` can legitimately be `None` (bug-mode runs where
  neither handoff node ever ran, e.g. QA-blocked runs) — reuse the
  existing `isinstance(handoff_resp, dict)` guard, do not assume a dict.
- No new Pydantic models, no new public interfaces.
- Follow the file's existing logging conventions if you add a log line
  for the override (optional; not required by acceptance criteria).

### References in Codebase
- `packages/ai-parrot/tests/flows/dev_loop/test_run_bundle_export.py` — test harness pattern (`_FakeFlow`, `brief` fixture, bundle-path helper) to extend for the two new tests.

---

## Acceptance Criteria

- [ ] `_close_host` records `RunClosed(outcome="failed")` when the
      terminal handoff response (`deployment_handoff` or
      `feature_handoff`) is `{"status": "blocked", ...}`, even though
      `FlowResult.status == "completed"`.
- [ ] `pr_url` remains `""` in that case.
- [ ] `FeatureHandoffNode`/`DeploymentHandoffNode` are NOT modified.
- [ ] `bots/flows/core/result.py` and `bots/flows/flow/flow.py` are NOT modified.
- [ ] `test_close_host_writes_bundle_and_report` (pre-existing) still passes unmodified.
- [ ] Two new tests (blocked `deployment_handoff`, blocked `feature_handoff`) pass, asserting `outcome == "failed"`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/runner.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_run_bundle_export.py — additions

@pytest.mark.asyncio
async def test_close_host_marks_blocked_deployment_handoff_as_failed(tmp_path, brief):
    flow = _FakeFlow(responses={
        "deployment_handoff": {"status": "blocked", "error": "push failed"},
    })
    runner = DevLoopRunner(flow, max_concurrent_runs=2)  # type: ignore[arg-type]

    result = await runner.run(brief, run_id="run-blocked-deployment1")
    assert result.status == FlowStatus.COMPLETED  # node didn't raise

    bundle_path, _ = _bundle_paths("run-blocked-deployment1")
    bundle = RunBundle.model_validate(json.loads(bundle_path.read_text()))
    assert bundle.outcome == "failed"
    assert bundle.pr_url == ""


@pytest.mark.asyncio
async def test_close_host_marks_blocked_feature_handoff_as_failed(tmp_path, brief):
    flow = _FakeFlow(responses={
        "feature_handoff": {"status": "blocked", "error": "PR create failed"},
    })
    runner = DevLoopRunner(flow, max_concurrent_runs=2)  # type: ignore[arg-type]

    result = await runner.run(brief, run_id="run-blocked-feature1")
    assert result.status == FlowStatus.COMPLETED

    bundle_path, _ = _bundle_paths("run-blocked-feature1")
    bundle = RunBundle.model_validate(json.loads(bundle_path.read_text()))
    assert bundle.outcome == "failed"
    assert bundle.pr_url == ""
```

(Verify `RunBundle`'s exact field name for `pr_url` against
`run_bundle.py` before writing the assertion — the spec's contract
traces it through `RunClosed.pr_url`, but confirm `build_run_bundle`
projects it onto the same field name on `RunBundle`.)

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none (`Depends-on: none`)
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2132-close-host-blocked-outcome.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
