# TASK-3115: `sdd_coder` package — Pydantic models, error codes and tool envelope

**Feature**: FEAT-549 — `sdd-worker` as Orchestrator of Parallel `sdd-coder` Sub-Agents
**Spec**: `sdd/specs/sdd-worker-subagents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Every other module of FEAT-549 (roster, engine, toolkit, tests)
imports its payloads from here: the roster/plan models the MCP `coder_plan` tool
returns, the job/result models `coder_run_chunk`/`coder_wait` return, the closed
error-code set, the tool-argument models validated in `_pre_execute` (design
research S6), and the `CoderResult` envelope that re-declares the shape of
`parrot_tools`' `OperationResult` because core must not import `parrot_tools`.
No logic lives here — only data contracts (spec §2 "Data Models").

---

## Scope

- Create the package `parrot.flows.dev_loop.sdd_coder` with `__init__.py` exporting the models.
- Implement every model of spec §2 "Data Models" in `models.py`, exactly as named there.
- Implement the seven tool-argument models with `extra="forbid"`, task-id and absolute-worktree validation.
- Implement the closed `ERROR_CODES` set and `CoderError`/`CoderResult`.
- Write unit tests for validation rules.

**NOT in scope**: probe/chunker logic (TASK-3116), engine (TASK-3120/3121),
toolkit (TASK-3122), any change to existing dev-loop models.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/__init__.py` | CREATE | Package init; exports the models (later tasks append engine/toolkit exports) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | CREATE | All Pydantic payloads, arg models, error codes, `CoderResult` |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/__init__.py` | CREATE | Empty test package marker (mirror the sibling test dirs — create only if `tests/flows/dev_loop/__init__.py` exists) |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py` | CREATE | Validation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from parrot.flows.dev_loop.models import DevAgentBackend, DevelopmentOutput   # verified: models/base.py:407 (Literal), :497 (class); re-exported by models/__init__.py
```
Import discipline (verified: `agent_pool.py` module docstring, lines 14-22): inside
`parrot/flows/dev_loop/` import from **submodules** (`parrot.flows.dev_loop.models`),
never `from parrot.flows.dev_loop import ...` — the package `__init__` is mid-initialisation
when `sdd_coder` is imported transitively and would raise `ImportError: partially initialized`.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
DevAgentBackend = Literal["claude-code","codex","gemini","nvidia","grok","zai","moonshot","google_coding","nova"]   # line 407-409
                                                                     # TASK-3118 adds "google-compat"; this task must not rely on it in tests
class DevelopmentOutput(BaseModel):   # line 497 — files_changed: List[str]; commit_shas: List[str]; summary: str;
                                      #   incomplete_tasks: List[str] = []; worker_summaries: List[WorkerSummary] = []
```

### Does NOT Exist
- ~~`parrot.flows.dev_loop.sdd_coder`~~ — this task creates it; nothing under it exists yet.
- ~~`from parrot_tools.tool_optimizations.models import OperationResult`~~ in core — `ai-parrot-tools` depends on `ai-parrot`, not the reverse; `CoderResult` re-declares the shape (spec §2).
- ~~`DevAgentSpec.label` / `.kind`~~ — `DevAgentSpec` has `agent`, `model`, `count`, `escalation_model` only (models/base.py:412-435); `RosterSeat` is a separate model by design (design research S7).
- ~~`"google-compat"` in `DevAgentBackend`~~ until TASK-3118 lands — tests here use `"nova"`, `"codex"`, `"nvidia"`.
- ~~`pydantic.v1`~~ — the repo is Pydantic v2 (`model_config = ConfigDict(...)`, `field_validator`).

---

## Implementation Notes

### Pattern to Follow
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py:412-435 — plain BaseModel with Field(..., description=...)
class DevAgentSpec(BaseModel):
    agent: DevAgentBackend = Field(..., description="Backend → existing dispatcher (claude-code, codex, ...).")
    model: str = Field(default="", description="'' ⇒ use the backend's default model.")
```

### Key Constraints
- Pydantic v2 only; every field typed; Google-style docstrings on every class.
- Arg models: `model_config = ConfigDict(extra="forbid")`; task ids match `^TASK-\d{1,5}$`; `worktree` must be an absolute path (`os.path.isabs`).
- `ERROR_CODES` is the single source of truth for `CoderError.code` — validate membership.
- No I/O, no logging, no imports from `parrot.mcp` or `parrot.tools` here.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/models.py:82-153` — `OperationError`/`OperationResult` shape being mirrored (read for field semantics; do NOT import).
- `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py:407-535` — the dev-loop models this package composes.

---

## Implementation Blueprint

