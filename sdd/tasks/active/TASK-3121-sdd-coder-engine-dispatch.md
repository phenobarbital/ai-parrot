# TASK-3121: `SddCoderEngine` — per-attempt dispatch, cross-seat retry, job runner, telemetry collector

**Feature**: FEAT-549 — `sdd-worker` as Orchestrator of Parallel `sdd-coder` Sub-Agents
**Spec**: `sdd/specs/sdd-worker-subagents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3118, TASK-3120
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (dispatch side), reshaped by design research S1: the engine calls
`dispatcher.dispatch()` **directly per attempt**, each attempt in a fresh sub-worktree
`<feature>--TASK-NNN-a<n>`, and owns the single cross-seat retry (spec G6, AC-6, AC-20).
`coder_run_chunk` must return before any dispatcher call starts (S4, AC-21); all slow
work runs inside the `JobTable` task. Every dispatch profile defaults to
`subagent="sdd-worker"`, so the engine forces `"sdd-coder"` (S7, AC-24). Token usage
only exists as a `dispatch.completed` event reaching the bound `session_host`, hence
`AttemptTelemetryCollector` (S8, AC-10).

---

## Scope

- Implement `AttemptTelemetryCollector`, `SddCoderEngine.run_chunk/wait/_run_attempt/_research_for/_labels_for/_runner`.
- Optional `default_smoke(seat, model)` used by the probe when the toolkit wires it (codex probe command; in-process one-token completion) — may stay `FILL IN`-guarded behind a flag.
- Fake-dispatcher tests: cwd per attempt, retry on other seat in a new worktree, forced `sdd-coder` subagent, return-before-dispatch, `task_already_running`, serialised merges, telemetry capture.

**NOT in scope**: the MCP toolkit (TASK-3122), the native Haiku agent (prompt, TASK-3123/3124), real network smoke calls in tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | replace the TASK-3121 stubs; add `AttemptTelemetryCollector` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/__init__.py` | MODIFY | export `AttemptTelemetryCollector` |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` | CREATE | fake-dispatcher tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio, time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from parrot.flows.dev_loop.agent_builder import build_dispatcher                    # verified: agent_builder.py:135
from parrot.flows.dev_loop.models import DevAgentSpec, DispatchLabels, DevelopmentOutput, ResearchOutput, TaskScopedBrief  # verified: models/base.py:412, :763, :497, :340, :458
from parrot.flows.dev_loop.dispatchers import DispatchExecutionError, DispatchOutputValidationError   # verified: dispatchers/__init__.py:37-49
# from TASK-3120: CoderFailure, _FeatureCtx, _git, SddCoderEngine (+ _manager_for, _consolidate, _journal, _jobs, _assigner, seats)
```

### Existing Signatures to Use
```python
# agent_builder.py:135
def build_dispatcher(spec: DevAgentSpec, *, redis_url: str, max_concurrent: int, stream_ttl_seconds: int, config_getter=...) -> Tuple[DevLoopCodeDispatcher, BaseModel]
# every dispatcher exposes (verified: llm.py:113, codex.py dispatch, nova.py dispatch; FakeDispatcher in tests/flows/dev_loop/test_agent_pool.py:36):
async def dispatch(self, *, brief: BaseModel, profile: BaseModel, output_model: Type[T], run_id: str, node_id: str, cwd: str,
                   session_host: Optional[Any] = None, labels: Optional[DispatchLabels] = None) -> T
# models/base.py
class TaskScopedBrief(BaseModel): research: ResearchOutput; task_id: str; task_file: str = ""                     # :458-478
class ResearchOutput(BaseModel): jira_issue_key, spec_path, feat_id, branch_name, worktree_path: str (required); repo_path="" ; log_excerpts=[]; base_branch=""   # :340-391
class DispatchLabels(BaseModel): task_id="", task_title="", task_file="", seat="", agent, model, attempt ...             # :763-790 — read the class for the exact field set
class DevelopmentOutput(BaseModel): files_changed, commit_shas, summary, incomplete_tasks=[], worker_summaries=[]       # :497
# profiles default subagent="sdd-worker": models/llm.py:18, gemini.py:22, codex.py:18, claude.py:18-27, google_coding.py:21 — TASK-3123 widens the Literal to accept "sdd-coder"
# dispatchers/_shared.py:92-117  _apply_to_session_host(event): host = _SESSION_HOST_CTX.get(); action = action_from_dispatch_event(kind, node_id, ts, payload, seat=...); host.apply(action)
# session_state.py:1188  SessionHost.apply(self, action: DevLoopAction, origin: Optional[ActionOrigin] = None)   ← duck-type this signature
# session_state.py:1457  action_from_dispatch_event(kind, node_id, ts, payload=None, seat="") -> Optional[DevLoopAction]
# llm.py:373  kind="dispatch.completed" event carries the usage payload built by _completion_usage_payload (:585)
```

