# TASK-2506: Single-agent path must honour the operator's declared dev agent

**Feature**: FEAT-466 — Dev-Loop Run Fidelity
**Spec**: `sdd/specs/dev-loop-run-fidelity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **spec Module 7** — Problem B of the feature.

An operator picks a backend and model in the console's "Agents & models" tab.
That selection travels correctly all the way to `DevelopmentNode`: the UI sends
`dev_agents` (`static/index.html:1344`), `_parse_dev_agents` builds
`DevAgentSpec` rows, and `_resolve_pool_config` correctly prefers the brief's
pool over the env's (`development.py:416-431`). Then it gets thrown away.

`execute()` has two degradation branches that both fall through to
`_execute_single()`:

```python
# nodes/development.py:190-207
        pool_cfg = self._resolve_pool_config(shared)
        if pool_cfg is None:
            return await self._execute_single(shared, research)
        if self._dispatcher_builder is None:                 # branch 1
            self.logger.warning(
                "Pool config present but no dispatcher_builder was configured "
                "on DevelopmentNode; degrading to single-agent."
            )
            return await self._execute_single(shared, research)

        scheduler = await self._build_scheduler(research)
        if scheduler is None:                                # branch 2 — STILL LIVE
            self.logger.warning(
                "No readable per-spec task index found for %s under %s; "
                "degrading to single-agent.", ...
            )
            return await self._execute_single(shared, research)
```

Branch 1 was fixed for the shipped examples by wiring the builder
(`examples/dev_loop/server.py:1499`; `server_dev.py:474` always had it).
**Branch 2 is still live** — and `_execute_single()` uses `self._dispatcher` /
`self._dispatch_profile`, both frozen at server startup from
`DEV_LOOP_DEVELOPMENT_AGENT`. It never looks at the resolved pool config. So
whenever no per-spec task index is readable, the run silently executes on the
server's env backend and the operator is told nothing.

This matters more after FEAT-466's other half: TASK-2507 makes hotfix runs
reserve no ids, which means **no per-spec task index**, which means branch 2 is
the *normal* path for every bugfix. Without this task, every hotfix would ignore
the operator's model choice. The two halves of this feature are load-bearing
for each other — that interaction is documented in spec §3 Module 2.

This task shares no files with any other task in the feature. It can run in
parallel from the start.

---

## Scope

- Change `_execute_single()` to accept the resolved pool config:
  `async def _execute_single(self, shared, research, pool_cfg=None)`.
- When `pool_cfg` is not `None` **and** `self._dispatcher_builder` is
  available, materialize `(dispatcher, profile)` from `pool_cfg.agents[0]` via
  the builder, instead of using `self._dispatcher` / `self._dispatch_profile`.
- When `pool_cfg` is `None` (or the builder is absent), behave **byte-identically
  to today**. This is the path every existing run takes; there is a dedicated
  regression test for it.
- Update all three call sites in `execute()` (lines 191, 197, 207) to pass
  `pool_cfg` where one was resolved. Note line 191's `pool_cfg` is `None` by
  definition — pass nothing there.
- Emit a `WorkerSummary` on the single path recording the backend/model
  actually used, and append it to the returned
  `DevelopmentOutput.worker_summaries`. `WorkerSummary` already carries exactly
  the right fields (`agent`, `model`) — reuse it, do not invent a new model.
- Log at WARNING when the pool was *requested* but the run is executing
  single-agent, naming the requested backend/model and the reason
  (no task index / no builder), so a substitution is never silent.
- Preserve the pool's first spec faithfully: if `pool_cfg.agents[0].count > 1`
  or `len(pool_cfg.agents) > 1`, log that only the first spec is used on the
  single path.
- Unit tests per the Test Specification below.

**NOT in scope**:
- Making the pool path itself work when there is no task index (i.e. inventing
  a synthetic single-task schedule). The single-agent path is the correct shape
  for a one-or-two-commit bugfix; do not build a scheduler substitute.
- Any change to `build_dispatcher` or its per-backend model defaults
  (`agent_builder.py:102-220`). It is already correct for all nine backends.
- Any change to `examples/dev_loop/server.py` or `server_dev.py` — the builder
  is already wired in both.
- Any change to `_execute_pool` (`development.py:539`) or `DevAgentPool`.
- The `scheduler is None` check at `development.py:312` — that is inside a
  different method; leave it alone unless a test proves otherwise.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` | MODIFY | `_execute_single(pool_cfg=…)`, call sites, WorkerSummary, warnings |
