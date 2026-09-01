---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Per-run dev-flow model plan

**Feature ID**: FEAT-490
**Date**: 2026-09-01
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.29.0

---

## 1. Motivation & Business Requirements

### Problem Statement

The dev console (`examples/dev_loop/server_dev.py`, port 8081) exposes
per-seat model selectors, but changing the **ideation model** or the
**adversarial review pair** for a single run does nothing. The run starts,
the server logs

```
dev-flow run_id=… requested a model plan that differs from the server's
build-time plan; the run will use the SERVER plan. Differing seats: …
```

and the operator is told to *"restart the console with the desired
`DEV_FLOW_*` env keys"*. For a console whose purpose is comparing models
on real work, a server restart per experiment is the wrong loop — and the
selectors read as a promise the product does not keep.

The cause is that `DevFlowModelPlan` is consumed at **flow-build** time:
`build_dev_flow(model_plan=…)` resolves the plan once and hands each seat
to a node constructor — `IdeationNode(model=…)` (`factories.py:308`),
`QANode(codereview_dispatcher=…)` (`factories.py:274,286`),
`DevelopmentNode(development_pool_config=…)` (`factories.py:286`). The
console builds one flow at startup (`server_dev.py:853`), so a per-run
plan has nowhere to land.

**The finding that makes this cheap.** That premise is already stale.
Since FEAT-480, a run with a stable `run_id` **and** `dev_loop_flow_kwargs`
configured goes through `DevCheckpointCoordinator.prepare()`
(`dev_loop/runner.py:1253`), and on a **cache miss — i.e. every new run —**
`prepare()` calls `flow_factory(None)` (`dev_loop/checkpoint.py:555`),
which is `DevFlowRunner._dev_loop_flow_factory()` →
`build_dev_flow(**self._dev_loop_flow_kwargs)` (`dev_flow/runner.py:295`).
The console passes both (`server_dev.py:525,586` supplies `run_id`;
`server_dev.py:826` builds the kwargs), so **a fresh flow is already built
for every console run**. Nothing needs to be re-architected: the per-run
plan simply is not threaded into those kwargs.

