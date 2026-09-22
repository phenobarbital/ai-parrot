# TASK-3599: Checkpointed execution path — probe, memory activation, `PlanFlow`, honest degradation

**Feature**: FEAT-585 — Plan-then-Execute Hardening
**Spec**: `sdd/specs/plan-then-execute-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3598, TASK-3594
**Assigned-to**: unassigned

---

## Context

Second toolkit task. Implements the execution part of spec §3 **Module 6** and goals D3–D8 /
AC3 / AC5 / AC6 / AC14.

`_run_plan` (`toolkit.py:175-266`) compiles with `AgentsFlow.from_definition(..., checkpoint=False)`,
allocates `run_{hex[:8]}` ids and keeps state only in `RunRecord`. This task makes it: allocate
a full UUID run id (== flow id), probe the configured store with a bounded awaited operation
(outage ⇒ fresh execution without checkpointing; configuration error ⇒ explicit), honour
`PlanMetadata.checkpoint=False`, `await self._memory_binding.prepare()` before dispatch,
seed `ctx.shared_data[PLAN_RUN_SHARED_KEY]` with `PlanRunMetadata`, build the flow through
`build_plan_flow`, and keep soft-timeout semantics. A `CheckpointPersistenceError` after a
checkpointed run started stops dispatch and returns `checkpoint_write_failed` with observed
progress and the last acknowledged checkpoint id — never a silent downgrade to unleased
execution. The live `self._plan_runs` cache keeps a `PlanRun` per run with explicitly marked
uncheckpointed progress.

---

## Scope

- `toolkit.py`: `_probe_checkpoint_store()` (cached per instance), `_new_run_metadata(plan, source, *, checkpointed)`,
  rewrite `_run_plan` and `_execute_flow` to use `build_plan_flow`, the binding, and
  `PlanRun` cache entries; map flow-level `CheckpointPersistenceError` / `FlowLockedError` to
  `PlanRunError` codes; keep `RunRecord` maintenance for backwards compatibility of the
  legacy fallback.
- Update `test_toolkit_core.py` fixtures so `_run_plan` tests run with an explicit
  `SerializingFakeCheckpointStore` (fast, deterministic) and add a `checkpoint=False` plan case.
- Write `test_checkpointed_execution.py` (spec §4 `test_checkpoint_outage` mid-run half,
  `test_read_ceiling` through a plan run, soft-timeout envelope).

**NOT in scope**:
- `plan_resume` / `plan_repair` (TASK-3600 / TASK-3601).
- `PlanFlow` internals (TASK-3594) or resolver logic (TASK-3593).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` | MODIFY | Probe, metadata, checkpoint-aware `_run_plan`/`_execute_flow` |
| `packages/ai-parrot/tests/tools/execution_plan/test_toolkit_core.py` | MODIFY | Fixture passes a fake store; add checkpoint=False case |
| `packages/ai-parrot/tests/tools/execution_plan/test_checkpointed_execution.py` | CREATE | Probe/outage/degradation, memory activation before dispatch, write-failure mid-run |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `3028213ee` on 2026-09-21.

