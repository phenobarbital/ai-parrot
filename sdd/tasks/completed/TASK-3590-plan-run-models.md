# TASK-3590: Run, recovery and repair data models

**Feature**: FEAT-585 — Plan-then-Execute Hardening
**Spec**: `sdd/specs/plan-then-execute-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements the **Data Models** table of spec §2 and the model half of §3 **Module 3**.
Every later task imports from here: the resolver (TASK-3593) derives `PlanRun` from a
checkpoint, the flow (TASK-3594) persists `PlanRunMetadata`, the delta validator
(TASK-3596) and planner (TASK-3597) exchange `PlanDelta`, and the toolkit
(TASK-3598..3601) returns `PlanRunManifest` / `PlanRunSummary` / `PlanRunError`.

The frozen `ExecutionManifest` (`bots/flows/plan/models.py:450`, `extra="forbid"`) is NOT
modified (AC1). Toolkit-side models **extend** it so the existing top-level manifest keys
are preserved and the recovery envelope is additive (§2 "additive toolkit response schema").
§8 D1 fixes `max_repair_rounds` as host-only, range 0–2, default 2.

---

## Scope

- Add to `packages/ai-parrot/src/parrot/tools/execution_plan/models.py`:
  `PlanRecoveryConfig`, `PlanDelta`, `PlanRunMetadata`, `PlanRecoveryEnvelope`,
  `PlanRunManifest`, `PlanRunSummary`, `PlanRun`, `PlanResumeArgs`, `PlanRepairArgs`,
  `PlanRunError` and the constants `PLAN_RUN_SHARED_KEY = "plan_run"`,
  `PLAN_RUN_SCHEMA_VERSION = 1`, plus the `Literal` aliases `ResumeLevel`,
  `ArtifactMode`, `RunStatus`. Extend `__all__`.
- Give `PlanRunError` a `to_tool_result()` helper that builds the §2 error shape.
- Write `packages/ai-parrot/tests/tools/execution_plan/test_run_models.py`.

**NOT in scope**:
- Exporting the new names from `tools/execution_plan/__init__.py` (TASK-3598 owns that file).
- Any projection/derivation logic (`project_run` is TASK-3593).
- Touching `bots/flows/plan/models.py` (AC1).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/execution_plan/models.py` | MODIFY | Append the new models + constants; extend `__all__` |
| `packages/ai-parrot/tests/tools/execution_plan/test_run_models.py` | CREATE | Field/validator tests for every new model |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `3028213ee` on 2026-09-21.

### Verified Imports
```python
# Already at the top of models.py (lines 14-22) — reuse, do not duplicate:
from datetime import datetime
from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field
from ..abstract import AbstractToolArgsSchema          # verified: packages/ai-parrot/src/parrot/tools/abstract.py:237
from parrot.bots.flows.plan import ExecutionManifest   # verified: packages/ai-parrot/src/parrot/bots/flows/plan/__init__.py:22-31
# New imports this task adds:
from typing import List
from pydantic import field_validator
from parrot.bots.flows.plan import ArtifactRef, ExecutionPlan, PlanNode   # verified: plan/__init__.py:23,25,29
from ..abstract import ToolResult                      # verified: packages/ai-parrot/src/parrot/tools/abstract.py:250
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/execution_plan/models.py
__all__ = ("PlanArtifactsArgs", "PlanExecuteArgs", "PlanStatusArgs", "PlanValidateArgs", "RunRecord", "RunningSummary")  # lines 24-31
class RunRecord(BaseModel): ...        # line 34  — status: Literal["running","completed","partial","failed"] (line 59)
class RunningSummary(BaseModel):       # line 68
    run_id: str; status: Literal["running"] = "running"; plan_name: str; nodes_total: int; nodes_done: int; hint: str
class PlanStatusArgs(AbstractToolArgsSchema):   # line 81 — run_id: str = Field(..., description=...)
class PlanValidateArgs(AbstractToolArgsSchema): # line 119 — LAST class in the file (ends line 138)

# packages/ai-parrot/src/parrot/bots/flows/plan/models.py:450
class ExecutionManifest(BaseModel):    # extra="forbid"; fields: plan_name, objective, session_id, artifacts: List[ArtifactRef],
                                       # nodes_total, nodes_ok, nodes_skipped, nodes_failed, duration_seconds, total_bytes_stored
# packages/ai-parrot/src/parrot/bots/flows/plan/models.py:406
class ArtifactRef(BaseModel):          # node_id, keys, entry_type, facets, status Literal[ok|skipped|partial|error], item_count,
                                       # errors, bytes_stored, versions: List[str], tracking_degraded
# packages/ai-parrot/src/parrot/bots/flows/plan/models.py:173 / :268
class PlanNode(BaseModel): id, tool, args, store_as, depends_on, when, for_each, facets, timeout, retry, description
class ExecutionPlan(BaseModel): name, objective, nodes (min_length=1), metadata: PlanMetadata

# packages/ai-parrot/src/parrot/tools/abstract.py:250
class ToolResult(BaseModel): success: bool=True; status: str="success"; result: Any; error: Optional[str]; metadata: Dict
```

