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

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-05
**Notes**:

`DevFlowRunner(DevLoopRunner)` overrides **only** `run()`. 19 tests (117
across `dev_flow`). No change to `DevLoopRunner` was needed — nothing in the
base had to be touched or made protected-accessible.

**Single topology, routed not branched.** Both brief kinds execute
`self.flow`; a `FeatureBrief` reaches `planner` because `dev_intake`'s
conditional edge sends it there, so "ideation is skipped by routing, not by
the runner" is literally true. `test_never_calls_run_feature` monkeypatches
`_run_feature` to raise and asserts `_feature_flow` stays `None`;
`test_both_kinds_use_the_same_flow_object` asserts `_rev_flow` and
`_feature_flow` are both still `None` after one run of each kind.

**Seeding**: `dev_brief` always; `feature_brief` additionally for a document
brief (pre-seeding a key `DevIntakeNode` would set anyway, so the context is
honest for any observer before intake runs); bug-mode keys never set
(`test_never_seeds_bug_mode_keys`). `extra_shared` merges last —
`test_extra_shared_passthrough` covers `require_plan_approval` + `skip_qa`,
which is the seam TASK-2123 and TASK-2129 depend on.

**Two projections instead of inline branching**, both static and unit-tested:

- `_summary_for` — the request `title` for an NL brief,
  `"Feature: <document_path>"` for a document brief (matching
  `_run_feature`'s wording). Also the `TypeError` guard: a bug-mode
  `WorkBrief` is rejected **before** any host is registered or slot acquired
  (`test_rejects_non_dev_flow_brief` asserts the flow never ran).
- `_work_kind_for` — `RunCreated.work_kind` is a closed
  `Literal["bug","enhancement","new_feature"]`, deliberately not extended
  with `"feature"` (TASK-1918). A `DevRequestBrief`'s kind maps *directly*
  onto two of those members (nicer than feature-mode, which has no NL kind
  to report); a document brief reuses `"bug"` as the structural placeholder
  exactly as `_run_feature` does, with the same explanatory comment.
  `test_run_created_work_kind_maps_per_brief` pins all three.

**On replicating the lifecycle block.** The task asked me to either replicate
`run()`'s sequence or call the smallest inherited helpers. The
host-registration/seeding/close parts *are* inherited helpers
(`_register_host`, `_apply_root_action`, `_run_summary_from_host`,
`_close_host`), but the ~35-line park-aware semaphore block is inlined in all
three existing base-class run paths with no extractable helper, so it is
replicated verbatim (comments included). This is necessary, not stylistic: an
ideation `open_questions` gate parks the run from deep inside `IdeationNode`
*while* `run_flow()` is in flight, so `async with self._semaphore` cannot
express the release/re-acquire, and without registering
`_run_completion[rid]` a `resume_run()` caller would have nothing to await.
`test_parked_run_frees_its_slot` proves it end-to-end: the gate opens, the run
parks, `active_runs` becomes empty, and answering the gate resumes it to
COMPLETED. (A future refactor extracting that block into a base-class helper
would now have four call sites — worth doing, out of scope here.)

`ruff`: whole `dev_flow` package + tests at **0** findings.

**Deviations from spec**: none.

Contract note: the task's Verified Imports did not name `FlowResult`'s module,
and my first draft guessed `parrot.bots.flows.core.types`, which raised
`ImportError`. Verified and corrected to `parrot.bots.flows.core.result` —
the module `dev_loop/runner.py:36` itself imports it from.
