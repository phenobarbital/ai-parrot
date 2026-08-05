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

### Goals
- A run whose handoff node returns `{"status": "blocked", ...}` MUST be
  recorded with `RunClosed(outcome="failed")`, never `"succeeded"`,
  regardless of what `FlowResult.status` says.
- No change to the intentional "handoff never raises" design — the node
  contract (`execute()` returns a dict, no exception) is preserved
  exactly as-is.
- No change to `AgentsFlow`/`determine_run_status` — the fix is
  contained entirely to `DevLoopRunner`'s own outcome projection, which
  already special-cases the two handoff node ids
  (`runner.py:1345-1352`: `deployment_handoff` / `feature_handoff`).

### Non-Goals (explicitly out of scope)
- Changing `bots/flows/core/result.py::determine_run_status` or
  `bots/flows/flow/flow.py`'s `completed`/`failed` bookkeeping — those
  are shared by every `AgentsFlow` consumer in the repo, not
  `dev_loop`-specific, and a behavior change there needs its own
  cross-cutting review.
- Making the handoff nodes raise instead of returning a blocked dict —
  that would change retry/park semantics for every existing caller and
  contradicts the documented, intentional design in
  `deployment_handoff.py:17`.
- `revision_handoff.py`'s blocked path — it does not create a PR and is
  not covered by the "successful run ⇒ PR exists" acceptance criterion;
  left untouched (no `_close_host` outcome inconsistency: a blocked
  revision-handoff still correctly has no PR to report either way, and
  `revision_handoff.py` is not one of the two ids `_close_host` inspects
  for `pr_url`).

---

## 2. Architectural Design

### Overview

Extend `DevLoopRunner._close_host`'s existing handoff-response lookup
(`runner.py:1345-1352`, which already reads
`result.responses.get("deployment_handoff") or
result.responses.get("feature_handoff")` to extract `pr_url`) to also
read that same response's `"status"` field. If it equals `"blocked"`,
force `outcome = "failed"` — overriding whatever
`_outcome_from_status(result.status)` computed — before constructing
`RunClosed`.

This is a single-function, additive change: every other outcome path
(no handoff response at all — bug-mode runs that fail earlier; a
handoff response with `"status"` absent or anything other than
`"blocked"`) is byte-for-byte unchanged.

### Component Diagram
```
DevLoopRunner._close_host(host, result, ctx)
        │
        ├─ outcome = _outcome_from_status(result.status)      # existing
        ├─ handoff_resp = result.responses.get("deployment_handoff")
        │                 or result.responses.get("feature_handoff")
        ├─ pr_url = handoff_resp.get("pr_url", "")             # existing
        ├─ NEW: if isinstance(handoff_resp, dict) and
        │        handoff_resp.get("status") == "blocked":
        │            outcome = "failed"
        └─ host.apply(RunClosed(outcome=outcome, ..., pr_url=pr_url))
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `DevLoopRunner._close_host` | modifies | Adds the blocked-outcome override; no signature change. |
| `RunClosed` (session_state.py) | uses (unchanged) | `outcome: Literal["succeeded", "failed"]` already supports the corrected value — no model change. |
| `FeatureHandoffNode` / `DeploymentHandoffNode` | reads (unchanged) | Their `execute()` contract and blocked-dict shape are NOT modified. |

### Data Models
No new or modified Pydantic models. `RunClosed.outcome` is already
`Literal["succeeded", "failed"]` (`session_state.py:351`) — the fix only
changes which value gets passed in for this one case.

### New Public Interfaces
None — this is a private-method (`_close_host`) behavior fix, no new
public surface.

---

## 3. Module Breakdown

### Module 1: Blocked-handoff outcome fix
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py`
- **Responsibility**: `_close_host` must record `outcome="failed"` when
  the terminal handoff response is `{"status": "blocked", ...}`, instead
  of trusting `FlowResult.status` alone.
- **Depends on**: none (self-contained within `runner.py`).