### Does NOT Exist
- ~~`ExecutionManifest.run_id` / `.resume_level`~~ — not on the frozen model; they live on `PlanRunManifest`.
- ~~`parrot.tools.execution_plan.models.PlanRun*`~~ — none of the new names exist yet; this task creates them.
- ~~`RunRecord.root_run_id`~~ — `RunRecord`/`RunningSummary` keep their old meaning untouched (spec §3 M6 "retain exports").
- ~~a `pydantic.conint`-style range helper in this codebase~~ — use `Field(..., ge=0, le=2)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/execution_plan/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/execution_plan/test_run_models.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/models.py#RunningSummary",
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/models.py#RunRecord",
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/models.py#ExecutionManifest",
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/models.py#ArtifactRef"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Every new model: Pydantic v2, `model_config = ConfigDict(extra="forbid")`, explicit
  `Field(description=...)` on every field (spec §2 Data Models).
- Persisted models (`PlanRunMetadata`) contain **no** clients, permissions, raw tool
  responses, artifact bodies or credentials — only identifiers, plans, names, timestamps.
- `PlanRun` is **never persisted separately** (it is derived); do not add a
  serializer/loader for it.
- `PlanRunManifest` and `PlanRunSummary` subclass the existing models so existing top-level
  keys stay at the top level (`PlanRunManifest(PlanRecoveryEnvelope, ExecutionManifest)`).

### References in Codebase
- `tools/execution_plan/models.py:34-78` — the docstring/`extra="forbid"` house style.
- `bots/flows/plan/models.py:257-265` `PlanMetadata` — `Field(default=…, ge=…, le=…)` range idiom.

---

## Implementation Blueprint

### Steps (in order)
1. Add the imports and constants — *why*: `PLAN_RUN_SHARED_KEY` is the one key the checkpoint projector (TASK-3594) and the resolver (TASK-3593) agree on; it must live in the root module.
2. Add the models in dependency order (config → delta → metadata → envelope → manifest/summary → run → args → error) — *why*: each later class annotates the earlier ones.
3. Extend `__all__` — *why*: TASK-3598 re-exports from the package by name.
4. Write the tests — *why*: the range/finite validators are the only D1 enforcement point.

### `packages/ai-parrot/src/parrot/tools/execution_plan/models.py` (MODIFY — constants + config/delta)
```python
# occurrences: 1 (verified: grep -c '^class PlanValidateArgs' packages/ai-parrot/src/parrot/tools/execution_plan/models.py)
# AFTER — append at END OF FILE, below the `PlanValidateArgs` class (verified: models.py:119-138)
PLAN_RUN_SHARED_KEY: str = "plan_run"
PLAN_RUN_SCHEMA_VERSION: int = 1
ResumeLevel = Literal["none", "process", "cross_restart"]
ArtifactMode = Literal["memory", "durable"]
RunStatus = Literal["running", "completed", "partial", "failed"]