### Steps (in order)
1. Create `sdd_coder/__init__.py` with the model re-exports — *why*: later tasks (`engine`, `toolkit`) only append to `__all__`; fixing the public path now keeps the spec's `from parrot.flows.dev_loop.sdd_coder import ...` stable.
2. Write `models.py` part 1 (roster + plan models) — *why*: `coder_plan`'s payload is consumed by `sdd-worker.md` (TASK-3124); names are fixed by spec §2.
3. Write `models.py` part 2 (attempt/job/result + arg models + envelope) — *why*: `_pre_execute` (TASK-3122) validates against the arg models, so `extra="forbid"` and the validators are mandatory here.
4. Write the tests, run `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder -v` — *why*: AC-23 depends on these validators rejecting malformed input before the engine runs.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/__init__.py` (CREATE)
```python
"""`sdd_coder` — orchestration kernel behind the `parrot-sdd-coder` MCP server (FEAT-549).

Composes the FEAT-323 dev-loop primitives (TaskScheduler, SubWorktreeManager,
build_dispatcher) so the interactive `sdd-worker` can run one task per seat in
parallel. Import from submodules only (see agent_pool.py module docstring).
"""
from parrot.flows.dev_loop.sdd_coder.models import (  # noqa: F401
    ERROR_CODES, AttemptRecord, CleanupReport, CoderError, CoderJob, CoderPlan, CoderResult,
    NativePrep, OrphanBranch, PlanChunk, PlannedTask, RosterConfig, RosterSeat,
    SeatKind, SeatProbeResult, TaskOutcome, TaskResult,
    CoderPlanArgs, CoderRunChunkArgs, CoderPrepareNativeArgs, CoderMergeArgs,
    CoderWaitArgs, CoderStatusArgs, CoderCleanupArgs,
)

__all__ = [
    "ERROR_CODES", "AttemptRecord", "CleanupReport", "CoderError", "CoderJob", "CoderPlan",
    "CoderResult", "NativePrep", "OrphanBranch", "PlanChunk", "PlannedTask", "RosterConfig",
    "RosterSeat", "SeatKind", "SeatProbeResult", "TaskOutcome", "TaskResult",
    "CoderPlanArgs", "CoderRunChunkArgs", "CoderPrepareNativeArgs", "CoderMergeArgs",
    "CoderWaitArgs", "CoderStatusArgs", "CoderCleanupArgs",
]
```
**Why this shape**: the spec's New Public Interfaces name `parrot.flows.dev_loop.sdd_coder` as the import path. TASK-3120/3121/3122 will append `SddCoderEngine`, `RosterProbe`, `ChunkAssigner`, `SddCoderToolkit` to this list — do not pre-declare them here (they do not exist yet and would break import).

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` (CREATE — part 1: roster + plan)
```python
"""Pydantic payloads of the sdd_coder kernel (spec §2 "Data Models"). No logic, no I/O."""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from parrot.flows.dev_loop.models import DevAgentBackend, DevelopmentOutput  # verified: models/base.py:407, :497

SeatKind = Literal["mcp", "native"]
TaskOutcome = Literal["queued", "running", "merged", "merge_conflict", "failed", "fidelity_violation", "retry_native"]
ERROR_CODES: frozenset[str] = frozenset({
    "feature_not_found", "index_unreadable", "dependency_cycle", "worktree_outside_base", "task_not_pending",
    "task_not_in_plan", "task_already_running", "seat_unavailable", "roster_empty", "job_not_found",
    "branch_not_found", "dirty_feature_worktree", "dirty_task_worktree", "merge_conflict", "fidelity_violation",
    "invalid_arguments", "internal_error",
})
_TASK_ID_RE = re.compile(r"^TASK-\d{1,5}$")


class RosterSeat(BaseModel):
    """One seat of the model roster (config-driven, spec G8). `backend` is required for kind='mcp'."""
    label: str = Field(..., min_length=1, max_length=32)
    kind: SeatKind = "mcp"
    backend: Optional[DevAgentBackend] = None
    model: str = ""
    fallback_model: str = ""

    @field_validator("backend")
    @classmethod
    def _backend_required_for_mcp(cls, v: Optional[str], info: Any) -> Optional[str]:
        """kind='mcp' ⇒ backend must be set; kind='native' ⇒ backend must be None."""
        # FILL IN: read info.data["kind"]; raise ValueError with the offending label — bounded by test_roster_config_requires_backend_for_mcp
        return v


class RosterConfig(BaseModel):
    """Ordered roster + engine bounds (spec: wait ≤ 300 s)."""
    seats: List[RosterSeat] = Field(..., min_length=1)
    wait_timeout_max_s: int = Field(default=300, ge=10, le=300)
    smoke_timeout_s: int = Field(default=60, ge=5, le=300)


class SeatProbeResult(BaseModel):
    """Outcome of probing one seat at first use (spec G8)."""
    label: str; kind: SeatKind; backend: Optional[str] = None
    available: bool; model_used: str = ""; fallback_used: bool = False; reason: str = ""


class PlannedTask(BaseModel):
    """A task with its assigned seat inside one chunk."""
    task_id: str; task_file: str; title: str = ""
    seat_label: str; native: bool = False; backend: Optional[str] = None; model: str = ""


class PlanChunk(BaseModel):
    index: int = Field(..., ge=0)
    tasks: List[PlannedTask]


class OrphanBranch(BaseModel):
    """A `<feature>--TASK-NNN-a<n>` branch with no live job (design research S2)."""
    task_id: str; branch: str; worktree_path: str = ""; commits: int = 0; files: List[str] = Field(default_factory=list)


class CoderPlan(BaseModel):
    """`coder_plan` payload: next wave sliced into distinct-seat chunks."""
    feature_id: str; feature: str; feature_branch: str; index_path: str
    pending: List[str]; blocked: List[str]
    chunks: List[PlanChunk]; roster: List[SeatProbeResult]; orphan_branches: List[OrphanBranch]
```
**Why this shape**: names and fields are fixed by spec §2 and consumed verbatim by `sdd-worker.md` (TASK-3124) and the engine (TASK-3120). `ERROR_CODES` is a frozenset so `CoderError` can validate membership without a second enum. Semicolon-joined field lines are only a notation here — expand one field per line when writing the file.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` (CREATE — part 2: append below part 1)
```python
class AttemptRecord(BaseModel):
    """Per-attempt telemetry (spec G9, design research S8)."""
    attempt: int = Field(..., ge=1, le=3); seat_label: str; backend: str = ""; model: str = ""
    started_at: str; ended_at: str = ""; duration_s: float = 0.0
    usage: Dict[str, Any] = Field(default_factory=dict); error: str = ""


