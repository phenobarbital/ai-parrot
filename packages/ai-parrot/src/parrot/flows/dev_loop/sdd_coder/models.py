"""Pydantic payloads of the sdd_coder kernel (spec §2 "Data Models"). No logic, no I/O."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from parrot.flows.dev_loop.models import (  # verified: models/base.py:407, :497
    DevAgentBackend,
    DevelopmentOutput,
    SeatUsageSummary,
)

SeatKind = Literal["mcp", "native"]
TaskOutcome = Literal["queued", "running", "merged", "merge_conflict", "failed", "fidelity_violation", "retry_native"]
ERROR_CODES: frozenset[str] = frozenset(
    {
        "feature_not_found",
        "index_unreadable",
        "dependency_cycle",
        "worktree_outside_base",
        "task_not_pending",
        "task_not_in_plan",
        "task_already_running",
        "seat_unavailable",
        "roster_empty",
        "job_not_found",
        "branch_not_found",
        "dirty_feature_worktree",
        "dirty_task_worktree",
        "merge_conflict",
        "fidelity_violation",
        "invalid_arguments",
        "internal_error",
    }
)
_TASK_ID_RE = re.compile(r"^TASK-\d{1,5}$")


class RosterSeat(BaseModel):
    """One seat of the model roster (config-driven, spec G8).

    `backend` is required for `kind == "mcp"` and must be omitted for
    `kind == "native"` (the Haiku seat, a native Claude Code sub-agent).
    """

    label: str = Field(..., min_length=1, max_length=32)
    kind: SeatKind = "mcp"
    backend: Optional[DevAgentBackend] = None
    model: str = ""
    fallback_model: str = ""

    @model_validator(mode="after")
    def _backend_required_for_mcp(self) -> "RosterSeat":
        """kind='mcp' ⇒ backend must be set; kind='native' ⇒ backend must be None.

        A `model_validator` (rather than a `field_validator` on `backend`) is
        used because Pydantic v2 field validators do not run against a field's
        default value unless `validate_default=True` — and `backend` defaults
        to `None`, which is exactly the case that must be rejected for `kind='mcp'`.
        """
        if self.kind == "mcp" and not self.backend:
            raise ValueError(f"RosterSeat {self.label!r}: backend is required when kind='mcp'")
        if self.kind == "native" and self.backend is not None:
            raise ValueError(f"RosterSeat {self.label!r}: backend must be None when kind='native'")
        return self


class RosterConfig(BaseModel):
    """Ordered roster + engine bounds (spec: wait ≤ 300 s)."""

    seats: List[RosterSeat] = Field(..., min_length=1)
    wait_timeout_max_s: int = Field(default=300, ge=10, le=300)
    smoke_timeout_s: int = Field(default=60, ge=5, le=300)


class SeatProbeResult(BaseModel):
    """Outcome of probing one seat at first use (spec G8)."""

    label: str
    kind: SeatKind
    backend: Optional[str] = None
    available: bool
    model_used: str = ""
    fallback_used: bool = False
    reason: str = ""


class PlannedTask(BaseModel):
    """A task with its assigned seat inside one chunk."""

    task_id: str
    task_file: str
    title: str = ""
    seat_label: str
    native: bool = False
    backend: Optional[str] = None
    model: str = ""


class PlanChunk(BaseModel):
    """One slice of the current wave, sized to at most `len(available_roster)`."""

    index: int = Field(..., ge=0)
    tasks: List[PlannedTask]


class OrphanBranch(BaseModel):
    """A `<feature>--TASK-NNN-a<n>` branch with no live job (design research S2)."""

    task_id: str
    branch: str
    worktree_path: str = ""
    commits: int = 0
    files: List[str] = Field(default_factory=list)


class CoderPlan(BaseModel):
    """`coder_plan` payload: next wave sliced into distinct-seat chunks."""

    feature_id: str
    feature: str
    feature_branch: str
    index_path: str
    pending: List[str]
    blocked: List[str]
    chunks: List[PlanChunk]
    roster: List[SeatProbeResult]
    orphan_branches: List[OrphanBranch]


class AttemptRecord(BaseModel):
    """Per-attempt telemetry (spec G9, design research S8)."""

    attempt: int = Field(..., ge=1, le=3)
    seat_label: str
    backend: str = ""
    model: str = ""
    started_at: str
    ended_at: str = ""
    duration_s: float = 0.0
    usage: Dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    attempt_uid: str = ""
    """Globally unique id for this attempt, minted by the engine.

    The telemetry join key. `attempt` cannot serve: it restarts at 1 on every
    `_run_task` invocation (engine.py:592) while each chunk gets a fresh job id
    (jobs.py:30), so a task re-dispatched in a later job reuses the same
    number. Defaults empty; the engine sets it.
    """
    job_id: str = ""
    resolved_model: str = ""
    """The model the dispatcher actually resolved, which can differ from the
    roster seat's configured `model` via `_resolve_model`'s client fallbacks
    (dispatchers/llm.py:879)."""
    turns: int = 0
    terminal: str = "completed"
    """One of "completed", "failed" or "salvaged"."""
    error_class: str = ""
    """Exception type name only. The full message stays in `error` and never
    reaches the dataset."""
    declared_files: Optional[int] = None
    """Count of files the task declared, captured DURING the attempt: the task
    file lives in the worktree that /sdd-done removes."""
    declared_files_known: bool = False
    turns_with_unknown_usage: int = 0
    turn_series: List[Tuple[int, Optional[int], Optional[int]]] = Field(default_factory=list)
    """Per turn: (round_number, input_tokens or None, output_tokens or None)."""
    budget_report: Dict[str, Any] = Field(default_factory=dict)
    """BudgetReport.model_dump() when an observational ledger was bound."""


class TaskResult(BaseModel):
    """Outcome of consolidating one task's latest attempt."""

    task_id: str
    outcome: TaskOutcome
    branch: str = ""
    worktree_path: str = ""
    attempts: List[AttemptRecord] = Field(default_factory=list)
    conflict_files: List[str] = Field(default_factory=list)
    unexpected_files: List[str] = Field(default_factory=list)
    diagnostics: str = ""
    development_output: Optional[DevelopmentOutput] = None