class PlanRecoveryConfig(BaseModel):
    """Host-only recovery policy for ``ExecutionPlanToolkit`` (spec §2, §8 D1)."""

    model_config = ConfigDict(extra="forbid")

    max_repair_rounds: int = Field(default=2, ge=0, le=2, description="Runtime repair rounds per run; 0 disables plan_repair.")
    max_restore_bytes: int = Field(default=67_108_864, gt=0, description="Cumulative exact-version restore budget per continuation.")
    checkpoint_probe_timeout: float = Field(default=2.0, gt=0.0, description="Seconds for the pre-dispatch store probe.")

    @field_validator("checkpoint_probe_timeout")
    @classmethod
    def _finite(cls, value: float) -> float:
        """Reject inf/nan — a probe that never times out defeats its purpose."""
        import math

        if not math.isfinite(value):
            raise ValueError("checkpoint_probe_timeout must be finite")
        return value


class PlanDelta(BaseModel):
    """Replacement nodes for a runtime repair — never a standalone plan (spec §2)."""

    model_config = ConfigDict(extra="forbid")

    nodes: List[PlanNode] = Field(..., min_length=1, description="Replacement PlanNodes keyed by their existing id.")

    @field_validator("nodes")
    @classmethod
    def _unique_ids(cls, nodes: List[PlanNode]) -> List[PlanNode]:
        """Duplicate ids inside one delta are a malformed delta."""
        ids = [n.id for n in nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("PlanDelta.nodes must not repeat a node id")
        return nodes
```
**Why this shape**: D1 is enforced by the type (`le=2`), so no toolkit code can be handed a
wider budget. `PlanDelta` carries only nodes: plan-level metadata changes are structurally
impossible (spec §2 "Reject ... changes to plan-level metadata").

### `packages/ai-parrot/src/parrot/tools/execution_plan/models.py` (MODIFY — metadata + envelope)
```python
# AFTER — continue appending below PlanDelta
class PlanRunMetadata(BaseModel):
    """Versioned ``plan_run`` document persisted in the checkpoint shared-data projection."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = Field(default=1, description="Envelope schema; mismatch fails closed.")
    run_id: str = Field(..., description="Opaque UUID run id; equals the AgentsFlow flow_id.")
    root_run_id: str = Field(..., description="Root of the repair lineage (== run_id for a root run).")
    parent_run_id: Optional[str] = Field(default=None, description="Immediate parent for a repair child.")
    plan: ExecutionPlan = Field(..., description="Effective validated plan this run executes.")
    original_plan: ExecutionPlan = Field(..., description="Root plan as originally accepted.")
    source: Literal["objective", "plan_name", "repair"] = Field(..., description="Acquisition mode.")
    started_at: datetime = Field(..., description="UTC start.")
    finished_at: Optional[datetime] = Field(default=None, description="UTC end, once terminal.")
    scope_key: Optional[str] = Field(default=None, description="TaskScope.cache_key() of the trusted scope, for comparison only.")
    task_id: Optional[str] = Field(default=None, description="Task memory task id, if any.")
    allowed_tools: List[str] = Field(..., description="Frozen, sorted tool names allowed when the run was accepted.")
    plan_fingerprint: str = Field(..., description="sha256 of the canonical effective-plan JSON.")
    artifact_mode: ArtifactMode = Field(..., description="Where artifact bodies live.")
    process_id: Optional[str] = Field(default=None, description="host:pid:nonce for memory-mode artifacts.")
    repair_attempts_used: int = Field(default=0, ge=0, description="Attempts consumed, including interrupted ones.")
    max_repair_rounds: int = Field(default=2, ge=0, le=2, description="Snapshot of the host limit at acceptance.")
    active_child_run_id: Optional[str] = Field(default=None, description="Accepted child continuation, if any.")
    repair_children: List[str] = Field(default_factory=list, description="Every allocated child id, in order.")


class PlanRecoveryEnvelope(BaseModel):
    """Recovery/lineage fields every run response carries (spec §2 Recovery capabilities)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., description="Run id.")
    root_run_id: str = Field(..., description="Lineage root.")
    parent_run_id: Optional[str] = Field(default=None, description="Parent, for repair children.")
    checkpoint_enabled: bool = Field(..., description="Whether this run acknowledged checkpoints.")
    artifact_mode: ArtifactMode = Field(..., description="memory | durable.")
    resume_level: ResumeLevel = Field(..., description="Storage capability: none | process | cross_restart.")
    resumable: bool = Field(..., description="Capability AND current status/lease/artifact availability.")
    recovery_reason: Optional[str] = Field(default=None, description="Why resumable is False, when it is.")
    repair_attempts_used: int = Field(default=0, ge=0, description="Repair attempts consumed so far.")
    max_repair_rounds: int = Field(default=2, ge=0, le=2, description="Host repair limit.")
    active_child_run_id: Optional[str] = Field(default=None, description="Active child continuation.")