### Verified Imports
```python
from parrot.bots.flows.core.checkpoint import CheckpointPersistenceError, FlowLockedError, CheckpointStore   # verified: checkpoint/__init__.py:9-14
from .checkpoint import build_plan_flow, PlanFlow            # TASK-3594
from .memory import RestoreError                              # TASK-3591
from .models import PLAN_RUN_SHARED_KEY, PlanRunMetadata, PlanRun, PlanRunError   # TASK-3590
from .runs import plan_fingerprint, process_identity, project_run, register_plan_checkpoint_types   # TASK-3593
# after TASK-3598, toolkit.py already imports: CheckpointStore, get_checkpoint_store, TaskScope, PlanMemoryBinding, PlanRecoveryConfig,
# PlanRun, PlanRunError, PlanRunManifest, PlanRunSummary, PlanRecoveryEnvelope, PlanRunResolver
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py (pre-TASK-3598 line numbers; re-verify after it lands)
async def _run_plan(self, plan: ExecutionPlan, *, source: str) -> ToolResult     # :175 — run_id = f"run_{uuid.uuid4().hex[:8]}" (:190);
    # factory (:191-197); AgentsFlow.from_definition(..., checkpoint=False) (:199-212); ctx = FlowContext(initial_task=plan.objective, agent_registry=...) (:215)
    # RunRecord (:217-227); listeners (:229-231); task = asyncio.create_task(self._execute_flow(...)) (:233); asyncio.wait timeout=soft_timeout (:236)
def _make_progress_listener(self, run_id, plan_node_ids) -> Callable                  # :268 — increments RunRecord.nodes_done
async def _execute_flow(self, run_id, flow, plan, ctx, started_monotonic) -> None    # :292 — await flow.run_flow(ctx) (:304); ref synthesis (:316-345); status derivation (:352-359)
def _evict_completed_runs(self) -> None                                              # :364
# packages/ai-parrot/src/parrot/bots/flows/plan/models.py:257-265  PlanMetadata.checkpoint: bool = True; durable: bool = False
# packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/base.py:37  async def latest(self, flow_id) — the bounded probe operation
# packages/ai-parrot/src/parrot/bots/flows/core/context.py:56 FlowContext; shared_data dict attribute (used at :340)
```