| `packages/ai-parrot/tests/flows/dev_loop/test_development_node.py` | MODIFY | Add cases (the existing suite already has the fixtures you need) |

> `test_development_node.py` already contains `_dispatcher_builder_factory`
> (line 90) and `test_no_dispatcher_builder_degrades_to_single` (line 387).
> Extend that module rather than creating a new one.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Any, Dict, Optional

from parrot.flows.dev_loop.models.base import (
    DevAgentPoolConfig,   # models/base.py:420
    DevAgentSpec,         # models/base.py:388
    DevelopmentOutput,    # models/base.py:476
    ResearchOutput,       # models/base.py:323
    WorkerSummary,        # models/base.py:454
)
from parrot.flows.dev_loop.models.claude import ClaudeCodeDispatchProfile
# already imported in development.py — used at line 449
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
class DevAgentSpec(BaseModel):                                  # line 388
    agent: DevAgentBackend    # Literal, see line 383           # line 396
    model: str = ""           # "" => backend default           # line 399
    count: int = 1                                              # line 402
    escalation_model: str = ""                                  # line 405

class DevAgentPoolConfig(BaseModel):                            # line 420
    agents: List[DevAgentSpec]      # min_length=1              # line 429
    isolation_mode: Literal["shared", "isolated"] = "shared"    # line 432

class WorkerSummary(BaseModel):                                 # line 454
    worker_id: str    # "Synthetic node id, e.g. 'development.w1'."  # line 462
    agent: str        # "Backend used for this worker, e.g. 'codex'." # line 465
    model: str        # "Model name/id used by this worker."          # line 466
    tasks_completed: List[str] = []                              # line 467
    tasks_failed: List[str] = []                                 # line 470
    summary: str = ""                                            # line 473

class DevelopmentOutput(BaseModel):                              # line 476
    files_changed: List[str]                                     # line 479
    commit_shas: List[str]                                       # line 480
    summary: str                                                 # line 481
    incomplete_tasks: List[str] = []                             # line 482
    worker_summaries: List[WorkerSummary] = []                   # line 490

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py
    def __init__(self, *, dispatcher, dispatch_profile=None, pool_config=None,
                 dispatcher_builder=None, pool_max=4,
                 require_plan_approval=False, jira_toolkit=None,
                 name="development") -> None:                     # line 86
        object.__setattr__(self, "_dispatch_profile", dispatch_profile)   # line 130
        object.__setattr__(self, "_dispatcher_builder", dispatcher_builder) # line 132

    async def execute(self, ctx, deps=None, **kwargs) -> DevelopmentOutput:  # line 141
        pool_cfg = self._resolve_pool_config(shared)              # line 189
        if pool_cfg is None:
            return await self._execute_single(shared, research)    # line 191
        if self._dispatcher_builder is None:
            ...warning...
            return await self._execute_single(shared, research)    # line 197
        scheduler = await self._build_scheduler(research)          # line 199
        if scheduler is None:
            ...warning...
            return await self._execute_single(shared, research)    # line 207
        return await self._execute_pool(shared, research, pool_cfg, scheduler)  # line 220

    def _resolve_pool_config(self, shared) -> Optional[DevAgentPoolConfig]:  # line 416
        # brief.dev_agents > self._pool_config > None

    async def _execute_single(self, shared, research) -> DevelopmentOutput:  # line 437
        profile = self._dispatch_profile or ClaudeCodeDispatchProfile(
            subagent="sdd-worker", permission_mode="acceptEdits",
            allowed_tools=["Read", "Edit", "Write", "Bash", "Grep", "Glob"],
            setting_sources=["project"],
        )                                                          # line 449-461
        dev_out: DevelopmentOutput = await self._dispatcher.dispatch(
            brief=research, profile=profile, output_model=DevelopmentOutput,
            run_id=shared["run_id"], node_id=self.name,
            cwd=research.worktree_path,
            session_host=shared.get("session_host"),
        )                                                          # line 463-476
        shared["development_output"] = dev_out
        return dev_out

    @staticmethod
    def _find_feature_slug(worktree_path: str, feat_id: str) -> Optional[str]:  # line 484
    async def _build_scheduler(self, research) -> Optional[TaskScheduler]:      # line 512
    async def _execute_pool(self, shared, research, pool_cfg, scheduler)        # line 539
        pool = DevAgentPool.build(pool_cfg, self._dispatcher_builder, self._pool_max)  # line 564

# packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py
def build_dispatcher(
    spec: DevAgentSpec, *, redis_url: str, max_concurrent: int,
    stream_ttl_seconds: int, config_getter: ConfigGetter = _default_config_getter,
) -> Tuple[DevLoopCodeDispatcher, BaseModel]:                      # line 102
    # spec.model (when non-empty) ALWAYS wins over the backend default.
```

```python
# The dispatcher_builder contract — packages/.../agent_pool.py:114,150
        dispatcher_builder: Callable[[DevAgentSpec],
                                     Tuple[DevLoopCodeDispatcher, BaseModel]]
        dispatcher, profile = dispatcher_builder(spec)   # SYNC call, not awaited
```

### Does NOT Exist

- ~~`DevelopmentOutput.requested_agent`~~ / ~~`.actual_agent`~~ / ~~`.backend`~~ —
  verified absent:
  `grep -rn "requested_agent\|actual_agent\|requested_backend" .../dev_loop/`
  → no matches. Use `WorkerSummary`, which already has `agent` + `model`.
- ~~`await self._dispatcher_builder(spec)`~~ — the builder is a **synchronous**
  callable (`agent_pool.py:150`). Do not await it.
- ~~`DevAgentPoolConfig.agents` being possibly empty~~ — it has
  `min_length=1` (`models/base.py:429`), so `agents[0]` is always safe.
- ~~`DevAgentSpec.count` meaning anything on the single path~~ — it does not;
  log it and use one worker.
- ~~a `_execute_single` override hook on `DevLoopNode`~~ — it is a plain method
  on `DevelopmentNode`.

---

## Implementation Notes

### Pattern to Follow

```python
    async def _execute_single(
        self,
        shared: Dict[str, Any],
        research: ResearchOutput,
        pool_cfg: Optional[DevAgentPoolConfig] = None,
    ) -> DevelopmentOutput:
        """Dispatch exactly one dev agent.

        FEAT-466: when a pool config resolved but the pool path was not
        reachable (no readable per-spec task index — the normal case for a
        hotfix, which reserves no ids), this path must still run on the
        backend/model the OPERATOR declared, not on the server's
        env-configured default. Falling back to ``self._dispatcher`` silently
        substituted the operator's choice.

        Args:
            shared: The flow's shared state dict.
            research: The upstream research output.
            pool_cfg: The resolved pool config, when one resolved. ``None``
                means no pool was declared and the legacy env dispatcher is
                correct.

        Returns:
            The validated :class:`DevelopmentOutput`, carrying one
            ``WorkerSummary`` describing the backend/model actually used.
        """
        dispatcher = self._dispatcher
        profile = self._dispatch_profile
        spec: Optional[DevAgentSpec] = None

        if pool_cfg is not None and self._dispatcher_builder is not None:
            spec = pool_cfg.agents[0]           # min_length=1 -> always safe
            if len(pool_cfg.agents) > 1 or spec.count > 1:
                self.logger.warning(
                    "Pool declared %d spec(s)/%d replica(s) but this run is "
                    "single-agent; using only %s/%s.",
                    len(pool_cfg.agents), spec.count,
                    spec.agent, spec.model or "<backend default>",
                )
            dispatcher, profile = self._dispatcher_builder(spec)   # sync call
            self.logger.info(
                "Single-agent dispatch honouring declared dev agent %s/%s.",
                spec.agent, spec.model or "<backend default>",
            )
        elif pool_cfg is not None:
            self.logger.warning(
                "Pool declared (%s) but no dispatcher_builder is configured; "
                "falling back to the env-configured dispatcher. The operator's "
                "selection is NOT being honoured.",
                ", ".join(f"{s.agent}/{s.model or 'default'}"
                          for s in pool_cfg.agents),
            )

        profile = profile or ClaudeCodeDispatchProfile(
            subagent="sdd-worker",
            permission_mode="acceptEdits",
            allowed_tools=["Read", "Edit", "Write", "Bash", "Grep", "Glob"],
            setting_sources=["project"],
        )

        dev_out: DevelopmentOutput = await dispatcher.dispatch(
            brief=research,
            profile=profile,
            output_model=DevelopmentOutput,
            run_id=shared["run_id"],
            node_id=self.name,
            cwd=research.worktree_path,
            session_host=shared.get("session_host"),
        )

        # Record what actually ran, so a substitution is auditable on the bundle.
        dev_out = dev_out.model_copy(
            update={
                "worker_summaries": [
                    *dev_out.worker_summaries,
                    WorkerSummary(
                        worker_id=f"{self.name}.single",
                        agent=(spec.agent if spec else self._env_backend_name()),
                        model=(spec.model if spec else "") or self._env_model_name(profile),
                        summary="single-agent dispatch",
                    ),
                ]
            }
        )
        shared["development_output"] = dev_out
        return dev_out
