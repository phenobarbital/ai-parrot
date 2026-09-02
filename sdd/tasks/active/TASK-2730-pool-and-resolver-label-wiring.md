# TASK-2730: Wire `DispatchLabels` from the dev-agent pool and the merge resolver

**Feature**: FEAT-496 — Dev-Loop Dispatch Event Legibility
**Spec**: `sdd/specs/dev-loop-dispatch-event-legibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2724, TASK-2725, TASK-2726, TASK-2727, TASK-2728
**Assigned-to**: unassigned

---

## Context

Spec §1 root cause 5, §3 Module 7, §5 AC5.

Everything up to here makes events *legible*. This task makes them
*attributable*: it is where the `TASK-<NNN>` finally enters the event stream.

`DevAgentPool._dispatch_one` (`agent_pool.py:225`) already holds every fact
the operator wants — the `TaskRef` (id, title, file), the `PoolWorker`
(worker_id, spec.agent, spec.model) — and already logs them
(`agent_pool.py:279-286`, `development.py:1180-1195`, `:1243-1250`). It just
never puts them on the wire. The pool's dispatch call
(`agent_pool.py:288-295`) passes `node_id=worker.worker_id` and nothing else
identifying.

The merge-conflict resolver (`development.py:1309-1381`) has the same gap: it
dispatches under the synthetic seat `"development.resolver"` with
`task_id="RESOLVE_MERGE_CONFLICT"` already in its brief
(`development.py:1350`) — but that never reaches an event either.

All five backends accept `labels=` once TASK-2724..2728 land; this task is the
caller side.

---

## Scope

- Build a `DispatchLabels` in `DevAgentPool._dispatch_one`
  (`agent_pool.py:225`) from the `TaskRef` and `PoolWorker`, and pass it to
  `worker.dispatcher.dispatch(...)` (`agent_pool.py:288`).
- Carry the retry/escalation attempt number into `DispatchLabels.attempt` so a
  retried task is distinguishable from its first attempt.
- Build a `DispatchLabels` for the merge-conflict resolver dispatches in
  `DevelopmentNode._resolve_conflict` (`development.py:1359`, `:1381`).
- Build a `DispatchLabels` for the single-agent (non-pool) development path
  (`development.py:493` / `:984`) so a non-pooled run is labelled too.
- Tests asserting the labels reach the dispatcher.

**NOT in scope**: the judge panel and QA node (TASK-2731); any dispatcher
internals; session state; console HTML.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py` | MODIFY | build + pass `DispatchLabels` in `_dispatch_one` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` | MODIFY | labels for the resolver seat and the single-agent path |
| `packages/ai-parrot/tests/flows/dev_loop/test_agent_pool.py` | MODIFY | assert labels forwarded per seat/task |
| `packages/ai-parrot/tests/flows/dev_loop/test_development_node.py` | MODIFY | assert resolver + single-agent labels |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# verified: agent_pool.py:47
from parrot.flows.dev_loop.task_scheduler import TaskRef
# add (created by TASK-2722):
from parrot.flows.dev_loop.models import DispatchLabels
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py
@dataclass
class PoolWorker:                                             # line 73
    worker_id: str      # "development.w1" — stable for the pool's life  # 85
    spec: DevAgentSpec                                        # line 86
    dispatcher: DevLoopCodeDispatcher                         # line 87
    profile: BaseModel                                        # line 88

_DispatchAttempt = Tuple[str, str, Optional[DevelopmentOutput],
                         Optional[str]]                       # line 69

class DevAgentPool:                                           # line 107
    async def _dispatch_one(self, task: TaskRef, worker: PoolWorker, *,
                            research: ResearchOutput, run_id: str,
                            cwd_for: Callable[[str], str],
                            escalate: bool = False,
                            session_host: Optional[Any] = None
                            ) -> _DispatchAttempt:            # line 225
        brief = TaskScopedBrief(research=research, task_id=task.id,
                                task_file=task.file)          # line 267
        # escalation profile swap when `escalate`             # lines 269-277
        # per-turn log line naming the task                   # lines 279-286
        output = await worker.dispatcher.dispatch(            # line 288
            brief=brief, profile=profile, output_model=DevelopmentOutput,
            run_id=run_id, node_id=worker.worker_id,          # line 293
            cwd=cwd_for(worker.worker_id), session_host=session_host,
        )                                                     # lines 289-295

    @staticmethod
    def _escalated_profile(worker: PoolWorker) -> BaseModel:  # line 195
    def _next_worker(self, failed_worker: PoolWorker) -> PoolWorker:  # line 177
    async def run_wave(self, tasks: List[TaskRef], *, research, run_id,
                       cwd_for, escalate=False,
                       session_host=None) -> WaveResult:      # line 371
        # round-robin assignment                              # lines 412-414
        # retry pass on _next_worker                          # lines 456-486

# packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py
class TaskRef(BaseModel):                                     # line 25
    id: str                # "TASK-1857"                      # line 33
    title: str = ""                                           # line 34
    status: str                                               # line 35
    depends_on: List[str]                                     # line 38
    file: str = ""         # "sdd/tasks/active/TASK-1857-<slug>.md"  # line 41

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py
    @staticmethod
    def _task_label(task: TaskRef) -> str                     # line 1069
    async def _resolve_conflict(self, path, description, *, pool, research,
                                run_id, session_host)         # line 1309
        brief = TaskScopedBrief(research=research,
                                task_id="RESOLVE_MERGE_CONFLICT")  # line 1350
        # dispatch with node_id="development.resolver"        # lines 1359, 1381
    # single-agent dispatch paths:                            # lines 493, 984
    # escalation flag for the QA repair loop:
    #   escalate = shared.get("qa_attempt", 1) >= 2           # ~line 1235

# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
class WorkerSummary(BaseModel):                               # line 481
    worker_id: str; agent: str; model: str                    # lines 489-491
```