### Does NOT Exist
- ~~`DevAgentPool.run_wave` here~~ — worker-keyed cwd (agent_pool.py:337/358) + retry into another worker's cwd ⇒ forbidden for per-task worktrees (S1).
- ~~`profile.subagent` accepting `"sdd-coder"` before TASK-3123~~ — until the Literal is widened, `model_copy(update={"subagent": "sdd-coder"})` bypasses validation (model_copy does not re-validate) — acceptable at runtime, but the unit test asserting the value must not construct the profile via `__init__` with that value until TASK-3123 lands. Order in the worktree: 3123 may land before or after; tests use `model_copy`.
- ~~`WaveResult`/`WorkerSummary` carrying duration/usage~~ — they don't (agent_pool.py:119-134, base.py:481-495); `AttemptRecord` is filled by the collector + engine timing.
- ~~a documented `DevLoopAction.usage` attribute~~ — the exact shape returned by `action_from_dispatch_event` for `dispatch.completed` is **(unverified — check before use)**: read `session_state.py:1457-1560` and pick the field(s) carrying the usage dict.
- ~~`asyncio.TaskGroup` requirement~~ — plain `asyncio.gather(*, return_exceptions=True)` is enough and matches `run_wave`'s style.

---

## Implementation Notes

### Pattern to Follow
```python
# agent_pool.py:244-330 (_dispatch_one) — how a brief/profile/labels are assembled for ONE dispatch; copy the assembly, not the worker/cwd logic.
brief = TaskScopedBrief(research=research, task_id=task.id, task_file=task.file)
output = await worker.dispatcher.dispatch(brief=brief, profile=profile, output_model=DevelopmentOutput, run_id=run_id,
                                          node_id=worker.worker_id, cwd=cwd_for(worker.worker_id), session_host=session_host, labels=labels)
```