```

For the no-spec case, derive the label defensively from the profile rather
than hardcoding `"claude-code"` — profiles differ per backend, so use
`getattr(profile, "model", "") or ""` and a `type(dispatcher).__name__`-based
backend name. Keep it best-effort: a label is not worth an exception.

### Key Constraints

- **The `pool_cfg is None` path must not change at all.** Same profile default,
  same `self._dispatcher`, same `dispatch(...)` kwargs. Diff it carefully.
- **Do not await the builder.**
- `DevelopmentOutput` is a pydantic model — append to `worker_summaries` via
  `model_copy(update=...)`, matching the idiom used in `research.py:384,416`.
- Never let `WorkerSummary` construction raise and kill a successful dispatch.
  Wrap the labelling in a `try/except Exception` with a WARNING if you cannot
  guarantee the fields.
- Keep `self.logger` for all output; the WARNING wording matters — it is the
  operator's only signal that a substitution happened.

### References in Codebase

- `development.py:564` — how `_execute_pool` calls the same builder, for the
  contract shape.
- `agent_builder.py:102-220` — what the builder returns per backend.
- `test_development_node.py:90` — `_dispatcher_builder_factory`, the fixture to
  reuse.
- `test_development_node.py:387` — `test_no_dispatcher_builder_degrades_to_single`,
  the existing degradation test to extend rather than duplicate.

---

## Acceptance Criteria

- [ ] `_execute_single` accepts `pool_cfg` and defaults it to `None`
- [ ] Pool config resolved + no readable task index → the dispatch runs on
      `pool_cfg.agents[0]`'s backend/model (assert the builder was called with
      that exact spec, and that `self._dispatcher` was **not** used)
- [ ] `pool_cfg is None` → the injected env dispatcher and profile are used,
      byte-identically to today (regression guard)
- [ ] Pool resolved but `dispatcher_builder is None` → env dispatcher used
      **and** a WARNING names the unhonoured selection
- [ ] Multi-spec / `count > 1` pool on the single path logs a WARNING naming
      which spec was used
- [ ] The returned `DevelopmentOutput` carries a `WorkerSummary` whose
      `agent`/`model` match what actually ran
- [ ] A failure while building the `WorkerSummary` does not fail the dispatch
- [ ] All 39 pre-existing tests in `test_development_node.py` +
      `test_agent_builder.py` still pass
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] `ruff check` and `mypy` clean on `development.py`

---

## Test Specification

```python
# Extend packages/ai-parrot/tests/flows/dev_loop/test_development_node.py

class TestSingleAgentHonoursDeclaredAgent:
    async def test_uses_pool_spec_when_no_task_index(self, tmp_path):
        """The core FEAT-466 Problem B case: pool declared, no per-spec index
        (as on every hotfix run), selection must still be honoured."""
        env_dispatcher = FakeDispatcher()          # must NOT be used
        pool_dispatcher = FakeDispatcher()
        builder_calls = []

        def _builder(spec):
            builder_calls.append(spec)
            return pool_dispatcher, FakeProfile(model=spec.model)

        node = DevelopmentNode(
            dispatcher=env_dispatcher,
            dispatcher_builder=_builder,
        )
        # brief.dev_agents = [DevAgentSpec(agent="codex", model="gpt-5.5")]
        # worktree has NO sdd/tasks/index/ -> _build_scheduler returns None
        ...
        assert builder_calls == [DevAgentSpec(agent="codex", model="gpt-5.5")]
        assert pool_dispatcher.dispatched
        assert not env_dispatcher.dispatched

    async def test_no_pool_uses_env_dispatcher(self, tmp_path):
        """Regression guard — the path every existing run takes."""
        ...

    async def test_warns_when_builder_missing(self, tmp_path, caplog):
        ...
        assert "NOT being honoured" in caplog.text

    async def test_warns_on_multi_spec_pool(self, tmp_path, caplog):
        ...

    async def test_worker_summary_records_actual_backend(self, tmp_path):
        out = ...
        assert out.worker_summaries[-1].agent == "codex"
        assert out.worker_summaries[-1].model == "gpt-5.5"
