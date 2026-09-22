# TASK-3598: Toolkit recovery configuration, resolver-backed `plan_status` / `plan_artifacts`, exports

**Feature**: FEAT-585 — Plan-then-Execute Hardening
**Spec**: `sdd/specs/plan-then-execute-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3592, TASK-3593
**Assigned-to**: unassigned

---

## Context

First of four sequential tasks on `tools/execution_plan/toolkit.py` (then TASK-3599
checkpointed execution, TASK-3600 `plan_resume`, TASK-3601 `plan_repair`). Implements the
configuration/resolution part of spec §3 **Module 6** and AC4 / AC5 / AC11.

`ExecutionPlanToolkit.__init__` (`toolkit.py:99`) gains the keyword-only inputs from §2 "New
Public Interfaces": `recovery`, `checkpoint_store`, `durable_store`, `task_memory_runtime`,
`scope`. Store/runtime objects are trusted host inputs and are **borrowed**; no network I/O
happens in the constructor (`get_checkpoint_store(<str>)` only constructs a client). The
toolkit builds a `PlanMemoryBinding` and a `PlanRunResolver`, and `plan_status` /
`plan_artifacts` resolve through the resolver so they work after a restart from checkpoint
metadata alone (metadata-only: zero artifact bytes). Every response carries the recovery
envelope. `unknown_run` diagnostics list at most a bounded set of locally known ids.

---

## Scope

- `toolkit.py`: new constructor kwargs + attributes (`self.recovery`, `self._checkpoint_store`,
  `self._durable_store`, `self._task_memory_runtime`, `self._scope`, `self._memory_binding`,
  `self._plan_runs: Dict[str, PlanRun]`, `self._resolver`); helper `_resolve_store(arg)`;
  `_error(exc: PlanRunError) -> ToolResult`; rewrite `plan_status` / `plan_artifacts` to
  resolve via `self._resolver.resolve(run_id)` first and fall back to the legacy
  `self._runs` record for runs that predate checkpointing in this process.
- `__init__.py`: export `PlanRecoveryConfig`, `PlanDelta`, `PlanRunManifest`, `PlanRunSummary`,
  `PlanResumeArgs`, `PlanRepairArgs`, `PlanRunError`, `PlanRunMetadata`; keep `RunRecord` /
  `RunningSummary`.
- Update `test_toolkit_core.py::test_unknown_run_id_tool_error` to assert
  `result.result["code"]` instead of the "Known:" text, and add
  `test_toolkit_recovery.py`.

**NOT in scope**:
- Changing `_run_plan` to checkpoint (TASK-3599). After this task `_run_plan` is unchanged and
  still produces legacy `RunRecord`s — the resolver falls back to them.
- `plan_resume` / `plan_repair` (TASK-3600 / TASK-3601).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` | MODIFY | Constructor kwargs, binding/resolver, resolver-backed status/artifacts, `_error` |
| `packages/ai-parrot/src/parrot/tools/execution_plan/__init__.py` | MODIFY | Export new models |
| `packages/ai-parrot/tests/tools/execution_plan/test_toolkit_core.py` | MODIFY | Unknown-run assertion uses the structured code |
| `packages/ai-parrot/tests/tools/execution_plan/test_toolkit_recovery.py` | CREATE | Constructor/borrowing, envelope on status/artifacts, tier classification through the toolkit |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `3028213ee` on 2026-09-21.

