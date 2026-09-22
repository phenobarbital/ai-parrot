# TASK-3592: PlanMemoryBinding and the private plan-only activation hook

**Feature**: FEAT-585 — Plan-then-Execute Hardening
**Spec**: `sdd/specs/plan-then-execute-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3591
**Assigned-to**: unassigned

---

## Context

Implements the binding half of spec §3 **Module 2** and goals D6–D8 / AC10 / AC11.

Today the example plan wiring uses a bare `WorkingMemoryToolkit()` (no `task_memory`), so
`_resolve_raw_budget` (`tools/working_memory/tool.py:274`) has no config and accepts any
requested byte budget (finding R3). This task prepares a **real** `TaskMemory` +
`TaskMemoryConfig` for plan use only — reusing a host-supplied, already-started
`TaskMemoryRuntime` + trusted `TaskScope` when given, otherwise owning an in-memory runtime
with a synthesized process-local scope — and installs it into the shared
`WorkingMemoryToolkit` through a **private** hook that also refreshes the already-generated
`wm_get_result` wrapper's `args_schema`. The global default of `WorkingMemoryToolkit`
(FEAT-538 AC13) is not inverted: a standalone toolkit nobody activates stays disabled.

---

## Scope

- Append `PlanMemoryBinding` to `packages/ai-parrot/src/parrot/tools/execution_plan/memory.py`
  (`__init__`, `prepare()`, `restore(refs)`, `close()`, `scope` / `artifact_mode` /
  `resume_level_hint` properties, `synthesize_process_scope(session_id)` helper).
- Add `WorkingMemoryToolkit._enable_plan_memory(task_memory, catalog)` to
  `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`: swap `_task_memory` +
  `_catalog`, remove `TASK_TOOL_METHODS` from the instance `exclude_tools`, and set
  `tool.args_schema = EnabledGetResultInput` on cached `get_result` wrappers. Underscore
  name ⇒ never LLM-exposed (`_generate_tools` skips `_`-prefixed names, `toolkit.py:544`).
- Write `packages/ai-parrot/tests/tools/execution_plan/test_plan_memory.py`
  (spec §4 `test_plan_memory_activation`, `test_read_ceiling`, `test_existing_wrapper_schema`).

**NOT in scope**:
- Constructing the binding from `ExecutionPlanToolkit` (TASK-3598) or calling `prepare()` before dispatch (TASK-3599).
- Changing `_resolve_raw_budget`, `_apply_raw_policy`, `EnabledGetResultInput` or any raw-policy default.
- The catalog subclass itself (TASK-3591).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/execution_plan/memory.py` | MODIFY | Append `PlanMemoryBinding` + `synthesize_process_scope` |
| `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` | MODIFY | Add private `_enable_plan_memory` |
| `packages/ai-parrot/tests/tools/execution_plan/test_plan_memory.py` | CREATE | Activation, ceiling and wrapper-schema tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `3028213ee` on 2026-09-21.