### Does NOT Exist
- ~~`CheckpointStore.ping()` / `.health()`~~ — probe with `await asyncio.wait_for(store.latest("__plan_probe__"), timeout=recovery.checkpoint_probe_timeout)`; `None` is a healthy answer.
- ~~a way to mark a `PlanFlow` "degraded" after start~~ — degradation is decided **before** `build_plan_flow` (store passed as `None`); once started checkpointed, a write failure is terminal for dispatch (§2).
- ~~`RunningSummary.resume_level`~~ — use `PlanRunSummary` (TASK-3590).
- ~~`FlowContext(shared_data=...)` kwarg~~ — set `ctx.shared_data[PLAN_RUN_SHARED_KEY] = metadata.model_dump(mode="json")` after construction.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/execution_plan/test_toolkit_core.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/execution_plan/test_checkpointed_execution.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py#ExecutionPlanToolkit._run_plan",
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py#ExecutionPlanToolkit._execute_flow",
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py#ExecutionPlanToolkit._make_progress_listener",
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/models.py#PlanMetadata",
    "sym:packages/ai-parrot/src/parrot/bots/flows/core/context.py#FlowContext"
  ]
}
```

---

## Implementation Notes

### Key Constraints (spec §2 "Recovery capabilities")
- Probe once per toolkit instance per store (cache `self._store_probe: Optional[bool]`); a
  `ConnectionError`/`OSError`/`asyncio.TimeoutError` ⇒ `False` (log warning, fresh execution,
  envelope `checkpoint_enabled=False`, `recovery_reason="checkpoint_unavailable"`);
  any other exception ⇒ re-raise as `PlanRunError("checkpoint_unavailable", …)` — a
  configuration error stays explicit.
- `checkpointed = probe_ok and plan.metadata.checkpoint and self._checkpoint_store is not None`.
  With `self._checkpoint_store is None` (host configured no tier) run fresh — do **not**
  silently default to Redis; that is what the current code's comment warns about (`toolkit.py:200-211`).
- Before dispatch: `task_memory = await self._memory_binding.prepare()`; on failure return
  `PlanRunError("artifacts_unavailable", …)` and dispatch nothing.
- `artifact_mode = self._memory_binding.artifact_mode`; `process_id = process_identity()` when
  memory-mode; `scope_key = binding.scope.cache_key()`; `allowed_tools = sorted(self.allowed_tools or tool_manager.list_tools())`.
- Run id: `str(uuid.uuid4())`; `root_run_id = run_id`; `source` as before.
- `_execute_flow`: catch `CheckpointPersistenceError` ⇒ status `failed`, cache entry
  `recovery_reason="checkpoint_write_failed"`, keep observed `nodes_done`, record
  `last_checkpoint_id` from `flow._checkpointer._last_checkpoint_id` if available; catch
  `FlowLockedError` ⇒ `run_busy`. Soft-timeout return uses `PlanRunSummary` with envelope and
  `uncheckpointed_progress = not checkpointed`.
- Terminal return: `PlanRunManifest` (manifest fields + envelope + status). The `RunRecord` in
  `self._runs` is still written (legacy fallback), but `self._plan_runs[run_id]` (a `PlanRun`
  from `project_run` when checkpointed, or hand-built when not) is the resolver's cache entry.

### References in Codebase
- `toolkit.py:175-266` and `:292-362` — the two methods to rewrite; keep soft-timeout structure.
- `tests/tools/execution_plan/test_toolkit_core.py:52-55` `wm_toolkit` fixture; `:66-95` how `_run_plan` is exercised.

---

## Implementation Blueprint

### Steps (in order)
1. `_probe_checkpoint_store` — *why*: the outage-vs-configuration distinction is the whole of D6/D8 "missing Redis does not prevent fresh execution".
2. `_new_run_metadata` — *why*: one constructor for the envelope keeps fingerprint/allowlist/scope consistent between fresh runs and (later) repair children.
3. Rewrite `_run_plan` to prepare memory, seed `shared_data`, call `build_plan_flow`, and cache a `PlanRun` — *why*: the flow needs the envelope in `ctx.shared_data` BEFORE its initial checkpoint (TASK-3594 projector).
4. Rewrite `_execute_flow` error mapping — *why*: AC6/AC14 "background task errors become bounded structured results".
5. Fixture update + tests.

### `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` (MODIFY — probe + metadata)
```python
# occurrences: 1 (verified: grep -c '    async def _run_plan' packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py)
# BEFORE — insert ABOVE `    async def _run_plan(self, plan: ExecutionPlan, *, source: str) -> ToolResult:`
    async def _probe_checkpoint_store(self) -> bool:
        """Bounded, cached probe: outage → False (fresh execution); configuration error → raised."""
        if self._checkpoint_store is None:
            return False
        if getattr(self, "_store_probe", None) is not None:
            return self._store_probe
        try:
            await asyncio.wait_for(self._checkpoint_store.latest("__plan_probe__"), timeout=self.recovery.checkpoint_probe_timeout)
            self._store_probe = True
        except (ConnectionError, OSError, asyncio.TimeoutError) as exc:
            self.logger.warning("checkpoint store unreachable (%s); plan runs execute without checkpointing", exc)
            self._store_probe = False
        except Exception as exc:  # noqa: BLE001 - configuration errors stay explicit
            raise PlanRunError("checkpoint_unavailable", f"checkpoint store misconfigured: {exc}") from exc
        return self._store_probe

    def _new_run_metadata(self, plan: ExecutionPlan, *, source: str, run_id: str, checkpointed: bool) -> PlanRunMetadata:
        """Build the persisted ``plan_run`` envelope for a fresh root run."""
        allowed = sorted(self.allowed_tools) if self.allowed_tools is not None else sorted(self._tool_manager.list_tools())
        scope = self._memory_binding.scope
        mode = self._memory_binding.artifact_mode
        return PlanRunMetadata(
            run_id=run_id, root_run_id=run_id, plan=plan, original_plan=plan, source=source,
            started_at=datetime.now(timezone.utc), scope_key=scope.cache_key() if scope is not None else None,
            allowed_tools=allowed, plan_fingerprint=plan_fingerprint(plan), artifact_mode=mode,
            process_id=process_identity() if mode == "memory" else None,
            max_repair_rounds=self.recovery.max_repair_rounds,
        )
