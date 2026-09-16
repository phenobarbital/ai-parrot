"""Pydantic payloads of the sdd_coder kernel (spec §2 "Data Models"). No logic, no I/O."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Literal, Optional, Tuple
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedback
from parrot.knowledge.wiki.ledger.coder_reviews import CoderReview
from parrot.knowledge.wiki.ledger.coder_suspensions import ModelKey, SuspensionPolicy, SuspensionReason

from parrot.flows.dev_loop.models import (  # verified: models/base.py:407, :497
    DevAgentBackend,
    DevelopmentOutput,
    SeatUsageSummary,
)

from parrot.flows.dev_loop.sdd_coder.complexity_models import (
    ComplexityAssessment,
    ComplexityBlock,
    ComplexityPolicy,
)

SeatKind = Literal["mcp", "native"]
TaskOutcome = Literal[
    "queued",
    "running",
    "merged",
    "merge_conflict",
    "failed",
    "fidelity_violation",
    "retry_native",
    "not_dispatched",
]
"""`not_dispatched` (FEAT-559): a queued task lost its seat before admission --
no synthetic attempt is recorded; the reason lives in `TaskResult.diagnostics`."""

ExecutionStatus = Literal["active", "exhausted", "recovery_required", "closed"]
"""Execution-pool lifecycle state (FEAT-559 spec §2 "Execution lifecycle, ownership and recovery")."""

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
        # Complexity routing error codes (FEAT-561 spec §2)
        "complexity_contract_invalid",
        "complexity_plan_stale",
        "complex_model_unavailable",
        "complexity_audit_failed",
        # FEAT-559: execution pool / suspension lifecycle errors (spec §2).
        "execution_required",
        "execution_not_found",
        "execution_scope_mismatch",
        "execution_config_mismatch",
        "execution_closed",
        "execution_in_progress",
        "execution_busy",
        "execution_recovery_required",
        "plan_stale",
        "model_suspended",
        "suspension_history_unavailable",
        "suspension_persistence_failed",
    }
)
_TASK_ID_RE = re.compile(r"^TASK-\d{1,5}$")


def _check_uuid(v: str) -> str:
    """Reject anything that is not a valid UUID string.

    Spec §2 architecture overview: "a caller-generated UUID `execution_id`".
    Applied only to fields where a fresh explicit id is always supplied by
    the caller -- NOT to the legacy-compatible `execution_id: str = ""`
    telemetry fields on `CoderPlan`/`CoderJob`/`AttemptRecord`/`NativePrep`,
    which must keep parsing historical records that predate this feature.
    """
    try:
        UUID(v)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"execution_id must be a valid UUID string, got {v!r}") from exc
    return v


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


LintFormatter = Literal["auto", "black", "ruff", "none"]


class LintConfig(BaseModel):
    """Engine-owned per-task lint pass, run at the merge boundary instead of by the coder LLM.

    Attributes:
        autofix: Run ``ruff check --fix`` + the formatter on the task's changed ``.py`` files
            and commit the result on the attempt branch before merging.
        formatter: ``auto`` picks black when the repo's ``pyproject.toml`` has ``[tool.black]``,
            ``ruff format`` when it has ruff format settings, and no formatter otherwise (so a
            repo with no declared style is never reformatted to a default line length).
        error_select: Correctness rules (syntax errors, undefined names) reported separately as
            ``LintReport.errors`` so the orchestrator fixes them; everything else is residual
            style debt left for the full pass in ``/sdd-done``. Never blocks the merge.
    """

    autofix: bool = True
    formatter: LintFormatter = "auto"
    error_select: List[str] = Field(default_factory=lambda: ["E9", "F63", "F7", "F82"])


class LintReport(BaseModel):
    """Outcome of the engine lint pass over one task branch."""

    formatter: str = "none"
    fixed_files: List[str] = Field(default_factory=list)
    commit: str = ""
    errors: List[str] = Field(default_factory=list)
    residual_count: int = 0
    residual: List[str] = Field(default_factory=list)
    tool_error: str = ""


class FeedbackConfig(BaseModel):
    """Bound historical lessons and allow a measured baseline without injection."""

    enabled: bool = True
    max_tokens: int = Field(default=1800, ge=0, le=6000)
    max_age_days: int = Field(default=90, ge=1, le=365)


class RosterConfig(BaseModel):
    """Ordered roster + engine bounds (spec: wait ≤ 300 s)."""

    seats: List[RosterSeat] = Field(..., min_length=1)
    wait_timeout_max_s: int = Field(default=300, ge=10, le=300)
    smoke_timeout_s: int = Field(default=60, ge=5, le=300)
    lint: LintConfig = Field(default_factory=LintConfig)
    feedback: FeedbackConfig = Field(default_factory=FeedbackConfig)
    complexity: ComplexityPolicy = Field(default_factory=ComplexityPolicy)
    suspension_policy: SuspensionPolicy = Field(default_factory=SuspensionPolicy)
    """FEAT-559: cooldown/summary-budget policy shared by every execution pool for this roster."""


class SeatProbeResult(BaseModel):
    """Outcome of probing one seat at first use (spec G8).

    `probe_*` fields (FEAT-559) are structured failure metadata for the
    ONE probe call that ran on this seat, so roster wiring need not infer
    a failure from prose. They are independent of `fallback_used`: a
    primary probe can fail (recorded here) while a configured fallback
    still succeeds, leaving `available=True`.
    """

    label: str
    kind: SeatKind
    backend: Optional[str] = None
    available: bool
    model_used: str = ""
    fallback_used: bool = False
    reason: str = ""
    probe_uid: str = ""
    probe_observed_at: str = ""
    probe_duration_s: float = 0.0
    probe_exception_class: str = ""


class PlannedTask(BaseModel):
    """A task with its assigned seat inside one chunk."""

    task_id: str
    task_file: str
    title: str = ""
    seat_label: str
    native: bool = False
    backend: Optional[str] = None
    model: str = ""
    assessment_id: str = ""


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
    assessments: Dict[str, ComplexityAssessment] = Field(default_factory=dict)
    """Task ID to ComplexityAssessment mapping for this plan's tasks."""
    routing_blocks: List[ComplexityBlock] = Field(default_factory=list)
    """Routing blocks preventing dispatch of affected tasks."""
    execution_id: str = ""
    """FEAT-559: the execution this plan was cached under. Empty only for
    plans predating this feature; a new plan always carries its execution."""
    pool_generation: int = Field(default=0, ge=0)
    """Execution pool generation this plan was computed against; `run_chunk`
    rejects a stale plan (`plan_stale`) once the generation has moved on."""


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
    assessment_id: str = ""
    """ComplexityAssessment ID for this attempt, enabling audit trail."""
    execution_id: str = ""
    """FEAT-559: the execution this attempt ran under. Empty for attempts
    recorded before this feature landed; new attempts always carry one."""


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
    lint: Optional[LintReport] = None