### Verified Imports
```python
from parrot.tools.execution_plan.memory import PlanWorkingMemoryCatalog, RestoreError   # created by TASK-3591
from parrot.tools.working_memory.tool import WorkingMemoryToolkit                        # verified: tool.py:47
from parrot.tools.working_memory.models import EnabledGetResultInput, GetResultInput    # verified: imported at tool.py:18-19
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig, TaskMemoryRuntime  # verified: config.py:57, :406
from parrot.tools.working_memory.task_memory.tools import TaskMemory                    # verified: tools.py:105
from parrot.tools.working_memory.task_memory.models import TaskScope, EvidenceRef       # verified: models.py:571, :619
from parrot.bots.flows.plan import ArtifactRef                                          # verified: plan/__init__.py:23
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/working_memory/tool.py
class WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit):     # :47
    def __init__(self, session_id=None, max_rows=10, max_cols=30, tool_locals_registry=None,
                 answer_memory=None, thread_offload_cells=None, task_memory=None, **kwargs)   # :106
        self._task_memory: Optional[Any] = task_memory                  # :144
        if task_memory is None:
            self.exclude_tools = (*type(self).exclude_tools, *TASK_TOOL_METHODS)   # :153 — instance-level hide
        self._catalog = WorkingMemoryCatalog(session_id=session_id, backend=getattr(task_memory,"artifacts",None),
                                             scope=getattr(task_memory,"scope",None), task_id=getattr(task_memory,"task_id",None))  # :155-160
        self._answer_memory = answer_memory                             # :165
    def _generate_tools(self) -> None:                                  # :170-189
        super()._generate_tools()
        if not self._catalog.is_enabled: return
        for tool in self._tool_cache.values():
            if getattr(tool, "_method_name", "") == "get_result":
                tool.args_schema = EnabledGetResultInput                # :189 — the swap you must repeat post-activation
    DEFAULT_MAX_REHYDRATE_BYTES: int = 2_000_000                        # :272
    def _resolve_raw_budget(self, requested: Optional[int]) -> int:     # :274 — config None → accepts `requested` unclamped
        config = getattr(self._task_memory, "config", None)             # :287
        return config.resolve_rehydrate_bytes(requested)                # :290

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):            # :206
    exclude_tools: tuple[str, ...] = ()            # :243
    self._tool_cache: dict[str, ToolkitTool] = {}  # :354
    def _generate_tools(self) -> None              # :539 — skips names starting with "_" (:544) and exclude_tools (:556)

# packages/ai-parrot/src/parrot/tools/working_memory/task_memory/config.py
class TaskMemoryConfig(BaseModel): enabled: bool = False (:122); durable: bool = False (:123);
                                   max_rehydrate_bytes: int = Field(default=2_000_000, ge=0) (:131)
    def resolve_rehydrate_bytes(self, requested: Optional[int]) -> int   # :263 — hard clamp; 0 disables
class TaskMemoryRuntime:                                                # :406
    def __init__(self, config: TaskMemoryConfig, *, file_manager=None, association=None, pool=None, archive=None)  # :432
    is_running -> bool (:462); async def start(self, *, start_scheduler: bool = True) -> TaskMemoryRuntime (:466)
    def _build_in_memory(self) -> None  # :560 — InMemoryTaskMemoryStore + InMemoryArtifactStore
    def task_memory(self, scope: Any, **kwargs) -> TaskMemory   # :628 — raises DurableStartupError if not started
    async def stop(self) -> None        # :648 — closes only what it owns

# packages/ai-parrot/src/parrot/tools/working_memory/task_memory/tools.py:127
class TaskMemory.__init__(self, store, artifacts, scope: TaskScope, config: Optional[TaskMemoryConfig] = None, *, association=None, cache=None, omission_store=None)
    self.store; self.artifacts; self.scope; self.config   # :141-144
```