```
**Why**: `latest()` is the cheapest awaited store operation (`store/base.py:37`); timeout and
connection failures are outages, anything else is configuration.

### `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` (MODIFY — `_run_plan` core)
```python
# REPLACE toolkit.py:189-212 (run_id allocation, factory, AgentsFlow.from_definition(... checkpoint=False)) with:
        run_id = str(uuid.uuid4())
        probe_ok = await self._probe_checkpoint_store()
        checkpointed = probe_ok and plan.metadata.checkpoint
        try:
            await self._memory_binding.prepare()
        except Exception as exc:  # noqa: BLE001 - activation failure dispatches nothing (§2)
            return self._error(PlanRunError("artifacts_unavailable", f"plan memory activation failed: {exc}"), run_id=run_id)
        metadata = self._new_run_metadata(plan, source=source, run_id=run_id, checkpointed=checkpointed)
        agent_registry = self._get_agent_registry()
        flow = build_plan_flow(
            plan, run=metadata, tool_manager=self._tool_manager, working_memory=self._working_memory,
            agent_registry=agent_registry, permission_context=self.permission_context, step_mapping=self.plan_step_mapping,
            store=self._checkpoint_store if checkpointed else None, durable_store=self._durable_store if checkpointed else None,
        )
        ctx = FlowContext(initial_task=plan.objective, agent_registry=agent_registry)
        ctx.shared_data[PLAN_RUN_SHARED_KEY] = metadata.model_dump(mode="json")
        # FILL IN: keep the RunRecord/listener/task/soft-timeout code that follows (toolkit.py:215-266) but:
        #   - also store self._plan_runs[run_id] = PlanRun(metadata=metadata, status="running", checkpoint_enabled=checkpointed,
        #       resume_level=("none" if not checkpointed else "process" if metadata.artifact_mode == "memory" else "cross_restart"),
        #       resumable=False, recovery_reason=None if checkpointed else "checkpoint_unavailable")
        #   - soft-timeout return → PlanRunSummary(**envelope, plan_name=..., nodes_total=..., nodes_done=..., uncheckpointed_progress=not checkpointed)
        #   - terminal return → PlanRunManifest (manifest fields + envelope + status); error → self._error(PlanRunError(code, ...))
        # bounded by AC5 (every response declares capability) and AC14 (soft timeout never cancels).
```
**Why**: the envelope must be in `ctx.shared_data` before `run_flow` so the initial checkpoint
(TASK-3594) projects it; `store=None` when not checkpointed is what makes `build_plan_flow`
build a plain flow — no hidden Redis dependency.

### `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` (MODIFY — `_execute_flow` error mapping)
```python
# REPLACE the `except Exception as exc:` block at toolkit.py:305-312 with:
        except CheckpointPersistenceError as exc:
            self._fail_run(run_id, code="checkpoint_write_failed", message=str(exc), flow=flow)
            return
        except FlowLockedError as exc:
            self._fail_run(run_id, code="run_busy", message=str(exc), flow=flow)
            return
        except Exception as exc:  # noqa: BLE001 - recorded, never re-raised
            self._fail_run(run_id, code="flow_error", message=str(exc), flow=flow)
            return
```
```python
# BEFORE — insert ABOVE `    def _evict_completed_runs(self) -> None:` (verified: toolkit.py:364)
    def _fail_run(self, run_id: str, *, code: str, message: str, flow: Any) -> None:
        """Record a flow-level failure as data on both the legacy record and the PlanRun cache entry."""
        self.logger.error("Plan run %r failed (%s): %s", run_id, code, message[:300])
        # FILL IN: update self._runs[run_id] (status failed, finished_at, flow_error) and self._plan_runs[run_id]
        # (status "failed", recovery_reason=code, keep nodes_done, checkpoint_id=getattr(getattr(flow, "_checkpointer", None),
        # "_last_checkpoint_id", None)); then self._evict_completed_runs() — bounded by AC6 "no falsely durable terminal success".
        raise NotImplementedError
```
**Why**: §2 "If persistence fails after a checkpointed run starts, stop further dispatch and
return `checkpoint_write_failed` with observed progress and last acknowledged checkpoint ID".
The scheduler already stops on a required-barrier failure; this records it honestly.

### `packages/ai-parrot/tests/tools/execution_plan/test_toolkit_core.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    return WorkingMemoryToolkit()' packages/ai-parrot/tests/tools/execution_plan/test_toolkit_core.py)
# ADD a fixture next to `wm_toolkit` (verified: test_toolkit_core.py:52-55) and pass `checkpoint_store=fake_store` in every
# ExecutionPlanToolkit(...) construction in this file (FILL IN: mechanical edit; keep one test constructing WITHOUT a store to
# prove fresh execution with `checkpoint_store=None` still works):
@pytest.fixture
def fake_store():
    from ._recovery_fakes import SerializingFakeCheckpointStore
    return SerializingFakeCheckpointStore()