### Does NOT Exist

- ~~`DevAgentSpec.model` being guaranteed non-empty~~ — an empty model means
  "the backend's own default" (see the dev-console hint text). Pass it through
  as-is; do not substitute a placeholder.
- ~~a `task_title` on `TaskScopedBrief`~~ — the brief carries `task_id` and
  `task_file` only (`agent_pool.py:267`). The title comes from `TaskRef.title`.
- ~~an existing `labels=` argument at `agent_pool.py:288`~~ — TASK-2722 adds
  it to the Protocol; TASK-2724..2728 add it to the five implementations.
- ~~a per-seat event emitted by the pool itself~~ — the pool does not publish
  events; labels ride on the dispatcher's own events. Do not add a publisher
  here.
- ~~`PoolWorker.model`~~ — the model lives on `worker.spec.model`, not on the
  worker.

---

## Implementation Notes

### In `_dispatch_one`

```python
labels = DispatchLabels(
    task_id=task.id,
    task_title=task.title,
    task_file=task.file,
    seat=worker.worker_id,
    agent=worker.spec.agent,
    model=worker.spec.model or "",
    subagent=getattr(profile, "subagent", "") or "",
    attempt=2 if escalate else 1,
)
output = await worker.dispatcher.dispatch(..., labels=labels)
```

Note `profile` here is the possibly-escalated profile computed at
`agent_pool.py:269-277`, not `worker.profile` — read the model/subagent off
the profile actually being dispatched so an escalated run reports its real
model.

### Retry attribution

`run_wave`'s retry pass (`agent_pool.py:456-486`) calls `_dispatch_one` again
on `_next_worker`. Make the retry visibly a retry — pass an explicit attempt
number rather than deriving it only from `escalate`, so the console can show
"TASK-1857 (attempt 2) on w3" instead of two indistinguishable runs.

### The resolver seat

```python
labels = DispatchLabels(
    task_id="RESOLVE_MERGE_CONFLICT",
    task_title=f"resolve merge conflict in {path}",
    seat="development.resolver",
    agent=..., model=...,
)
```

Keep the existing `node_id="development.resolver"` — do not change the seat
string; `_owning_node_id` and TASK-2729's seat projection both key off it.

