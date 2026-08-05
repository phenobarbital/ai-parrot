# TASK-2132: `_close_host` must record `outcome="failed"` for a failed terminal node

**Feature**: FEAT-413 — devloop-handoff-blocked-outcome
**Spec**: `sdd/specs/devloop-handoff-blocked-outcome.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Every `dev_loop` terminal node is written to **never raise** — by
explicit, intentional design they return a status dict instead
(`{"status": "blocked", ...}`, `{"status": "escalated", ...}`, …).
`AgentsFlow` only distinguishes `completed`/`failed` nodes by whether the
node *raised* (`flow.py:1701/1717`), so a terminal failure still lands in
`FlowResult.status == "completed"`. `DevLoopRunner._close_host` maps that
straight through `_outcome_from_status` to `outcome="succeeded"` —
recording a "succeeded" run with no PR, contradicting the "a successful
run always has a PR" invariant assumed across both `dev_loop` and
`dev_flow` (FEAT-412).

Two instances, same root cause, same fix point:

1. **Blocked handoff** (`deployment_handoff` / `feature_handoff` /
   `revision_handoff` → `"blocked"`): push or PR creation failed, nothing
   was delivered. Discovered via FEAT-412's code review; reproduces
   identically on unmodified `dev`.
2. **Escalated run** (`failure_handler` → `"escalated"` /
   `"escalated_without_ticket"` / `"escalation_failed"`): QA failed, the
   handoff node was *skipped*, so `handoff_resp` is `None` — and the run
   is recorded as a clean success. `RunPhase` documents `"failed"` as
   *"failure_handler terminal"* (`session_state.py:168`), but that phase
   is currently unreachable via the failure path. **This is the more
   consequential of the two** and was added by the v0.2 spec review.

See spec §1 and §6's verified status-vocabulary table for the full trace.

This is the spec's only task — implements spec §3 Modules 1 and 2
together (one file-pair change).

---

## Scope

- In `DevLoopRunner._close_host`, **after** (not inside) the existing
  `handoff_resp`/`pr_url` block, scan `result.responses` over an explicit
  terminal-node allowlist and force `outcome = "failed"` when any of them
  reported a failure status — overriding whatever
  `_outcome_from_status(result.status)` computed — plus a REQUIRED
  WARNING log naming the node id and status.
- Add the module-level constants `_TERMINAL_NODE_IDS` and
  `_FAILED_TERMINAL_STATUSES` (exact contents in Implementation Notes).
- Add five regression tests using the existing `_FakeFlow` harness from
  `test_run_bundle_export.py`: blocked `deployment_handoff`, blocked
  `feature_handoff`, escalated `failure_handler`, blocked
  `revision_handoff` (all → `outcome == "failed"`), plus a
  `comment_failed` control (→ `outcome == "succeeded"`).
- Confirm the existing succeeded-path test
  (`test_close_host_writes_bundle_and_report`) still passes unmodified.

**NOT in scope**:
- Any change to `FeatureHandoffNode` / `DeploymentHandoffNode` /
  `RevisionHandoffNode` / `FailureHandlerNode` — their `execute()`
  contracts (return a dict, never raise) are untouched. This task only
  *reads* their status values from `_close_host`.
- Any change to `bots/flows/core/result.py::determine_run_status` or
  `bots/flows/flow/flow.py`'s `completed`/`failed` bookkeeping — shared
  by every `AgentsFlow` consumer, out of scope for this task.
- **Touching the `pr_url` extraction.** The override changes `outcome`
  only. Do NOT add `pr_url = ""` on the failure path: a blocked
  deployment-approval rejection (`deployment_handoff.py:199`) happens
  *after* a real draft PR was created, so forcing an empty `pr_url` would
  freeze that information loss in place. See spec Non-Goals.
- `revision_handoff`'s `comment_failed` status — the revision WAS pushed
  and the PR exists; only the courtesy comment failed. Stays
  `"succeeded"` (there is a control test for this).
- `close`'s `close_failed` status — not inspected (the PR exists, only
  Jira bookkeeping failed).
- Changing the caller-visible `FlowResult.status`, which stays
  `"completed"` by design (the required WARNING log is what reconciles the
  logs with the bundle).
- Adding a third `Literal` value to `RunClosed.outcome` — it stays
  `["succeeded", "failed"]`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` | MODIFY | `_TERMINAL_NODE_IDS` + `_FAILED_TERMINAL_STATUSES` constants; `_close_host` — force `outcome="failed"` + WARNING log when a terminal node reported a failure status |