class NativePrep(BaseModel):
    """Sub-worktree handed to `sdd-worker` for a `native` (Haiku) planned task."""

    task_id: str
    task_file: str
    branch: str
    worktree_path: str
    seat_label: str
    model: str = "haiku"
    attempt_uid: str = ""
    coder_feedback: str = ""
    assessment_id: str = ""
    """ComplexityAssessment ID for native attempts, enabling attribution."""
    execution_id: str = ""
    """FEAT-559: the execution this native reservation belongs to."""


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
    execution_id: str = ""
    """FEAT-559: the execution that dispatched this chunk. Empty only for
    jobs journaled before this feature; `JobTable.create` always requires
    one for new jobs (never minted implicitly)."""


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


class PoolSeatView(BaseModel):
    """One seat's admission state inside an execution pool (spec §2 `PoolSeatView`).

    `configured_model`/`backend` are the roster's static configuration;
    `resolved_key` is the effective `ModelKey` once the seat has actually
    been probed/dispatched (absent before then). Runtime locks/conditions
    belong to the pool's own runtime object, never to this serialized view.
    """

    model_config = ConfigDict(extra="forbid")

    label: str = Field(..., min_length=1, max_length=32)
    kind: SeatKind
    backend: Optional[str] = None
    configured_model: str = ""
    resolved_key: Optional[ModelKey] = None
    available: bool = False
    busy: bool = False
    suspended: bool = False
    probe_unavailable: bool = False
    reason: str = ""
    suspension_id: str = ""
    suspended_until: str = ""


class ExecutionPoolView(BaseModel):
    """`coder_begin_execution` / status payload: one execution's pool state (spec §2 `ExecutionPoolView`).

    Bound immutably to `(execution_id, feature_id, worktree_path)` for its
    whole lifetime; `generation` increments on every suspension so a stale
    cached plan can be rejected before it reaches admission.
    """

    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(..., min_length=1)
    feature_id: str = Field(..., min_length=1)
    worktree_path: str = Field(..., min_length=1)
    status: ExecutionStatus
    generation: int = Field(..., ge=0)
    seats: List[PoolSeatView] = Field(default_factory=list)
    fallback_required: bool = False
    fallback_reason: str = ""
    persisted: bool = True
    persistence_degraded: bool = False

    _exec = field_validator("execution_id")(_check_uuid)