### Does NOT Exist
- ~~`WorkingMemoryToolkit.enable_task_memory()` / `.attach()` / any public activation API~~ — you add the private `_enable_plan_memory` only.
- ~~`WorkingMemoryCatalog.migrate_to(backend)`~~ — migration is: read old `_store` entries, `await new_catalog.aput_generic(...)` each, then swap.
- ~~`TaskMemoryRuntime.from_memory()`~~ — build with `TaskMemoryRuntime(TaskMemoryConfig(enabled=True, durable=False))` then `await runtime.start(start_scheduler=False)`.
- ~~`TaskMemoryRuntime.scope`~~ — the runtime has no scope; the host passes `TaskScope` separately.
- ~~`WorkingMemoryToolkit.session_id`~~ — the session id lives on `self._catalog.session_id`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/execution_plan/memory.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/tools/working_memory/tool.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/execution_plan/test_plan_memory.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/working_memory/tool.py#WorkingMemoryToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/working_memory/tool.py#WorkingMemoryToolkit._generate_tools",
    "sym:packages/ai-parrot/src/parrot/tools/working_memory/tool.py#WorkingMemoryToolkit._resolve_raw_budget",
    "sym:packages/ai-parrot/src/parrot/tools/working_memory/task_memory/config.py#TaskMemoryRuntime",
    "sym:packages/ai-parrot/src/parrot/tools/working_memory/task_memory/config.py#TaskMemoryConfig",
    "sym:packages/ai-parrot/src/parrot/tools/working_memory/task_memory/tools.py#TaskMemory"
  ]
}
```

---

## Implementation Notes

### Key Constraints (from spec §2 "Plan memory binding")
- Preserve a supplied enabled composition root: if `working_memory._task_memory` is already
  set, `prepare()` reuses it (and its scope) — never build a second backend beside it.
- Host-supplied runtime + scope ⇒ durable-capable, borrowed (never closed by `close()`).
  Runtime supplied **without** scope ⇒ `ValueError` (configuration error). Unbound ⇒ own an
  in-memory runtime (`enabled=True, durable=False`) and synthesize
  `TaskScope(chatbot_id="execution-plan", user_id=<process nonce>, session_id=catalog.session_id)`,
  cached per `WorkingMemoryToolkit` instance (`_plan_scope` attribute) so runs sharing the
  memory share the scope.
- `prepare()` is idempotent and serialized by an `asyncio.Lock`. Migration: for every
  existing local entry, `await new_catalog.aput_generic(...)`; on ANY failure keep the old
  `_catalog`, raise, dispatch nothing. Only after success call `_enable_plan_memory`.
- `_enable_plan_memory` must preserve `_answer_memory`, `_tool_locals`, session id; it
  updates cached `get_result` wrappers in place (identity preserved) and lets newly
  generated ones pick the enabled schema via the existing `_generate_tools` branch.
- `restore(refs)`: for each `ArtifactRef`, `zip(ref.keys, ref.versions)` (cardinality must
  match, else `RestoreError("checkpoint_invalid", …)`), accumulate `byte_size` against
  `max_restore_bytes`, call `catalog.restore_version(key, EvidenceRef.parse(v), max_bytes=remaining)`.
- `artifact_mode` is `"durable"` iff the bound config has `durable=True`; `resume_level_hint`
  is `"cross_restart"` only for durable + host-supplied scope, else `"process"`.

### References in Codebase
- `tool.py:170-189` — the exact wrapper-swap loop to reuse.
- `agent.py:186-188` — how a bot starts a runtime (`await runtime.start()`).
- `tests/tools/working_memory/task_memory/test_enabled_working_memory.py` — enabled-toolkit fixtures.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_enable_plan_memory` to `tool.py` — *why*: the binding needs a single swap point that owns the toolkit's private attributes; doing it from outside the class would fork the invariants `__init__` maintains.
2. Append `synthesize_process_scope` and `PlanMemoryBinding` to `memory.py` — *why*: TASK-3591 created the file; the binding composes its catalog.
3. Tests: activation atomicity, ceiling through a wrapper obtained **before** activation, standalone unchanged — *why*: AC10 is literally "wrappers registered both before and after activation".

### `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    def from_runtime' packages/ai-parrot/src/parrot/tools/working_memory/tool.py)
# BEFORE — insert ABOVE the `@classmethod` decorating `def from_runtime(cls, runtime, scope, **kwargs)` (verified: tool.py:191-192)
    async def _enable_plan_memory(self, task_memory: Any, catalog: Any) -> None:
        """Install a prepared plan-only task memory and catalog (FEAT-585 M2, private).

        Underscore-prefixed on purpose: ``_generate_tools`` never exposes it as an
        LLM tool. Preserves ``_answer_memory``, ``_tool_locals`` and the session id;
        refreshes already-generated ``get_result`` wrappers in place so a wrapper the
        agent obtained before activation enforces the enabled raw-read ceiling (AC10).

        Args:
            task_memory: A ``TaskMemory`` whose ``config.enabled`` is True.
            catalog: An enabled ``WorkingMemoryCatalog`` (or subclass) already
                holding every migrated entry.
        """
        if not getattr(getattr(task_memory, "config", None), "enabled", False):
            raise ValueError("_enable_plan_memory requires a TaskMemory with config.enabled=True")
        if not getattr(catalog, "is_enabled", False):
            raise ValueError("_enable_plan_memory requires an enabled catalog")
        self._task_memory = task_memory
        self._catalog = catalog
        self.exclude_tools = tuple(name for name in self.exclude_tools if name not in TASK_TOOL_METHODS)
        for tool in self._tool_cache.values():
            if getattr(tool, "_method_name", "") == "get_result":
                tool.args_schema = EnabledGetResultInput
        self.logger.debug("plan memory enabled on WorkingMemoryToolkit session=%s", self._catalog.session_id)