| `packages/ai-parrot/tests/flows/dev_loop/test_run_bundle_export.py` | MODIFY | Add the five terminal-outcome regression tests |

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

# ── Terminal-node status vocabulary (COMPLETE, grepped 2026-08-05) ─────
# Node files are NOT modified — these are the values to match on.
#
# feature_handoff.py:238      {"status": "ready_to_deploy", "pr_url", "pr_number", ...}  -> succeeded
# feature_handoff.py:164,189  {"status": "blocked", "error": ...}                        -> FAILED
# deployment_handoff.py:241   {"status": "ready_to_deploy", "pr_url", "pr_number"}       -> succeeded
# deployment_handoff.py:143,175,199
#                             {"status": "blocked", "error": ...}                        -> FAILED
#   (:199 is the deployment-approval rejection — a real PR exists but its
#    url is NOT in the payload; see Scope "NOT in scope" re: pr_url)
# revision_handoff.py:96      {"status": "revised", "pr_number", "branch"}               -> succeeded
# revision_handoff.py:74      {"status": "blocked", "error", "branch"}                   -> FAILED
# revision_handoff.py:89-94   {"status": "comment_failed", "pr_number", "branch", ...}   -> succeeded (degraded)
# failure_handler.py:125      {"status": "escalated", "issue_key"}                       -> FAILED
# failure_handler.py:92       {"status": "escalated_without_ticket"}                     -> FAILED
# failure_handler.py:111-112  {"status": "escalation_failed", "error"}                   -> FAILED
# close.py                    {"status": "closed"|"closed_without_ticket"|"close_failed"} -> not inspected

# ── Mechanics this fix relies on (all verified 2026-08-05) ─────────────
# 1. FlowResult.responses maps node_id -> the node's RAW execute() dict, so
#    isinstance(resp, dict) holds in production, not just under _FakeFlow:
#      bots/flows/flow/flow.py:891  ->  responses=dict(results)
# 2. failed[] only gets nodes that RAISED (flow.py:1701); skipped nodes are
#    absent from responses entirely -> a non-raising terminal failure yields
#    FlowStatus.COMPLETED (core/result.py:242-260).
# 3. RunClosed is applied in EXACTLY ONE place repo-wide: runner.py:1354.
# 4. Assertion chain: RunClosed.outcome -> state.phase (session_state.py:761)
#                                       -> RunBundle.outcome (run_bundle.py:330)
# 5. RunBundle has NO top-level pr_url — it is NESTED:
#      run_bundle.py:144  class RunBundle:    outcome: RunPhase
#      run_bundle.py:98   class DevelopedWork: pr_url: str = ""
#      run_bundle.py:308  developed = DevelopedWork(pr_url=state.pr_url or "", ...)
#    -> assert bundle.developed.pr_url == ""   # bundle.pr_url -> AttributeError
# 6. _mark_blocked() (feature_handoff.py:331-346) only touches JIRA — it
#    applies no SessionHost action, which is why _close_host is the only
#    viable fix point.

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
- ~~`bundle.pr_url`~~ — no such attribute on `RunBundle`; it is
  `bundle.developed.pr_url` (`run_bundle.py:98`, populated at `:308`).
  Asserting `bundle.pr_url` raises `AttributeError`.
- ~~a `"blocked"` value in `RunClosed.outcome`'s `Literal`~~ — stays
  `["succeeded", "failed"]`.
- ~~raising from any terminal node on the failure path~~ — not part of
  this task; their `execute()` contracts are unchanged.
- ~~a change to `determine_run_status` / `AgentsFlow`'s
  `completed`/`failed` bookkeeping~~
  (`bots/flows/core/result.py`, `bots/flows/flow/flow.py:1701/1717`) —
  out of scope.
- ~~`revision_handoff.py` / `failure_handler.py` **file** changes~~ —
  their statuses are read from `_close_host`; the node files are not
  edited.
- ~~a session-state "blocked" action~~ — `_mark_blocked()` is Jira-only
  (see mechanics note 6).

---

## Implementation Notes