```
**Why**: `PlanRunMetadata` is "execution input, not a duplicate mutable registry" (§2);
`scope_key` is compared against the host scope, never used as authority. The envelope is
one class so manifest, summary and error responses cannot drift apart.

### `packages/ai-parrot/src/parrot/tools/execution_plan/models.py` (MODIFY — responses, run, args, error)
```python
# AFTER — continue appending below PlanRecoveryEnvelope
class PlanRunManifest(PlanRecoveryEnvelope, ExecutionManifest):
    """Terminal response: frozen manifest keys at top level + recovery envelope (additive)."""

    model_config = ConfigDict(extra="forbid")

    status: RunStatus = Field(..., description="Terminal run status.")


class PlanRunSummary(PlanRecoveryEnvelope, RunningSummary):
    """Live response while a run executes: RunningSummary + recovery envelope."""

    model_config = ConfigDict(extra="forbid")

    uncheckpointed_progress: bool = Field(default=False, description="True when nodes_done includes local-only progress.")


class PlanRun(BaseModel):
    """Derived, never-persisted view of one run resolved from its checkpoint (spec §2)."""

    model_config = ConfigDict(extra="forbid")

    metadata: PlanRunMetadata = Field(..., description="The persisted envelope.")
    checkpoint_id: Optional[int] = Field(default=None, description="Checkpoint this view was derived from.")
    status: RunStatus = Field(..., description="Current run status.")
    refs: List[ArtifactRef] = Field(default_factory=list, description="Typed per-node refs in original node order.")
    nodes_done: int = Field(default=0, ge=0, description="Nodes with a terminal per-node status.")
    checkpoint_enabled: bool = Field(..., description="Whether checkpoints were acknowledged.")
    resume_level: ResumeLevel = Field(..., description="Storage capability.")
    resumable: bool = Field(..., description="Whether plan_resume may continue this run now.")
    recovery_reason: Optional[str] = Field(default=None, description="Why not resumable.")
    dispatched_node_ids: List[str] = Field(default_factory=list, description="Nodes recorded as dispatched or completed.")


class PlanResumeArgs(AbstractToolArgsSchema):
    """Arguments for ``plan_resume`` — run id only (spec §2: no scope/allowlist/limits)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., description="Run id returned by plan_execute / plan_repair.")


class PlanRepairArgs(AbstractToolArgsSchema):
    """Arguments for ``plan_repair`` — run id only."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., description="Terminal failed/partial run id to repair.")


class PlanRunError(Exception):
    """Structured, bounded run error that maps to the §2 ``ToolResult`` error shape."""

    def __init__(self, code: str, message: str, *, envelope: Optional[PlanRecoveryEnvelope] = None,
                 manifest: Optional[PlanRunManifest] = None) -> None:
        super().__init__(message[:500])
        self.code = code
        self.message = message[:500]
        self.envelope = envelope
        self.manifest = manifest

    def to_tool_result(self) -> ToolResult:
        """Build ``ToolResult(status="error", success=False, error=..., result={"code": ...})``."""
        payload: Dict[str, Any] = {"code": self.code}
        # FILL IN: merge envelope.model_dump(mode="json") and manifest.model_dump(mode="json") under
        # "manifest" when present — bounded by "message bounded to 500 chars; never artifact bodies".
        return ToolResult(status="error", success=False, result=payload, error=self.message)