class ExecutionSnapshot(BaseModel):
    """Durable per-execution journal payload (spec §2 `ExecutionSnapshot`; architecture
    "Execution lifecycle, ownership and recovery" -- journaled under
    `<feature-worktree>/.sdd-coder/executions/<uuid>.json`).

    Carries everything a restart needs to replay: scope/fingerprint binding,
    admitted attempts, native reservations, outstanding jobs and both local
    (this execution's own) and inherited (durable, pre-existing) exclusions.
    """

    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(..., min_length=1)
    feature_id: str = Field(..., min_length=1)
    worktree_path: str = Field(..., min_length=1)
    roster_fingerprint: str = Field(..., min_length=1)
    admitted_attempts: Dict[str, str] = Field(default_factory=dict)
    """attempt_uid -> task_id."""
    native_reservations: Dict[str, str] = Field(default_factory=dict)
    """task_id -> reservation id."""
    outstanding_job_ids: List[str] = Field(default_factory=list)
    local_exclusions: List[ModelKey] = Field(default_factory=list)
    inherited_exclusions: List[ModelKey] = Field(default_factory=list)
    status: ExecutionStatus
    generation: int = Field(..., ge=0)

    _exec = field_validator("execution_id")(_check_uuid)


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
    execution_id: str = Field(..., min_length=1)
    _wt = field_validator("worktree")(_check_abs)
    _exec = field_validator("execution_id")(_check_uuid)


class CoderRunChunkArgs(_Args):
    feature: str
    worktree: str
    task_ids: List[str] = Field(..., min_length=1)
    execution_id: str = Field(..., min_length=1)
    _wt = field_validator("worktree")(_check_abs)
    _tids = field_validator("task_ids")(_check_task_ids)
    _exec = field_validator("execution_id")(_check_uuid)


class CoderPrepareNativeArgs(_Args):
    feature: str
    worktree: str
    task_id: str
    execution_id: str = Field(..., min_length=1)
    _wt = field_validator("worktree")(_check_abs)
    _tid = field_validator("task_id")(_check_task_id)
    _exec = field_validator("execution_id")(_check_uuid)


class CoderMergeArgs(CoderPrepareNativeArgs):
    """Same shape as prepare_native."""


class CoderRecordFeedbackArgs(CoderPlanArgs):
    """Record a worker-confirmed correction from a known coder attempt."""

    feedback: CoderFeedback


class CoderRecordReviewArgs(CoderPlanArgs):
    """Complete review measurement, including zero-fix deliveries."""

    review: CoderReview


class CoderWaitArgs(_Args):
    job_id: str
    timeout_seconds: int = Field(default=120, ge=1, le=300)


class CoderStatusArgs(_Args):
    job_id: str


class CoderCleanupArgs(_Args):
    feature: str
    worktree: str
    execution_id: str = Field(..., min_length=1)
    keep_conflicted: bool = True
    _wt = field_validator("worktree")(_check_abs)
    _exec = field_validator("execution_id")(_check_uuid)


class CoderFeedbackReportArgs(_Args):
    """`coder_feedback_report` arguments -- read-only and repository-wide.

    Deliberately split from `CoderPlanArgs` (FEAT-559): the feedback report
    never starts, resumes or requires an execution, unlike the other seven
    scoped orchestration/review tools.
    """

    feature: str
    worktree: str
    _wt = field_validator("worktree")(_check_abs)


class SuspendModelArgs(_Args):
    """`coder_suspend_model` arguments.

    The target model is resolved by the engine from `attempt_uid` -- the
    caller never names a model directly, so it cannot invent an arbitrary
    suspension target.
    """

    execution_id: str = Field(..., min_length=1)
    attempt_uid: str = Field(..., min_length=1, max_length=128)
    reason: SuspensionReason
    evidence_ref: str = Field(default="", max_length=300)
    _exec = field_validator("execution_id")(_check_uuid)


class CoderEndExecutionArgs(_Args):
    """`coder_end_execution` arguments (FEAT-559 TASK-3283).

    Deliberately minimal: `coder_begin_execution` reuses `CoderPlanArgs`
    (identical feature/worktree/execution_id shape); no other existing model
    has ONLY `execution_id`, so this one small class is unavoidable here --
    a disclosed exception to TASK-3283's own file scope (see its Completion
    Note), added in this ledger-adjacent models module rather than guessed
    into toolkit.py.
    """

    execution_id: str = Field(..., min_length=1)
    _exec = field_validator("execution_id")(_check_uuid)