```
**Why**: mirrors `__init__` (`:144-160`) and `_generate_tools` (`:186-189`) exactly, in the
opposite direction. `TASK_TOOL_METHODS` and `EnabledGetResultInput` are already imported in
this module (`:18`, and the tuple used at `:153`).

### `packages/ai-parrot/src/parrot/tools/execution_plan/memory.py` (MODIFY — append)
```python
# occurrences: 1 (verified: grep -c '^class PlanWorkingMemoryCatalog' packages/ai-parrot/src/parrot/tools/execution_plan/memory.py)
# AFTER — append at END OF FILE, below PlanWorkingMemoryCatalog; extend __all__ with the two new names
def synthesize_process_scope(session_id: str) -> TaskScope:
    """Process-local namespace for legacy wiring — NOT user authentication (spec §2)."""
    return TaskScope(chatbot_id="execution-plan", user_id=f"proc-{os.getpid()}-{uuid.uuid4().hex[:8]}", session_id=session_id)


class PlanMemoryBinding:
    """Own plan-only memory preparation and borrowed/owned resource lifetimes."""

    def __init__(self, working_memory: "WorkingMemoryToolkit", *, runtime: Optional[TaskMemoryRuntime],
                 scope: Optional[TaskScope], max_restore_bytes: int) -> None:
        """Prepare configuration without I/O; retain supplied scope and runtime."""
        if runtime is not None and scope is None and getattr(working_memory, "_task_memory", None) is None:
            raise ValueError("a host-supplied TaskMemoryRuntime requires a trusted TaskScope")
        self._wm = working_memory
        self._runtime = runtime
        self._owns_runtime = runtime is None and getattr(working_memory, "_task_memory", None) is None
        self._scope = scope
        self._max_restore_bytes = max_restore_bytes
        self._restored_bytes = 0
        self._lock = asyncio.Lock()
        self._task_memory: Optional[TaskMemory] = None
        self._catalog: Optional[PlanWorkingMemoryCatalog] = None
        self.logger = logging.getLogger(f"{__name__}.PlanMemoryBinding")

    @property
    def scope(self) -> Optional[TaskScope]:
        """Trusted scope in force after ``prepare()``."""
        return self._scope

    @property
    def artifact_mode(self) -> str:
        """``"durable"`` when the bound config is durable, else ``"memory"``."""
        config = getattr(self._task_memory, "config", None)
        return "durable" if getattr(config, "durable", False) else "memory"

    async def prepare(self) -> TaskMemory:
        """Enable plan memory atomically; retain legacy state on migration failure."""
        async with self._lock:
            if self._task_memory is not None:
                return self._task_memory
            existing = getattr(self._wm, "_task_memory", None)
            # FILL IN: (a) existing → reuse it and its scope (already enabled; no migration);
            # (b) host runtime + scope → task_memory = runtime.task_memory(scope);
            # (c) unbound → self._runtime = TaskMemoryRuntime(TaskMemoryConfig(enabled=True, durable=False));
            #     await start(start_scheduler=False); scope = getattr(self._wm, "_plan_scope", None) or
            #     synthesize_process_scope(self._wm._catalog.session_id) cached on self._wm._plan_scope.
            # Then build PlanWorkingMemoryCatalog(session_id=self._wm._catalog.session_id,
            # backend=task_memory.artifacts, scope=scope, task_id=None), migrate every entry of
            # self._wm._catalog._store via await catalog.aput_generic(...), and ONLY on success
            # await self._wm._enable_plan_memory(task_memory, catalog) — bounded by "on failure,
            # preserve the old catalog and dispatch nothing" (raise the original exception).
            raise NotImplementedError

    async def restore(self, refs: Sequence[ArtifactRef]) -> None:
        """Restore authorized exact versions within budget, without allocating versions."""
        if self._catalog is None:
            raise RestoreError("artifacts_unavailable", "plan memory is not prepared")
        for ref in refs:
            if len(ref.keys) != len(ref.versions):
                raise RestoreError("checkpoint_invalid", f"node {ref.node_id!r}: keys/versions cardinality mismatch")
            for key, version in zip(ref.keys, ref.versions):
                remaining = self._max_restore_bytes - self._restored_bytes
                if remaining <= 0:
                    raise RestoreError("restore_budget_exceeded", f"max_restore_bytes={self._max_restore_bytes} exhausted")
                # FILL IN: await self._catalog.restore_version(key, EvidenceRef.parse(version), max_bytes=remaining)
                # and add the descriptor byte_size to self._restored_bytes — bounded by AC13.
                raise NotImplementedError

    async def close(self) -> None:
        """Close only owned runtime resources after in-flight operations finish."""
        async with self._lock:
            if self._owns_runtime and self._runtime is not None:
                await self._runtime.stop()