class NativePrep(BaseModel):
    """Sub-worktree handed to `sdd-worker` for a `native` (Haiku) planned task."""

    task_id: str
    task_file: str
    branch: str
    worktree_path: str
    seat_label: str


class CoderJob(BaseModel):
    """A running/finished chunk dispatch, tracked by the in-memory `JobTable`."""

    job_id: str
    feature_id: str
    chunk_task_ids: List[str]
    state: Literal["running", "done", "error"]
    started_at: str
    ended_at: str = ""
    tasks: List[TaskResult] = Field(default_factory=list)
    error: str = ""


class CoderJobView(CoderJob):
    """A `CoderJob` snapshot plus its per-seat roll-up, as `coder_status`/`coder_wait` return it.

    `seats` is computed by `summary.summarize_job_seats` over this one job at
    read time — never journaled — so the orchestrator prints the Seats table
    from data instead of re-deriving it from `tasks[*].attempts[*]` by hand.
    """

    seats: List[SeatUsageSummary] = Field(default_factory=list)


class CleanupReport(BaseModel):
    """Result of `coder_cleanup` — sub-worktrees removed vs. kept for inspection."""

    removed: List[str] = Field(default_factory=list)
    kept: List[str] = Field(default_factory=list)


class CoderError(BaseModel):
    """A domain failure, closed to `ERROR_CODES`."""

    code: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("code")
    @classmethod
    def _known_code(cls, v: str) -> str:
        """Only codes from ERROR_CODES are allowed (closed set, spec §2)."""
        if v not in ERROR_CODES:
            raise ValueError(f"unknown error code {v!r}")
        return v


class CoderResult(BaseModel):
    """Tool envelope — mirrors parrot_tools OperationResult; core MUST NOT import parrot_tools."""

    status: Literal["ok", "error"]
    operation: str
    data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[CoderError] = None
    elapsed_ms: int = Field(default=0, ge=0)


class _Args(BaseModel):
    """Base for every MCP tool argument model — no undeclared keys accepted (design research S6)."""

    model_config = ConfigDict(extra="forbid")


def _check_task_id(v: str) -> str:
    """Reject anything that does not match `^TASK-\\d{1,5}$`."""
    if not _TASK_ID_RE.fullmatch(v):
        raise ValueError(f"invalid task id {v!r}; expected TASK-<1-5 digits>")
    return v


def _check_task_ids(vs: List[str]) -> List[str]:
    """Apply `_check_task_id` to every element of a list."""
    return [_check_task_id(v) for v in vs]


def _check_abs(v: str) -> str:
    """Reject a non-absolute worktree path."""
    if not os.path.isabs(v):
        raise ValueError("worktree must be an absolute path")
    return v


class CoderPlanArgs(_Args):
    feature: str
    worktree: str
    _wt = field_validator("worktree")(_check_abs)


class CoderRunChunkArgs(_Args):
    feature: str
    worktree: str
    task_ids: List[str] = Field(..., min_length=1)
    _wt = field_validator("worktree")(_check_abs)
    _tids = field_validator("task_ids")(_check_task_ids)


class CoderPrepareNativeArgs(_Args):
    feature: str
    worktree: str
    task_id: str
    _wt = field_validator("worktree")(_check_abs)
    _tid = field_validator("task_id")(_check_task_id)


class CoderMergeArgs(CoderPrepareNativeArgs):
    """Same shape as prepare_native."""


class CoderWaitArgs(_Args):
    job_id: str
    timeout_seconds: int = Field(default=120, ge=1, le=300)


class CoderStatusArgs(_Args):
    job_id: str


class CoderCleanupArgs(_Args):
    feature: str
    worktree: str
    keep_conflicted: bool = True
    _wt = field_validator("worktree")(_check_abs)