```

---

## Agent Instructions

1. **Read the spec** — §1 Problem B (it names the exact line numbers and what
   is already correct), §3 Module 7, and §3 Module 2's
   "Interaction with Module 7 (intentional)" note explaining why this task
   matters more than it looks.
2. **Verify the Codebase Contract** — especially that the builder is called
   synchronously:
   ```bash
   sed -n '145,155p' packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py
   ```
3. **Establish the regression baseline before touching anything**:
   ```bash
   pytest packages/ai-parrot/tests/flows/dev_loop/test_development_node.py \
          packages/ai-parrot/tests/flows/dev_loop/test_agent_builder.py -q
   ```
   Record the count (39 at time of writing). It must not drop.
4. **Write failing tests, then implement** (TDD). Reuse
   `_dispatcher_builder_factory` and the existing `FakeDispatcher`.
5. **Diff the `pool_cfg is None` branch line by line** against the original
   `_execute_single` before you call it done — that path is load-bearing for
   every existing run.
6. Move this file to `sdd/tasks/completed/` and set the index entry to `done`.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-27
**Notes**: Implemented `_execute_single(shared, research, pool_cfg=None)` per
the task's pattern, with one deliberate, documented deviation (below).
Updated all three `execute()` call sites to pass `pool_cfg` at lines 197/207
(197: builder-missing degradation; 207: no-readable-index degradation) while
leaving the `pool_cfg is None` call site (line 191) passing nothing, exactly
as instructed. Verified the builder is called synchronously per
`agent_pool.py:150` (`dispatcher, profile = dispatcher_builder(spec)`, not
awaited). Extended `test_development_node.py`: added the
`TestSingleAgentHonoursDeclaredAgent` class (6 new tests) and made
`FakeDispatcher.dispatch` tolerate `**_kwargs` so it accepts the
single-agent path's `session_host=` kwarg (the pool path never passes it).
Baseline was 39 passing tests in `test_development_node.py` +
`test_agent_builder.py`; now 45 (39 + 6 new), all passing. Full
`pytest packages/ai-parrot/tests/flows/dev_loop/` run: 1097 passed (up from
1091 pre-task), same 3 pre-existing unrelated failures as TASK-2503
(confirmed via baseline diff, not touched by this task). `ruff check` on
`development.py`: 32 findings vs 31 baseline — the +1 is two new
`Optional[...]`-style UP045 findings (consistent with the file's existing
10 UP045 instances and its established `Optional[X]` convention throughout,
not `X | None`) minus one `RUF100 unused noqa` I removed after ruff flagged
it as superfluous on my own new `except Exception:` block. `ruff check` on
the test file: byte-identical finding count/content to baseline (2
pre-existing, untouched). `mypy` times out project-wide (60s, same as
TASK-2503) — environment limitation, not confirmed clean, not specific to
these files.

**Deviations from spec**: The task's own "Pattern to Follow" snippet
unconditionally appends a `WorkerSummary` via `dev_out.model_copy(...)`
regardless of whether a pool spec was actually used. Applied literally,
this breaks object identity (`result is dev_out`) on BOTH the `pool_cfg is
None` path AND the "pool declared but no `dispatcher_builder`" path — which
directly contradicts (a) the task's own Key Constraint "The `pool_cfg is
None` path must not change at all... Diff it carefully", and (b) two
pre-existing regression tests (`test_no_pool_exact_current_behavior`,
`test_no_dispatcher_builder_degrades_to_single`) that assert exactly that
identity, protected by the acceptance criterion "All 39 pre-existing tests
... still pass". Resolved by only appending the `WorkerSummary` when a pool
`spec` was actually materialized via the builder (i.e. the one case where
behaviour is intentionally changing) — this satisfies every literal
acceptance criterion (all of which describe pool-declared scenarios) while
keeping both explicitly-protected byte-identical paths untouched. Also
rewrote the third existing test, `test_missing_index_degrades_to_single`
(renamed `..._via_declared_agent`), because its assertions encoded the
exact Problem-B bug this task exists to fix (pool declared + builder
present + missing index → old code asserted the ENV dispatcher was used;
new code correctly uses the builder) — this is the intended, in-scope
behavior change per acceptance criterion "Pool config resolved + no
readable task index → the dispatch runs on `pool_cfg.agents[0]`'s
backend/model ... `self._dispatcher` was **not** used".