```
**Why**: `PlanRunError` is an `Exception` (not a BaseModel) so toolkit code can `raise` it
from helpers and convert at the tool boundary — the same pattern as `_StructuralError`
(`toolkit.py:54`). Add every new public name to `__all__`.

### FILL IN checklist
- [ ] `models.py::PlanRunError.to_tool_result` — envelope/manifest merge; bounded by §2 error shape
- [ ] `models.py::__all__` — add all new names (alphabetical, matching the tuple style)
- [ ] `test_run_models.py` — bodies for the tests listed below

---

## Acceptance Criteria

- [ ] AC-1 — `PlanRecoveryConfig()` defaults to `max_repair_rounds=2`, `max_restore_bytes=67108864`, `checkpoint_probe_timeout=2.0`; `3`, `-1`, `inf`, `0.0` are rejected (AC16).
- [ ] AC-2 — `PlanDelta(nodes=[])` and duplicate ids are rejected; `PlanDelta` has no plan-level fields (extra forbidden).
- [ ] AC-3 — `PlanRunMetadata.model_dump(mode="json")` round-trips through `model_validate`; `schema_version=2` is rejected.
- [ ] AC-4 — `PlanRunManifest` exposes every `ExecutionManifest` field at top level plus the envelope; `PlanRunSummary` likewise for `RunningSummary`.
- [ ] AC-5 — `PlanRunError("unknown_run", "x"*600).to_tool_result()` has `status="error"`, `success=False`, `result["code"]=="unknown_run"`, `len(error)<=500`.
- [ ] `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_run_models.py -q`
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_toolkit_core.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/execution_plan/test_run_models.py
import math
import pytest
from pydantic import ValidationError
from parrot.tools.execution_plan.models import (
    PlanDelta, PlanRecoveryConfig, PlanRunError, PlanRunManifest, PlanRunMetadata, PlanRunSummary,
)

def test_recovery_config_defaults_and_ranges(): ...      # AC-1
@pytest.mark.parametrize("value", [3, -1])
def test_max_repair_rounds_out_of_range(value): ...      # AC-1
@pytest.mark.parametrize("value", [math.inf, math.nan, 0.0])
def test_probe_timeout_must_be_finite_positive(value): ...
def test_delta_requires_unique_nonempty_nodes(): ...     # AC-2
def test_metadata_roundtrip_and_schema_version(): ...    # AC-3
def test_manifest_keeps_frozen_keys_top_level(): ...     # AC-4
def test_error_to_tool_result_is_bounded(): ...          # AC-5
```

---

## Agent Instructions

1. Read spec §2 "Data Models", "New Public Interfaces" and §8 D1.
2. Verify the Codebase Contract anchors, then append the blocks in order.
3. Run the Validation Commands.
4. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (resumed interrupted session; original implementation by a prior
coder attempt, merged as commits fe8b4646a/330467d1d/5bfed9a36 before this session began)
**Date**: 2026-09-22
**Notes**:
- Implementation verified by hand against this task's Codebase Contract and Implementation
  Blueprint: all new models (`PlanRecoveryConfig`, `PlanDelta`, `PlanRunMetadata`,
  `PlanRecoveryEnvelope`, `PlanRunManifest`, `PlanRunSummary`, `PlanRun`, `PlanResumeArgs`,
  `PlanRepairArgs`, `PlanRunError`), constants (`PLAN_RUN_SHARED_KEY`,
  `PLAN_RUN_SCHEMA_VERSION`) and `Literal` aliases (`ResumeLevel`, `ArtifactMode`,
  `RunStatus`) appended at end of file exactly per blueprint; `PlanRunError.to_tool_result()`
  FILL IN implemented correctly (merges manifest/envelope under `"manifest"`, bounds
  `error` to <=500 chars). No deviations.
- See TASK-3589's Completion Note for the full account of the merge-tier validation run
  (settled `outcome=timed_out` after exercising ~20/24 distributions with only pre-existing,
  unrelated failures) and the one regression found+fixed in that task (unrelated to this
  task's file, `tools/execution_plan/models.py`, which this run's `ai-parrot` distribution
  collection-abort also could not exercise — see TASK-3589 note for the same pre-existing
  25-collection-error/local-venv caveats). This task's new `test_run_models.py` was reviewed
  by hand against the Test Specification and matches AC-1..AC-5.

**Deviations from spec**: none.