### Module 2: Regression tests
- **Path**: `packages/ai-parrot/tests/flows/dev_loop/test_run_bundle_export.py` (extend) and/or a new `packages/ai-parrot/tests/flows/dev_loop/test_handoff_blocked_outcome.py`
- **Responsibility**: Drive `DevLoopRunner.run()` end-to-end with the
  existing `_FakeFlow` harness (`test_run_bundle_export.py`'s pattern),
  supplying `responses={"deployment_handoff": {"status": "blocked",
  "error": "..."}}` (and the `feature_handoff` equivalent), and assert
  the resulting `RunBundle.outcome == "failed"` with an empty `pr_url` —
  plus a not-blocked control case proving the existing
  `outcome == "succeeded"` behavior (already covered by
  `test_close_host_writes_bundle_and_report`) is untouched.
- **Depends on**: Module 1.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_close_host_marks_blocked_deployment_handoff_as_failed` | Module 1 | `responses={"deployment_handoff": {"status": "blocked", "error": "push failed"}}`, `FlowResult.status=COMPLETED` → asserts `RunBundle.outcome == "failed"` and `pr_url == ""`. |
| `test_close_host_marks_blocked_feature_handoff_as_failed` | Module 1 | Same as above with `"feature_handoff"` key (FEAT-412's dev-flow topology uses this id). |
| `test_close_host_writes_bundle_and_report` (existing) | Module 1 | Regression: `responses={"deployment_handoff": {"pr_url": "http://pr/1"}}` still yields `outcome == "succeeded"` — must still pass unmodified. |

### Integration Tests
| Test | Description |
|---|---|
| Full `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` | No pre-existing test regresses (the fix only changes behavior for the specific `status == "blocked"` case, which no other passing test currently exercises with a `COMPLETED` `FlowResult.status`). |

### Test Data / Fixtures
Reuse `test_run_bundle_export.py`'s existing `_FakeFlow` and `brief`
fixtures — no new fixtures required.

---

## 5. Acceptance Criteria

- [ ] `DevLoopRunner._close_host` records `RunClosed(outcome="failed")`
      when the terminal handoff response (`deployment_handoff` or
      `feature_handoff`) is `{"status": "blocked", ...}`, even though
      `FlowResult.status == "completed"`.
- [ ] `pr_url` remains `""` in that case (already true today — no
      change needed there, verified by the new test).
- [ ] The existing "handoff never raises" contract on
      `FeatureHandoffNode`/`DeploymentHandoffNode` is unchanged — no
      edits to either node file.
- [ ] `bots/flows/core/result.py` and `bots/flows/flow/flow.py` are
      unchanged — the fix is contained to `dev_loop/runner.py`.
- [ ] `test_close_host_writes_bundle_and_report` (pre-existing,
      succeeded-path) still passes unmodified.
- [ ] Two new tests (blocked deployment_handoff, blocked
      feature_handoff) pass, asserting `outcome == "failed"`.
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
- ~~`revision_handoff.py` changes~~ — not in scope (see Non-Goals);
  `_close_host` does not inspect its response for `pr_url` today either.

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
  refactor the surrounding method.
- Follow existing logging conventions (`self.logger`) if a log line is
  added for the override (optional — not required by the acceptance
  criteria, but consistent with the rest of `_close_host`'s
  observability).
- Pydantic v2 / async-first conventions already apply to the touched
  file; no new patterns introduced.

### Known Risks / Gotchas
- `handoff_resp` can be `None` (bug-mode runs where neither
  `deployment_handoff` nor `feature_handoff` ever ran — e.g. QA-blocked
  runs) — the existing `isinstance(handoff_resp, dict)` guard at
  `runner.py:1349` already handles this; reuse the same guard for the
  new status check rather than assuming a dict.
- Do not confuse this with `revision_handoff.py`'s separate blocked
  path — it is a different node id, not read by `_close_host`'s
  `handoff_resp` lookup at all, and out of scope here.

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