### Pattern to Follow
```python
# Module level in runner.py (near the other module constants):
_TERMINAL_NODE_IDS = (
    "deployment_handoff", "feature_handoff", "revision_handoff", "failure_handler",
)
_FAILED_TERMINAL_STATUSES = frozenset({
    "blocked",                    # all three handoff nodes: nothing delivered
    "escalated",                  # failure_handler: QA failed, run escalated
    "escalated_without_ticket",   # failure_handler, no Jira / skip_jira
    "escalation_failed",          # failure_handler, Jira call raised
})

# Inside _close_host, AFTER the existing pr_url block (leave it untouched):
for _nid in _TERMINAL_NODE_IDS:
    _resp = result.responses.get(_nid)
    if isinstance(_resp, dict) and _resp.get("status") in _FAILED_TERMINAL_STATUSES:
        self.logger.warning(
            "Run %s: terminal node %s reported status=%s — recording "
            "outcome=failed (FlowResult.status=%s)",
            run_id, _nid, _resp.get("status"), result.status,
        )
        outcome = "failed"
        break
```
Keep this as a minimal, additive insertion — do not refactor the
surrounding method or reorder existing lines.

### Key Constraints
- **Do not build the scan on `handoff_resp`.** That variable is
  `deployment_handoff or feature_handoff`; in the `failure_handler` case
  the handoff node was *skipped*, so it is `None` and a scan based on it
  would miss the most important case. Iterate `result.responses` by node
  id, as shown.
- Every `result.responses` value can be `None` or a non-dict (a node that
  never ran, or a skipped node absent from the mapping) — guard each with
  `isinstance(resp, dict)`, mirroring `runner.py:1349`.
- Keep the node-id list an explicit allowlist: a NON-terminal node
  returning `{"status": "blocked"}` must never flip a run's outcome.
- Do not touch the `pr_url` lines, and do not gate the override on
  `pr_url` being empty.
- The WARNING log is REQUIRED (spec §5), not optional — use the file's
  existing `self.logger` convention.
- No new Pydantic models, no new public interfaces.

### References in Codebase
- `packages/ai-parrot/tests/flows/dev_loop/test_run_bundle_export.py` — test harness pattern (`_FakeFlow`, `brief` fixture, bundle-path helper) to extend for the two new tests.

---

## Acceptance Criteria

- [ ] `_close_host` records `RunClosed(outcome="failed")` when any node in
      `_TERMINAL_NODE_IDS` reported a status in
      `_FAILED_TERMINAL_STATUSES`, even though
      `FlowResult.status == "completed"` — covering blocked
      `deployment_handoff`, blocked `feature_handoff`, blocked
      `revision_handoff`, and `failure_handler`'s three escalation
      statuses.
- [ ] The override emits a WARNING log naming the node id and status.
- [ ] The `pr_url` extraction block is byte-for-byte unchanged (verify
      with `git diff` — the only changed lines are the two new constants
      and the new scan).
- [ ] A non-terminal node returning `{"status": "blocked"}` does NOT flip
      the outcome (explicit node-id allowlist).
- [ ] `revision_handoff`'s `comment_failed` still records
      `outcome="succeeded"`.
- [ ] No node file is modified (`feature_handoff.py`,
      `deployment_handoff.py`, `revision_handoff.py`,
      `failure_handler.py`).
- [ ] `bots/flows/core/result.py` and `bots/flows/flow/flow.py` are NOT modified.
- [ ] `test_close_host_writes_bundle_and_report` (pre-existing) still passes unmodified.
- [ ] The five new tests pass, using `bundle.developed.pr_url` (NOT
      `bundle.pr_url`).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/runner.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_run_bundle_export.py — additions
#
# NOTE the assertion is bundle.developed.pr_url — RunBundle has NO top-level
# pr_url field (run_bundle.py:98/144/308). bundle.pr_url -> AttributeError.


@pytest.mark.parametrize(
    "case_id, node_id, response, expected_outcome",
    [
        # FAILED — nothing was delivered.
        ("blocked-deployment", "deployment_handoff",
         {"status": "blocked", "error": "push failed"}, "failed"),
        ("blocked-feature", "feature_handoff",
         {"status": "blocked", "error": "PR create failed"}, "failed"),
        ("blocked-revision", "revision_handoff",
         {"status": "blocked", "error": "push: boom", "branch": "b"}, "failed"),
        # FAILED — QA failed and the run escalated; the handoff node was
        # SKIPPED, so there is no handoff response at all.
        ("escalated", "failure_handler",
         {"status": "escalated", "issue_key": "OPS-1"}, "failed"),
        # SUCCEEDED — degraded but delivered: the revision WAS pushed, only
        # the courtesy PR comment failed.
        ("comment-failed", "revision_handoff",
         {"status": "comment_failed", "pr_number": 7, "branch": "b"}, "succeeded"),
    ],
)
@pytest.mark.asyncio
async def test_close_host_outcome_from_terminal_status(
    tmp_path, brief, case_id, node_id, response, expected_outcome,
):
    flow = _FakeFlow(responses={node_id: response})
    runner = DevLoopRunner(flow, max_concurrent_runs=2)  # type: ignore[arg-type]
    run_id = f"run-terminal-{case_id}"

    result = await runner.run(brief, run_id=run_id)
    # The terminal node never raises, so the flow itself still reports
    # COMPLETED — that is deliberate (spec Non-Goals); only the RECORDED
    # outcome is corrected.
    assert result.status == FlowStatus.COMPLETED

    bundle_path, _ = _bundle_paths(run_id)
    bundle = RunBundle.model_validate(json.loads(bundle_path.read_text()))
    assert bundle.outcome == expected_outcome
    # No PR url in any of these canned payloads.
    assert bundle.developed.pr_url == ""