### Verified Imports
```python
# toolkit.py already imports (lines 21-47): asyncio, time, uuid, datetime/timezone, Path, typing names, FlowContext, AgentsFlow,
# ArtifactRef/ExecutionPlan/PlanToolNode/build_manifest/ensure_tool_node_registered/make_tool_node_factory/to_flow_definition,
# AgentRegistry, tool_schema, AbstractToolkit, ToolResult, build_catalog/validate_with_allowlist, models (PlanArtifactsArgs, PlanExecuteArgs,
# PlanStatusArgs, PlanValidateArgs, RunningSummary, RunRecord), PlanAuthoringError/PlanPlanner, PlanFileStore/PlanLoadError
from parrot.bots.flows.core.checkpoint import CheckpointStore, get_checkpoint_store   # verified: checkpoint/__init__.py:25-30
from parrot.tools.working_memory.task_memory.config import TaskMemoryRuntime           # verified: config.py:406 (TYPE_CHECKING is enough)
from parrot.tools.working_memory.task_memory.models import TaskScope                   # verified: models.py:571
from .memory import PlanMemoryBinding                                                  # TASK-3592
from .models import PlanRecoveryConfig, PlanRun, PlanRunError, PlanRunManifest, PlanRunSummary, PlanRecoveryEnvelope  # TASK-3590
from .runs import PlanRunResolver, process_identity                                    # TASK-3593
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py
class ExecutionPlanToolkit(AbstractToolkit):                       # :62
    def __init__(self, *, tool_manager, working_memory, planner_llm=None, plans_dir=None, allowed_tools=None, soft_timeout=60.0,
                 permission_context=None, on_node_event=None, max_completed_runs=50, plan_step_mapping=None, **kwargs)   # :99-111
        self._runs: Dict[str, RunRecord] = {} (:157); self._run_tasks (:159); self._run_contexts (:160); self._agent_registry (:164)
    @tool_schema(PlanStatusArgs) async def plan_status(self, run_id: str) -> ToolResult        # :387-408 — "Unknown run_id … Known: …" error text at :395
    @tool_schema(PlanArtifactsArgs) async def plan_artifacts(self, run_id: str) -> ToolResult  # :410-433
    # ── Agent-facing tools ── header at :385
# packages/ai-parrot/src/parrot/tools/execution_plan/__init__.py:14-21 models import block; __all__ :26-44 (alphabetical tuple)
# packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/factory.py:41
def get_checkpoint_store(arg: str | CheckpointStore | None = None) -> CheckpointStore   # instance → as-is; str → registry; None → env/redis
# tests: packages/ai-parrot/tests/tools/execution_plan/test_toolkit_core.py:282-292 test_unknown_run_id_tool_error asserts "does-not-exist" in result.error
```