A related gap was already closed separately: the **development pool** is
per-run (commit `33ec41e46` — `DevelopmentNode._resolve_pool_config` now
reads dev-flow's brief keys). This spec covers the two seats that remain
genuinely build-time.

### Goals

- A `DevFlowModelPlan` submitted with `POST /api/flow/run` selects the
  ideation model and the review pair **for that run only**, with no server
  restart.
- Concurrent runs with different plans never leak seats into each other
  (`DevLoopRunner` runs up to `max_concurrent_runs` simultaneously,
  `dev_loop/runner.py:403`).
- Checkpoint/resume identity stays honest: a resumed run must not silently
  come back with different seats than the ones it started with.
- Callers that pass no per-run plan keep byte-identical behaviour —
  including every embedder of `DevFlowRunner` outside this repo.
- The console's `model_plan_ignored` warning and its UI banner narrow to
  what is *actually* ignored after this change, instead of over-claiming.

### Non-Goals (explicitly out of scope)

- **Mid-run seat switching.** Seats are fixed once the run's flow is built.
  Changing a model while a run is in flight is not in scope.
- **The ops console / dev-loop bug flow** (`examples/dev_loop/server.py`,
  `build_dev_loop_flow`). Same seam exists there; deliberately deferred so
  this feature ships against one topology.
- **Changing the `DevFlowModelPlan` schema.** The model, its validators and
  `resolve_model_plan()` precedence are unchanged.
- **The development pool.** Already per-run; this spec must not regress it.
- **Making a resumed run adopt a new plan.** See §8 Q1 — the recommended
  answer is explicitly "no".

---

## 2. Architectural Design

### Overview

Thread an optional `model_plan` from the HTTP request down to the per-run
flow build:

1. `DevFlowRunner.run()` accepts `model_plan: DevFlowModelPlan | None`.
2. The flow-factory closure is built **per call** with that plan merged
   over `self._dev_loop_flow_kwargs` — never stored on the instance, which
   would race across concurrent runs.
3. `_execution_policy_for_fingerprint()` derives its routing-relevant
   fields from the **effective** plan for that run, preserving today's
   deliberate split: pool shape / review backend / partner-enabled are IN
   the fingerprint, pure model strings are OUT (`dev_flow/runner.py:306-330`).
4. On a checkpoint **resume**, the run keeps the seats it was created with;
   the newly submitted plan is reported back as not applied.
5. The console passes the parsed plan through, and reports as "ignored"
   only what the run genuinely did not honour (in practice: only the
   resume case).

### Component Diagram

```
POST /api/flow/run  ──_parse_model_plan()──→  requested_plan
        │                                          │
        │                                          ▼
        └────────────────→ DevFlowRunner.run(brief, run_id=…, model_plan=…)
                                                   │
                                    ┌──────────────┴───────────────┐
                                    ▼                              ▼
                    _dev_loop_flow_factory(plan)     _execution_policy_for_fingerprint(plan)
                                    │                              │
                                    ▼                              ▼
                        DevCheckpointCoordinator.prepare(flow_factory=…, execution_policy=…)
                                    │
                     ┌──────────────┴───────────────┐
              cache miss                        resume hit
                     ▼                                ▼
        build_dev_flow(**kwargs | model_plan)   seats from the ORIGINAL run
                     │                                │
                     ▼                                ▼
   IdeationNode(model=…) · QANode(review pair) · DevelopmentNode(pool)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `DevFlowRunner.run()` (`dev_flow/runner.py:58`) | extends signature | New keyword-only `model_plan`, default `None` |
| `DevFlowRunner._dev_loop_flow_factory()` (`dev_flow/runner.py:276`) | changes signature | Takes the run's plan; closure is per-call |
| `DevLoopRunner.run()` (`dev_loop/runner.py:1171`) | seam only | Must keep working unchanged for the bug flow |
| `DevCheckpointCoordinator.prepare()` (`dev_loop/checkpoint.py:471`) | uses | Consumes the per-call `flow_factory` / `execution_policy` — no change to the coordinator itself |
| `build_dev_flow()` (`dev_flow/flow.py:86`) | uses | Already accepts `model_plan`; no change |
| `examples/dev_loop/server_dev.py` `handle_run` (`:482`) | uses | Passes `requested_plan`; narrows `model_plan_ignored` |
| `examples/dev_loop/static/dev.html` `planMismatchWarning` (`:1712`) | copy | Banner narrows to the resume case |

### Data Models

No new models. The per-run input is the existing
`parrot.flows.dev_flow.model_plan.DevFlowModelPlan` (`model_plan.py:167`),
already parsed from the form by `server_dev._parse_model_plan()`
(`server_dev.py:153`).

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/flows/dev_flow/runner.py
class DevFlowRunner(DevLoopRunner):
    async def run(
        self,
        brief: DevRequestBrief | FeatureBrief,
        *,
        run_id: str | None = None,
        initial_task: str = "",
        extra_shared: dict[str, Any] | None = None,
        model_plan: DevFlowModelPlan | None = None,   # NEW
    ) -> FlowResult:
        ...
```

The result must let the caller see what really ran. Recommended shape (see
§8 Q4): the runner records the effective plan and whether the run was
`fresh` or `resumed` on the run bundle/snapshot it already persists
(`dev_loop/runner.py:810,887`), so the console can report it without
guessing.

---

## 3. Module Breakdown

### Module 1: Per-run plan on `DevFlowRunner.run`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_flow/runner.py`
- **Responsibility**: Accept `model_plan`, build the flow-factory closure
  per call with the plan merged over `self._dev_loop_flow_kwargs`, and
  pass it to `prepare()`. Must not store the plan on `self`.
- **Depends on**: Module 2 (the base-class seam).

### Module 2: Base-class factory seam
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py`
- **Responsibility**: `DevLoopRunner.run()` currently calls
  `self._dev_loop_flow_factory()` with no arguments (`:1258`). Introduce a
  per-run seam (e.g. an optional overrides mapping threaded from `run()`)
  that the dev-loop bug path leaves empty, so its behaviour is unchanged.
- **Depends on**: none.

### Module 3: Fingerprint & resume semantics
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_flow/runner.py`
  (`_execution_policy_for_fingerprint`, `:306`)
- **Responsibility**: Derive the routing-relevant policy from the run's
  effective plan rather than only from the construction kwargs, preserving
  the documented in/out split. Implement and document the resume rule:
  a resumed run keeps its original seats.
- **Depends on**: Module 1.

### Module 4: Console wiring
- **Path**: `examples/dev_loop/server_dev.py`
- **Responsibility**: Pass `requested_plan` into `runner.run(...)`; compute
  `model_plan_ignored` from what the run actually did (fresh vs resumed)
  instead of from a build-time comparison; keep echoing the effective plan
  in the run response.
- **Depends on**: Modules 1, 3.

### Module 5: Operator-facing copy
- **Path**: `examples/dev_loop/static/dev.html`, `examples/dev_loop/README.md`
- **Responsibility**: The banner must stop saying "restart the console with
  the `DEV_FLOW_*` env keys" for seats that are now per-run, and must
  explain the one case that remains ("this run resumed a checkpoint and
  kept its original seats"). README's build-time limitation note narrows
  to the same.
- **Depends on**: Module 4.

### Module 6: Tests & docs
- **Path**: `packages/ai-parrot/tests/flows/dev_flow/`, `docs/dev_loop/dev-flow-model-plan.md`
- **Responsibility**: The §4 matrix, plus updating the model-plan reference
  doc, which currently documents the build-time-only rule.
- **Depends on**: Modules 1-5.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_run_without_plan_is_byte_identical` | 1 | No `model_plan` ⇒ `build_dev_flow` receives exactly today's kwargs |
| `test_per_run_plan_reaches_build_dev_flow` | 1 | A submitted plan appears in the factory's `model_plan` kwarg |
| `test_per_run_plan_never_stored_on_instance` | 1 | Two interleaved `run()` calls with different plans each build with their own |
| `test_concurrent_runs_do_not_leak_seats` | 1 | Two concurrent runs (`max_concurrent_runs=2`) build with distinct ideation models |
| `test_dev_loop_bug_path_factory_unchanged` | 2 | `DevLoopRunner.run()` still builds via `build_dev_loop_flow` with unchanged kwargs |
| `test_fingerprint_includes_review_backend_change` | 3 | A per-run plan changing the review backend changes the fingerprint |
| `test_fingerprint_ignores_pure_model_swap` | 3 | Changing only a model string keeps the fingerprint stable (still a cache hit) |
| `test_resumed_run_keeps_original_seats` | 3 | A resume does not adopt the newly submitted plan |
| `test_pool_stays_per_run` | 3 | Regression guard for `33ec41e46` — the brief's `dev_agents` still win |

### Integration Tests

| Test | Description |
|---|---|
| `test_run_endpoint_applies_ideation_model` | `POST /api/flow/run` with a different `research_primary` builds the flow with that model |
| `test_run_endpoint_reports_nothing_ignored_on_fresh_run` | `model_plan_ignored == []` for a fresh run with any valid plan |
| `test_run_endpoint_reports_seats_kept_on_resume` | A resumed run reports the seats it kept and why |
| `test_ui_banner_no_longer_tells_operators_to_restart` | `dev.html` copy assertion, in the style of `TestUiSurfacesTheOverride` |

### Test Data / Fixtures

Reuse the existing console harness in
`packages/ai-parrot/tests/flows/dev_flow/test_server_dev_model_plan.py`
(`_load_module`, `_StubFlow`, `make_client`, `_nl_form`) — it already loads
`server_dev.py` by path and drives it with `aiohttp_client`.

---

## 5. Acceptance Criteria

- [ ] A run submitted with a `research_primary` different from the server's
      builds its flow with that model, with no restart.
- [ ] A run submitted with a different review pair builds its flow with that
      pair (when the pair is the active reviewer, i.e. `DEV_FLOW_USE_REVIEW_PAIR=true`).
- [ ] `DevFlowRunner.run()` called without `model_plan` produces a
      `build_dev_flow` call byte-identical to today's.
- [ ] Two concurrent runs with different plans build with their own seats;
      no per-run plan is ever stored on the runner instance.
- [ ] A resumed run keeps the seats it was created with, and the response
      says so explicitly.
- [ ] The checkpoint fingerprint changes for pool shape / review backend /
      partner-enabled differences and does NOT change for a pure model swap.
- [ ] The development pool remains per-run (regression guard on `33ec41e46`).
- [ ] The console reports `model_plan_ignored == []` for a fresh run.
- [ ] Neither `dev.html` nor `README.md` tells the operator to restart the
      console for a seat that is now per-run.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow packages/ai-parrot/tests/flows/dev_loop -v`
- [ ] `docs/dev_loop/dev-flow-model-plan.md` updated.

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot.flows.dev_flow.model_plan import DevFlowModelPlan, resolve_model_plan  # dev_flow/model_plan.py:167, :340
from parrot.flows.dev_flow.flow import build_dev_flow                              # dev_flow/flow.py:86
from parrot.flows.dev_flow.runner import DevFlowRunner                             # dev_flow/runner.py:40
from parrot.flows.dev_flow.models import DevRequestBrief                           # imported by dev_flow/runner.py
from parrot.flows.dev_loop.models import FeatureBrief                              # models/base.py:730
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/flows/dev_flow/runner.py
class DevFlowRunner(DevLoopRunner):                                     # line 40
    async def run(                                                      # line 58
        self,
        brief: DevRequestBrief | FeatureBrief,
        *,
        run_id: str | None = None,
        initial_task: str = "",
        extra_shared: dict[str, Any] | None = None,
    ) -> FlowResult: ...
    def _dev_loop_flow_factory(self) -> Callable[[Any], AgentsFlow]:    # line 276
        # closes over dict(self._dev_loop_flow_kwargs); calls build_dev_flow
        # with checkpoint=True, checkpoint_required=True                 # line 295-302
    def _execution_policy_for_fingerprint(self) -> dict[str, Any]:      # line 306
        # reads self._dev_loop_flow_kwargs; FEAT-486 note at line 313-321
        # documents which model_plan fields join the fingerprint

# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py
class DevLoopRunner:                                                    # line 371
    def __init__(..., max_concurrent_runs: Optional[int] = None,        # line 403
                 dev_loop_flow_kwargs: Optional[Dict[str, Any]] = None) # line 412
    self._dev_loop_flow_kwargs = dev_loop_flow_kwargs                   # line 466
    async def run(...)                                                  # line 1171
        recovery_enabled = run_id is not None and self._dev_loop_flow_kwargs is not None  # line 1219
        flow, mode = await self._checkpoint_coordinator.prepare(         # line 1253
            workflow="dev-loop", run_id=rid, brief=brief,
            live_context=ctx,
            flow_factory=self._dev_loop_flow_factory(),                  # line 1258
            execution_policy=self._execution_policy_for_fingerprint(),
        )

# packages/ai-parrot/src/parrot/flows/dev_loop/checkpoint.py
class DevCheckpointCoordinator:
    async def prepare(                                                   # line 471
        ..., flow_factory: Callable[[FlowDefinition | None], AgentsFlow],
    ) -> tuple[AgentsFlow, Literal["fresh", "resumed"]]:                 # line 480
        if existing is None:                                             # line 553
            self.emit_recovery_event("cache_miss", ...)                  # line 554
            flow = flow_factory(None)                                    # line 555
            return flow, "fresh"                                         # line 558

# packages/ai-parrot/src/parrot/flows/dev_flow/factories.py — where seats are baked in
resolved_plan = resolve_model_plan(model_plan)                           # line 259
pool_config = resolved_plan.to_pool_config()                             # line 260
review_dispatcher = _assemble_review_pair(resolved_plan, dispatcher)     # line 274 (only when codereview_dispatcher is None)
    development_pool_config=pool_config,                                 # line 286
    codereview_dispatcher=review_dispatcher,                             # line 286 block
IdeationNode(model=resolved_plan.research_primary if resolved_plan else None)  # line 301-308
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `run(model_plan=…)` | `_dev_loop_flow_factory` | per-call closure argument | `dev_flow/runner.py:276` |
| per-run factory | `build_dev_flow(model_plan=…)` | kwarg merge | `dev_flow/flow.py:101` |
| per-run plan | `DevCheckpointCoordinator.prepare` | `flow_factory` / `execution_policy` | `dev_loop/runner.py:1253-1259` |
| `handle_run` | `runner.run(...)` | new keyword | `examples/dev_loop/server_dev.py:482` |
| `model_plan_ignored` | run response JSON | already present | `examples/dev_loop/server_dev.py:617` |

### Does NOT Exist (Anti-Hallucination)

- ~~`DevFlowRunner.set_model_plan()`~~ — no such method; the plan is not
  mutable state on the runner today, and this feature must not make it so.
- ~~`build_dev_flow(model_plan_override=…)`~~ — the kwarg is `model_plan`
  (`dev_flow/flow.py:101`) and it already exists.
- ~~`AgentsFlow.rebuild_nodes()` / `AgentsFlow.set_node_model()`~~ — there
  is no API to re-seat a constructed flow. Per-run seats come from building
  a new flow, not from mutating one.
- ~~`DevFlowModelPlan.merge()`~~ — does not exist. Precedence is
  `resolve_model_plan()` (`model_plan.py:340`), *explicit argument > env >
  built-in*, tracked via Pydantic `model_fields_set`.
- ~~`shared["model_plan"]`~~ — no node reads a plan from shared state; seats
  are constructor arguments. A shared-state plan would be dead config.
- ~~`DevCheckpointCoordinator.prepare(model_plan=…)`~~ — the coordinator
  takes no plan; it must stay workflow-agnostic.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Per-run state travels as **call arguments and closures**, never as
  instance attributes — `DevLoopRunner` executes up to
  `max_concurrent_runs` runs concurrently (`dev_loop/runner.py:403,415`),
  and the existing code is careful about this (`SessionHost` is created per
  run and seeded into `shared`, `dev_flow/runner.py:105-110`, precisely so
  nodes never capture a runner-level reference).
- Keep `resolve_model_plan()` as the single precedence rule; do not
  hand-merge plan fields.
- The `dev_loop` (bug) path must be untouched: its factory and fingerprint
  behaviour are covered by existing tests and are not part of this feature.

### Known Risks / Gotchas

- **Concurrency leak.** The tempting shortcut — assign the plan to
  `self._current_model_plan` before `prepare()` — silently corrupts
  concurrent runs. Mitigation: the acceptance criteria include an explicit
  concurrent-runs test.
- **Resume ambiguity.** A resumed run rebuilds nothing through
  `flow_factory` on the resume branch; adopting a newly submitted plan
  there would produce a run whose seats disagree with its own checkpoint
  history. Mitigation: specify "original seats win on resume" and report it
  (§8 Q1).
- **Fingerprint churn.** Moving fingerprint inputs from construction kwargs
  to the per-run plan can change existing fingerprints and invalidate
  in-flight checkpoints on deploy. Mitigation: keep the exact same field
  set (`dev_flow/runner.py:313-321`) and add a test asserting a plan-less
  run's fingerprint is unchanged.
- **Review pair is usually inactive.** The dev console wires the FEAT-378
  judge panel as `codereview_dispatcher`, and an explicit dispatcher wins
  over the plan (`factories.py:273`), so the review seats only take effect
  under `DEV_FLOW_USE_REVIEW_PAIR=true`. Making the plan per-run does not
  change that precedence; the UI already reports it via
  `review_pair_active` (`server_dev.py:_model_plan_payload`).
- **`_execution_policy_for_fingerprint` is shared with the base class.**
  The dev-flow override exists precisely because the kwarg shapes differ
  (`dev_flow/runner.py:306-330`); keep that separation.

### External Dependencies

None. No new packages.

---

## 8. Open Questions

- [ ] **Q1 — Resume semantics.** When a run resumes from a checkpoint and
      the caller submits a *different* plan, do we keep the original seats
      or adopt the new ones? *Owner: Jesus Lara.* **Recommendation: keep
      the original.** A resumed run's completed nodes were produced by the
      original seats; adopting new ones mid-history makes the bundle
      self-contradictory. Report it instead of silently doing either.
- [ ] **Q2 — Should a pure model swap force a fresh run?** Today's
      fingerprint deliberately excludes model strings so a model swap is a
      cache hit (`dev_flow/runner.py:313-321`). *Owner: Jesus Lara.*
      **Recommendation: keep that.** Changing the answer would make every
      model experiment a forced fresh run, which is the opposite of this
      feature's goal.
- [ ] **Q3 — Does the ops console get the same treatment?** *Owner: Jesus
      Lara.* **Recommendation: not in this feature** — same seam, different
      builder (`build_dev_loop_flow`); do it as a follow-up once this
      lands.
- [ ] **Q4 — How does the console learn the effective plan and the
      fresh/resumed mode?** `run()` currently returns a `FlowResult`, and
      the console's `handle_run` returns its HTTP response *before* the run
      completes (`server_dev.py:_run` is a background task). So
      `model_plan_ignored` cannot depend on the run's outcome unless the
      resume decision is made (or predicted) synchronously. *Owner: Jesus
      Lara.* Options: (a) have the runner expose a cheap
      "would this run resume?" probe before dispatch; (b) report the plan
      as applied at request time and surface a correction over the existing
      WebSocket when a resume is detected; (c) drop `model_plan_ignored`
      for fresh runs and let the resume case be a run event only.
- [ ] **Q5 — Naming of the base-class seam (Module 2).** An optional
      overrides mapping (`flow_kwargs_overrides`) keeps `DevLoopRunner`
      workflow-agnostic; a typed `model_plan` parameter on the base class
      would leak a dev-flow concept into the bug flow. *Owner: Jesus Lara.*
      **Recommendation: the generic overrides mapping.**

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — one worktree, tasks run
  sequentially.
- **Rationale**: Modules 1-3 all edit the two runner files and are
  causally chained (the seam must exist before the plan can be threaded,
  and the fingerprint depends on the threading). Modules 4-6 depend on 1-3.
  There is no parallel front worth the merge cost.
- **Cross-feature dependencies**: none outstanding. Depends on work already
  merged: FEAT-480 (per-run flow build), FEAT-486 (`DevFlowModelPlan`),
  FEAT-487 (partner key dedup), and commit `33ec41e46` (per-run dev pool),
  whose regression guard is an acceptance criterion here.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-01 | Jesus Lara | Initial draft |
