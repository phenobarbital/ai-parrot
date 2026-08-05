# TASK-2128: DevFlowRunner — host the dev-flow topology

**Feature**: FEAT-412 — Dev-Flow: SDD-Oriented AgentsFlow for Feature Development
**Spec**: `sdd/specs/sdd-dev-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2127
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. `DevLoopRunner.run()` switches flows per brief kind
(bug graph vs `_run_feature`); dev-flow has exactly ONE topology, so the
subclass pins it while inheriting the whole hosting machinery: concurrency
cap, SessionHost per run, actions stream, gates + park/resume, retention
sweep, bundle/report persistence.

---

## Scope

- Create `packages/ai-parrot/src/parrot/flows/dev_flow/runner.py` with
  `DevFlowRunner(DevLoopRunner)`:
  - `async def run(self, brief: DevFlowBrief, *, run_id=None,
    initial_task="", extra_shared=None) -> FlowResult` — accepts
    `DevRequestBrief | FeatureBrief`; seeds `ctx["dev_brief"]` (always) and
    `ctx["feature_brief"]` (when the brief IS a `FeatureBrief`); never
    calls the bug-mode path; always executes the dev-flow graph the runner
    was constructed with.
  - `extra_shared` passthrough preserved (carries `skip_qa`,
    `require_plan_approval`, … from the server).
  - Do NOT re-implement gates/park/resume/bundle logic — inherit.
- Unit tests with a stub flow.

**NOT in scope**: server wiring (TASK-2129); changes to `DevLoopRunner`
itself (if a private hook must be touched, prefer overriding in the
subclass; report any unavoidable base change in the Completion Note).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_flow/runner.py` | CREATE | DevFlowRunner subclass |
| `packages/ai-parrot/tests/flows/dev_flow/test_runner.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.runner import DevLoopRunner   # verified 2026-08-05
from parrot.flows.dev_flow.models import DevFlowBrief, DevRequestBrief  # TASK-2121
from parrot.flows.dev_loop.models import FeatureBrief    # models/base.py:725
from parrot.flows.dev_flow.flow import build_dev_flow    # TASK-2127
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py (verified 2026-08-05)
class DevLoopRunner:
    def __init__(self, flow, *, dispatcher=..., jira_toolkit=...,
                 git_toolkit=..., wiki_toolkit=..., redis_url=...,
                 codereview_dispatcher=..., graph_memory=...)  # keyword wiring
    async def run(self, brief: Union[WorkBrief, FeatureBrief], *,
                  run_id: Optional[str] = None, initial_task: str = "",
                  extra_shared: Optional[Dict[str, Any]] = None
                  ) -> FlowResult                               # :885
    async def resolve_gate(self, run_id, gate_id, resolution,
                           resolved_by, comment, origin) -> ...  # :713
    async def resume_run(self, run_id) -> FlowResult
    def cancel_run(self, run_id, requested_by) -> ...
    # per-run hosting internals inherited as-is:
    # _register_host / _make_envelope_sink / _persist_run_bundle /
    # _close_host / park (_park/_auto_resume) / sweep loop
    async def _run_feature(self, brief) -> FlowResult   # FEAT-378 switch —
    #   dev-flow must NOT use this (single-topology runner)
```

### Does NOT Exist
- ~~`DevFlowRunner`~~ — created here.
- ~~a `mode`/`topology` parameter on `DevLoopRunner.run`~~ — flow switching
  in the base is kind-driven and internal (`_run_feature`, `_feature_flow`
  cache); the subclass bypasses it by overriding `run`.
- ~~`ctx["work_brief"]` / `ctx["bug_brief"]` seeding in dev-flow~~ — bug-mode
  keys stay unset.

---

## Implementation Notes

### Key Constraints
- Read `DevLoopRunner.run` (runner.py:885 onward) BEFORE coding: replicate
  its host-registration/envelope-sink/close-host sequence (or better,
  refactor-free: call the smallest inherited helpers it uses) so session
  state, streams, park/resume and bundles behave identically for dev-flow
  runs. The subclass's job is brief-typing + seeding + single-topology; the
  lifecycle plumbing must remain the base class's.
- `initial_task` default mirrors the server's per-mode strings; keep it a
  passthrough.
- The FEAT-378 `_feature_flow` cache and `_run_feature` must be left
  untouched and unused.

### References in Codebase
- `dev_loop/runner.py::DevLoopRunner.run/_run_feature` — sequence to mirror
- `tests/flows/dev_loop/test_runner_park.py` — runner test style

---

## Acceptance Criteria

- [ ] `DevFlowRunner.run(DevRequestBrief)` executes the dev-flow graph and seeds `ctx["dev_brief"]`
- [ ] `DevFlowRunner.run(FeatureBrief)` additionally seeds `ctx["feature_brief"]`; ideation is skipped by routing (not by the runner)
- [ ] Gates opened during a run resolve via the inherited `resolve_gate`; park/resume unaffected
- [ ] Tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow/test_runner.py -v`; `ruff` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_flow/test_runner.py
async def test_run_accepts_dev_request_brief(): ...
async def test_run_accepts_feature_brief_seeds_feature_key(tmp_path): ...
async def test_extra_shared_passthrough(): ...       # require_plan_approval et al
async def test_never_calls_run_feature(monkeypatch): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2127 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/sdd-dev-flow.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`,
   update index → `"done"`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
