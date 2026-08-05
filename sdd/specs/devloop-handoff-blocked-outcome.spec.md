---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: devloop-handoff-blocked-outcome

**Feature ID**: FEAT-413
**Date**: 2026-08-05
**Author**: Jesus (via code-review follow-up, FEAT-412 close-out)
**Status**: approved
**Target version**: n/a (internal orchestration correctness fix)

---

## 1. Motivation & Business Requirements

### Problem Statement

`DeploymentHandoffNode` and `FeatureHandoffNode` (the two PR-creating
terminal nodes of `dev_loop`'s bug-mode and feature-mode topologies) never
raise on a blocked handoff (failed `git push` or failed PR creation after
retry) — by explicit design (`deployment_handoff.py:17`: *"The node does
NOT raise on the blocked path — it returns a structured
`{"status": "blocked", "error": ...}`"*). This is intentional: a
transient push/PR failure shouldn't be treated identically to a node
crash by the generic retry/park machinery.

However, `AgentsFlow`'s completion bookkeeping
(`bots/flows/flow/flow.py`) only distinguishes `completed` vs. `failed`
nodes by whether `event.error is not None` — i.e. whether the node
*raised*. A node that returns `{"status": "blocked", ...}` without
raising lands in the `completed` set, so
`determine_run_status(len(completed), len(failed))`
(`bots/flows/core/result.py:242`) reports `FlowResult.status ==
"completed"` even though the handoff never produced a PR.

`DevLoopRunner._close_host` (`flows/dev_loop/runner.py:1314`) then maps
that `"completed"` status through `_outcome_from_status` to
`outcome="succeeded"` (`runner.py:446`) and records
`RunClosed(outcome="succeeded", pr_url="")` — a run whose session state,
run bundle, and root-catalogue summary all say "succeeded" with **no
PR**, silently contradicting `sdd-dev-flow`'s (FEAT-412) acceptance
criterion "every successful run terminates with a draft PR against
`dev`" and the equivalent invariant already assumed by `dev_loop`'s own
bug-mode users.

This was discovered as a code-review finding during FEAT-412's close-out
(dev-flow reuses `FeatureHandoffNode` verbatim) but reproduces
identically and independently on unmodified `dev` via
`DeploymentHandoffNode` — it predates FEAT-412 and FEAT-378 both, tracing
back to the original FEAT-129 `dev_loop` handoff design. It is being
filed and fixed as its own feature rather than folded into FEAT-412's
diff, because the fix's blast radius (`dev_loop/runner.py`) is shared
infrastructure outside FEAT-412's task scope.

### The same defect on the other terminal nodes (v0.2 — spec review)

A pre-implementation review of this spec (2026-08-05) found that the
blocked handoff is **not the only** instance of this bookkeeping gap —
every `dev_loop` terminal node is written to never raise, so *none* of
their failure states reach `outcome`:

| Terminal node (id) | Non-success statuses | Recorded today |
|---|---|---|
| `deployment_handoff` | `blocked` | `succeeded` ❌ |
| `feature_handoff` | `blocked` | `succeeded` ❌ |
| `revision_handoff` | `blocked`, `comment_failed` | `succeeded` ❌ |
| `failure_handler` | `escalated`, `escalated_without_ticket`, `escalation_failed` | `succeeded` ❌ |

The `failure_handler` case is the **most consequential** one: when QA
fails and the run escalates, the handoff node is *skipped* (explicit-edge
skip-propagation), so `handoff_resp` is `None`, no node raised, and the
run is recorded `outcome="succeeded"` — a QA-failed, escalated run
reported as a clean success. `RunPhase`'s own Literal documents
`"failed"` as *"failure_handler terminal"*
(`session_state.py:168`), yet `RunClosed` is applied in exactly ONE place
in the repo (`runner.py:1354`) and `_outcome_from_status` is its only
decider — so that documented phase is currently **unreachable** via the
failure path (it only happens when some node genuinely raises).

Because all of these collapse to the same one-line insertion point in
`_close_host`, and because leaving them out would mean shipping a fix
that makes `"succeeded"` trustworthy for one path while it stays
unreliable on a *more common* one, this spec covers the whole terminal
node family rather than the blocked handoff alone.

### Goals
- A run that terminates through any `dev_loop` terminal node with a
  non-success status MUST be recorded with `RunClosed(outcome="failed")`,
  never `"succeeded"`, regardless of what `FlowResult.status` says. In
  particular: a blocked `deployment_handoff`/`feature_handoff`/
  `revision_handoff`, and an escalating `failure_handler`.
- The override MUST emit a WARNING log line naming the node id and its
  status, so run logs cannot contradict the persisted bundle (the
  caller-visible `FlowResult.status` is deliberately left as
  `"completed"` — see Non-Goals — so the log is the only place the two
  views are reconciled).
- No change to the intentional "handoff never raises" design — the node
  contract (`execute()` returns a dict, no exception) is preserved
  exactly as-is.
- No change to `AgentsFlow`/`determine_run_status` — the fix is
  contained entirely to `DevLoopRunner`'s own outcome projection, which
  already special-cases the two handoff node ids
  (`runner.py:1345-1352`: `deployment_handoff` / `feature_handoff`).
- No change to `pr_url` extraction — the blocked-outcome override must
  not touch it (see Non-Goals).

### Non-Goals (explicitly out of scope)
- Changing `bots/flows/core/result.py::determine_run_status` or
  `bots/flows/flow/flow.py`'s `completed`/`failed` bookkeeping — those
  are shared by every `AgentsFlow` consumer in the repo, not
  `dev_loop`-specific, and a behavior change there needs its own
  cross-cutting review.
- Making the terminal nodes raise instead of returning a status dict —
  that would change retry/park semantics for every existing caller and
  contradicts the documented, intentional design in
  `deployment_handoff.py:17`.
- Changing the caller-visible `FlowResult.status`, which stays
  `"completed"` for a non-raising terminal node. The originating
  code-review finding was phrased as *"blocked PR still reports
  `status: completed`"*, and this spec deliberately fixes the **recorded
  run outcome** rather than that return value: `FlowResult.status` is
  produced by shared `AgentsFlow` core (out of scope, above), the
  console/UI read the session `phase` (which this fix corrects), and the
  required WARNING log line (Goals) keeps `runner.py:433` /
  `examples/dev_loop/server.py:1174`'s `finished status=completed` from
  standing alone as the only visible signal.
- Forcing or clearing `pr_url` on the override path. `pr_url == ""` today
  for every blocked return is an **accident of the payloads**, not an
  invariant to enforce: the deployment-approval-rejected path
  (`deployment_handoff.py:199`) returns `{"status": "blocked", ...}`
  *after* a draft PR was created, and its URL never reaches session state
  because `PullRequestLinked` fires only from a node result carrying
  `pr_url` (`flow.py:222-230`). Recording that run as `failed` is right;
  hard-coding `pr_url = ""` alongside it would freeze that information
  loss in place and would wipe a legitimate PR link the day a blocked
  payload does carry one. The fix touches `outcome` only.
- `revision_handoff.py`'s `comment_failed` status — the revision WAS
  pushed and the PR does exist; only the courtesy comment failed. That is
  degraded, not failed, and stays `succeeded`. (Its `blocked` status —
  push failed, nothing delivered — IS in scope, see above.)
- Surfacing the deployment-approval-rejected PR URL in session state
  (the `flow.py:222-230` gap noted above). Pre-existing, orthogonal, and
  a `deployment_handoff`/`flow.py` change rather than a `_close_host`
  one — file separately if it matters.

---

## 2. Architectural Design

### Overview

`DevLoopRunner._close_host` already reads the handoff response
(`runner.py:1345-1352`: `result.responses.get("deployment_handoff") or
result.responses.get("feature_handoff")`) to extract `pr_url`. Add — next
to it, NOT inside it — a **terminal-status scan** over the four known
terminal node ids in `result.responses`. If any of them reported a
failure status, force `outcome = "failed"` (overriding whatever
`_outcome_from_status(result.status)` computed) and log a WARNING, before
constructing `RunClosed`.

The scan is keyed on an explicit node-id allowlist rather than "any
response with `status == blocked`", so a non-terminal node that happens
to use the same vocabulary can never flip a run's outcome.

Two module-level constants carry the (verified — see §6) vocabulary:

```python
_TERMINAL_NODE_IDS = (
    "deployment_handoff", "feature_handoff", "revision_handoff", "failure_handler",
)
_FAILED_TERMINAL_STATUSES = frozenset({
    "blocked",                    # all three handoff nodes: nothing delivered
    "escalated",                  # failure_handler: QA failed, run escalated
    "escalated_without_ticket",   # failure_handler, no Jira/skip_jira
    "escalation_failed",          # failure_handler, Jira call raised
})
```

This is a single-function, additive change: every other outcome path (no
terminal response at all; a terminal response whose `"status"` is absent
or a success/degraded value — `ready_to_deploy`, `revised`,
`comment_failed`) is byte-for-byte unchanged, and `pr_url` extraction is
untouched.

### Component Diagram
```
DevLoopRunner._close_host(host, result, ctx)
        │
        ├─ outcome = _outcome_from_status(result.status)      # existing
        ├─ handoff_resp = result.responses.get("deployment_handoff")
        │                 or result.responses.get("feature_handoff")
        ├─ pr_url = handoff_resp.get("pr_url", "")             # existing, UNTOUCHED
        ├─ NEW: for nid in _TERMINAL_NODE_IDS:
        │           resp = result.responses.get(nid)
        │           if isinstance(resp, dict) and \
        │              resp.get("status") in _FAILED_TERMINAL_STATUSES:
        │               outcome = "failed"          # override
        │               logger.warning(... nid, status ...)
        │               break
        └─ host.apply(RunClosed(outcome=outcome, ..., pr_url=pr_url))
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `DevLoopRunner._close_host` | modifies | Adds the terminal-status override + WARNING log; no signature change; `pr_url` extraction untouched. |
| `RunClosed` (session_state.py) | uses (unchanged) | `outcome: Literal["succeeded", "failed"]` already supports the corrected value — no model change. |
| `FeatureHandoffNode` / `DeploymentHandoffNode` / `RevisionHandoffNode` / `FailureHandlerNode` | reads (unchanged) | Their `execute()` contracts and status-dict shapes are NOT modified. |
| `DevFlowRunner` (FEAT-412, branch `feat-412-sdd-dev-flow`) | inherits (no change) | Subclasses `DevLoopRunner` and inherits `_close_host`; its topology uses the same `feature_handoff` node id (`dev_flow/flow.py:165-173`), so dev-flow is fixed without touching FEAT-412's diff. |

### Data Models
No new or modified Pydantic models. `RunClosed.outcome` is already
`Literal["succeeded", "failed"]` (`session_state.py:351`) — the fix only
changes which value gets passed in for this one case.

### New Public Interfaces
None — this is a private-method (`_close_host`) behavior fix, no new
public surface.

---

## 3. Module Breakdown

### Module 1: Terminal-status outcome fix
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py`
- **Responsibility**: `_close_host` must record `outcome="failed"` (plus
  a WARNING log) when any terminal node in `_TERMINAL_NODE_IDS` reported
  a status in `_FAILED_TERMINAL_STATUSES`, instead of trusting
  `FlowResult.status` alone. `pr_url` extraction stays as-is.
- **Depends on**: none (self-contained within `runner.py`).

### Module 2: Regression tests
- **Path**: `packages/ai-parrot/tests/flows/dev_loop/test_run_bundle_export.py` (extend) and/or a new `packages/ai-parrot/tests/flows/dev_loop/test_handoff_blocked_outcome.py`
- **Responsibility**: Drive `DevLoopRunner.run()` end-to-end with the
  existing `_FakeFlow` harness (`test_run_bundle_export.py`'s pattern),
  supplying a canned terminal response per case (blocked
  `deployment_handoff`, blocked `feature_handoff`, escalating
  `failure_handler`, blocked `revision_handoff`) and asserting
  `RunBundle.outcome == "failed"` — plus two control cases proving
  success (`test_close_host_writes_bundle_and_report`, unmodified) and
  the degraded-but-delivered `comment_failed` path still record
  `"succeeded"`.
- **`pr_url` assertion — field name**: `RunBundle` has **no** top-level
  `pr_url`. It lives on the nested `DevelopedWork` model
  (`run_bundle.py:98`, populated at `:308` from `state.pr_url`), so the
  assertion is `bundle.developed.pr_url == ""` — `bundle.pr_url` raises
  `AttributeError`.
- **Depends on**: Module 1.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_close_host_marks_blocked_deployment_handoff_as_failed` | Module 1 | `responses={"deployment_handoff": {"status": "blocked", "error": "push failed"}}`, `FlowResult.status=COMPLETED` → asserts `RunBundle.outcome == "failed"` and `bundle.developed.pr_url == ""`. |
| `test_close_host_marks_blocked_feature_handoff_as_failed` | Module 1 | Same as above with `"feature_handoff"` key (FEAT-412's dev-flow topology uses this id). |
| `test_close_host_marks_escalated_failure_handler_as_failed` | Module 1 | `responses={"failure_handler": {"status": "escalated", "issue_key": "OPS-1"}}` (no handoff response at all — the handoff node was skipped) → `outcome == "failed"`. This is the case the v0.2 spec review added. |
| `test_close_host_marks_blocked_revision_handoff_as_failed` | Module 1 | `responses={"revision_handoff": {"status": "blocked", "error": "push: ...", "branch": "b"}}` → `outcome == "failed"`. |
| `test_close_host_keeps_comment_failed_revision_as_succeeded` | Module 1 | Control: `responses={"revision_handoff": {"status": "comment_failed", "pr_number": 7}}` → `outcome == "succeeded"` (degraded, but the revision WAS pushed — see Non-Goals). |
| `test_close_host_writes_bundle_and_report` (existing) | Module 1 | Regression: `responses={"deployment_handoff": {"pr_url": "http://pr/1"}}` still yields `outcome == "succeeded"` — must still pass unmodified. |

### Integration Tests
| Test | Description |
|---|---|
| Full `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` | No pre-existing test regresses. Verified 2026-08-05: **no** test under `tests/flows/dev_loop/` currently feeds a `{"status": "blocked"}` (or any `_FAILED_TERMINAL_STATUSES`) response into a `COMPLETED` `FlowResult`, so no existing `outcome == "succeeded"` / `phase == "succeeded"` assertion can flip. |

### Test Data / Fixtures
Reuse `test_run_bundle_export.py`'s existing `_FakeFlow` and `brief`
fixtures — no new fixtures required.

---

## 5. Acceptance Criteria

- [ ] `DevLoopRunner._close_host` records `RunClosed(outcome="failed")`
      when any node id in `_TERMINAL_NODE_IDS` reported a status in
      `_FAILED_TERMINAL_STATUSES`, even though
      `FlowResult.status == "completed"`. Covers, at minimum: blocked
      `deployment_handoff`, blocked `feature_handoff`, blocked
      `revision_handoff`, and `failure_handler` reporting `escalated` /
      `escalated_without_ticket` / `escalation_failed`.
- [ ] The override emits a WARNING log line naming the node id and the
      status that triggered it.
- [ ] The `pr_url` extraction in `_close_host` is **byte-for-byte
      unchanged** — the override touches `outcome` only. Do NOT add
      `pr_url = ""` on the blocked path (see Non-Goals: a blocked
      deployment-approval rejection can coexist with a real PR).
- [ ] The node-id allowlist is explicit — a non-terminal node returning
      `{"status": "blocked"}` must NOT flip the run's outcome.
- [ ] `revision_handoff`'s `comment_failed` status still records
      `outcome="succeeded"` (degraded, but delivered).
- [ ] The "terminal nodes never raise" contract on
      `FeatureHandoffNode`/`DeploymentHandoffNode`/`RevisionHandoffNode`/
      `FailureHandlerNode` is unchanged — no edits to any node file.
- [ ] `bots/flows/core/result.py` and `bots/flows/flow/flow.py` are
      unchanged — the fix is contained to `dev_loop/runner.py`.
- [ ] `test_close_host_writes_bundle_and_report` (pre-existing,
      succeeded-path) still passes unmodified.
- [ ] The five new tests in §4 pass, asserting `outcome` per case and
      using `bundle.developed.pr_url` (NOT `bundle.pr_url`, which does
      not exist).
- [ ] Full `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` passes;
      `ruff` clean on the changed file.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified 2026-08-05 on `dev` (post fast-forward, HEAD `4177b280e`).

### Verified Imports
```python
from parrot.flows.dev_loop.runner import DevLoopRunner  # runner.py:37 (class def, verified)
from parrot.flows.dev_loop.session_state import RunClosed, SessionHost  # session_state.py:349, imported by runner.py
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py
class DevLoopRunner:
    @staticmethod
    def _outcome_from_status(status: Any) -> str:              # :446
        # "completed" -> "succeeded"; "partial"/"failed" -> "failed"

    def _close_host(                                            # :1314
        self, host: SessionHost, result: FlowResult, ctx: FlowContext,
    ) -> None:
        # :1342  outcome = self._outcome_from_status(result.status)
        # :1345-1347
        #   handoff_resp = result.responses.get("deployment_handoff") \
        #       or result.responses.get("feature_handoff")
        # :1349-1351
        #   pr_url = ""
        #   if isinstance(handoff_resp, dict):
        #       pr_url = str(handoff_resp.get("pr_url", "") or "")
        # :1353-1355
        #   host.apply(RunClosed(
        #       outcome=outcome, jira_issue_key=jira_issue_key, pr_url=pr_url,
        #   ))

# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py:349-353
class RunClosed(_ActionBase):
    type: Literal["run/closed"] = "run/closed"
    outcome: Literal["succeeded", "failed"]     # already binary — no model change needed
    jira_issue_key: str = ""
    pr_url: str = ""

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/feature_handoff.py:186-189
#   pr_url is None:
#       await self._mark_blocked(issue_key, last_error or "unknown PR error")
#       return {"status": "blocked", "error": last_error or "unknown PR error"}

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py:142-143, 199
#   return {"status": "blocked", "error": f"push: {exc}"}
#   return {"status": "blocked", "error": gate_error}
```

### Verified terminal-node status vocabulary (v0.2 — grepped 2026-08-05)

Complete set of `{"status": ...}` values the four terminal nodes can
return. The `→` column is what `_close_host` must record.

| Node id | File:line | Status | → outcome |
|---|---|---|---|
| `deployment_handoff` | `deployment_handoff.py:241` | `ready_to_deploy` | `succeeded` |
| `deployment_handoff` | `:143`, `:175`, `:199` | `blocked` | **`failed`** |
| `feature_handoff` | `feature_handoff.py:238` | `ready_to_deploy` | `succeeded` |
| `feature_handoff` | `:164`, `:189` | `blocked` | **`failed`** |
| `revision_handoff` | `revision_handoff.py:96` | `revised` | `succeeded` |
| `revision_handoff` | `:74` | `blocked` | **`failed`** |
| `revision_handoff` | `:89-94` | `comment_failed` | `succeeded` (degraded — Non-Goals) |
| `failure_handler` | `failure_handler.py:125` | `escalated` | **`failed`** |
| `failure_handler` | `:92` | `escalated_without_ticket` | **`failed`** |
| `failure_handler` | `:111-112` | `escalation_failed` | **`failed`** |
| `close` | `close.py` | `closed` / `closed_without_ticket` / `close_failed` | not inspected (out of scope — the PR exists, only Jira bookkeeping failed) |

### Verified mechanics the fix relies on
```python
# 1. FlowResult.responses maps node_id -> the node's RAW execute() return dict
#    (NOT a wrapped response object), so isinstance(resp, dict) holds in
#    production, not only under _FakeFlow:
#    bots/flows/flow/flow.py:891   ->  responses=dict(results)

# 2. failed[] is populated ONLY when a node raised (flow.py:1701); completed[]
#    otherwise (:1717); skipped nodes count toward neither. determine_run_status
#    returns "completed" whenever failure_count == 0 (core/result.py:242-260)
#    -> a non-raising terminal failure yields FlowStatus.COMPLETED.

# 3. RunClosed is applied in EXACTLY ONE place in the repo:
#    runner.py:1354 (verified: grep -rn "RunClosed(" src/parrot/ -> 2 hits,
#    the class def + this call). _outcome_from_status is its only decider.

# 4. The assertion chain the tests use:
#    RunClosed.outcome -> state.phase        (session_state.py:761)
#                      -> RunBundle.outcome  (run_bundle.py:330)
#    RunPhase Literal (session_state.py:163-170) already contains "failed",
#    documented as "failure_handler terminal" — today unreachable via that path.

# 5. RunBundle field layout — pr_url is NESTED, there is no bundle.pr_url:
#    run_bundle.py:98    class DevelopedWork: pr_url: str = ""
#    run_bundle.py:308   developed = DevelopedWork(pr_url=state.pr_url or "", ...)
#    run_bundle.py:144   class RunBundle: outcome: RunPhase   # top-level
#    -> assert bundle.developed.pr_url == ""     # bundle.pr_url -> AttributeError
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| Blocked-outcome check | `_close_host`'s existing `handoff_resp` lookup | reuses the same variable, adds one `isinstance`+dict-key check | `runner.py:1345-1352` |

### Does NOT Exist (Anti-Hallucination)
- ~~a `"blocked"` value in `RunClosed.outcome`'s `Literal`~~ — the
  Literal stays `["succeeded", "failed"]`; a blocked handoff maps to the
  existing `"failed"` value, it does not need (or get) a third state.
- ~~raising from `FeatureHandoffNode`/`DeploymentHandoffNode` on the
  blocked path~~ — explicitly out of scope (see Non-Goals); the fix
  lives entirely in `_close_host`'s projection, not the nodes.
- ~~a change to `determine_run_status` / `AgentsFlow`'s
  `completed`/`failed` bookkeeping~~ (`bots/flows/core/result.py`,
  `bots/flows/flow/flow.py:1701/1717`) — explicitly out of scope; those
  are shared by every flow, not `dev_loop`-specific.
- ~~`revision_handoff.py` / `failure_handler.py` **file** changes~~ — the
  fix reads their response `"status"` from `_close_host`; neither node
  file is edited. (v0.2 note: their *statuses* ARE now in scope, their
  *code* is not.)
- ~~`bundle.pr_url`~~ — no such attribute; it is
  `bundle.developed.pr_url` (`run_bundle.py:98/308`).
- ~~a session-state action that marks a run "blocked"~~ — the handoff
  nodes' `_mark_blocked()` (`feature_handoff.py:331-346`) only transitions
  and comments on **Jira**; it applies no `SessionHost` action, which is
  precisely why `_close_host` is the only viable fix point.

### Existing Test Harness Pattern (for Module 2)
```python
# packages/ai-parrot/tests/flows/dev_loop/test_run_bundle_export.py
class _FakeFlow:
    def __init__(self, *, status: FlowStatus = FlowStatus.COMPLETED,
                 responses: Dict[str, Any] | None = None) -> None: ...
    async def run_flow(self, ctx, **kwargs) -> FlowResult:
        return FlowResult(output=..., status=self.status,
                           responses=dict(self.responses))

# existing succeeded-path assertion to preserve, verbatim:
#   flow = _FakeFlow(responses={"deployment_handoff": {"pr_url": "http://pr/1"}})
#   result = await runner.run(brief, run_id="run-bundle-export1")
#   assert result.status == FlowStatus.COMPLETED
#   bundle = RunBundle.model_validate(json.loads(bundle_path.read_text()))
#   assert bundle.outcome == "succeeded"
```

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Keep the fix a minimal, additive diff inside `_close_host` — do not
  refactor the surrounding method, and do not fold the new scan into the
  existing `handoff_resp`/`pr_url` lines (they must stay unchanged).
- The WARNING log line is REQUIRED (see Goals) — use the file's existing
  `self.logger` convention, and include the node id and status.
- Pydantic v2 / async-first conventions already apply to the touched
  file; no new patterns introduced.

### Known Risks / Gotchas
- Every `result.responses` value can be `None` or a non-dict (bug-mode
  runs where a node never ran; skipped nodes are absent entirely) —
  guard each with `isinstance(resp, dict)`, mirroring the existing guard
  at `runner.py:1349`. Never assume a dict.
- **Do not reuse `handoff_resp` for the status scan.** It is
  `deployment_handoff or feature_handoff` — in the `failure_handler` case
  the handoff node was *skipped*, so `handoff_resp` is `None` and a scan
  built on it would miss the most important case. Iterate
  `_TERMINAL_NODE_IDS` against `result.responses` directly.
- Do not gate the override on `pr_url` being empty, and do not set
  `pr_url` from the override — `_close_host`'s `pr_url` block is
  off-limits (§5, Non-Goals).
- Keep the status set an explicit allowlist. `"comment_failed"` is
  deliberately absent (degraded, delivered) and `close`'s statuses are
  deliberately not inspected.
- The `RunClosed` reducer is terminal-sticky
  (`session_state.py:758-759`: a run already in a terminal phase ignores
  a later `run/closed`). Irrelevant here — a run reaching `_close_host`
  is still `running`/`awaiting_gate` — but do not add a second
  `RunClosed` apply expecting it to correct an earlier one.

### External Dependencies
None — no new packages.

---

## 8. Open Questions

None — this is a fully-scoped, single-function bug fix; the code-review
finding that prompted it already specified the exact root cause and the
constraint (do not touch shared `AgentsFlow` core).

---

## Worktree Strategy

- **Isolation unit**: per-spec (single task, single worktree).
- One task: implement Module 1 + Module 2 together (they are the same
  file-pair change: `runner.py` + its test file) — no parallelism
  needed or possible for a fix this small.
- **Cross-feature dependencies**: none. FEAT-412 (`sdd-dev-flow`) is
  the feature that surfaced this via code review but does not depend on
  this fix landing first — dev-flow's `feature_handoff` reuse already
  works correctly modulo this pre-existing outcome-recording gap.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-05 | Jesus (via /sdd-done FEAT-412 code-review follow-up) | Initial draft, filed as a follow-up from FEAT-412's adversarial code review. |
| 0.2 | 2026-08-05 | Jesus (pre-implementation spec review) | Widened scope from "blocked handoff" to the whole terminal-node family after finding `failure_handler`-terminated runs are recorded `succeeded` by the same root cause (§1 new subsection). Corrected the `pr_url` acceptance criterion (was asserted as an invariant; it is an accident of the payloads — override must not touch `pr_url`). Fixed the test contract: `bundle.developed.pr_url`, not `bundle.pr_url` (no such attribute). Made the WARNING log line required. Reworked the `revision_handoff` Non-Goal (its `blocked` is now in scope; only `comment_failed` stays `succeeded`). Added the verified status-vocabulary table and the five mechanics the fix relies on (§6). Recorded explicitly that the caller-visible `FlowResult.status` stays `"completed"` by design. |