### Does NOT Exist
- ~~`ExecutionPlanToolkit.recovery` / `._resolver` / `._memory_binding`~~ — new attributes in this task.
- ~~`get_checkpoint_store()` returning `None`~~ — with `None` it resolves to env/`"redis"` and constructs a Redis client object; to mean "no store", keep `self._checkpoint_store = None` when the constructor arg is `None` **and** decide the default at first use (TASK-3599's probe). In THIS task: `None` → `None`, `str`/instance → `get_checkpoint_store(arg)`.
- ~~a toolkit `close()`/`cleanup()` override~~ — `AbstractToolkit.cleanup` exists (`toolkit.py:382`); you add `async def cleanup(self)` that awaits `self._memory_binding.close()` then `await super().cleanup()`; borrowed stores are NOT closed.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/tools/execution_plan/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/execution_plan/test_toolkit_core.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/execution_plan/test_toolkit_recovery.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py#ExecutionPlanToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py#ExecutionPlanToolkit.plan_status",
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py#ExecutionPlanToolkit.plan_artifacts",
    "sym:packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/factory.py#get_checkpoint_store",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit.cleanup"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `recovery=None` ⇒ `PlanRecoveryConfig()` (defaults of §8 D1). A durable runtime supplied
  without `scope` is a `ValueError` at construction (delegated to `PlanMemoryBinding.__init__`).
- No awaits, no connections in `__init__`. `get_checkpoint_store("redis")` constructs a client
  lazily — acceptable; probing is TASK-3599.
- `plan_status` for a resolved `PlanRun`: `status == "running"` → `PlanRunSummary` (with
  `uncheckpointed_progress` when merged from cache); terminal → `PlanRunManifest` built from
  `build_manifest(run.metadata.plan, run.refs)` fields + envelope + `status`.
- `plan_artifacts` returns `{"run_id", "artifacts": [ref.model_dump()...], **envelope}` — from
  `run.refs`; **no** `restore()`/`aget()` call (AC13 metadata-only).
- Legacy fallback: if the resolver raises `unknown_run`/`missing_or_expired`/`checkpoint_unavailable`
  and `run_id in self._runs`, answer from the `RunRecord` with an envelope of
  `checkpoint_enabled=False, resume_level="none", resumable=False, recovery_reason="checkpoint_unavailable"`.
- `unknown_run` error: `result["known_run_ids"] = sorted(self._plan_runs | self._runs)[:20]`.

### References in Codebase
- `toolkit.py:387-433` — the two methods being rewritten.
- `toolkit.py:54-59` `_StructuralError` — the exception-at-boundary pattern `PlanRunError` follows.

---

## Implementation Blueprint

### Steps (in order)
1. Constructor kwargs + attributes + `_resolve_store` — *why*: everything downstream reads them.
2. `_envelope_for(run)` / `_legacy_envelope(record)` / `_error(exc)` helpers — *why*: AC5 says *every* response declares capability; helpers make that mechanical.
3. Rewrite `plan_status` / `plan_artifacts` — *why*: they must work from checkpoint metadata alone after restart (AC4).
4. Exports, test update, new tests.

### `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` (MODIFY — constructor)
```python
# occurrences: 1 (verified: grep -c '        plan_step_mapping: Optional\[Mapping\[str, str\]\] = None,' packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py)
# AFTER — insert below `        plan_step_mapping: Optional[Mapping[str, str]] = None,` (verified: toolkit.py:110), before `**kwargs`
        recovery: Optional[PlanRecoveryConfig] = None,
        checkpoint_store: Union["CheckpointStore", str, None] = None,
        durable_store: Union["CheckpointStore", str, None] = None,
        task_memory_runtime: Optional["TaskMemoryRuntime"] = None,
        scope: Optional[TaskScope] = None,
```
```python
# occurrences: 1 (verified: grep -c '        self._agent_registry: Optional\[AgentRegistry\] = None' packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py)
# AFTER — insert below `        self._agent_registry: Optional[AgentRegistry] = None` (verified: toolkit.py:164)
        # FEAT-585 recovery wiring — trusted host inputs, borrowed, no I/O here.
        self.recovery: PlanRecoveryConfig = recovery or PlanRecoveryConfig()
        self._checkpoint_store: Optional[CheckpointStore] = self._resolve_store(checkpoint_store)
        self._durable_store: Optional[CheckpointStore] = self._resolve_store(durable_store)
        self._task_memory_runtime = task_memory_runtime
        self._scope: Optional[TaskScope] = scope
        self._memory_binding = PlanMemoryBinding(
            working_memory, runtime=task_memory_runtime, scope=scope, max_restore_bytes=self.recovery.max_restore_bytes
        )
        self._plan_runs: Dict[str, PlanRun] = {}          # live cache of checkpoint-derived runs (bounded like _runs)
        self._resolver = PlanRunResolver(
            store=self._checkpoint_store, durable_store=self._durable_store, scope=scope, cache=self._plan_runs
        )
```
**Why**: §2 "New Public Interfaces" verbatim; `None` recovery selects D1 defaults; the binding
raises for runtime-without-scope at construction, which is the earliest honest moment.

### `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` (MODIFY — helpers)
```python
# occurrences: 1 (verified: grep -c '    def _get_agent_registry' packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py)
# BEFORE — insert ABOVE `    def _get_agent_registry(self) -> AgentRegistry:` (verified: toolkit.py:169)
    @staticmethod
    def _resolve_store(arg: Union["CheckpointStore", str, None]) -> Optional[CheckpointStore]:
        """``None`` stays ``None`` (no tier configured); a name or instance resolves via the factory."""
        return None if arg is None else get_checkpoint_store(arg)

    def _legacy_envelope(self, record: RunRecord) -> PlanRecoveryEnvelope:
        """Envelope for a pre-checkpoint RunRecord: honest 'none' capability."""
        return PlanRecoveryEnvelope(run_id=record.run_id, root_run_id=record.run_id, checkpoint_enabled=False,
                                    artifact_mode=self._memory_binding.artifact_mode, resume_level="none", resumable=False,
                                    recovery_reason="checkpoint_unavailable", max_repair_rounds=self.recovery.max_repair_rounds)

    def _error(self, exc: PlanRunError, *, run_id: Optional[str] = None) -> ToolResult:
        """Map a PlanRunError to the §2 ToolResult error shape, adding bounded diagnostics."""
        result = exc.to_tool_result()
        if exc.code == "unknown_run" and isinstance(result.result, dict):
            result.result["known_run_ids"] = sorted(set(self._plan_runs) | set(self._runs))[:20]
        self.logger.info("plan run error code=%s run_id=%s", exc.code, run_id)
        return result

    async def _resolve_or_legacy(self, run_id: str) -> "tuple[Optional[PlanRun], Optional[RunRecord]]":
        """Resolve through the checkpoint authority; fall back to a same-process legacy record."""
        try:
            return await self._resolver.resolve(run_id), None
        except PlanRunError as exc:
            record = self._runs.get(run_id)
            if record is not None and exc.code in ("unknown_run", "missing_or_expired", "checkpoint_unavailable"):
                return None, record
            raise

    async def cleanup(self) -> None:
        """Close owned plan-memory resources; borrowed stores/runtimes are left open."""
        await self._memory_binding.close()
        await super().cleanup()
```
**Why**: one resolution path for all four run tools (§2 "All four run operations … resolve
through the same service"); the legacy branch keeps in-process runs answerable until
TASK-3599 makes `_run_plan` checkpoint-aware.

### `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` (MODIFY — status/artifacts)
```python
# occurrences: 1 each (verified: grep -c '    async def plan_status' / '    async def plan_artifacts' → 1)
# REPLACE the bodies of plan_status (toolkit.py:388-408) and plan_artifacts (:411-433), keeping decorators and docstrings:
        try:
            run, record = await self._resolve_or_legacy(run_id)
        except PlanRunError as exc:
            return self._error(exc, run_id=run_id)
        if record is not None:
            # FILL IN: legacy path — reproduce the old RunningSummary/manifest response but wrapped as
            # PlanRunSummary / PlanRunManifest with self._legacy_envelope(record) — bounded by AC5 and AC11.
            raise NotImplementedError
        envelope = self._resolver.envelope(run)
        # FILL IN (plan_status): running → PlanRunSummary(**envelope.model_dump(), plan_name=..., nodes_total=len(plan.nodes),
        #   nodes_done=run.nodes_done, uncheckpointed_progress=...); terminal → PlanRunManifest(**build_manifest(...).model_dump(),
        #   **envelope.model_dump(), status=run.status). Return ToolResult(status="success", result=model.model_dump(mode="json")).
        # FILL IN (plan_artifacts): {"run_id": run_id, "artifacts": [r.model_dump(mode="json") for r in run.refs], **envelope.model_dump(mode="json")}
        raise NotImplementedError
```
**Why**: AC4 "Status and artifacts reconstruct after process loss without a second persisted
RunRecord/manifest"; AC13 "Metadata-only reads load zero artifact payload bytes".

### `packages/ai-parrot/src/parrot/tools/execution_plan/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    RunRecord,$' packages/ai-parrot/src/parrot/tools/execution_plan/__init__.py)
# AFTER — insert below `    RunRecord,` inside the `from .models import (` block (verified: __init__.py:20); then add each name to __all__ alphabetically
    PlanDelta,
    PlanRecoveryConfig,
    PlanRepairArgs,
    PlanResumeArgs,
    PlanRunError,
    PlanRunManifest,
    PlanRunMetadata,
    PlanRunSummary,
```

### `packages/ai-parrot/tests/tools/execution_plan/test_toolkit_core.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        assert "does-not-exist" in result.error' packages/ai-parrot/tests/tools/execution_plan/test_toolkit_core.py)
# REPLACE that line (verified: test_toolkit_core.py:292) with:
        assert result.result["code"] in ("unknown_run", "missing_or_expired", "checkpoint_unavailable")
        assert "does-not-exist" in result.error
```

### `packages/ai-parrot/tests/tools/execution_plan/test_toolkit_recovery.py` (CREATE)
```python
"""FEAT-585 M6 — recovery configuration and resolver-backed status/artifacts."""
from __future__ import annotations
import pytest
from parrot.tools.execution_plan import ExecutionPlanToolkit, PlanRecoveryConfig
from parrot.tools.working_memory.tool import WorkingMemoryToolkit
from ._recovery_fakes import CountingToolManager, SerializingFakeCheckpointStore

pytestmark = pytest.mark.asyncio

async def test_defaults_select_d1_policy(): ...                        # recovery.max_repair_rounds == 2; stores None
async def test_store_instances_are_borrowed_and_not_closed_on_cleanup(): ...
async def test_runtime_without_scope_is_configuration_error(): ...    # ValueError at construction
async def test_status_and_artifacts_from_checkpoint_only(): ...       # seed a checkpoint by hand into the fake store (no _run_plan);
                                                                      # plan_status → manifest with envelope; plan_artifacts → refs + envelope; no restore
async def test_unknown_vs_missing_by_tier(): ...                      # durable configured → unknown_run (+known_run_ids); ephemeral only → missing_or_expired
async def test_legacy_in_process_run_still_answers(): ...             # _run_plan (unchanged) then plan_status → envelope resume_level "none"
async def test_new_exports(): ...                                     # from parrot.tools.execution_plan import PlanDelta, PlanRunManifest, ...
```

### FILL IN checklist
- [ ] `toolkit.py::plan_status` / `plan_artifacts` bodies — bounded by AC4, AC5, AC13
- [ ] legacy branch responses — AC11
- [ ] `__all__` in `__init__.py`
- [ ] `test_toolkit_recovery.py` bodies

---

## Acceptance Criteria

- [ ] AC-1 — Constructor accepts the five new kwargs; `recovery=None` yields `max_repair_rounds == 2`; no network call occurs (fake stores never receive a call at construction).
- [ ] AC-2 — With a checkpoint seeded into `SerializingFakeCheckpointStore` and NO in-process record, `plan_status` returns a `PlanRunManifest`-shaped dict with `resume_level`, `resumable`, `recovery_reason`, `root_run_id`; `plan_artifacts` returns the refs plus the same envelope; the artifact store receives zero `load_payload` calls (AC4, AC5, AC13).
- [ ] AC-3 — Durable tier configured + unknown id ⇒ `result["code"] == "unknown_run"` with `known_run_ids`; ephemeral-only ⇒ `missing_or_expired`; no tiers ⇒ `checkpoint_unavailable` (AC16).
- [ ] AC-4 — A legacy in-process run (via the unchanged `_run_plan`) still answers `plan_status`/`plan_artifacts`, with `checkpoint_enabled=False`, `resume_level="none"` (AC11).
- [ ] AC-5 — `cleanup()` does not close a borrowed store or runtime.
- [ ] `ruff check` clean; existing `test_toolkit_core.py`, `test_execute_validate.py`, `test_integration.py` pass.

## Validation Commands
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_toolkit_recovery.py -q`
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_toolkit_core.py -q`
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_execute_validate.py -q`
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_integration.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Read spec §2 "New Public Interfaces", "Recovery capabilities" (table), §8 D3, §3 Module 6.
2. Verify anchors, implement, run Validation Commands.
3. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