```
**Why this shape**: the three constructor cases of §2 are decided at `prepare()` time, not
in the constructor (no I/O in constructors — §2 "No network I/O occurs in the toolkit
constructor" applies transitively). Add `import os, uuid` and
`from typing import Sequence`, `from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig, TaskMemoryRuntime`,
`from parrot.tools.working_memory.task_memory.tools import TaskMemory`,
`from parrot.bots.flows.plan import ArtifactRef` at the top of `memory.py`, and a
`TYPE_CHECKING` import of `WorkingMemoryToolkit`.

### FILL IN checklist
- [ ] `memory.py::PlanMemoryBinding.prepare` — the three binding cases + atomic migration; bounded by §2 activation paragraph
- [ ] `memory.py::PlanMemoryBinding.restore` — per-key restore + byte accounting; AC13
- [ ] `test_plan_memory.py` — test bodies below

---

## Acceptance Criteria

- [ ] AC-1 — `prepare()` on a bare `WorkingMemoryToolkit` with pre-existing entries keeps every entry readable, sets `_task_memory.config.enabled is True`, and returns the same `TaskMemory` on a second call.
- [ ] AC-2 — When migration fails (backend `put` raising), `_catalog` is the ORIGINAL object and `_task_memory` is still `None`.
- [ ] AC-3 — A `get_result` wrapper obtained BEFORE `prepare()` has `args_schema is EnabledGetResultInput` afterwards; a standalone toolkit never prepared keeps `GetResultInput` (AC11 / FEAT-538 AC13).
- [ ] AC-4 — After activation, `get_result(include_raw=True, max_rehydrate_bytes=40_000_000)` on a ~40 MB JSON value returns `raw_omitted` and `raw_policy.max_rehydrate_bytes == 2_000_000`; `max_rehydrate_bytes=0` disables raw (AC10).
- [ ] AC-5 — A host-supplied runtime without scope raises `ValueError`; a host runtime is not stopped by `close()`; an owned one is.
- [ ] `ruff check` clean.
- [ ] Dependency suites still pass (files created by upstream tasks, so not listed under Validation Commands): `pytest packages/ai-parrot/tests/tools/execution_plan/test_plan_memory_restore.py -q`

## Validation Commands
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_plan_memory.py -q`
- `pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_disabled_compatibility.py -q`
- `pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_enabled_working_memory.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/execution_plan/test_plan_memory.py
import pytest
from parrot.tools.execution_plan.memory import PlanMemoryBinding
from parrot.tools.working_memory.models import EnabledGetResultInput, GetResultInput
from parrot.tools.working_memory.tool import WorkingMemoryToolkit

pytestmark = pytest.mark.asyncio

async def test_activation_keeps_existing_entries_and_is_idempotent(): ...     # AC-1
async def test_activation_failure_preserves_legacy_catalog(): ...             # AC-2 (monkeypatch InMemoryArtifactStore.put)
async def test_pre_registered_wrapper_gets_enabled_schema(): ...              # AC-3
async def test_standalone_toolkit_unchanged(): ...                            # AC-3 (FEAT-538 AC13)
async def test_read_ceiling_clamps_and_zero_disables(): ...                   # AC-4
async def test_host_runtime_requires_scope_and_is_borrowed(): ...             # AC-5
```