@pytest.mark.asyncio
async def test_close_host_ignores_blocked_status_on_non_terminal_node(tmp_path, brief):
    """A non-terminal node using the same status vocabulary must NOT flip
    the run outcome — the scan is an explicit node-id allowlist."""
    flow = _FakeFlow(responses={
        "development": {"status": "blocked", "error": "not a terminal node"},
        "deployment_handoff": {"status": "ready_to_deploy", "pr_url": "http://pr/9"},
    })
    runner = DevLoopRunner(flow, max_concurrent_runs=2)  # type: ignore[arg-type]

    await runner.run(brief, run_id="run-terminal-allowlist")

    bundle_path, _ = _bundle_paths("run-terminal-allowlist")
    bundle = RunBundle.model_validate(json.loads(bundle_path.read_text()))
    assert bundle.outcome == "succeeded"
    assert bundle.developed.pr_url == "http://pr/9"
```

The `parametrize` form is a suggestion — five separate test functions are
equally acceptable, as long as all five cases plus the allowlist case are
covered. `_FakeFlow`, the `brief` fixture and `_bundle_paths` already
exist in that file (`test_run_bundle_export.py:34-70`); the autouse
`_isolate_dev_loop_run_artifacts` fixture in `conftest.py` already
redirects `conf.OUTPUT_DIR` to `tmp_path`.

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

**Completed by**: sdd-worker (Claude Sonnet, autonomous)
**Date**: 2026-08-05
**Notes**: Implemented exactly as specified. Added `_TERMINAL_NODE_IDS` and
`_FAILED_TERMINAL_STATUSES` module-level constants next to
`_SWEEP_INTERVAL_SECONDS`, and inserted the terminal-status scan in
`_close_host` immediately after the existing `pr_url` extraction block
(left byte-for-byte unchanged, verified via `git diff`). The scan iterates
`_TERMINAL_NODE_IDS` against `result.responses` directly (not
`handoff_resp`), guards each lookup with `isinstance(resp, dict)`, emits
the required WARNING log naming the node id and status, and forces
`outcome = "failed"` on match. Added 6 regression tests to
`test_run_bundle_export.py` (5 parametrized terminal-status cases —
blocked deployment/feature/revision handoff, escalated failure_handler,
comment_failed control — plus 1 non-terminal-node allowlist-isolation
test) using the existing `_FakeFlow` harness. All 10 tests in the file
pass (4 pre-existing + 6 new), asserting `bundle.developed.pr_url`
(never `bundle.pr_url`) per the contract.

Ran the full `pytest packages/ai-parrot/tests/flows/dev_loop/ -q -m "not
live"` suite in the worktree and cross-checked against an unmodified
`dev` checkout: both report the identical pre-existing 22 failed / 13
errors (missing/misconfigured server-wiring fixtures unrelated to this
change — `test_adversarial_server_wiring.py`, `test_code_review.py`,
`test_server_repo_wiring.py`, `test_qa_codereview.py`,
`test_examples_form.py`); the only delta is the 6 new passing tests
added here. No regression introduced.

The worktree's `.venv` was missing several optional runtime deps needed
just to import `parrot.flows.dev_loop` for collection (`aioquic`,
`rustworkx`, `networkx`, `google-genai`, `hypothesis`) — pre-existing
environment gaps unrelated to this task's diff; installed them via `uv
pip install` in the shared `.venv` to unblock test collection. No
project files were changed to work around this.

`ruff check` on both changed files shows only pre-existing findings
(64 in `runner.py`, 5 in the test file) — none fall within the lines
this task added (verified by line-range cross-reference); the new code
is ruff-clean.

**Deviations from spec**: none.