class TaskResult(BaseModel):
    task_id: str; outcome: TaskOutcome; branch: str = ""; worktree_path: str = ""
    attempts: List[AttemptRecord] = Field(default_factory=list)
    conflict_files: List[str] = Field(default_factory=list); unexpected_files: List[str] = Field(default_factory=list)
    diagnostics: str = ""; development_output: Optional[DevelopmentOutput] = None


class NativePrep(BaseModel):
    task_id: str; task_file: str; branch: str; worktree_path: str; seat_label: str


class CoderJob(BaseModel):
    job_id: str; feature_id: str; chunk_task_ids: List[str]
    state: Literal["running", "done", "error"]; started_at: str; ended_at: str = ""
    tasks: List[TaskResult] = Field(default_factory=list); error: str = ""


class CleanupReport(BaseModel):
    removed: List[str] = Field(default_factory=list); kept: List[str] = Field(default_factory=list)


class CoderError(BaseModel):
    code: str; message: str; details: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("code")
    @classmethod
    def _known_code(cls, v: str) -> str:
        """Only codes from ERROR_CODES are allowed (closed set, spec §2)."""
        # FILL IN: raise ValueError(f"unknown error code {v!r}") when v not in ERROR_CODES — bounded by test_coder_result_error_codes_closed_set
        return v


class CoderResult(BaseModel):
    """Tool envelope — mirrors parrot_tools OperationResult; core MUST NOT import parrot_tools."""
    status: Literal["ok", "error"]; operation: str
    data: Dict[str, Any] = Field(default_factory=dict); error: Optional[CoderError] = None
    elapsed_ms: int = Field(default=0, ge=0)


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _check_task_id(v: str) -> str:
    # FILL IN: raise ValueError when not _TASK_ID_RE.fullmatch(v) — bounded by test_toolkit_pre_execute_rejects_bad_args (TASK-3122)
    return v


def _check_abs(v: str) -> str:
    # FILL IN: raise ValueError("worktree must be an absolute path") when not os.path.isabs(v)
    return v


class CoderPlanArgs(_Args):
    feature: str; worktree: str
    _wt = field_validator("worktree")(_check_abs)

class CoderRunChunkArgs(_Args):
    feature: str; worktree: str; task_ids: List[str] = Field(..., min_length=1)
    _wt = field_validator("worktree")(_check_abs)
    # FILL IN: field_validator("task_ids") applying _check_task_id to each element

class CoderPrepareNativeArgs(_Args):
    feature: str; worktree: str; task_id: str
    _wt = field_validator("worktree")(_check_abs); _tid = field_validator("task_id")(_check_task_id)

class CoderMergeArgs(CoderPrepareNativeArgs):
    """Same shape as prepare_native."""

class CoderWaitArgs(_Args):
    job_id: str; timeout_seconds: int = Field(default=120, ge=1, le=300)