---

## Agent Instructions

1. Read spec §2 "Plan memory binding and recovery reads" and §3 Module 2; AC10/AC11/AC13.
2. Verify anchors (`tool.py:144-189`, `config.py:406-470`, `:560`, `:628`), implement, run Validation Commands.
3. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

**Completed by**: codex / gpt-5.6-terra (via parrot-sdd-coder MCP orchestration), attempt_uid
`29565c87ace34182a8536c3f268d3f4f`
**Date**: 2026-09-22
**Notes**:
- Delivered exactly the 3 scoped files (`memory.py` +166, `working_memory/tool.py` +27,
  `test_plan_memory.py` +102 lines), no out-of-scope files, no `sdd/` touched (fidelity_ok).
- Reviewed by hand: `WorkingMemoryToolkit._enable_plan_memory` matches the blueprint exactly
  (validates enabled task_memory/catalog, swaps `_task_memory`/`_catalog`, strips
  `TASK_TOOL_METHODS` from `exclude_tools`, refreshes cached `get_result` wrapper schemas in
  place). `PlanMemoryBinding.prepare()` is idempotent, reuses an already-enabled
  `_task_memory` when present, requires scope for a host-supplied runtime, synthesizes and
  caches a process scope (`_plan_scope`) otherwise, migrates every existing local entry via
  `aput_generic` before calling `_enable_plan_memory` (keeps old catalog on failure per spec).
  `restore()` enforces `max_restore_bytes` cumulatively and validates keys/versions
  cardinality. `close()` only stops an owned runtime. The unused `TYPE_CHECKING` import of
  `AnswerMemory` (never referenced as a type annotation, only in docstrings/comments) was
  correctly dropped by the engine's lint pass — verified this is not the same class of bug
  as TASK-3589's codec-registration regression (no import-time side effect here).
- Merge-tier `coder_run_validation` (budget 300s) settled `outcome=timed_out` — same
  established, pre-existing pattern as TASK-3589..3591 (25 unrelated `ai-parrot` collection
  errors; `ai-parrot-advisors`/`-client-amazon`/`-client-anthropic`/`-client-gemma4` all clean;
  `-client-google`'s slow video-reel-assembly suite, known from the earlier run to take ~9.5
  minutes alone, still mid-flight at cutoff). No failure observed relates to this task's files
  (`tools/execution_plan/memory.py`, `tools/working_memory/tool.py`). Local `pytest` remains
  blocked by the pre-existing broken local venv (`parrot.utils.types` import error).

**Deviations from spec**: none.

**Addendum (2026-09-22, during TASK-3599 consolidation)**: "no failure observed relates to this
task's files" above was premature — `test_plan_memory.py` (this task's own test file) was never
actually collected/executed at the time of that statement, masked by an unrelated TASK-3594
dead-code ImportError bug that TASK-3599 later activated. Once collection was unblocked,
`test_activation_keeps_existing_entries_and_is_idempotent` failed for real:
`toolkit.get_result("result")` was called without `await` (the method is `async def`) and the
returned coroutine was subscripted directly. Fixed in commit `f605b9f81` (added `await`).
Verified: `pytest test_plan_memory.py -q` → passed.