### Key Constraints

- Labels are **display metadata only**. Never let a missing/empty label change
  control flow, and never let building them raise into the dispatch path —
  they are best-effort like every other telemetry surface in this feature.
- Do not change the round-robin assignment, the retry policy, or
  `WaveResult`/`WorkerSummary` shapes.
- `development.py` and `agent_pool.py` are both hot files under active
  development — keep the diff surgical.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py:279-286` — the existing per-task log line; the labels should carry the same facts.
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py:1180-1250` — the wave/task logging that already knows everything the UI is missing.

---

## Acceptance Criteria

- [ ] `_dispatch_one` passes a `DispatchLabels` whose `task_id`, `task_title`, `task_file`, `seat`, `agent` and `model` match the `TaskRef` / `PoolWorker` it was given.
- [ ] A two-seat, two-task wave forwards **different** `task_id`s to the two seats (no cross-talk).
- [ ] A retried task reports `attempt=2` and the retry worker's seat.
- [ ] An escalated dispatch reports the escalation profile's model, not the base model.
- [ ] The merge-conflict resolver dispatch carries `task_id="RESOLVE_MERGE_CONFLICT"` and `seat="development.resolver"`.
- [ ] The single-agent (non-pool) development dispatch is labelled too.
- [ ] A dispatcher that does not accept `labels` (a duck-typed test double) does not break the pool — labels are best-effort.
- [ ] Existing pool behaviour is unchanged: round-robin assignment, retry-once policy, `WaveResult` / `WorkerSummary` contents.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_agent_pool.py  (additions)

class RecordingDispatcher:
    def __init__(self): self.calls = []
    async def dispatch(self, *, brief, profile, output_model, run_id,
                       node_id, cwd, session_host=None, labels=None):
        self.calls.append((node_id, labels))
        return DevelopmentOutput(files_changed=[], ...)


class TestPoolLabelWiring:
    async def test_labels_carry_task_identity(self):
        d = RecordingDispatcher()
        pool = _pool_with(d, seats=["development.w1"])
        await pool.run_wave([TaskRef(id="TASK-1857", title="Wire the shim",
                                     status="pending", file="sdd/tasks/active/x.md")],
                            research=..., run_id="r1", cwd_for=lambda w: "/wt")
        node_id, labels = d.calls[-1]
        assert node_id == "development.w1"
        assert labels.task_id == "TASK-1857"
        assert labels.task_title == "Wire the shim"
        assert labels.seat == "development.w1"

    async def test_two_seats_get_their_own_task(self):
        """No cross-talk: w1 must never be told it is running w2's task."""
        ...
        by_seat = {n: l.task_id for n, l in d.calls}
        assert by_seat["development.w1"] != by_seat["development.w2"]

    async def test_retry_reports_attempt_two(self):
        ...
        assert d.calls[-1][1].attempt == 2

    async def test_escalated_dispatch_reports_escalation_model(self):
        ...

    async def test_dispatcher_without_labels_kwarg_still_works(self):
        """Labels are best-effort — a duck-typed double must not break."""
        ...


# packages/ai-parrot/tests/flows/dev_loop/test_development_node.py  (additions)

class TestResolverLabels:
    async def test_resolver_dispatch_is_labelled(self):
        ...
        assert labels.task_id == "RESOLVE_MERGE_CONFLICT"
        assert labels.seat == "development.resolver"

    async def test_single_agent_path_is_labelled(self):
        ...
```

---

## Agent Instructions

1. **Read the spec** — §1 root cause 5, §3 Module 7, §5 AC5.
2. **Check dependencies** — TASK-2724, 2725, 2726, 2727 and 2728 must all be in `sdd/tasks/completed/`. All five dispatchers must accept `labels=` before this lands.
3. **Verify the Codebase Contract** — re-read `agent_pool.py:225-300` and `development.py:1309-1390`; both churn.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement**. Change no control flow — labels are metadata.
6. **Verify** all acceptance criteria, the two-seat no-cross-talk one especially.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