```

### `packages/ai-parrot/tests/tools/execution_plan/test_checkpointed_execution.py` (CREATE)
```python
"""FEAT-585 M6 — checkpointed execution, probe/outage degradation, write-failure mid-run."""
from __future__ import annotations
import pytest
from parrot.tools.execution_plan import ExecutionPlanToolkit, PlanRecoveryConfig
from parrot.tools.working_memory.tool import WorkingMemoryToolkit
from ._recovery_fakes import CountingToolManager, SerializingFakeCheckpointStore

pytestmark = pytest.mark.asyncio

async def test_checkpointed_run_writes_records_and_reports_capability(): ...     # put_calls >= 2; envelope checkpoint_enabled True; resume_level "process"
async def test_no_store_configured_runs_fresh_with_none_level(): ...           # checkpoint_store=None → put never called; resume_level "none", reason checkpoint_unavailable
async def test_probe_outage_degrades_and_is_cached(): ...                      # store.latest raises ConnectionError → fresh; second run does not re-probe
async def test_probe_configuration_error_is_explicit(): ...                    # store.latest raises TypeError → checkpoint_unavailable error, nothing dispatched
async def test_plan_metadata_checkpoint_false_is_honoured(): ...
async def test_memory_activation_precedes_dispatch_and_caps_reads(): ...       # wm._task_memory enabled before first dispatch; 40MB payload → raw_omitted via get_result
async def test_mid_run_write_failure_stops_dispatch(): ...                     # store.failures=[2] on a 3-node chain → checkpoint_write_failed; dispatch_counts show halt
async def test_soft_timeout_summary_carries_envelope(): ...
```

### FILL IN checklist
- [ ] `toolkit.py::_run_plan` — RunRecord + PlanRun cache + response models; AC5/AC14
- [ ] `toolkit.py::_fail_run` — body; AC6
- [ ] `test_toolkit_core.py` — fixture threading
- [ ] `test_checkpointed_execution.py` — bodies

---

## Acceptance Criteria

- [ ] AC-1 — A run with a reachable fake store writes an initial and a terminal checkpoint; its manifest response has `checkpoint_enabled=True` and `run_id == root_run_id == flow.flow_id` (UUID).
- [ ] AC-2 — `checkpoint_store=None`, a probe outage, or `PlanMetadata.checkpoint=False` each yield fresh execution with `checkpoint_enabled=False`, `resume_level="none"`, `recovery_reason="checkpoint_unavailable"`; the probe outage is cached per toolkit (AC5).
- [ ] AC-3 — A probe raising a non-connection exception returns `checkpoint_unavailable` and dispatches zero tools.
- [ ] AC-4 — `_memory_binding.prepare()` completes before the first dispatch; after the run a `get_result(include_raw=True, max_rehydrate_bytes=40_000_000)` on a large plan artifact is refused (AC10).
- [ ] AC-5 — A checkpoint write failure mid-run yields `checkpoint_write_failed` with `nodes_done` reflecting observed progress; no further nodes are dispatched (AC6).
- [ ] AC-6 — The soft-timeout `PlanRunSummary` carries the envelope and never cancels the run (AC14).
- [ ] `ruff check` clean; `test_toolkit_core.py`, `test_execute_validate.py`, `test_integration.py` pass.
- [ ] Dependency suites still pass (files created by upstream tasks, so not listed under Validation Commands): `pytest packages/ai-parrot/tests/tools/execution_plan/test_toolkit_recovery.py -q`

## Validation Commands
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_checkpointed_execution.py -q`
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_toolkit_core.py -q`
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_integration.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Read spec §2 "Recovery capabilities" (all paragraphs), "Plan memory binding", §3 Module 6, AC5/AC6/AC14.
2. Re-verify `toolkit.py` line anchors AFTER TASK-3598 landed (they shift).
3. Implement, run Validation Commands.
4. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