### Key Constraints
- `run_chunk`: validate (`task_not_in_plan`, `task_already_running`), create the job via `self._jobs.create(...)`, journal, **return** — no `await` on git or dispatchers before returning.
- `_runner`: `asyncio.gather` over `_run_task(task)` for the chunk; `_run_task` = attempt 1 → on error attempt 2 on `self._assigner.retry_seat(seat.label, {seat.label})` in a NEW manager/worktree → `_consolidate` on the successful attempt's branch; two failures ⇒ `outcome="failed"` with both attempts' errors in `diagnostics`.
- `_run_attempt`: `dispatcher, profile = self._dispatcher_builder(DevAgentSpec(agent=seat.backend, model=seat.model), redis_url=..., max_concurrent=1, stream_ttl_seconds=...)`; `profile = profile.model_copy(update={"subagent": "sdd-coder"})`; `node_id=f"sdd-coder.{seat.label}"`; `run_id=job_id`; measure `duration_s`; catch `DispatchExecutionError`, `DispatchOutputValidationError`, `asyncio.TimeoutError`, generic `Exception` ⇒ error text.
- `wait`: `min(timeout_seconds, self.roster.wait_timeout_max_s)`; journal after every wait.
- Native tasks in a chunk are skipped by `run_chunk` (they are `sdd-worker`'s); passing a native task id ⇒ `task_not_in_plan` with a message saying "native task — use coder_prepare_native".

### References in Codebase
- `packages/ai-parrot/tests/flows/dev_loop/test_agent_pool.py:23-80` — `FakeDispatcher` variants (success / raise / capture cwd) to mirror.

---

## Implementation Blueprint

### Steps (in order)
1. `AttemptTelemetryCollector` — *why*: usage never comes back from `dispatch()`; only the bound host sees the `dispatch.completed` event (S8).
2. `_research_for`, `_labels_for`, `_run_attempt` — *why*: one attempt = one dispatcher call in one fresh worktree (S1).
3. `_run_task` (retry ladder) + `_runner` + `run_chunk` + `wait` — *why*: AC-6/AC-20/AC-21.
4. Tests; `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder -v`.

### `engine.py` (MODIFY — add collector + replace the two stubs; anchors from TASK-3120)
```python
# occurrences: 1 (verified after TASK-3120: grep -c '^class SddCoderEngine:' .../sdd_coder/engine.py)
# BEFORE `class SddCoderEngine:` — insert:
class AttemptTelemetryCollector:
    """Duck-typed session host (see dispatchers/_shared.py:92-117 → host.apply(action)). Captures usage + timing per attempt."""

    def __init__(self, *, attempt: int, seat: RosterSeat) -> None:
        self.attempt, self.seat = attempt, seat
        self.started = time.monotonic(); self.started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.usage: Dict[str, Any] = {}; self.error = ""

    def apply(self, action: Any, origin: Any = None) -> None:
        """Called by _apply_to_session_host for every dispatch event. Keep only usage from 'dispatch.completed'."""
        # FILL IN: read session_state.py:1457-1560 to find where action_from_dispatch_event puts payload["usage"] for kind
        #          "dispatch.completed"; store it in self.usage (dict) — (unverified — check before use); bounded by test_telemetry_collector_captures_usage
        return None

    def record(self) -> AttemptRecord:
        return AttemptRecord(attempt=self.attempt, seat_label=self.seat.label, backend=self.seat.backend or "native", model=self.seat.model,
                             started_at=self.started_at, ended_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             duration_s=round(time.monotonic() - self.started, 3), usage=self.usage, error=self.error)


# occurrences: 1 (verified after TASK-3120: grep -c 'raise NotImplementedError("TASK-3121")' .../sdd_coder/engine.py → 2 lines; REPLACE both stubs with:)
    def _research_for(self, ctx: _FeatureCtx, *, worktree_path: str) -> ResearchOutput:
        return ResearchOutput(jira_issue_key="", spec_path=ctx.spec_path, feat_id=ctx.feature_id, branch_name=ctx.feature_branch,
                              worktree_path=worktree_path, repo_path=ctx.worktree, log_excerpts=[], base_branch=ctx.base_branch)

    def _labels_for(self, task: PlannedTask, seat: RosterSeat, attempt: int) -> DispatchLabels:
        # FILL IN: DispatchLabels(task_id=..., task_title=task.title, task_file=task.task_file, seat=f"sdd-coder.{seat.label}", agent=seat.backend, model=seat.model, attempt=attempt)
        #          — confirm field names at models/base.py:763-790 before writing
        raise NotImplementedError

    async def _run_attempt(self, ctx: _FeatureCtx, task: PlannedTask, seat: RosterSeat, *, attempt: int, job_id: str
                           ) -> Tuple[AttemptRecord, Optional[DevelopmentOutput], str, SubWorktreeManager, str, str]:
        """ONE dispatch in ONE fresh sub-worktree. Returns (record, output|None, error, manager, branch, path)."""
        manager = self._manager_for(ctx, task.task_id, attempt)
        path = await manager.create(f"{task.task_id}.a{attempt}")
        branch = f"{ctx.feature_branch}--{task.task_id}-a{attempt}"
        collector = AttemptTelemetryCollector(attempt=attempt, seat=seat)
        dispatcher, profile = self._dispatcher_builder(DevAgentSpec(agent=seat.backend, model=seat.model), redis_url=self._redis_url,
                                                       max_concurrent=1, stream_ttl_seconds=self._stream_ttl)
        profile = profile.model_copy(update={"subagent": "sdd-coder"})                 # S7 — every profile defaults to sdd-worker
        output: Optional[DevelopmentOutput] = None; error = ""
        try:
            output = await dispatcher.dispatch(brief=TaskScopedBrief(research=self._research_for(ctx, worktree_path=path), task_id=task.task_id,
                                                                    task_file=task.task_file), profile=profile, output_model=DevelopmentOutput,
                                               run_id=job_id, node_id=f"sdd-coder.{seat.label}", cwd=path, session_host=collector,
                                               labels=self._labels_for(task, seat, attempt))
        except Exception as exc:  # noqa: BLE001 — every failure becomes an attempt error; the ladder decides
            error = f"{type(exc).__name__}: {exc}"; collector.error = error
            self.logger.warning("attempt %d of %s on %s failed: %s", attempt, task.task_id, seat.label, error)
        return collector.record(), output, error, manager, branch, path

    async def _run_task(self, ctx: _FeatureCtx, task: PlannedTask, seat: RosterSeat, *, job_id: str) -> TaskResult:
        attempts: List[AttemptRecord] = []
        rec, out, err, manager, branch, path = await self._run_attempt(ctx, task, seat, attempt=1, job_id=job_id); attempts.append(rec)
        if err:
            assert self._assigner is not None
            retry = self._assigner.retry_seat(seat.label, {seat.label})
            if retry is not None:
                rec, out, err, manager, branch, path = await self._run_attempt(ctx, task, retry, attempt=2, job_id=job_id); attempts.append(rec)
        if err:
            return TaskResult(task_id=task.task_id, outcome="failed", branch=branch, worktree_path=path, attempts=attempts,
                              diagnostics="\n".join(a.error for a in attempts if a.error))
        result = await self._consolidate(ctx, manager, task, branch=branch, path=path)
        return result.model_copy(update={"attempts": attempts, "development_output": out})

    async def run_chunk(self, feature: str, worktree: str, task_ids: List[str]) -> CoderJob:
        """Validate, register, RETURN. Everything slow happens inside the job (S4)."""
        plan = await self.plan(feature, worktree); ctx = await self._resolve_feature(feature, worktree)
        first = {t.task_id: t for t in (plan.chunks[0].tasks if plan.chunks else [])}
        # FILL IN: raise task_not_in_plan for ids not in `first` or with .native=True (message: "native task — use coder_prepare_native");
        #          raise task_already_running for ids in self._jobs.running_task_ids() — bounded by AC-21
        seats = {s.label: s for s in self.seats}
        async def runner() -> List[TaskResult]:
            results = await asyncio.gather(*(self._run_task(ctx, first[tid], seats[first[tid].seat_label], job_id=job.job_id) for tid in task_ids),
                                           return_exceptions=True)
            # FILL IN: map Exception entries to TaskResult(outcome="failed", diagnostics=str(exc)); journal; return list — bounded by test_engine_run_chunk_merges_clean_branches
            return [r for r in results if isinstance(r, TaskResult)]
        job = self._jobs.create(ctx.feature_id, list(task_ids), runner)
        self._journal(ctx.worktree, job)
        return job

    async def wait(self, job_id: str, timeout_seconds: int) -> CoderJob:
        try:
            job = await self._jobs.wait(job_id, min(timeout_seconds, self.roster.wait_timeout_max_s))
        except KeyError as exc:
            raise CoderFailure("job_not_found", f"unknown job {job_id}") from exc
        # FILL IN: journal to the job's worktree (keep a job_id → worktree map set in run_chunk) — bounded by test_engine_journals_job_snapshot
        return job
```
**Why this shape**: `_run_attempt` is the only place a dispatcher is touched, so the S1 invariant (cwd == this attempt's worktree) is checkable in one test; the runner captures `job` by closure because `JobTable.create` schedules immediately; `gather(return_exceptions=True)` keeps one crashing task from killing the chunk.

### `sdd_coder/__init__.py` (MODIFY)
```python
# occurrences: 1 — extend the engine import line added by TASK-3120:
from parrot.flows.dev_loop.sdd_coder.engine import AttemptTelemetryCollector, CoderFailure, SddCoderEngine  # noqa: F401
# in __all__: "AttemptTelemetryCollector",
```

### FILL IN checklist
- [ ] `engine.py::AttemptTelemetryCollector.apply` — usage extraction; bounded by `test_telemetry_collector_captures_usage` (verify `DevLoopAction` shape first)
- [ ] `engine.py::_labels_for` — exact `DispatchLabels` fields; bounded by models/base.py:763-790
- [ ] `engine.py::run_chunk` — validation errors; bounded by AC-21
- [ ] `engine.py::runner` / `wait` — exception mapping + journaling; bounded by `test_engine_journals_job_snapshot`
- [ ] (optional) `default_smoke` — codex probe (`codex exec ... "Reply with exactly the single word OK." < /dev/null`, timeout) and in-process one-token completion via `LLMFactory.create(f"{provider}:{model}")._chat_completion(...)`; guard behind an engine flag `live_smoke: bool = False`; bounded by AC-9 (unit-tested via injected smoke, live path opt-in)

---

## Acceptance Criteria

- [ ] For every attempt the fake dispatcher's received `cwd` equals that attempt's own sub-worktree path; attempt 2 uses a different path and branch than attempt 1 (`test_engine_attempt_cwd_is_task_branch`, `test_engine_retry_on_other_seat_then_failed`) — AC-20.
- [ ] `attempts[1].seat_label != attempts[0].seat_label`; second failure ⇒ `outcome="failed"` with both errors in `diagnostics` — AC-6.
- [ ] Every profile handed to `dispatch()` has `subagent == "sdd-coder"` — AC-24.
- [ ] `run_chunk` returns while the fake dispatcher is blocked on an `asyncio.Event`; `status` shows `running`; second `run_chunk` for the same task ⇒ `task_already_running`; native task id ⇒ `task_not_in_plan` — AC-21.
- [ ] Two jobs consolidating concurrently never overlap inside `_merge_lock` (instrumented lock or timestamps).
- [ ] Synthetic `dispatch.completed` action with usage ⇒ `AttemptRecord.usage` filled and `duration_s > 0` — AC-10.
- [ ] Full-chunk happy path: 3 fake coders write listed files + commit ⇒ job `done`, every task `merged`, feature branch has the 3 commits.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder -v` passes; `ruff`/`mypy` clean.

---

## Test Specification

```python
# test_engine_dispatch.py (sketch)
class FakeDispatcher:
    """dispatch(**kw): records kw["cwd"], kw["profile"].subagent, kw["node_id"]; behaviour per label: "ok" writes the task's listed
    file in cwd + `git add/commit`, "fail" raises DispatchExecutionError, "block" awaits an Event, "extra" also writes an unlisted file."""

def fake_builder_factory(behaviour_by_backend): ...   # returns (spec) -> (FakeDispatcher, LLMCodeDispatchProfile())  (keyword-compatible with build_dispatcher)

async def test_engine_attempt_cwd_is_task_branch(...): ...
async def test_engine_retry_on_other_seat_then_failed(...): ...
async def test_engine_forces_sdd_coder_subagent(...): ...
async def test_engine_run_chunk_returns_before_dispatch(...): ...
async def test_engine_run_chunk_rejects_running_task(...): ...
async def test_engine_run_chunk_merges_clean_branches(...): ...
async def test_engine_merges_serialised_across_jobs(...): ...
def test_telemetry_collector_captures_usage(): ...   # build the action with session_state.action_from_dispatch_event("dispatch.completed", ...)
```

---

## Agent Instructions

1. **Read the spec** §2 step 2, §3 Module 4 `_run_attempt`, §6 Integration Points, §9 rows S1/S4/S7/S8.
2. **Check dependencies** — TASK-3118 and TASK-3120 completed (TASK-3123 is NOT required; see Does NOT Exist on `model_copy`).
3. **Verify the Codebase Contract** — read `agent_pool.py:244-360`, `_shared.py:92-117`, `session_state.py:1188` and `:1457-1560`, `models/base.py:763-790`.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** from the blueprint.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3121-sdd-coder-engine-dispatch.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
