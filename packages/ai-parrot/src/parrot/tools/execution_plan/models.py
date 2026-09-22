"""Toolkit-internal models for ``ExecutionPlanToolkit``.

``RunRecord``/``RunningSummary`` are the run-registry data models (spec
§2 Data Models). The live ``asyncio.Task``/``AgentsFlow`` handle for a run
is deliberately NOT a field here — it stays out-of-band in the toolkit's
own internal dict so this model stays a plain, ``extra="forbid"``
serializable record.

Tool-argument schemas (``PlanStatusArgs``, ``PlanArtifactsArgs``,
``PlanExecuteArgs``, ``PlanValidateArgs``) follow the repo's
``AbstractToolArgsSchema`` convention (see
``.agent/workflows/create-parrot-tool.md``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..abstract import AbstractToolArgsSchema, ToolResult
from parrot.bots.flows.plan import ArtifactRef, ExecutionManifest, ExecutionPlan, PlanNode

__all__ = (
    "ArtifactMode",
    "PLAN_RUN_SCHEMA_VERSION",
    "PLAN_RUN_SHARED_KEY",
    "PlanArtifactsArgs",
    "PlanDelta",
    "PlanExecuteArgs",
    "PlanRecoveryConfig",
    "PlanRecoveryEnvelope",
    "PlanRepairArgs",
    "PlanResumeArgs",
    "PlanRun",
    "PlanRunError",
    "PlanRunManifest",
    "PlanRunMetadata",
    "PlanRunSummary",
    "PlanStatusArgs",
    "PlanValidateArgs",
    "ResumeLevel",
    "RunRecord",
    "RunStatus",
    "RunningSummary",
)


class RunRecord(BaseModel):
    """Registry entry for one plan run (toolkit-internal).

    Attributes:
        run_id: Short unique id, e.g. ``"run_ab12cd"``.
        plan_name: The executed plan's ``name``.
        source: Which acquisition mode produced the plan.
        status: Current run status.
        started_at: When the run's background task was created.
        finished_at: When the run reached a terminal status, if it has.
        manifest: The final :class:`ExecutionManifest`, set on completion.
        nodes_total: Total plan nodes (bound for progress reporting).
        nodes_done: Nodes that have reached a terminal per-node status
            (``ok``/``skipped``/``partial``/``error``) so far.
        flow_error: Set when the run failed at the FLOW level (before any
            manifest could be built) — e.g. an infrastructure error, not a
            per-node tool failure (those show up inside ``manifest``
            instead). Bounded to 500 chars.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    plan_name: str
    source: Literal["objective", "plan_name"]
    status: Literal["running", "completed", "partial", "failed"]
    started_at: datetime
    finished_at: Optional[datetime] = None
    manifest: Optional[ExecutionManifest] = None
    nodes_total: int
    nodes_done: int = 0
    flow_error: Optional[str] = None


class RunningSummary(BaseModel):
    """What ``plan_execute`` returns when ``soft_timeout`` elapses first."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: Literal["running"] = "running"
    plan_name: str
    nodes_total: int
    nodes_done: int
    hint: str = "poll plan_status(run_id)"


class PlanStatusArgs(AbstractToolArgsSchema):
    """Arguments for the ``plan_status`` tool."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., description="Run id returned by plan_execute.")


class PlanArtifactsArgs(AbstractToolArgsSchema):
    """Arguments for the ``plan_artifacts`` tool."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., description="Run id returned by plan_execute.")


class PlanExecuteArgs(AbstractToolArgsSchema):
    """Arguments for the ``plan_execute`` tool.

    Exactly one of ``objective``/``plan_name`` must be set.
    """

    model_config = ConfigDict(extra="forbid")

    objective: Optional[str] = Field(
        default=None,
        description="Natural-language objective for objective mode (planner-authored).",
    )
    plan_name: Optional[str] = Field(
        default=None,
        description="Versioned plan filename (no extension) under plans_dir.",
    )
    params: Optional[Dict[str, Any]] = Field(
        default=None,
        description="{params.<name>} values for plan_name mode; not valid with objective.",
    )


class PlanValidateArgs(AbstractToolArgsSchema):
    """Arguments for the ``plan_validate`` tool.

    Same shape as :class:`PlanExecuteArgs` — a dry run never executes.
    """

    model_config = ConfigDict(extra="forbid")

    objective: Optional[str] = Field(
        default=None,
        description="Natural-language objective for objective mode (planner-authored).",
    )
    plan_name: Optional[str] = Field(
        default=None,
        description="Versioned plan filename (no extension) under plans_dir.",
    )
    params: Optional[Dict[str, Any]] = Field(
        default=None,
        description="{params.<name>} values for plan_name mode; not valid with objective.",
    )


PLAN_RUN_SHARED_KEY: str = "plan_run"
PLAN_RUN_SCHEMA_VERSION: int = 1
ResumeLevel = Literal["none", "process", "cross_restart"]
ArtifactMode = Literal["memory", "durable"]
RunStatus = Literal["running", "completed", "partial", "failed"]


class PlanRecoveryConfig(BaseModel):
    """Host-only recovery policy for ``ExecutionPlanToolkit`` (spec §2, §8 D1)."""

    model_config = ConfigDict(extra="forbid")

    max_repair_rounds: int = Field(
        default=2, ge=0, le=2, description="Runtime repair rounds per run; 0 disables plan_repair."
    )
    max_restore_bytes: int = Field(
        default=67_108_864, gt=0, description="Cumulative exact-version restore budget per continuation."
    )
    checkpoint_probe_timeout: float = Field(
        default=2.0, gt=0.0, description="Seconds for the pre-dispatch store probe."
    )

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
    scope_key: Optional[str] = Field(
        default=None, description="TaskScope.cache_key() of the trusted scope, for comparison only."
    )
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


class PlanRunManifest(PlanRecoveryEnvelope, ExecutionManifest):
    """Terminal response: frozen manifest keys at top level + recovery envelope (additive)."""

    model_config = ConfigDict(extra="forbid")

    status: RunStatus = Field(..., description="Terminal run status.")


class PlanRunSummary(PlanRecoveryEnvelope, RunningSummary):
    """Live response while a run executes: RunningSummary + recovery envelope."""

    model_config = ConfigDict(extra="forbid")

    uncheckpointed_progress: bool = Field(
        default=False, description="True when nodes_done includes local-only progress."
    )


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
    dispatched_node_ids: List[str] = Field(
        default_factory=list, description="Nodes recorded as dispatched or completed."
    )


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

    def __init__(
        self,
        code: str,
        message: str,
        *,
        envelope: Optional[PlanRecoveryEnvelope] = None,
        manifest: Optional[PlanRunManifest] = None,
    ) -> None:
        super().__init__(message[:500])
        self.code = code
        self.message = message[:500]
        self.envelope = envelope
        self.manifest = manifest

    def to_tool_result(self) -> ToolResult:
        """Build ``ToolResult(status="error", success=False, error=..., result={"code": ...})``."""
        payload: Dict[str, Any] = {"code": self.code}
        if self.manifest is not None:
            payload["manifest"] = self.manifest.model_dump(mode="json")
        elif self.envelope is not None:
            payload["manifest"] = self.envelope.model_dump(mode="json")
        return ToolResult(status="error", success=False, result=payload, error=self.message)