class CoderStatusArgs(_Args):
    job_id: str

class CoderCleanupArgs(_Args):
    feature: str; worktree: str; keep_conflicted: bool = True
    _wt = field_validator("worktree")(_check_abs)
```
**Why this shape**: `extra="forbid"` + validators are what AC-23 tests; `CoderWaitArgs.timeout_seconds ≤ 300` encodes the resolved job-API bound. `CoderMergeArgs` subclasses `CoderPrepareNativeArgs` because the spec fixes identical fields. Expand the semicolon notation to one field per line.

### FILL IN checklist
- [ ] `models.py::RosterSeat._backend_required_for_mcp` — enforce backend/kind coupling; bounded by `test_roster_config_requires_backend_for_mcp`
- [ ] `models.py::CoderError._known_code` — membership in `ERROR_CODES`; bounded by `test_coder_result_error_codes_closed_set`
- [ ] `models.py::_check_task_id`, `_check_abs`, `CoderRunChunkArgs` list validator — reject malformed ids / relative worktree; bounded by AC-23

---

## Acceptance Criteria

- [ ] `from parrot.flows.dev_loop.sdd_coder import RosterConfig, CoderPlan, CoderJob, CoderResult, CoderRunChunkArgs` works.
- [ ] `RosterSeat(label="x", kind="mcp")` raises; `RosterSeat(label="h", kind="native")` validates; `RosterSeat(label="q", backend="nova")` validates.
- [ ] `CoderError(code="bogus", message="m")` raises; every code in `ERROR_CODES` validates.
- [ ] `CoderRunChunkArgs(feature="f", worktree="rel/path", task_ids=["TASK-1"])` raises (relative); `task_ids=["nope"]` raises; extra key raises.
- [ ] `CoderWaitArgs(job_id="j", timeout_seconds=900)` raises (le=300).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/` and `mypy` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py
import pytest
from pydantic import ValidationError
from parrot.flows.dev_loop.sdd_coder import (ERROR_CODES, CoderError, CoderRunChunkArgs, CoderWaitArgs, RosterSeat)


def test_roster_config_requires_backend_for_mcp():
    with pytest.raises(ValidationError):
        RosterSeat(label="x", kind="mcp")
    assert RosterSeat(label="h", kind="native").backend is None
    assert RosterSeat(label="q", backend="nova").kind == "mcp"


def test_coder_result_error_codes_closed_set():
    with pytest.raises(ValidationError):
        CoderError(code="bogus", message="m")
    for code in ERROR_CODES:
        assert CoderError(code=code, message="m").code == code


@pytest.mark.parametrize("kwargs", [
    dict(feature="f", worktree="rel/path", task_ids=["TASK-1"]),
    dict(feature="f", worktree="/abs", task_ids=["nope"]),
    dict(feature="f", worktree="/abs", task_ids=["TASK-1"], extra=1),
])
def test_run_chunk_args_reject_bad_input(kwargs):
    with pytest.raises(ValidationError):
        CoderRunChunkArgs(**kwargs)


def test_wait_args_cap():
    with pytest.raises(ValidationError):
        CoderWaitArgs(job_id="j", timeout_seconds=900)
    assert CoderWaitArgs(job_id="j").timeout_seconds == 120
```

---

## Agent Instructions

1. **Read the spec** §2 "Data Models" and §3 Module 1.
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — `grep -n "^DevAgentBackend" packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` and `grep -n "class DevelopmentOutput" ...` before writing.
4. **Update status** in `sdd/tasks/index/sdd-worker-subagents.json` → `"in-progress"`.
5. **Implement** from the blueprint; expand the semicolon notation; complete every `FILL IN`.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3115-sdd-coder-models.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Sonnet)
**Date**: 2026-09-10
**Notes**: Implemented `sdd_coder/__init__.py` + `models.py` exactly per the
blueprint. All `FILL IN` items completed: `RosterSeat` backend/kind coupling,
`CoderError` closed-code validation, `_check_task_id`/`_check_abs` and the
`task_ids` list validator. 8/8 unit tests pass; `ruff check` clean.

**Deviations from spec**: `RosterSeat._backend_required_for_mcp` was written
as a `model_validator(mode="after")` instead of the blueprint's
`field_validator("backend")`. A plain `field_validator` on `backend` does not
run against the field's own default (`None`) in Pydantic v2 unless
`validate_default=True` is set — so `RosterSeat(label="x", kind="mcp")` (no
`backend` given) silently passed instead of raising, failing
`test_roster_config_requires_backend_for_mcp`. The `model_validator` reads
`self.kind`/`self.backend` after both are populated (including defaults) and
enforces the same rule; behavior and error message intent are unchanged.
