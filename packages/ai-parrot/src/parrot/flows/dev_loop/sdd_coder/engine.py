"""SddCoderEngine — stateless-by-design orchestration kernel (FEAT-549, spec §3 M4).

Every call re-reads the per-spec index from the feature worktree. Dispatch is
direct per attempt (design research S1) — NOT DevAgentPool.run_wave.

This module implements the READ side (plan, prepare_native) and the
CONSOLIDATION side (merge, cleanup, orphan discovery, journal) of the
engine. The DISPATCH side (`run_chunk`, `wait`, `_run_attempt`,
`_research_for`, `_labels_for`, `AttemptTelemetryCollector`) is stubbed here
and filled in by TASK-3121 — the signatures below are final.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import typing
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from parrot.flows.dev_loop.sdd_coder.models import ExecutionPoolView

from parrot import conf
from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedback, CoderFeedbackReceipt, CoderFeedbackStore
from parrot.knowledge.wiki.ledger.coder_reviews import (
    CoderReview,
    CoderReviewMeasurement,
    CoderReviewReport,
    CoderReviewStore,
)
from parrot.knowledge.wiki.store import estimate_tokens
from parrot.flows.dev_loop.agent_builder import build_dispatcher  # verified: agent_builder.py:135
from parrot.flows.dev_loop.models import (  # verified: models/base.py:412, :763, :497, :340, :458
    DevAgentSpec,
    DevelopmentOutput,
    DispatchLabels,
    ResearchOutput,
    TaskScopedBrief,
)
from parrot.flows.dev_loop.session_state import DispatchCompleted  # verified: session_state.py:476
from parrot.flows.dev_loop.task_scheduler import TaskScheduler  # verified: task_scheduler.py:53
from parrot.flows.dev_loop.worktree_manager import (  # verified: worktree_manager.py:75, :41
    SubWorktreeManager,
    SubWorktreeMergeError,
)
from parrot.flows.dev_loop.sdd_coder.fidelity import check_banned_imports, check_fidelity, parse_task_files
from parrot.flows.dev_loop.test_scope.context import write_attempt_context
from parrot.flows.dev_loop.test_scope.datatypes import AttemptContext
from parrot.flows.dev_loop.sdd_coder.jobs import JobTable
from parrot.flows.dev_loop.sdd_coder.lint import run_lint_pass
from parrot.flows.dev_loop.sdd_coder.models import (
    AttemptRecord,
    CleanupReport,
    CoderJob,
    CoderPlan,
    ExecutionSnapshot,
    NativePrep,
    OrphanBranch,
    PlannedTask,
    RosterConfig,
    RosterSeat,
    SeatProbeResult,
    TaskResult,
)
from parrot.flows.dev_loop.sdd_coder.complexity_models import (
    ComplexityAssessment,
    ComplexityBlock,
)
from parrot.flows.dev_loop.sdd_coder.complexity_collectors import (
    collect_complexity,
    validate_complexity_snapshot,
)
from parrot.flows.dev_loop.sdd_coder.complexity import (
    ComplexityContractError,
    evaluate_complexity,
)
from parrot.flows.dev_loop.sdd_coder.roster import ChunkAssigner, RosterProbe, available_seats, eligible_seats
from parrot.flows.dev_loop.sdd_coder.pool import ExecutionPool, roster_fingerprint
from parrot.flows.dev_loop.models.telemetry import AttemptTelemetry
from parrot.flows.dev_loop.sdd_coder.telemetry import (
    CoderTelemetrySink,
    OutcomeRow,
    build_attempt_row,
)
from parrot.knowledge.wiki.ledger.coder_suspensions import (
    CoderSuspensionStore,
    ModelKey,
    SuspensionReason,
    SuspensionReceipt,
    SuspensionRecord,
)

_ORPHANS_INDEX_NAME = "_orphans.json"
_CONFLICT_LINE = re.compile(r"^CONFLICT \([^)]*\):.* in (.+)$", re.M)


class CoderFailure(Exception):
    """Domain failure; `code` ∈ ERROR_CODES (toolkit maps it to CoderResult.error)."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


async def _git(*args: str, cwd: str) -> Tuple[int, str, str]:
    """Run git in `cwd`; returns (rc, stdout, stderr). Shape copied from worktree_manager.py:113."""
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def _consolidate_diff_base(feature_branch: str, branch: str, *, cwd: str) -> str:
    """Resolve the correct diff base for `branch`'s own changes against `feature_branch`.

    Normally this is `git merge-base feature_branch branch` (spec-review R1 / the
    triple-dot rationale in `_consolidate`): `branch` has not been merged into
    `feature_branch` yet, so the merge-base IS the commit `branch` forked from, and
    diffing from there sees only `branch`'s own commits — not a sibling task's merge
    that landed on `feature_branch` first under the same `_merge_lock`.

    FEAT-553 code-review finding: `sdd-worker.md`'s documented `merge_conflict`
    recovery — resolve the conflict manually with `git merge <branch>` directly in the
    feature worktree, commit, then call `coder_merge` (→ `_consolidate`) again — makes
    `branch` an ANCESTOR of `feature_branch` by the second `_consolidate` call. At that
    point `merge-base(feature_branch, branch)` collapses to `branch`'s own tip (it is
    now fully contained in `feature_branch`'s history), so a `feature_branch...branch`
    diff comes back EMPTY and silently skips both `check_fidelity` and
    `check_banned_imports` for whatever the manual resolution introduced.

    When that happens, find the merge commit in `feature_branch`'s history whose
    parents include `branch`'s tip, and return its OTHER parent (the pre-merge
    `feature_branch` tip) instead — diffing from there sees exactly what merging
    `branch` in introduced, including any manual conflict-resolution edits. If no such
    merge commit exists (e.g. an unexpected fast-forward, which `merge_sequential`'s
    `--no-ff` and a genuinely conflicted manual merge both rule out in practice),
    `branch`'s own tip is returned — the same (empty-diff) behavior as before this fix,
    never a regression.
    """
    _rc, merge_base, _err = await _git("merge-base", feature_branch, branch, cwd=cwd)
    merge_base = merge_base.strip()
    _rc, branch_tip, _err = await _git("rev-parse", branch, cwd=cwd)
    branch_tip = branch_tip.strip()
    if merge_base != branch_tip:
        return merge_base
    # `branch` is already an ancestor of `feature_branch` — find the specific merge
    # commit that incorporated it. `--merges` bounds the scan to merge commits only,
    # not the entire (potentially large) history.
    _rc, out, _err = await _git("log", "--merges", "--format=%H %P", feature_branch, cwd=cwd)
    for line in out.splitlines():
        parts = line.split()
        if not parts:
            continue
        parents = parts[1:]
        if branch_tip in parents:
            others = [p for p in parents if p != branch_tip]
            if others:
                # `others[0]` (the merge's other parent — feature_branch's tip right
                # before this merge) is a SIBLING of `branch`, not necessarily its
                # ancestor: both typically descend from the same earlier fork point,
                # so a plain double-dot diff against it would also pick up whatever
                # else landed on feature_branch in between (a false unexpected-file
                # / false banned-import positive). One more merge-base resolves back
                # to that true, shared fork point.
                _rc, base2, _err = await _git("merge-base", others[0], branch, cwd=cwd)
                return base2.strip()
    return branch_tip


@dataclass(frozen=True)
class _FeatureCtx:
    """Resolved per-call context: which feature, which worktree, which branch."""

    worktree: str
    feature_id: str
    feature: str
    feature_branch: str
    index_path: str
    spec_path: str
    base_branch: str


class AttemptTelemetryCollector:
    """Duck-typed session host (dispatchers/_shared.py:92-117 -> host.apply(action)).

    Captures usage + timing per attempt. `dispatch()` binds this object as
    `session_host`; every dispatch event reaching the bound host is folded
    into a `DevLoopAction` and handed to `apply()` — only `DispatchCompleted`
    carries usage (session_state.py:476-484), so every other action kind is
    a no-op here.
    """

    def __init__(
        self,
        *,
        attempt: int,
        seat: RosterSeat,
        attempt_uid: Optional[str] = None,
        job_id: Optional[str] = None,
        execution_id: Optional[str] = None,
    ) -> None:
        self.attempt, self.seat = attempt, seat
        self.attempt_uid = attempt_uid or ""
        self.job_id = job_id or ""
        self.execution_id = execution_id or ""
        self.started = time.monotonic()
        self.started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.usage: Dict[str, Any] = {}
        self.error = ""
        self.error_class = ""
        """Set by `_run_attempt`'s `except` block alongside `.error`. Used by
        `record()` only as a fallback when `on_attempt_telemetry` never
        fired (a pre-dispatch failure), since `AttemptTelemetry.error_class`
        is normally the source of truth."""
        self.telemetry: Optional[Any] = None
        self.declared_files: Optional[int] = None
        self.declared_files_known: bool = False

    def on_attempt_telemetry(self, telemetry: AttemptTelemetry) -> None:
        """Receive the dispatcher's terminal telemetry (FEAT-554, spec §10 R3).

        Called by `LLMCodeDispatcher._emit_attempt_telemetry` through the bound
        session host. Separate from `apply()` because this payload deliberately
        does NOT travel as a `DispatchCompleted` action: that projection copies
        only seven whitelisted `usage` scalars and swallows validation errors,
        so a per-turn series or a budget report would vanish in silence.
        """
        self.telemetry = telemetry

    def apply(self, action: Any, origin: Any = None) -> None:
        """Called by _apply_to_session_host for every dispatch event. Keep only usage from 'dispatch/completed'."""
        if not isinstance(action, DispatchCompleted):
            return
        for field in (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
            "total_cost_usd",
            "num_turns",
            "duration_ms",
        ):
            value = getattr(action, field, None)
            if value is not None:
                self.usage[field] = value

    def record(self) -> AttemptRecord:
        # Extract telemetry data if available
        error_class = ""
        resolved_model = ""
        turns = 0
        terminal = "completed"
        turns_with_unknown_usage = 0
        turn_series = []
        budget_report = {}

        usage = dict(self.usage)
        if self.telemetry is not None:
            error_class = self.telemetry.error_class
            resolved_model = self.telemetry.resolved_model
            turns = self.telemetry.turns
            terminal = self.telemetry.terminal
            turns_with_unknown_usage = self.telemetry.turns_with_unknown_usage

            # Convert turn series to the expected format
            turn_series = [(tu.round_number, tu.input_tokens, tu.output_tokens) for tu in self.telemetry.turn_series]

            if self.telemetry.budget_report:
                budget_report = self.telemetry.budget_report

            # `self.usage` comes from `apply()`'s `DispatchCompleted` action,
            # which is only populated on the SUCCESS path — a failed dispatch
            # burns real tokens but may never produce that action at all
            # (spec Goal 6: "record a failed attempt's consumption too").
            # `AttemptTelemetry.provider_input_tokens`/`_output_tokens` are
            # populated on every exit path (llm.py's dispatch `finally`), so
            # fill the gap from there rather than losing the data.
            if usage.get("input_tokens") is None and self.telemetry.provider_input_tokens is not None:
                usage["input_tokens"] = self.telemetry.provider_input_tokens
            if usage.get("output_tokens") is None and self.telemetry.provider_output_tokens is not None:
                usage["output_tokens"] = self.telemetry.provider_output_tokens
        elif self.error:
            # `on_attempt_telemetry` never fired: the failure happened before
            # `dispatch()` was even entered (e.g. `manager.create()` or
            # `build_dispatcher()` raising in `_run_attempt`'s try block, per
            # the code-review-fix comment there). No `AttemptTelemetry` was
            # ever produced, so `terminal` must not default to "completed"
            # for a genuinely failed attempt.
            terminal = "failed"
            error_class = self.error_class

        return AttemptRecord(
            attempt=self.attempt,
            seat_label=self.seat.label,
            backend=self.seat.backend or "native",
            model=self.seat.model,
            started_at=self.started_at,
            ended_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            duration_s=round(time.monotonic() - self.started, 3),
            usage=usage,
            error=self.error,
            attempt_uid=self.attempt_uid,
            job_id=self.job_id,
            resolved_model=resolved_model,
            turns=turns,
            terminal=terminal,
            error_class=error_class,
            execution_id=self.execution_id,
            declared_files=self.declared_files,
            declared_files_known=self.declared_files_known,
            turns_with_unknown_usage=turns_with_unknown_usage,
            turn_series=turn_series,
            budget_report=budget_report,
        )


class SddCoderEngine:
    """See spec §3 M4 for the method contracts.

    Stateless-by-design: every call re-reads the per-spec index. The only
    state kept across calls is the probed roster/assigner (cached by
    `open()`), the job table, and the `SubWorktreeManager` instances keyed
    by `"<TASK-NNN>.a<attempt>"` — one manager per attempt so a merge only
    ever touches that attempt's own branch.
    """

    def __init__(
        self,
        *,
        roster: RosterConfig,
        probe: Optional[RosterProbe] = None,
        redis_url: Optional[str] = None,
        worktree_base_path: Optional[str] = None,
        dispatcher_builder: Callable[..., Any] = build_dispatcher,
        stream_ttl_seconds: int = 3600,
        telemetry_dir: Optional[str] = None,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.roster, self._probe = roster, probe or RosterProbe(smoke_timeout_s=roster.smoke_timeout_s)
        self._redis_url = redis_url if redis_url is not None else conf.REDIS_URL
        self._base_path = os.path.realpath(worktree_base_path or conf.WORKTREE_BASE_PATH)
        self._dispatcher_builder, self._stream_ttl = dispatcher_builder, stream_ttl_seconds
        self.seats: List[RosterSeat] = []
        self.probe_results: List[SeatProbeResult] = []
        self._assigner: Optional[ChunkAssigner] = None
        self._plan_cache: Dict[str, CoderPlan] = (
            {}
        )  # feature_id -> most recently computed plan (see plan()/_cached_plan)
        self._jobs = JobTable()
        self._merge_lock = asyncio.Lock()
        self._managers: Dict[str, SubWorktreeManager] = {}  # key: f"{task_id}.a{attempt}"
        self._job_worktrees: Dict[str, str] = {}  # job_id -> feature worktree, for re-journaling in wait()
        self._opened = False
        # attempt_uid -> last emitted OutcomeRow.event_seq. Persists across
        # `_run_task`/`merge()` calls so a re-merge after a manual conflict
        # repair gets event_seq=2 (not a re-derived duplicate of 1) for the
        # SAME attempt_uid (spec AC-19).
        self._event_seq_counters: Dict[str, int] = {}
        # task_id -> the most recent AttemptRecord used for consolidation.
        # `merge()` has no `AttemptRecord` of its own (it only resolves a
        # branch/worktree from `self._managers`), so it reads this to attach
        # the correct attempt_uid/job_id to its re-merge outcome row. Native
        # tasks never populate this (they bypass `_run_attempt` entirely, per
        # spec's non-goal: no telemetry rows for the native/codex seats), so
        # `merge()` on a native task correctly emits nothing.
        self._latest_attempt: Dict[str, AttemptRecord] = {}
        # Manager keys (f"{task_id}.a{attempt}") handed out by `prepare_native` whose
        # background `Agent` has not been consolidated through `merge()` yet. The engine
        # never sees a native attempt run (no job row, so `_jobs.running_task_ids()` is
        # blind to it); `cleanup()` must not remove these worktrees while the coder may
        # still be working inside them (FEAT-555 incident: TASK-230-a1 was deleted mid-run).
        self._native_inflight: set[str] = set()
        # FEAT-559: manager key (worker id, see `_worker_id`) -> owning execution_id,
        # or "" for a legacy/no-execution call. `cleanup()`/`merge()` use this to
        # never enumerate or touch a DIFFERENT execution's managers (AC-6).
        self._manager_execution: Dict[str, str] = {}
        # FEAT-559: (execution_id, task_id) -> attempt_uid, so a duplicate
        # `prepare_native` call for the same task in the same execution reuses the
        # existing reservation instead of admitting (and worktree-creating) twice.
        self._native_reservations: Dict[Tuple[str, str], str] = {}
        # Attribution for feedback is checked against attempts this engine issued.
        self._feedback_sources: Dict[str, Tuple[str, str, str, str]] = {}
        self._feedback_contexts: Dict[str, str] = {}
        self._feedback_unknown_exposure: set[str] = set()

        # FEAT-559: execution pools (begin_execution/end_execution lifecycle)
        self._executions: Dict[str, ExecutionPool] = {}  # execution_id -> pool
        self._execution_owners: Dict[str, str] = {}  # canonical worktree path -> execution_id (exclusive ownership)
        self._suspension_store: Optional[CoderSuspensionStore] = None

        # Telemetry setup (FEAT-554). `conf.DEV_LOOP_CODER_TELEMETRY` is the
        # master switch — mirrors the same conf-fallback pattern `redis_url`/
        # `worktree_base_path` already use above, so the documented env-var
        # workflow (docs/dev_loop/sdd-coder-orchestrator.md) actually enables
        # the sink, not just the observational ledger in llm.py. An explicit
        # `telemetry_dir` constructor kwarg (e.g. from a test, or a future
        # toolkit YAML override) still wins over conf either way.
        self._sink: Optional[CoderTelemetrySink] = None
        if telemetry_dir is not None or conf.DEV_LOOP_CODER_TELEMETRY:
            from parrot.flows.dev_loop.sdd_coder.telemetry import CoderTelemetrySink, resolve_durable_root

            effective_dir = telemetry_dir if telemetry_dir is not None else (conf.SDD_CODER_TELEMETRY_DIR or None)
            telemetry_root = resolve_durable_root(effective_dir, worktree_base_path=self._base_path)
            self._sink = CoderTelemetrySink(telemetry_root)

    async def open(self) -> None:
        """Probe once; cache seats/assigner. Idempotent. Raises roster_empty when nothing is available.

        NOTE: This is the legacy initialization path. For FEAT-559 execution pools,
        use begin_execution() instead, which reads history before probing.
        """
        if self._opened:
            return
        self.probe_results = await self._probe.probe(self.roster)
        self.seats = available_seats(self.roster, self.probe_results)
        if not self.seats:
            raise CoderFailure(
                "roster_empty", "no roster seat is available", probe=[r.model_dump() for r in self.probe_results]
            )
        self._assigner, self._opened = ChunkAssigner(self.seats), True

    async def begin_execution(
        self,
        feature: str,
        worktree: str,
        execution_id: str,
    ) -> "ExecutionPoolView":
        """Begin a new execution with history-gated startup (FEAT-559 M3).

        Reads durable suspension history BEFORE probing. Binds execution_id
        immutably to the canonical worktree path. Only one active execution
        may own a canonical worktree at a time.

        Args:
            feature: Feature identifier (matches per-spec index header).
            worktree: Absolute path to the feature worktree.
            execution_id: Caller-generated UUID for this execution.

        Returns:
            ExecutionPoolView with the execution's initial state.

        Raises:
            CoderFailure with codes:
                - execution_in_progress: another execution already owns this worktree
                - execution_scope_mismatch: resuming with different feature/worktree
                - execution_config_mismatch: roster changed since execution was created
                - execution_closed: trying to resume a closed execution for new work
                - suspension_history_unavailable: cannot read durable history (fallback_required)
        """
        # Resolve feature context first (validates feature/worktree binding)
        ctx = await self._resolve_feature(feature, worktree)
        canonical_worktree = ctx.worktree

        # Check for existing owner of this worktree
        if canonical_worktree in self._execution_owners:
            existing_id = self._execution_owners[canonical_worktree]
            if existing_id != execution_id:
                raise CoderFailure(
                    "execution_in_progress",
                    f"worktree {canonical_worktree} is already owned by execution {existing_id}",
                    owner_execution_id=existing_id,
                )

        # Check for resume case: same execution_id already exists in memory
        if execution_id in self._executions:
            existing = self._executions[execution_id]
            # Validate scope binding (same feature and worktree)
            if existing.feature_id != ctx.feature_id:
                raise CoderFailure(
                    "execution_scope_mismatch",
                    f"execution {execution_id} is bound to feature {existing.feature_id}, not {ctx.feature_id}",
                )
            if existing.worktree_path != canonical_worktree:
                raise CoderFailure(
                    "execution_scope_mismatch",
                    f"execution {execution_id} is bound to worktree {existing.worktree_path}, not {canonical_worktree}",
                )
            # Validate roster fingerprint (same configuration): a resume with a
            # roster that has since changed is a config mismatch, not a silent
            # no-op -- compare the pool's fingerprint (fixed at its construction)
            # against the CURRENT roster's fingerprint.
            if existing.roster_fingerprint != roster_fingerprint(self.roster):
                raise CoderFailure(
                    "execution_config_mismatch",
                    f"execution {execution_id} was bound to a different roster configuration",
                )
            # Check if closed
            if existing.view().status == "closed":
                raise CoderFailure(
                    "execution_closed",
                    f"execution {execution_id} is closed and cannot start new work",
                )
            # Idempotent resume: return current view
            return existing.view()

        # Check for durable snapshot (after MCP restart): read and restore from disk
        durable_snapshot = await self._read_execution_snapshot(canonical_worktree, execution_id)
        if durable_snapshot is not None:
            # Validate scope binding against durable record
            if durable_snapshot.feature_id != ctx.feature_id:
                raise CoderFailure(
                    "execution_scope_mismatch",
                    f"durable snapshot for {execution_id} is bound to feature {durable_snapshot.feature_id}, not {ctx.feature_id}",
                )
            if durable_snapshot.worktree_path != canonical_worktree:
                raise CoderFailure(
                    "execution_scope_mismatch",
                    f"durable snapshot for {execution_id} is bound to worktree {durable_snapshot.worktree_path}, not {canonical_worktree}",
                )
            # Validate roster fingerprint against durable record
            if durable_snapshot.roster_fingerprint != roster_fingerprint(self.roster):
                raise CoderFailure(
                    "execution_config_mismatch",
                    f"durable snapshot for {execution_id} was bound to a different roster configuration",
                )

            # Check if snapshot says closed: a closed execution never starts fresh work
            if durable_snapshot.status == "closed":
                raise CoderFailure(
                    "execution_closed",
                    f"execution {execution_id} is closed and cannot start new work",
                )

            # Restore the pool with persistent local + inherited exclusions
            if self._suspension_store is None:
                self._suspension_store = await asyncio.to_thread(
                    CoderSuspensionStore.from_root, Path(canonical_worktree)
                )

            # Combine durable inherited exclusions with current inherited exclusions
            # (per spec: replay own suspensions regardless of expiry)
            now = datetime.now(timezone.utc)
            combined_inherited = list(durable_snapshot.inherited_exclusions)

            # Recreate pool with combined exclusions
            try:
                # Probe with combined exclusions
                excluded_set = set(combined_inherited) | set(durable_snapshot.local_exclusions)
                self.probe_results = await self._probe.probe(self.roster, excluded=excluded_set)
                self.seats = available_seats(self.roster, self.probe_results)

                pool = ExecutionPool(
                    execution_id=execution_id,
                    feature_id=ctx.feature_id,
                    worktree_path=canonical_worktree,
                    roster=self.roster,
                    seats=self.seats,
                    suspension_store=self._suspension_store,
                    initial_exclusions=combined_inherited,
                )

                # Restore local exclusions (from this execution's own suspensions)
                pool._local_exclusions = set(durable_snapshot.local_exclusions)

                # Check for unresolved running/prepared attempts that require reconciliation
                if (
                    durable_snapshot.admitted_attempts
                    or durable_snapshot.native_reservations
                    or durable_snapshot.outstanding_job_ids
                ):
                    # Uncertain work requires reconciliation before dispatch
                    pool._status = "recovery_required"

                # Check if pool has any available seats
                view = pool.view()
                if not any(seat.available and not seat.suspended for seat in view.seats):
                    pool._fallback_required = True
                    pool._fallback_reason = "all_seats_exhausted"

                self._executions[execution_id] = pool
                self._execution_owners[canonical_worktree] = execution_id
                return pool.view()
            except Exception as exc:
                self.logger.warning(
                    "failed to restore execution from snapshot %s: %s",
                    execution_id,
                    exc,
                )
                raise CoderFailure(
                    "internal_error",
                    f"failed to restore execution from snapshot: {exc}",
                ) from exc

        # New execution: read durable suspension history BEFORE probing
        try:
            if self._suspension_store is None:
                self._suspension_store = await asyncio.to_thread(
                    CoderSuspensionStore.from_root, Path(canonical_worktree)
                )
            now = datetime.now(timezone.utc)
            # Get all model keys from roster to query history
            model_keys = []
            for seat in self.roster.seats:
                if seat.kind == "native":
                    model_keys.append(ModelKey(backend="native", model=seat.model or "haiku"))
                    continue
                if seat.model:
                    model_keys.append(ModelKey(backend=seat.backend or "", model=seat.model))
                # A previously-suspended FALLBACK-only identity must also be
                # excluded before the initial probe -- omitting it left a
                # recently-failed fallback model eligible for a fresh smoke
                # probe/dispatch even though its own incident is still within
                # cooldown (AC-4: "excludes all unexpired matching records
                # BEFORE any primary/fallback smoke probe or dispatcher call").
                if seat.fallback_model:
                    model_keys.append(ModelKey(backend=seat.backend or "", model=seat.fallback_model))
            # Query recent suspensions. `CoderSuspensionStore.recent` is itself an
            # `async def` that already offloads its file I/O via `asyncio.to_thread`
            # internally -- wrapping it in ANOTHER `asyncio.to_thread` here would call
            # the coroutine function in a worker thread without ever awaiting the
            # coroutine it returns, silently discarding the result (surfaced as
            # `TypeError: 'coroutine' object is not iterable` below, masked by the
            # broad `except Exception` as a false "suspension_history_unavailable").
            recent = await self._suspension_store.recent(model_keys, now)
            # Build initial exclusions from history
            initial_exclusions: List[ModelKey] = []
            for record in recent:
                for key in record.blocked_keys:
                    if key not in initial_exclusions:
                        initial_exclusions.append(key)
        except Exception as exc:
            # History unavailable: fallback required, but still create pool
            # so the worker can decide what to do
            self.logger.warning(
                "could not read suspension history for execution %s: %s",
                execution_id,
                exc,
            )
            # Create pool with empty exclusions but mark fallback required
            pool = ExecutionPool(
                execution_id=execution_id,
                feature_id=ctx.feature_id,
                worktree_path=canonical_worktree,
                roster=self.roster,
                seats=[],  # No seats until probed
                suspension_store=self._suspension_store,
                initial_exclusions=[],
            )
            pool._fallback_required = True
            pool._fallback_reason = "suspension_history_unavailable"
            # Spec §2 "Persistence failure behavior": unreadable/invalid
            # suspension history at begin "yields an EXHAUSTED pool" --
            # not just fallback_required with status left at "active".
            pool._status = "exhausted"
            self._executions[execution_id] = pool
            self._execution_owners[canonical_worktree] = execution_id
            return pool.view()

        # Probe with exclusions: only eligible candidates
        excluded_set = set(initial_exclusions)
        self.probe_results = await self._probe.probe(self.roster, excluded=excluded_set)
        self.seats = available_seats(self.roster, self.probe_results)

        # Create the execution pool with probed seats and initial exclusions
        pool = ExecutionPool(
            execution_id=execution_id,
            feature_id=ctx.feature_id,
            worktree_path=canonical_worktree,
            roster=self.roster,
            seats=self.seats,
            suspension_store=self._suspension_store,
            initial_exclusions=initial_exclusions,
        )

        # Check if pool has any available seats
        view = pool.view()
        if not any(seat.available and not seat.suspended for seat in view.seats):
            pool._fallback_required = True
            pool._fallback_reason = "all_seats_exhausted"

        self._executions[execution_id] = pool
        self._execution_owners[canonical_worktree] = execution_id
        return pool.view()

    async def end_execution(self, execution_id: str) -> "ExecutionPoolView":
        """End an execution, releasing worktree ownership.

        Refuses while known attempts/reservations are in flight. Records a
        durable close after they settle.

        Args:
            execution_id: The execution to close.

        Returns:
            ExecutionPoolView with final state (status='closed').

        Raises:
            CoderFailure with codes:
                - execution_not_found: unknown execution_id
                - execution_busy: attempts/jobs still in flight
        """
        if execution_id not in self._executions:
            raise CoderFailure("execution_not_found", f"no execution found with id {execution_id}")

        pool = self._executions[execution_id]
        view = pool.view()

        # Check for in-flight work. Gated on "not already closed" (idempotent
        # re-close is a no-op below), NOT on "== active": a pool transitions to
        # "exhausted" the instant its last eligible seat is suspended, which can
        # happen while a native/MCP attempt admitted BEFORE that suspension is
        # still genuinely running -- gating on "active" alone let a just-exhausted
        # pool skip this busy check entirely (code-review regression: a native
        # agent suspended via `suspend_model` while it was the pool's only seat
        # made `end_execution` fall straight through to the snapshot-enrichment
        # loop below with the in-flight reservation never having settled).
        if view.status != "closed":
            # Check admitted attempts
            snapshot = pool.snapshot()
            if snapshot.admitted_attempts:
                raise CoderFailure(
                    "execution_busy",
                    f"execution {execution_id} has {len(snapshot.admitted_attempts)} admitted attempts still in flight",
                )
            # Check native reservations
            if snapshot.native_reservations:
                raise CoderFailure(
                    "execution_busy",
                    f"execution {execution_id} has {len(snapshot.native_reservations)} native reservations still in flight",
                )
            # Check outstanding jobs
            if snapshot.outstanding_job_ids:
                raise CoderFailure(
                    "execution_busy",
                    f"execution {execution_id} has {len(snapshot.outstanding_job_ids)} outstanding jobs",
                )

        # Mark as closed and write durable snapshot before releasing ownership
        pool._status = "closed"
        canonical_worktree = pool.worktree_path

        # Enrich snapshot with native reservations and outstanding job IDs from engine bookkeeping
        snapshot = pool.snapshot()

        # Collect native reservations belonging to this execution
        for (exec_id, task_id), _attempt_uid in list(self._native_reservations.items()):
            if exec_id == execution_id:
                manager_key = f"{task_id}.a{self._latest_attempt.get(task_id, AttemptRecord(attempt=1)).attempt}"
                if manager_key in self._manager_execution and self._manager_execution[manager_key] == execution_id:
                    snapshot.native_reservations[task_id] = manager_key

        # Collect outstanding job IDs belonging to this execution (track via _job_worktrees)
        for job_id, job_wt in list(self._job_worktrees.items()):
            if job_wt == canonical_worktree:
                snapshot.outstanding_job_ids.append(job_id)

        # Write durable snapshot atomically
        persisted = await self._write_execution_snapshot(canonical_worktree, execution_id, snapshot)
        if not persisted:
            pool._persistence_degraded = True
            self.logger.warning("failed to durably close execution %s; persistence status is degraded", execution_id)

        # Release ownership after durable close
        if self._execution_owners.get(canonical_worktree) == execution_id:
            del self._execution_owners[canonical_worktree]

        return pool.view()

    async def _resolve_feature(self, feature: str, worktree: str) -> _FeatureCtx:
        """Match sdd/tasks/index/*.json headers in the sdd-worker.md §1 order.

        Order (first match wins): feature_id exact -> feature exact ->
        feature_id numeric/any suffix -> feature substring -> spec filename.
        """
        wt = await asyncio.to_thread(os.path.realpath, worktree)
        if not (wt == self._base_path or wt.startswith(self._base_path + os.sep)):
            raise CoderFailure("worktree_outside_base", f"{worktree} is not under {self._base_path}")

        index_dir = Path(wt) / "sdd" / "tasks" / "index"

        def _read_headers() -> List[Tuple[Path, Dict[str, Any]]]:
            headers: List[Tuple[Path, Dict[str, Any]]] = []
            if not index_dir.is_dir():
                return headers
            for p in sorted(index_dir.glob("*.json")):
                if p.name == _ORPHANS_INDEX_NAME:
                    continue
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                headers.append((p, data))
            return headers

        headers = await asyncio.to_thread(_read_headers)

        def _match() -> Optional[Tuple[Path, Dict[str, Any]]]:
            for p, h in headers:
                if h.get("feature_id") == feature:
                    return p, h
            for p, h in headers:
                if h.get("feature") == feature:
                    return p, h
            for p, h in headers:
                fid = h.get("feature_id") or ""
                if fid and feature and fid.endswith(feature):
                    return p, h
            for p, h in headers:
                feat = h.get("feature") or ""
                if feature and feature in feat:
                    return p, h
            for p, h in headers:
                spec = h.get("spec") or ""
                if spec and Path(spec).name == feature:
                    return p, h
            return None

        found = _match()
        if found is None:
            candidates = sorted({h.get("feature_id", "?") for _, h in headers})
            raise CoderFailure("feature_not_found", f"no per-spec index matches {feature!r}", candidates=candidates)

        index_path, header = found
        rc, out, _err = await _git("rev-parse", "--abbrev-ref", "HEAD", cwd=wt)
        if rc != 0:
            raise CoderFailure("internal_error", f"could not determine the current branch of {wt}")

        return _FeatureCtx(
            worktree=wt,
            feature_id=header.get("feature_id", ""),
            feature=header.get("feature", ""),
            feature_branch=out.strip(),
            index_path=str(index_path),
            spec_path=header.get("spec", ""),
            base_branch=header.get("base_branch", ""),
        )

    async def _scheduler_for(self, ctx: _FeatureCtx) -> TaskScheduler:
        try:
            sched = await asyncio.to_thread(TaskScheduler.from_index_file, Path(ctx.index_path))  # S11
        except ValueError as exc:
            raise CoderFailure("dependency_cycle", str(exc)) from exc
        if sched is None:
            raise CoderFailure("index_unreadable", f"cannot read {ctx.index_path}")
        return sched

    async def plan(
        self,
        feature: str,
        worktree: str,
        *,
        execution_id: Optional[str] = None,
    ) -> CoderPlan:
        """Compute the next wave plan for a feature.

        Args:
            feature: Feature identifier.
            worktree: Absolute path to the feature worktree.
            execution_id: Optional execution ID for FEAT-559 pools. When provided,
                uses the execution's private assigner and carries execution_id in
                the returned plan. When omitted, uses the legacy global assigner.

        Returns:
            CoderPlan with the next wave of tasks.
        """
        # If execution_id provided, use the execution pool's assigner
        pool_generation = 0
        if execution_id is not None:
            if execution_id not in self._executions:
                raise CoderFailure(
                    "execution_not_found",
                    f"no execution found with id {execution_id}; call begin_execution first",
                )
            pool = self._executions[execution_id]
            pool_generation = pool.generation
            # Use the pool's own eligibility-filtered assigner -- `pool.assigner()`
            # excludes suspended/busy/probe-failed seats (its own documented
            # contract); constructing a bare `ChunkAssigner(pool._seats)` here
            # bypassed that filtering entirely, so a replan right after a
            # mid-execution suspension could still assign a task to the
            # just-suspended seat (caught later by `pool.admit()`, but wasting
            # a plan slot instead of routing to a healthy seat). `None` means
            # the pool is currently exhausted -- same empty-chunks/fallback
            # shape as the "no seats at all" case.
            assigner = pool.assigner()
            if assigner is None:
                ctx = await self._resolve_feature(feature, worktree)
                sched = await self._scheduler_for(ctx)
                pending = sorted(t.id for t in sched.pending())
                return CoderPlan(
                    feature_id=ctx.feature_id,
                    feature=ctx.feature,
                    feature_branch=ctx.feature_branch,
                    index_path=ctx.index_path,
                    pending=pending,
                    blocked=[],
                    chunks=[],
                    roster=[],
                    orphan_branches=[],
                    execution_id=execution_id,
                    pool_generation=pool_generation,
                )
            seats = pool._seats
            probe_results = [
                SeatProbeResult(
                    label=s.label,
                    kind=s.kind,
                    backend=s.backend,
                    model_used=s.model,
                    available=True,
                )
                for s in seats
            ]
        else:
            # Legacy path: use global open() state
            await self.open()
            assigner = self._assigner
            seats = self.seats
            probe_results = self.probe_results

        ctx = await self._resolve_feature(feature, worktree)
        sched = await self._scheduler_for(ctx)
        wave = sorted(sched.next_wave(), key=lambda t: t.id)  # S3

        # Collect complexity assessments and determine eligible seats for each
        # task, restricted to the CURRENT (execution-pool or legacy) `seats`
        # list -- not always `self.seats` -- so a suspended/busy/probe-failed
        # seat filtered out by the execution pool never re-enters through the
        # complexity eligibility check.
        assessments: Dict[str, ComplexityAssessment] = {}
        routing_blocks: List[ComplexityBlock] = []
        eligible_labels: Dict[str, Set[str]] = {}
        blocked_task_ids: Set[str] = set()

        for task_ref in wave:
            try:
                # Get assessment for this task
                planned_task = PlannedTask(
                    task_id=task_ref.id,
                    task_file=task_ref.file,
                    title=task_ref.title,
                    seat_label="",
                    native=False,
                )
                assessment = await self._compute_assessment(ctx, planned_task, task_ref.file)
                assessments[task_ref.id] = assessment

                # Determine eligible seats based on complexity classification
                eligible = eligible_seats(assessment, seats, self.roster.complexity)
                if eligible:
                    eligible_labels[task_ref.id] = {seat.label for seat in eligible}
                else:
                    # No eligible seats for this task: block it, but keep other
                    # ready tasks dispatchable (spec: "Other ready tasks can
                    # continue"). Excluded from the wave passed to
                    # `ChunkAssigner.assign` below -- `assign` rejects a task
                    # with an empty eligible-label set outright.
                    blocked_task_ids.add(task_ref.id)
                    routing_blocks.append(
                        ComplexityBlock(
                            task_id=task_ref.id,
                            assessment_id=assessment.assessment_id,
                            code="complex_model_unavailable",
                            message=f"No eligible seats available for {assessment.classification} task {task_ref.id}",
                            details={
                                "classification": assessment.classification,
                                "required_models": [sm.canonical_model for sm in self.roster.complexity.strong_models],
                            },
                        )
                    )

            except CoderFailure as exc:
                if exc.code == "complexity_plan_stale":
                    # Stale assessment - need to replan
                    raise
                # Any other complexity-routing failure blocks only this task;
                # `exc.code` is already the specific code `_assessment_for`
                # raised (`complexity_contract_invalid` or
                # `complexity_audit_failed`) -- never relabel it.
                blocked_task_ids.add(task_ref.id)
                routing_blocks.append(
                    ComplexityBlock(
                        task_id=task_ref.id,
                        code=exc.code,
                        message=f"Complexity routing failed for {task_ref.id}: {exc.message}",
                        details=exc.details,
                    )
                )

        assert assigner is not None

        # Assign tasks to chunks using eligible labels; routing-blocked tasks
        # never reach the assigner (see above).
        assignable_wave = [t for t in wave if t.id not in blocked_task_ids]
        chunks = assigner.assign(
            assignable_wave, {t.id: t.file for t in assignable_wave}, eligible_labels=eligible_labels
        )

        pending = sorted(t.id for t in sched.pending())
        blocked = sorted(set(pending) - {t.id for t in wave})
        orphans = await self._orphan_branches(ctx)

        result = CoderPlan(
            feature_id=ctx.feature_id,
            feature=ctx.feature,
            feature_branch=ctx.feature_branch,
            index_path=ctx.index_path,
            pending=pending,
            blocked=blocked,
            chunks=chunks,
            roster=probe_results,
            orphan_branches=orphans,
            assessments=assessments,
            routing_blocks=routing_blocks,
            execution_id=execution_id or "",
            pool_generation=pool_generation,
        )
        # Cache the computed plan, keyed by feature_id (and execution_id when present).
        # For execution pools, also store against execution_id for private cache.
        cache_key = f"{ctx.feature_id}:{execution_id}" if execution_id else ctx.feature_id
        self._plan_cache[cache_key] = result
        return result

    async def _assessment_for(
        self, ctx: _FeatureCtx, task: PlannedTask, task_file: str, *, execution_id: Optional[str] = None
    ) -> ComplexityAssessment:
        """Revalidate the CURRENTLY DISPLAYED plan's assessment before a dispatch
        side effect (spec: "revalidate task/index/policy/target hashes and HEAD ...
        before run_chunk and prepare_native side effects").

        NOT used by `plan()` itself: a fresh `plan()` call always recomputes
        (spec: "Recompute measurements at planning; never cache a wiki result
        across plans") via `_compute_assessment` directly -- reusing a PRIOR
        plan's cached assessment while building a NEW plan would be
        self-defeating (it would always disagree with itself the moment
        anything the assessment covers changes between calls).

        `execution_id` (FEAT-559), when given, must match the same value
        `plan()` cached this plan under (`_plan_cache`'s key is
        `f"{feature_id}:{execution_id}"` for an execution-scoped plan, plain
        `feature_id` for the legacy path) -- looking this up under the wrong
        key would spuriously report a fresh plan as stale.

        Returns the currently-cached assessment if it is still valid, or
        raises `CoderFailure` with code `complexity_plan_stale` (spec: "a
        change returns complexity_plan_stale and requires replanning rather
        than silently changing an already displayed assignment").
        """
        cache_key = f"{ctx.feature_id}:{execution_id}" if execution_id else ctx.feature_id
        cached_plan = self._plan_cache.get(cache_key)
        if cached_plan is None or task.task_id not in cached_plan.assessments:
            raise CoderFailure(
                "complexity_plan_stale",
                f"No cached plan/assessment for {task.task_id}; call plan() first",
                task_id=task.task_id,
            )
        cached_assessment = cached_plan.assessments[task.task_id]
        is_valid = await validate_complexity_snapshot(
            Path(ctx.worktree),
            Path(task_file),
            Path(ctx.index_path),
            cached_assessment,
            self.roster.complexity,
        )
        if not is_valid:
            raise CoderFailure(
                "complexity_plan_stale",
                f"Cached assessment for {task.task_id} is stale",
                task_id=task.task_id,
                assessment_id=cached_assessment.assessment_id,
            )
        return cached_assessment

    async def _compute_assessment(self, ctx: _FeatureCtx, task: PlannedTask, task_file: str) -> ComplexityAssessment:
        """Collect fresh evidence, evaluate and persist a new assessment.

        Always recomputes (per `plan()`'s "never cache across plans"
        requirement); never consults `_plan_cache`. Raises `CoderFailure`
        with code `complexity_contract_invalid` (the task's own Complexity
        Contract section is malformed/missing/contradictory -- spec: "Invalid
        task structure blocks rather than classifies") or
        `complexity_audit_failed` (collection or persistence failed -- spec:
        "an audit write failure blocks that task"). Collector-level tool
        failures (missing Ruff/wiki, timeouts, etc.) are NOT raised here:
        `collect_complexity`'s own sub-collectors already degrade those to
        `unknown` `MetricEvidence` states.
        """
        try:
            evidence = await collect_complexity(
                Path(ctx.worktree),
                Path(task_file),
                Path(ctx.index_path),
                self.roster.complexity,
            )
        except ComplexityContractError as exc:
            raise CoderFailure(
                "complexity_contract_invalid",
                f"Complexity contract invalid for {task.task_id}: {exc}",
                task_id=task.task_id,
                details=exc.details,
            ) from exc
        except Exception as exc:
            # Structural collection failure (missing worktree/task/index file,
            # or similar) -- distinct from a per-metric tool failure, which
            # collect_complexity already reports as `unknown` evidence rather
            # than raising.
            raise CoderFailure(
                "complexity_audit_failed",
                f"Failed to collect complexity evidence for {task.task_id}: {exc}",
                task_id=task.task_id,
                error=str(exc),
            ) from exc

        assessment = evaluate_complexity(evidence, self.roster.complexity)

        try:
            await self._persist_assessment(ctx, assessment)
        except Exception as exc:
            raise CoderFailure(
                "complexity_audit_failed",
                f"Failed to persist complexity assessment for {task.task_id}: {exc}",
                task_id=task.task_id,
                assessment_id=assessment.assessment_id,
                error=str(exc),
            ) from exc

        return assessment

    async def _persist_assessment(self, ctx: _FeatureCtx, assessment: ComplexityAssessment) -> None:
        """Persist assessment to artifacts/sdd-coder/complexity/<feature-id>/<task-id>/<assessment-id>.json.

        Creates parent directories and writes canonical JSON atomically.
        """
        artifacts_dir = (
            Path(ctx.worktree) / "artifacts" / "sdd-coder" / "complexity" / ctx.feature_id / assessment.task_id
        )
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        assessment_path = artifacts_dir / f"{assessment.assessment_id}.json"

        # Write assessment as canonical JSON
        assessment_json = assessment.model_dump_json()
        assessment_path.write_text(assessment_json, encoding="utf-8")

    async def _cached_plan(
        self, feature: str, worktree: str, ctx: _FeatureCtx, execution_id: Optional[str] = None
    ) -> CoderPlan:
        """Reuse the most recently computed plan for this feature instead of recomputing.

        `run_chunk`/`prepare_native` must see EXACTLY the chunk `coder_plan` most recently
        returned to the caller — recomputing would advance `ChunkAssigner`'s rotation state
        again and could reclassify a task from mcp to native or vice versa (see `plan()`).
        Falls back to a fresh `plan()` (which populates the cache) when nothing is cached yet
        — e.g. a `coder_prepare_native`/`coder_run_chunk` call with no preceding `coder_plan`.

        FEAT-559: `plan()` stores execution-scoped plans under the QUALIFIED key
        `f"{feature_id}:{execution_id}"` (never under the bare `feature_id` when an
        execution is involved) -- this lookup and the fallback `plan()` call below
        must use the SAME qualified key, or every execution-scoped caller misses the
        cache every time and silently falls back to the legacy, unscoped global
        roster/assigner (bypassing suspension-aware seat filtering entirely).
        """
        cache_key = f"{ctx.feature_id}:{execution_id}" if execution_id else ctx.feature_id
        cached = self._plan_cache.get(cache_key)
        if cached is not None:
            return cached
        return await self.plan(feature, worktree, execution_id=execution_id)

    async def _eligible_retry_labels(
        self, ctx: _FeatureCtx, task: PlannedTask, *, execution_id: Optional[str] = None
    ) -> Optional[Set[str]]:
        """Current eligible seat labels for `task`'s retry, or `None` when unrestricted.

        `None` means "standard classification, no restriction" and must be passed
        straight through to `ChunkAssigner.retry_seat`'s `eligible_labels` (which
        applies no filter for `None`) -- an empty `set()` would instead mean
        "no seat is eligible," which is only correct once we know the task IS
        restricted.

        `execution_id` (FEAT-559), when given, must match `_cached_plan`'s and
        looks the seats up from that execution's own pool (not the legacy
        global `self.seats`), same rationale as `_assessment_for`.
        """
        plan = await self._cached_plan(ctx.feature, ctx.worktree, ctx, execution_id=execution_id)
        assessment = plan.assessments.get(task.task_id)
        if assessment is None:
            # A task reaching retry was, by definition, just dispatched under SOME
            # cached plan/assessment (`_run_attempt`'s own admission check just used
            # one to fail attempt 1). A missing assessment here is an anomaly, never
            # evidence this task is unrestricted -- fail closed rather than letting
            # `_select_retry_seat` search the full, unrestricted roster
            # (issue:e01c03baf493).
            return set()
        if assessment.classification not in ("complex", "unknown"):
            return None
        seats = self._executions[execution_id]._seats if execution_id in self._executions else self.seats
        return {s.label for s in eligible_seats(assessment, seats, self.roster.complexity)}

    @staticmethod
    def _worker_id(task_id: str, attempt: int, execution_id: Optional[str]) -> str:
        """Centralized worker id: `TASK-N.a<attempt>[.<execution_uuid_hex>]` (spec §2 Execution lifecycle).

        Passed to `SubWorktreeManager.create()`; its `_branch_suffix` replaces every
        `.` with `-`, so this is also the single source of truth `_branch_for`/
        `_path_for` derive from -- never hand-construct a branch/path string
        separately (that duplication was the FEAT-559 regression this task's scope
        calls out: "remove duplicated hard-coded branch construction from
        dispatch/merge paths"). Execution-qualified so successive executions never
        collide on the same branch/path even for the same task+attempt.
        """
        base = f"{task_id}.a{attempt}"
        return f"{base}.{execution_id.replace('-', '')}" if execution_id else base

    def _branch_for(self, ctx: _FeatureCtx, task_id: str, attempt: int, execution_id: Optional[str]) -> str:
        """The exact branch `SubWorktreeManager.create()` produces for this worker id."""
        return f"{ctx.feature_branch}--{SubWorktreeManager._branch_suffix(self._worker_id(task_id, attempt, execution_id))}"  # noqa: SLF001

    def _path_for(self, ctx: _FeatureCtx, task_id: str, attempt: int, execution_id: Optional[str]) -> str:
        """The exact sub-worktree path `SubWorktreeManager.create()` produces for this worker id."""
        worker_id = self._worker_id(task_id, attempt, execution_id)
        return str(
            Path(self._base_path) / f"{ctx.feature_branch}--pool" / SubWorktreeManager._branch_suffix(worker_id)
        )  # noqa: SLF001

    async def _write_attempt_scope(self, worktree_path: str, task_id: str, task_file: str, base_ref: str) -> None:
        """Write the task-tier test-scope context into an attempt sub-worktree (FEAT-563).

        The file turns the pytest guard on for that attempt only. A failure is
        logged and swallowed: without the file the guard is inactive, which is
        the pre-FEAT-563 behaviour, never a failed attempt.

        Args:
            worktree_path: The attempt sub-worktree root.
            task_id: TASK id being implemented.
            task_file: Repo-relative task markdown path.
            base_ref: Feature branch the attempt diffs against.
        """
        context = AttemptContext(tier="task", task_id=task_id, task_file=task_file, base_ref=base_ref)
        try:
            await asyncio.to_thread(write_attempt_context, Path(worktree_path), context)
        except Exception as exc:  # noqa: BLE001 — guard context is best-effort
            self.logger.warning("could not write test-scope context for %s in %s: %s", task_id, worktree_path, exc)

    def _manager_for(
        self, ctx: _FeatureCtx, task_id: str, attempt: int, execution_id: Optional[str] = None
    ) -> SubWorktreeManager:
        key = self._worker_id(task_id, attempt, execution_id)
        if key not in self._managers:
            self._managers[key] = SubWorktreeManager(
                base_worktree=ctx.worktree, feature_branch=ctx.feature_branch, worktree_base_path=self._base_path
            )
            self._manager_execution[key] = execution_id or ""
        return self._managers[key]

    async def prepare_native(
        self, feature: str, worktree: str, task_id: str, execution_id: Optional[str] = None
    ) -> NativePrep:
        """Sub-worktree for a `native` planned task (attempt 1); branch <feature_branch>--<TASK-NNN>-a1[-<exechex>].

        FEAT-559: when `execution_id` is given, the native seat's model identity is
        admitted through the execution's pool BEFORE the worktree is created (so a
        suspended/excluded native seat is rejected up front, not discovered later),
        and a duplicate call for the same (execution, task) reuses the existing
        reservation/attempt instead of admitting (and worktree-creating) twice.
        """
        ctx = await self._resolve_feature(feature, worktree)
        pool: Optional[ExecutionPool] = None
        if execution_id is not None:
            if execution_id not in self._executions:
                raise CoderFailure("execution_not_found", f"no execution found with id {execution_id}")
            pool = self._executions[execution_id]

        plan = await self._cached_plan(feature, worktree, ctx, execution_id=execution_id)
        planned = next((t for c in plan.chunks for t in c.tasks if t.task_id == task_id), None)
        if planned is None or not planned.native:
            raise CoderFailure("task_not_in_plan", f"{task_id} is not a native task of the current chunk plan")

        # Admission (spec: "Validate native tasks before allocating their
        # worktree"): revalidate the assessment BEFORE `manager.create()`
        # below -- a stale assessment raises `complexity_plan_stale` and
        # allocates no worktree.
        assessment = await self._assessment_for(ctx, planned, planned.task_file, execution_id=execution_id)
        assessment_id = assessment.assessment_id

        seat = next(seat for seat in self.roster.seats if seat.label == planned.seat_label)
        if assessment.classification in ("complex", "unknown"):
            # Spec: "NativePrep returns ... the exact planned effective model,
            # never seat.model-or-haiku for restricted tasks" -- a native seat
            # with no configured model cannot serve a restricted task at all.
            if not seat.model:
                raise CoderFailure(
                    "complex_model_unavailable",
                    f"native seat {seat.label!r} has no configured model for {assessment.classification} "
                    f"task {task_id}",
                    task_id=task_id,
                    assessment_id=assessment_id,
                )
            model = seat.model
        else:
            model = seat.model or "haiku"

        if pool is not None:
            reservation_key = (execution_id, task_id)
            existing_uid = self._native_reservations.get(reservation_key)
            if existing_uid is not None:
                attempt_uid = existing_uid
            else:
                attempt_uid = await pool.admit(task_id, ModelKey(backend="native", model=model))
                self._native_reservations[reservation_key] = attempt_uid
        else:
            attempt_uid = uuid.uuid4().hex

        worker_id = self._worker_id(task_id, 1, execution_id)
        manager = self._manager_for(ctx, task_id, 1, execution_id)
        path = await manager.create(worker_id)
        await self._write_attempt_scope(path, task_id, planned.task_file, ctx.feature_branch)
        self._native_inflight.add(worker_id)
        branch = self._branch_for(ctx, task_id, 1, execution_id)
        self._feedback_sources[attempt_uid] = (ctx.worktree, task_id, "native", model)
        feedback_context = await self._feedback_for(ctx, planned, "native", model)
        self._feedback_contexts[attempt_uid] = feedback_context
        return NativePrep(
            task_id=task_id,
            task_file=planned.task_file,
            branch=branch,
            worktree_path=path,
            seat_label=planned.seat_label,
            model=model,
            attempt_uid=attempt_uid,
            coder_feedback=feedback_context,
            assessment_id=assessment_id,
            execution_id=execution_id or "",
        )

    async def suspend_model(
        self,
        execution_id: str,
        attempt_uid: str,
        reason: str,
        evidence_ref: str,
    ) -> SuspensionReceipt:
        """Report a WORKER-observed failure for one of ITS OWN admitted attempts (spec §2 M3).

        The target model is resolved SERVER-SIDE from `attempt_uid` via the pool's own
        admission record (`ExecutionPool._admitted`) -- the caller never names a model
        directly, so it cannot invent or cross-execution an arbitrary suspension target.
        Delegates all local-exclusion/generation/persistence mechanics to
        `ExecutionPool.suspend()` (TASK-3276) rather than duplicating them here.

        Constrained to valid worker-report sources (spec: "constrain worker reports to
        valid native/critical-review sources"): a native attempt may report any reason;
        an MCP attempt may only report `review_critical` (any other MCP failure is the
        engine's own internal `_classify_and_suspend`, never a worker-initiated report).

        Args:
            execution_id: The execution owning `attempt_uid`.
            attempt_uid: The attempt that failed, as issued by `prepare_native`/`pool.admit`.
            reason: One of `SuspensionReason`.
            evidence_ref: A short reference (log path, commit sha), never a transcript.

        Raises:
            CoderFailure with codes:
                - execution_not_found: unknown execution_id
                - attempt_not_found: attempt_uid is not an admitted reservation in this execution
                - invalid_arguments: reason is not a valid SuspensionReason, or an MCP attempt
                  reported a reason other than review_critical
        """
        if execution_id not in self._executions:
            raise CoderFailure("execution_not_found", f"no execution found with id {execution_id}")
        pool = self._executions[execution_id]

        entry = pool._admitted.get(attempt_uid)  # noqa: SLF001 — engine already reaches into pool internals elsewhere
        if entry is None:
            raise CoderFailure(
                "attempt_not_found", f"attempt {attempt_uid} is not an admitted reservation in execution {execution_id}"
            )
        task_id, key = entry

        if reason not in typing.get_args(SuspensionReason):
            raise CoderFailure("invalid_arguments", f"unknown suspension reason {reason!r}")

        is_native = key.backend == "native"
        if not is_native and reason != "review_critical":
            raise CoderFailure(
                "invalid_arguments",
                "an MCP attempt's suspension may only be worker-reported for reason='review_critical'; "
                "other MCP failures are classified and suspended internally by the engine, never the worker",
            )

        seat = next(
            (
                s
                for s in self.roster.seats
                if (s.backend if s.kind == "mcp" else "native") == key.backend
                and (s.model if s.kind == "mcp" else (s.model or "haiku")) == key.model
            ),
            None,
        )
        seat_label = seat.label if seat is not None else key.backend

        now = datetime.now(timezone.utc)
        record = SuspensionRecord(
            execution_id=execution_id,
            feature_id=pool.feature_id,
            task_id=task_id,
            attempt_uid=attempt_uid,
            source="worker_review" if reason == "review_critical" else "native_report",
            seat_label=seat_label,
            backend=key.backend,
            configured_model=key.model,
            blocked_keys=[key],
            reason=reason,
            occurred_at=now,
            expires_at=now + timedelta(seconds=self.roster.suspension_policy.cooldown_seconds),
            duration_s=0.0,
            evidence_ref=(evidence_ref or "")[:300],
            explanation=f"Worker-reported {reason} for {task_id} (attempt {attempt_uid}).",
        )
        return await pool.suspend(record)

    async def record_feedback(
        self, feature: str, worktree: str, feedback: CoderFeedback, execution_id: Optional[str] = None
    ) -> CoderFeedbackReceipt:
        """Persist a reviewed correction after checking its attempt/model attribution.

        FEAT-559: when `execution_id` is given, it is attached to `feedback` (rejecting
        a caller-supplied `feedback.execution_id` that conflicts with it) before recording.
        """
        ctx = await self._resolve_feature(feature, worktree)
        expected = (ctx.worktree, feedback.task_id, feedback.backend, feedback.model)
        if self._feedback_sources.get(feedback.attempt_uid) != expected:
            raise CoderFailure(
                "invalid_arguments", "feedback must match a known attempt's task, backend and actual model"
            )
        if execution_id is not None:
            if feedback.execution_id and feedback.execution_id != execution_id:
                raise CoderFailure("invalid_arguments", "feedback execution_id does not match the calling execution")
            feedback = feedback.model_copy(update={"execution_id": execution_id})
        store = await asyncio.to_thread(CoderFeedbackStore.from_root, Path(ctx.worktree))
        return await store.record(feedback)

    async def _feedback_for(self, ctx: _FeatureCtx, task: PlannedTask, backend: str, model: str) -> str:
        """Refresh preventive feedback before each dispatch, including retries."""
        policy = self.roster.feedback
        if not policy.enabled or policy.max_tokens == 0:
            return ""
        if not model:
            return "Feedback unavailable: configure an explicit seat model to retrieve its prior corrections."
        try:
            root = await asyncio.to_thread(Path(ctx.worktree).resolve)
            task_path = await asyncio.to_thread((root / task.task_file).resolve)
            if not task_path.is_relative_to(root):
                raise ValueError("task path is outside the worktree")
            task_md = await asyncio.to_thread(task_path.read_text, encoding="utf-8")
            store = await asyncio.to_thread(CoderFeedbackStore.from_root, root)
            return await store.context(
                backend, model, list(parse_task_files(task_md)), policy.max_tokens, policy.max_age_days
            )
        except Exception:  # feedback outages are visible but do not invalidate code delivery
            self.logger.warning(
                "Coder feedback unavailable for %s (%s/%s)", task.task_id, backend, model, exc_info=True
            )
            return "Feedback unavailable: retrieval failed; this is not evidence of a clean history."

    async def record_review(
        self, feature: str, worktree: str, review: CoderReview, execution_id: Optional[str] = None
    ) -> CoderFeedbackReceipt:
        """Measure a reviewed delivery and validate its review-fix commits.

        FEAT-559: when `execution_id` is given, it is attached to `review` (rejecting a
        caller-supplied `review.execution_id` that conflicts with it) before recording.
        """
        ctx = await self._resolve_feature(feature, worktree)
        expected = (ctx.worktree, review.task_id, review.backend, review.model)
        if self._feedback_sources.get(review.attempt_uid) != expected:
            raise CoderFailure(
                "invalid_arguments", "review must match a known attempt's task, backend and actual model"
            )
        if execution_id is not None:
            if review.execution_id and review.execution_id != execution_id:
                raise CoderFailure("invalid_arguments", "review execution_id does not match the calling execution")
            review = review.model_copy(update={"execution_id": execution_id})
        for sha in set(review.fix_commits):
            rc, subject, _err = await _git("show", "-s", "--format=%s", sha, cwd=ctx.worktree)
            ancestor_rc, _out, _err = await _git("merge-base", "--is-ancestor", sha, "HEAD", cwd=ctx.worktree)
            if (
                rc
                or ancestor_rc
                or not subject.startswith("fix(")
                or not re.search(rf"\b{re.escape(review.task_id)}\b", subject)
                or "review fixes" not in subject.lower()
            ):
                raise CoderFailure(
                    "invalid_arguments", f"{sha} must be a reachable fix(...) {review.task_id} review fixes commit"
                )
        context = self._feedback_contexts.get(review.attempt_uid, "Feedback unavailable")
        exposure = (
            "unavailable"
            if context.startswith("Feedback unavailable") or review.attempt_uid in self._feedback_unknown_exposure
            else "with_feedback" if "[coder-feedback:" in context else "without_feedback"
        )
        measurement = CoderReviewMeasurement(
            **review.model_dump(), exposure=exposure, feedback_tokens=estimate_tokens(context)
        )
        store = await asyncio.to_thread(CoderFeedbackStore.from_root, Path(ctx.worktree))
        return await CoderReviewStore(store.log).record(measurement)

    async def feedback_report(self, feature: str, worktree: str) -> CoderReviewReport:
        """Return repository-wide review-fix rates by model and exposure cohort."""
        ctx = await self._resolve_feature(feature, worktree)
        store = await asyncio.to_thread(CoderFeedbackStore.from_root, Path(ctx.worktree))
        return await CoderReviewStore(store.log).report()

    async def _consolidate(
        self, ctx: _FeatureCtx, manager: SubWorktreeManager, task: PlannedTask, *, branch: str, path: str
    ) -> TaskResult:
        """clean status -> fidelity (committed diff only) -> locked merge. Never raises for domain outcomes."""
        _rc, status, _err = await _git("status", "--porcelain", "--untracked-files=all", cwd=path)
        if status.strip():
            return TaskResult(
                task_id=task.task_id,
                outcome="failed",
                branch=branch,
                worktree_path=path,
                diagnostics="dirty_task_worktree: uncommitted/untracked changes:\n" + status,
            )
        # Triple-dot semantics (merge-base-relative), NOT double-dot (direct tree comparison):
        # `git diff A..B` is a literal two-tree diff, so if `ctx.feature_branch` has advanced
        # since `branch` was created (e.g. a sibling task's attempt merged first, under the SAME
        # `_merge_lock` but in an EARLIER `_consolidate` call), a two-dot diff would list every
        # file the other merge introduced too — this branch would then fail fidelity for files
        # it never touched. `_consolidate_diff_base` resolves the equivalent of `A...B`'s merge
        # base, but ALSO covers the re-merge case (`branch` already an ancestor of
        # `ctx.feature_branch` — see its docstring) that a plain `git merge-base` gets wrong.
        diff_base = await _consolidate_diff_base(ctx.feature_branch, branch, cwd=ctx.worktree)
        _rc, diff, _err = await _git("diff", "--name-only", f"{diff_base}..{branch}", cwd=ctx.worktree)
        # Code-review fix (FEAT-549, IMPORTANT): resolve + verify containment before reading.
        # `os.path.join(ctx.worktree, task.task_file)` silently discards `ctx.worktree` if
        # `task.task_file` were ever absolute (`os.path.join` semantics), reading an arbitrary
        # local path instead. `task.task_file` comes from the per-spec index's TaskRef.file —
        # repo-local SDD data, not raw external input — but no containment check existed;
        # mirrors `_resolve_feature`'s own worktree-containment pattern.
        task_md_path = await asyncio.to_thread(lambda: Path(ctx.worktree, task.task_file).resolve())
        worktree_root = await asyncio.to_thread(lambda: Path(ctx.worktree).resolve())
        if not (task_md_path == worktree_root or str(task_md_path).startswith(str(worktree_root) + os.sep)):
            return TaskResult(
                task_id=task.task_id,
                outcome="failed",
                branch=branch,
                worktree_path=path,
                diagnostics=f"task_file {task.task_file!r} resolves outside the feature worktree",
            )
        task_md = await asyncio.to_thread(task_md_path.read_text, "utf-8")
        changed = [p for p in diff.splitlines() if p.strip()]
        report = check_fidelity(parse_task_files(task_md), changed)
        if not report.ok:
            return TaskResult(
                task_id=task.task_id,
                outcome="fidelity_violation",
                branch=branch,
                worktree_path=path,
                unexpected_files=report.unexpected + report.sdd_touched,
            )
        # Engine-owned lint pass: ruff --fix + formatter on the task's own files, committed on the
        # attempt branch so the merge carries it. Runs for every entry point (MCP seats, native
        # merge, re-merge) and never blocks — findings ride on the TaskResult for the orchestrator.
        lint_report = await run_lint_pass(
            path,
            changed,
            config=self.roster.lint,
            commit_message=f"style({ctx.feature}): {task.task_id} — engine lint autofix",
        )
        # FEAT-553 (spec §10 R1): the shared merge boundary — `merge()` reaches here directly
        # for native tasks and re-merges, so the banned-import gate lives HERE, not only in
        # `_run_attempt`. Nothing with a banned import can merge no matter which entry point
        # produced the branch.
        violations = await check_banned_imports(path, changed)
        if violations:
            return TaskResult(
                task_id=task.task_id,
                outcome="fidelity_violation",
                branch=branch,
                worktree_path=path,
                diagnostics="BannedImport: " + "; ".join(violations),
                lint=lint_report,
            )
        async with self._merge_lock:
            try:
                await manager.merge_sequential(resolver=None)
            except SubWorktreeMergeError as exc:
                # worktree_manager.merge_sequential already ran `git merge --abort`
                # by the time it raises, so the feature worktree is clean again and
                # a fresh `git diff --diff-filter=U` would show nothing; the only
                # remaining signal is the raw merge stderr, which git sometimes (not
                # always — content conflicts are usually reported on stdout, which
                # merge_sequential discards) prefixes with "CONFLICT (...): ... in
                # <path>" lines. Best-effort parse; an empty list here does not
                # affect AC-13, which only requires the outcome/clean-worktree/kept
                # branch — not a populated file list.
                conflict_files = _CONFLICT_LINE.findall(exc.stderr)
                return TaskResult(
                    task_id=task.task_id,
                    outcome="merge_conflict",
                    branch=branch,
                    worktree_path=path,
                    conflict_files=conflict_files,
                    diagnostics=exc.stderr,
                    lint=lint_report,
                )
            # `merge_sequential` only merges branches the manager still remembers in
            # `_created`; if that map was emptied (a `cleanup()` ran first, FEAT-555
            # incident) it silently merges nothing. Never answer `merged` on trust —
            # ask git whether `branch` is now part of the feature branch.
            rc, _out, err = await _git("merge-base", "--is-ancestor", branch, ctx.feature_branch, cwd=ctx.worktree)
        if rc != 0:
            return TaskResult(
                task_id=task.task_id,
                outcome="failed",
                branch=branch,
                worktree_path=path,
                diagnostics=(
                    f"branch_not_merged: {branch} is not an ancestor of {ctx.feature_branch} after "
                    f"merge_sequential (nothing landed); merge it manually with `git merge --no-ff {branch}`. "
                    + err.strip()
                ),
                lint=lint_report,
            )
        return TaskResult(task_id=task.task_id, outcome="merged", branch=branch, worktree_path=path, lint=lint_report)

    @staticmethod
    def _parse_worker_id(key: str) -> Tuple[str, int, str]:
        """Parse a `_worker_id`-produced dict key: `(task_id, attempt, execution_hex_or_empty)`.

        Dict keys use literal dots (`TASK-N.a<attempt>[.hex]`), unlike the sanitized
        branch/path forms -- never `int()` a suffix that might carry a UUID hex
        (Codebase Contract warning); this partitions on the FIRST `.a`, then the
        first `.` in what remains, so a hex fragment can never be mistaken for
        another `.a` boundary.
        """
        task_id, sep, rest = key.partition(".a")
        if not sep:
            return key, 0, ""
        attempt_part, _, exec_hex = rest.partition(".")
        return task_id, int(attempt_part), exec_hex

    async def merge(self, feature: str, worktree: str, task_id: str, execution_id: Optional[str] = None) -> TaskResult:
        """Consolidate the task's LATEST attempt branch (native tasks; re-merge after Sonnet fixed a conflict).

        FEAT-559: when `execution_id` is given, only that execution's OWN managers
        are considered -- never another execution's, nor the legacy/no-execution scope.
        """
        ctx = await self._resolve_feature(feature, worktree)
        scope = execution_id or ""
        attempts = sorted(
            (
                self._parse_worker_id(key)[1]
                for key in self._managers
                if self._manager_execution.get(key, "") == scope and self._parse_worker_id(key)[0] == task_id
            ),
            reverse=True,
        )
        if not attempts:
            raise CoderFailure("branch_not_found", f"no known attempt worktree for {task_id}")
        attempt = attempts[0]
        manager = self._manager_for(ctx, task_id, attempt, execution_id)
        branch = self._branch_for(ctx, task_id, attempt, execution_id)
        path = self._path_for(ctx, task_id, attempt, execution_id)

        sched = await self._scheduler_for(ctx)
        task_ref = next((t for t in sched.all_tasks() if t.id == task_id), None)
        if task_ref is None:
            raise CoderFailure("task_not_in_plan", f"{task_id} not found in the per-spec index")
        planned = PlannedTask(
            task_id=task_id, task_file=task_ref.file, title=task_ref.title, seat_label="", native=True
        )
        result = await self._consolidate(ctx, manager, planned, branch=branch, path=path)
        # The orchestrator calls `merge()` only after the native `Agent` returned, so
        # whatever the outcome the sub-worktree is no longer in use and `cleanup()` may
        # reclaim it (conflicts are still protected by `keep_conflicted`).
        self._native_inflight.discard(self._worker_id(task_id, attempt, execution_id))
        # FEAT-559: this IS the settlement point (spec: "reporting and settlement [are]
        # separate... native completion is acknowledged only after the worker has
        # received the child result") -- release the pool's seat reservation now,
        # regardless of merge outcome, so another task can use this model again.
        # `.pop()` makes this idempotent across a conflict-then-re-merge call pair.
        if execution_id is not None:
            pool = self._executions.get(execution_id)
            if pool is not None:
                reservation_uid = self._native_reservations.pop((execution_id, task_id), None)
                if reservation_uid is not None:
                    await pool.release(reservation_uid)

        # Emit an outcome row for the re-merge, attributed to the SAME
        # attempt_uid the original (pre-repair) outcome used. `_consolidate`
        # returns a bare `TaskResult` with no `attempts` of its own (it only
        # knows a branch/worktree, not telemetry identity) — `merge()` reads
        # `self._latest_attempt`, populated by `_run_task` for MCP-seat
        # tasks. A native task (`prepare_native`, never routed through
        # `_run_attempt`) has no entry here, so this correctly emits nothing
        # for it, per the spec's non-goal that native/codex seats produce no
        # telemetry rows at all.
        last_attempt = self._latest_attempt.get(task_id)
        if last_attempt is not None:
            await self._emit_outcome(
                ctx,
                attempt_rec=last_attempt,
                task_id=task_id,
                outcome=result.outcome,
                conflict_file_count=len(result.conflict_files),
                unexpected_file_count=len(result.unexpected_files),
            )
            result = result.model_copy(update={"attempts": [last_attempt]})

        return result

    async def cleanup(
        self, feature: str, worktree: str, keep_conflicted: bool = True, execution_id: Optional[str] = None
    ) -> CleanupReport:
        """Remove finished sub-worktrees THIS execution created; never touches orphan branches it never adopted.

        FEAT-559: when `execution_id` is given, only managers created under that
        exact execution scope are enumerated -- another execution's (or the legacy/
        no-execution scope's) managers, native reservations and jobs are untouched,
        even if they belong to the same engine instance/worktree.
        """
        await self._resolve_feature(feature, worktree)
        scope = execution_id or ""
        removed: List[str] = []
        kept: List[str] = []
        for key, manager in list(self._managers.items()):
            if self._manager_execution.get(key, "") != scope:
                continue  # a different execution's (or scope's) manager -- never enumerate it
            if key in self._native_inflight:
                # A native coder may still be running in there — see `_native_inflight`.
                kept.extend(branch for _path, branch in manager._created.values())  # noqa: SLF001
                continue
            before = dict(manager._created)  # noqa: SLF001 — no public API to enumerate created worktrees
            await manager.cleanup(keep_on_conflict=keep_conflicted)
            after = manager._created  # noqa: SLF001
            for worker_id, (_path, branch) in before.items():
                (kept if worker_id in after else removed).append(branch)
        return CleanupReport(removed=removed, kept=kept)

    _EXEC_HEX_BRANCH_SUFFIX = re.compile(r"-([0-9a-f]{32})$")

    @classmethod
    def _parse_orphan_suffix(cls, suffix: str) -> str:
        """Recognize both legacy (`TASK-N-a<attempt>`) and execution-qualified
        (`TASK-N-a<attempt>-<32 lowercase hex chars>`) branch suffixes, returning
        just `task_id` (or "" if unparseable).

        Strips a trailing 32-hex-char execution suffix FIRST (fixed length,
        unambiguous) before splitting on the last "-a" -- once dashes replace the
        worker id's dots (`_branch_suffix`), the hex fragment itself can contain
        "-a"-shaped substrings (e.g. a hex starting with "a" right after "a1-"),
        so a plain `rpartition("-a")` alone would mis-split an execution-qualified
        name. Never auto-adopts either form -- this is parsing for reporting only.
        """
        match = cls._EXEC_HEX_BRANCH_SUFFIX.search(suffix)
        core = suffix[: match.start()] if match else suffix
        task_id, sep, _attempt = core.rpartition("-a")
        return task_id if sep and task_id else ""

    async def _orphan_branches(self, ctx: _FeatureCtx) -> List[OrphanBranch]:
        rc, out, _err = await _git(
            "branch", "--list", f"{ctx.feature_branch}--TASK-*", "--format=%(refname:short)", cwd=ctx.worktree
        )
        if rc != 0:
            return []
        live = self._jobs.running_task_ids()
        prefix = f"{ctx.feature_branch}--"
        orphans: List[OrphanBranch] = []
        for branch in (b.strip() for b in out.splitlines() if b.strip()):
            if not branch.startswith(prefix):
                continue
            suffix = branch[len(prefix) :]  # e.g. "TASK-0001-a1" or "TASK-0001-a1-<32 hex chars>"
            task_id = self._parse_orphan_suffix(suffix)
            if not task_id:
                continue
            if task_id in live:
                continue
            _rc, commits_out, _err = await _git(
                "rev-list", "--count", f"{ctx.feature_branch}..{branch}", cwd=ctx.worktree
            )
            commits = int(commits_out.strip() or 0)
            _rc, files_out, _err = await _git(
                "diff", "--name-only", f"{ctx.feature_branch}...{branch}", cwd=ctx.worktree
            )
            files = [f for f in files_out.splitlines() if f.strip()]
            orphans.append(OrphanBranch(task_id=task_id, branch=branch, commits=commits, files=files))
        return orphans

    async def _journal(self, worktree: str, job: CoderJob) -> None:
        """Write-only snapshot: <worktree>/.sdd-coder/jobs/<job_id>.json (dir is git-ignored, TASK-3122 adds the rule).

        Code-review fix (FEAT-549, IMPORTANT): wrapped the `mkdir`/`write_text` pair in
        `asyncio.to_thread` — this method used to call them directly from async call sites
        (`run_chunk`, `wait`), inconsistent with the S11 pattern this same module otherwise
        follows everywhere else for sync I/O (`_resolve_feature`'s index glob/read,
        `_scheduler_for`, `_consolidate`'s task-file read).
        """

        def _write() -> None:
            d = Path(worktree) / ".sdd-coder" / "jobs"
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{job.job_id}.json").write_text(job.model_dump_json(indent=2), encoding="utf-8")

        await asyncio.to_thread(_write)

    async def _write_execution_snapshot(self, worktree: str, execution_id: str, snapshot: ExecutionSnapshot) -> bool:
        """Write an atomic per-execution snapshot (TASK-3282).

        Persists to <worktree>/.sdd-coder/executions/<uuid>.json using atomic
        replace: writes to a temporary sibling, then renames over the original
        if it exists. Returns True if write succeeded, False if write/durable
        persistence failed.
        """

        def _write_atomic() -> bool:
            """Write atomically using temporary file + rename pattern."""
            try:
                base_dir = Path(worktree) / ".sdd-coder" / "executions"
                base_dir.mkdir(parents=True, exist_ok=True)
                target_file = base_dir / f"{execution_id}.json"
                temp_file = base_dir / f"{execution_id}.tmp"

                # Write to temporary file first
                temp_file.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")

                # Atomic replace: rename temp over target
                temp_file.replace(target_file)
                return True
            except OSError as exc:  # IOError is an alias of OSError since Python 3.3
                self.logger.warning("failed to write execution snapshot for %s: %s", execution_id, exc)
                return False

        return await asyncio.to_thread(_write_atomic)

    async def _read_execution_snapshot(self, worktree: str, execution_id: str) -> Optional[ExecutionSnapshot]:
        """Read a persisted execution snapshot (TASK-3282).

        Returns the snapshot if found and valid, None if not found, and raises
        CoderFailure if the file is corrupt/unreadable.
        """

        def _read() -> Optional[ExecutionSnapshot]:
            """Read from disk, validating structure."""
            try:
                snapshot_file = Path(worktree) / ".sdd-coder" / "executions" / f"{execution_id}.json"
                if not snapshot_file.is_file():
                    return None
                data = json.loads(snapshot_file.read_text(encoding="utf-8"))
                return ExecutionSnapshot(**data)
            except FileNotFoundError:
                return None
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                raise CoderFailure(
                    "internal_error",
                    f"corrupt execution snapshot for {execution_id}: {exc}",
                ) from exc

        return await asyncio.to_thread(_read)

    async def status(self, job_id: str) -> CoderJob:
        """Get job status and flush any pending execution snapshots (TASK-3282).

        Retries pending suspension persistence idempotently; exposes latest pool
        state and degraded persistence status if applicable.
        """
        try:
            job = self._jobs.get(job_id)
        except KeyError as exc:
            raise CoderFailure("job_not_found", f"unknown job {job_id}") from exc

        # Flush any pending execution snapshots (retry persistence if degraded)
        for execution_id, pool in list(self._executions.items()):
            if pool._persistence_degraded:
                # Try to persist current state atomically
                snapshot = pool.snapshot()
                # Enrich with engine bookkeeping (native_reservations and outstanding_job_ids)
                for (exec_id, task_id), _attempt_uid in list(self._native_reservations.items()):
                    if exec_id == execution_id:
                        manager_key = (
                            f"{task_id}.a{self._latest_attempt.get(task_id, AttemptRecord(attempt=1)).attempt}"
                        )
                        if (
                            manager_key in self._manager_execution
                            and self._manager_execution[manager_key] == execution_id
                        ):
                            snapshot.native_reservations[task_id] = manager_key

                for job_id_iter, job_wt in list(self._job_worktrees.items()):
                    if job_wt == pool.worktree_path and job_id_iter not in snapshot.outstanding_job_ids:
                        snapshot.outstanding_job_ids.append(job_id_iter)

                persisted = await self._write_execution_snapshot(pool.worktree_path, execution_id, snapshot)
                if persisted:
                    pool._persistence_degraded = False
                    self.logger.info("recovered persistence for execution %s", execution_id)

        return job

    def _research_for(self, ctx: _FeatureCtx, *, worktree_path: str) -> ResearchOutput:
        """Synthetic ResearchOutput — TaskScopedBrief requires one; no Jira ticket exists for a coder attempt."""
        return ResearchOutput(
            jira_issue_key="",
            spec_path=ctx.spec_path,
            feat_id=ctx.feature_id,
            branch_name=ctx.feature_branch,
            worktree_path=worktree_path,
            repo_path=ctx.worktree,
            log_excerpts=[],
            base_branch=ctx.base_branch,
        )

    def _labels_for(self, task: PlannedTask, seat: RosterSeat, attempt: int) -> DispatchLabels:
        return DispatchLabels(
            task_id=task.task_id,
            task_title=task.title,
            task_file=task.task_file,
            seat=f"sdd-coder.{seat.label}",
            agent=seat.backend or "native",
            model=seat.model,
            subagent="sdd-coder",
            attempt=attempt,
        )

    async def _run_attempt(
        self,
        ctx: _FeatureCtx,
        task: PlannedTask,
        seat: RosterSeat,
        *,
        attempt: int,
        job_id: str,
        execution_id: Optional[str] = None,
        pool: Optional["ExecutionPool"] = None,
    ) -> Tuple[AttemptRecord, Optional[DevelopmentOutput], str, SubWorktreeManager, str, str]:
        """ONE dispatch in ONE fresh sub-worktree. Returns (record, output|None, error, manager, branch, path).

        FEAT-559: When execution_id/pool are provided, performs admission gating
        before dispatch. If the seat is no longer eligible (suspended, busy),
        returns immediately with a not_dispatched error without creating a worktree.
        """
        assert seat.backend is not None, "_run_attempt is only called for mcp seats; native tasks use prepare_native"
        manager = self._manager_for(ctx, task.task_id, attempt, execution_id)
        # `_branch_for`/`_path_for` derive from the SAME `_worker_id` passed to
        # `manager.create()` below (spec: "centralize derived names; remove
        # duplicated hard-coded branch construction from dispatch/merge paths"),
        # so `path`/`branch` are always defined even if `manager.create()` itself
        # raises below — see the code-review fix note on the `try:` block having
        # moved to cover worktree-creation and dispatcher-construction too.
        branch = self._branch_for(ctx, task.task_id, attempt, execution_id)
        path = self._path_for(ctx, task.task_id, attempt, execution_id)
        # A unique id per attempt: `attempt` restarts at 1 on every _run_task
        # invocation (line 592) and both attempts of a task share `job_id`, so
        # neither can key the telemetry join (spec §10 R3).
        attempt_uid = uuid.uuid4().hex

        # FEAT-559: Admission gating - check pool admission before dispatch
        if pool is not None and execution_id is not None:
            from parrot.flows.dev_loop.sdd_coder.pool import _effective_key

            key = _effective_key(seat)
            if key is None:
                # No model identity - cannot admit
                return (
                    AttemptRecord(
                        attempt=attempt,
                        seat_label=seat.label,
                        backend=seat.backend,
                        model=seat.model,
                        started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        ended_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        duration_s=0.0,
                        usage={},
                        error="model_identity_required: seat has no configured model",
                        attempt_uid=attempt_uid,
                        job_id=job_id,
                    ),
                    None,
                    "model_identity_required: seat has no configured model",
                    manager,
                    "",
                    "",
                )

            try:
                # Reserve the seat - this will block if busy, raise if excluded
                attempt_uid = await pool.admit(task.task_id, key)
            except ValueError as exc:
                # Seat is excluded or pool is closed - return not_dispatched
                error_msg = str(exc)
                return (
                    AttemptRecord(
                        attempt=attempt,
                        seat_label=seat.label,
                        backend=seat.backend,
                        model=seat.model,
                        started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        ended_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        duration_s=0.0,
                        usage={},
                        error=error_msg,
                        attempt_uid=attempt_uid,
                        job_id=job_id,
                        execution_id=execution_id or "",
                    ),
                    None,
                    error_msg,
                    manager,
                    "",
                    "",
                )

        collector = AttemptTelemetryCollector(
            attempt=attempt, seat=seat, attempt_uid=attempt_uid, job_id=job_id, execution_id=execution_id
        )
        # Read `task.task_file` and count `parse_task_files(...)` NOW,
        # while the worktree still exists — set declared_files /
        # declared_files_known on the collector. An unreadable file means
        # known=False, never 0.
        try:
            task_md_path = await asyncio.to_thread(lambda: Path(ctx.worktree, task.task_file).resolve())
            worktree_root = await asyncio.to_thread(lambda: Path(ctx.worktree).resolve())
            if task_md_path == worktree_root or str(task_md_path).startswith(str(worktree_root) + os.sep):
                task_md = await asyncio.to_thread(task_md_path.read_text, "utf-8")
                collector.declared_files = len(parse_task_files(task_md))
                collector.declared_files_known = True
        except Exception:
            # File unreadable or parsing failed - set known=False
            collector.declared_files_known = False
        output: Optional[DevelopmentOutput] = None
        error = ""
        assessment: Optional[ComplexityAssessment] = None
        try:
            # Admission (spec: "check the constructed dispatch profile's model
            # before dispatcher.dispatch: a missing or changed effective model
            # is ineligible on restricted tasks"). `seat` is the roster's
            # already-probed entry (`available_seats` substitutes any smoke-test
            # fallback model before `plan()`/`eligible_seats` ever saw it), so
            # this defends against a plan/seat mismatch, not against re-probing.
            # `execution_id` (FEAT-559) MUST be threaded through here: the plan
            # was cached under the qualified `f"{feature_id}:{execution_id}"`
            # key, and omitting it would silently miss that cache entry and
            # recompute an unscoped legacy plan on every dispatch attempt.
            plan = await self._cached_plan(ctx.feature, ctx.worktree, ctx, execution_id=execution_id)
            assessment = plan.assessments.get(task.task_id)
            if assessment is not None and assessment.classification in ("complex", "unknown"):
                strong_keys = {(sm.backend, sm.model) for sm in self.roster.complexity.strong_models}
                if (seat.backend, seat.model or "") not in strong_keys:
                    raise CoderFailure(
                        "complex_model_unavailable",
                        f"seat {seat.label!r} (backend={seat.backend!r}, model={seat.model!r}) is not "
                        f"eligible for {assessment.classification} task {task.task_id}",
                        task_id=task.task_id,
                    )

            # Code-review fix (FEAT-549, IMPORTANT): sub-worktree creation and dispatcher
            # construction used to happen BEFORE this try block — a `git worktree add`
            # failure or a `build_dispatcher` error would propagate raw out of
            # `_run_attempt`/`_run_task`, landing in `run_chunk`'s outer
            # `asyncio.gather(..., return_exceptions=True)` as a bare "failed" TaskResult
            # with an EMPTY `attempts` list, bypassing the attempt-2-on-a-different-seat
            # retry ladder entirely. Moved inside so every failure mode becomes a proper
            # attempt error the ladder can act on.
            await manager.create(self._worker_id(task.task_id, attempt, execution_id))
            await self._write_attempt_scope(path, task.task_id, task.task_file, ctx.feature_branch)
            dispatcher, profile = self._dispatcher_builder(
                DevAgentSpec(agent=seat.backend, model=seat.model),
                redis_url=self._redis_url,
                max_concurrent=1,
                stream_ttl_seconds=self._stream_ttl,
            )
            profile = profile.model_copy(update={"subagent": "sdd-coder"})  # S7 — every profile defaults to sdd-worker
            feedback_context = await self._feedback_for(ctx, task, seat.backend, seat.model)
            self._feedback_contexts[attempt_uid] = feedback_context
            output = await dispatcher.dispatch(
                brief=TaskScopedBrief(
                    research=self._research_for(ctx, worktree_path=path),
                    task_id=task.task_id,
                    task_file=task.task_file,
                    coder_feedback=feedback_context,
                ),
                profile=profile,
                output_model=DevelopmentOutput,
                run_id=job_id,
                # NOT f"sdd-coder.{seat.label}" (spec's literal wording): `_publish_event` rolls
                # `node_id` up via `_owning_node_id` (splits on the first '.') and hands it to
                # `action_from_dispatch_event`, which constructs a `DevLoopAction` typed with the
                # CLOSED `NodeId` Literal (session_state.py:140-158) — "sdd-coder" is not a member,
                # so that construction would raise and `_apply_to_session_host` silently swallows
                # it (by design — "the shim must never break a dispatch"), meaning
                # `AttemptTelemetryCollector.apply()` would NEVER fire and AC-10's usage capture
                # would silently no-op for every real dispatch. "development" IS a valid NodeId
                # (the same one the interactive DevAgentPool dispatches under) and is not touched
                # by this feature; per-seat identity for downstream consumers still flows through
                # `labels.seat` ("sdd-coder.<label>"), which `action_from_dispatch_event` reads
                # from `payload["seat"]` (stamped by `DispatchLabels.as_payload()`) in preference to
                # `node_id` — verified: dispatchers/_shared.py:92-117, session_state.py:1457-1489.
                node_id=f"development.sdd-coder-{seat.label}",
                cwd=path,
                session_host=collector,
                labels=self._labels_for(task, seat, attempt),
            )
            # FEAT-553: a banned import is an attempt error (not a fidelity outcome) so the
            # retry ladder below gives a different seat a shot at the same task.
            _rc, diff, _err = await _git("diff", "--name-only", f"{ctx.feature_branch}...HEAD", cwd=path)
            violations = await check_banned_imports(path, [p for p in diff.splitlines() if p.strip()])
            if violations:
                error = "BannedImport: " + "; ".join(violations)
                collector.error = error
                output = None
        except Exception as exc:  # noqa: BLE001 — DispatchExecutionError/DispatchOutputValidationError/
            # asyncio.TimeoutError all subclass Exception; every failure becomes an attempt error, the
            # ladder (attempt 2 on a different seat, then "failed") decides what happens next.
            error = f"{type(exc).__name__}: {exc}"
            collector.error = error
            collector.error_class = type(exc).__name__
            self.logger.warning("attempt %d of %s on %s failed: %s", attempt, task.task_id, seat.label, error)

        record = collector.record()
        if record.resolved_model and record.resolved_model != seat.model:
            self._feedback_unknown_exposure.add(attempt_uid)

        # Spec: "A provider-reported resolved_model outside the allowlist is a
        # model mismatch: record it and refuse consolidation as successful
        # delivery; it must not be relabeled as an allowed model." A same-provider
        # probe fallback (or any other post-dispatch model substitution) that
        # lands outside the strong-model allowlist turns an otherwise-clean
        # attempt into an error, so `_run_task` never consolidates it.
        if not error and assessment is not None and assessment.classification in ("complex", "unknown"):
            reported_model = record.resolved_model or seat.model or ""
            strong_keys = {(sm.backend, sm.model) for sm in self.roster.complexity.strong_models}
            if (seat.backend, reported_model) not in strong_keys:
                error = (
                    f"complex_model_unavailable: reported model {reported_model!r} is not an allowed "
                    f"strong-model identity for {assessment.classification} task {task.task_id}"
                )
                collector.error = error
                record = record.model_copy(update={"error": error, "error_class": "complex_model_unavailable"})

        # Attach the assessment this attempt was dispatched under (spec: "attempt
        # records refer to the assessment ID").
        assessment_id = assessment.assessment_id if assessment is not None else ""
        record = record.model_copy(update={"assessment_id": assessment_id})

        self._feedback_sources[attempt_uid] = (
            ctx.worktree,
            task.task_id,
            seat.backend,
            record.resolved_model or record.model,
        )

        # FEAT-559: Release the pool reservation after attempt settles
        if pool is not None:
            try:
                await pool.release(attempt_uid)
            except Exception:
                self.logger.warning("failed to release pool reservation for attempt_uid=%s", attempt_uid, exc_info=True)

        # Write the measurement BEFORE consolidation: if the server dies between
        # here and the outcome, the attempt row still survives and the analysis
        # reports an incomplete pair rather than losing the sample (spec §2).
        # `self._sink is not None`, NOT `hasattr(self, "_sink")` — the attribute
        # is always set in __init__ (to None or an instance), so `hasattr`
        # alone is always True and calling `None.write_attempt(...)` here
        # would raise AttributeError on every attempt when telemetry is off,
        # silently swallowed below with no log line (contradicting AC-11's
        # "logs and drops").
        if self._sink is not None:
            try:
                await self._sink.write_attempt(
                    build_attempt_row(
                        record,
                        feature_id=ctx.feature_id,
                        job_id=job_id,
                        task_id=task.task_id,
                        declared_files=record.declared_files,
                    )
                )
            except Exception:
                # Sink failure must not change the outcome (AC-11) — but it
                # must still be visible, or a silent build_attempt_row/write
                # regression (e.g. a ValidationError) would go unnoticed forever.
                self.logger.warning(
                    "telemetry attempt-row write failed for %s attempt %d", task.task_id, attempt, exc_info=True
                )
        return record, output, error, manager, branch, path

    async def _emit_outcome(
        self,
        ctx: _FeatureCtx,
        *,
        attempt_rec: AttemptRecord,
        task_id: str,
        outcome: str,
        conflict_file_count: int = 0,
        unexpected_file_count: int = 0,
    ) -> None:
        """Write one `OutcomeRow` for `attempt_rec`, never raising (AC-11).

        `event_seq` is drawn from `self._event_seq_counters`, keyed on
        `attempt_rec.attempt_uid` and persisted for the engine's lifetime —
        NOT re-derived per call — so a `merge()` re-emission for the same
        attempt_uid after a manual conflict repair correctly gets the NEXT
        sequence number rather than a recomputed duplicate (spec AC-19: "a
        merge_conflict followed by a repaired merge() yields two rows for
        one attempt_uid with increasing event_seq").
        """
        if self._sink is None:
            return
        seq = self._event_seq_counters.get(attempt_rec.attempt_uid, 0) + 1
        self._event_seq_counters[attempt_rec.attempt_uid] = seq
        try:
            await self._sink.write_outcome(
                OutcomeRow(
                    ts=datetime.now(timezone.utc).isoformat(),
                    attempt_uid=attempt_rec.attempt_uid,
                    job_id=attempt_rec.job_id,
                    feature_id=ctx.feature_id,
                    task_id=task_id,
                    attempt=attempt_rec.attempt,
                    event_seq=seq,
                    outcome=outcome,
                    conflict_file_count=conflict_file_count,
                    unexpected_file_count=unexpected_file_count,
                    execution_id=attempt_rec.execution_id,
                )
            )
        except Exception:
            # Sink failure must not change the outcome (AC-11) — but it must
            # still be visible, or a silent regression here would go
            # unnoticed forever (matching CoderTelemetrySink._append's own
            # self.logger.warning(...) pattern).
            self.logger.warning(
                "telemetry outcome-row write failed for %s attempt_uid=%s",
                task_id,
                attempt_rec.attempt_uid,
                exc_info=True,
            )

    def _classify_failure_reason(self, error: str, error_class: str, outcome: Optional[str] = None) -> Optional[str]:
        """Classify a failure into a suspension reason (FEAT-559).

        Traverse bounded exception cause chain for TimeoutError. Distinguish
        dispatch timeout from poll timeout. Returns None for non-suspendable
        failures (lint, cancellation, Git conflicts, etc.).

        Args:
            error: The error message string.
            error_class: The exception class name.
            outcome: Optional outcome from consolidation (e.g., "fidelity_violation").

        Returns:
            Suspension reason string or None if not suspendable.
        """
        # Check for fidelity violation from consolidation
        if outcome == "fidelity_violation":
            return "fidelity_violation"

        # Check for dirty delivery
        if error_class == "dirty_task_worktree" or (error and error.startswith("dirty_task_worktree:")):
            return "dirty_delivery"

        # Check for dispatch timeout - traverse cause chain for wrapped TimeoutError.
        # The real production wrap (`dispatchers/llm.py`'s `except TimeoutError as
        # exc: raise DispatchExecutionError(f"Dispatch exceeded {timeout}s
        # wall-clock cap") from exc`) never puts the literal substring
        # "TimeoutError" in its message -- only "wall-clock cap" survives into
        # `error`. Without this, every real dispatch timeout was silently
        # misclassified as a generic "dispatch_error" (AC-3/AC-12's recorded
        # `reason` was wrong for the exact scenario the spec's own motivation
        # describes), even though it still qualified for suspension either way.
        if error_class == "TimeoutError" or "TimeoutError" in error or "wall-clock cap" in error:
            return "timeout"

        # Check for dispatch execution error
        if error_class in ("DispatchExecutionError", "DispatchOutputValidationError"):
            # Check if wrapped cause is a timeout
            if "TimeoutError" in error or "wall-clock cap" in error:
                return "timeout"
            if error_class == "DispatchOutputValidationError":
                return "invalid_output"
            return "dispatch_error"

        # Check for banned import - this is a fidelity issue
        if error and error.startswith("BannedImport:"):
            return "fidelity_violation"

        # Non-suspendable failures
        # - Lint findings
        # - Cancellation
        # - Git merge conflicts
        # - Poll timeout (not dispatch timeout)
        # - Worktree creation failures
        # - Build/setup errors
        non_suspendable_prefixes = (
            "LintError:",
            "CancelledError",
            "merge_conflict",
            "worktree creation",
            "git worktree",
            "MergeConflict",
        )
        if any(error.startswith(prefix) for prefix in non_suspendable_prefixes if error):
            return None

        # Default: check error class for known suspendable types
        if error_class in ("RuntimeError", "Exception") and error:
            # Generic dispatch failure - suspendable
            if "dispatch" in error.lower() or "timeout" in error.lower():
                return "dispatch_error"

        return None

    async def _classify_and_suspend(
        self,
        ctx: _FeatureCtx,
        pool: "ExecutionPool",
        execution_id: str,
        task: PlannedTask,
        seat: RosterSeat,
        attempt_rec: AttemptRecord,
        error: str,
        job_id: str,
    ) -> None:
        """Classify failure and suspend model if qualifying (FEAT-559).

        Builds SuspensionRecord with fixed timestamps, observed duration,
        sanitized evidence and both configured/resolved keys. Atomically
        suspends first, then awaits persistence before retry.

        Does NOT suspend for:
        - Lint findings
        - Cancellation
        - Poll timeout
        - Git conflicts
        """
        from parrot.flows.dev_loop.sdd_coder.pool import _effective_key
        from parrot.knowledge.wiki.ledger.coder_suspensions import (
            SuspensionRecord,
        )

        reason = self._classify_failure_reason(error, attempt_rec.error_class)
        if reason is None:
            self.logger.info(
                "Non-suspendable failure for %s on %s: %s",
                task.task_id,
                seat.label,
                error[:100] if error else "(no error)",
            )
            return

        key = _effective_key(seat)
        if key is None:
            self.logger.warning("Cannot suspend seat %s - no model identity", seat.label)
            return

        # Build blocked_keys - include both configured and resolved if different
        blocked_keys = [key]
        if attempt_rec.resolved_model and attempt_rec.resolved_model != seat.model:
            resolved_key = ModelKey(backend=seat.backend or "", model=attempt_rec.resolved_model)
            if resolved_key not in blocked_keys:
                blocked_keys.append(resolved_key)

        now = datetime.now(timezone.utc)
        cooldown_seconds = self.roster.suspension_policy.cooldown_seconds
        expires_at = datetime.fromtimestamp(now.timestamp() + cooldown_seconds, tz=timezone.utc)

        record = SuspensionRecord(
            execution_id=execution_id,
            feature_id=ctx.feature_id,
            task_id=task.task_id,
            attempt_uid=attempt_rec.attempt_uid,
            job_id=job_id,
            source="engine",
            seat_label=seat.label,
            backend=seat.backend or "",
            configured_model=seat.model,
            resolved_model=attempt_rec.resolved_model,
            blocked_keys=blocked_keys,
            reason=reason,
            occurred_at=now,
            expires_at=expires_at,
            duration_s=attempt_rec.duration_s,
            exception_class=attempt_rec.error_class,
            evidence_ref=f"job:{job_id}",
            explanation=f"Model {seat.model} failed with {reason} on {task.task_id}",
        )

        receipt = await pool.suspend(record)
        self.logger.info(
            "Suspended model %s (reason=%s, persisted=%s, pool_generation=%s)",
            seat.model,
            reason,
            receipt.persisted,
            receipt.pool_generation,
        )
        # Persist the new local exclusion to disk immediately: `end_execution`/
        # `status()`'s degraded-retry were the only other snapshot-write call
        # sites, so a process crash between a real suspension and either of
        # those would restart with the suspension durably recorded in the
        # ledger (via `pool.suspend()`'s own `_suspension_store.record()` call
        # above) but the local worktree snapshot at `.sdd-coder/executions/`
        # would not yet reflect it -- writing here closes that gap for the
        # exact event AC-10/AC-13 depend on surviving a restart.
        persisted_snapshot = await self._write_execution_snapshot(pool.worktree_path, execution_id, pool.snapshot())
        if not persisted_snapshot:
            self.logger.warning(
                "failed to persist execution snapshot for %s after suspending %s", execution_id, seat.model
            )

    async def _select_retry_seat(
        self,
        pool: Optional["ExecutionPool"],
        failed_label: str,
        tried_seats: set[str],
        *,
        eligible_labels: Optional[Set[str]] = None,
    ) -> Optional[RosterSeat]:
        """Select a healthy, not-yet-tried seat for retry (FEAT-559).

        When pool is available, uses pool's eligible seats and waits on busy
        healthy seats through the pool condition. Falls back to legacy
        assigner-based retry when pool is None.

        `eligible_labels` (FEAT-561), when given, additionally restricts the
        candidate to that set -- spec: "a failed strong-model attempt cannot
        retry through a weak seat." `None` means unrestricted (standard
        classification).

        Args:
            pool: The execution pool (or None for legacy behavior).
            failed_label: The label of the seat that just failed.
            tried_seats: Set of seat labels already tried.
            eligible_labels: Optional restriction to a specific label set.

        Returns:
            A healthy RosterSeat for retry, or None if exhausted.
        """
        if pool is None:
            # Legacy path: use global assigner
            if self._assigner is None:
                return None
            return self._assigner.retry_seat(failed_label, tried_seats, eligible_labels=eligible_labels)

        # Pool-based selection: find healthy, not-yet-tried seats
        async with pool._condition:
            while True:
                # Check pool status
                if pool._status in ("closed", "recovery_required"):
                    return None

                # Find eligible seats
                for seat in pool._seats:
                    from parrot.flows.dev_loop.sdd_coder.pool import _effective_key

                    # A native seat has no dispatcher: `_run_attempt` asserts
                    # `seat.backend is not None` and `_run_task` never routes a
                    # retry through `coder_prepare_native`, so selecting one here
                    # would crash the attempt instead of retrying it (mirrors
                    # `ChunkAssigner.retry_seat`'s own `kind == "native"` guard,
                    # issue:e01c03baf493).
                    if seat.kind == "native":
                        continue
                    key = _effective_key(seat)
                    if key is None:
                        continue
                    if seat.label in tried_seats:
                        continue
                    if eligible_labels is not None and seat.label not in eligible_labels:
                        continue
                    if key in pool._busy_seats:
                        continue
                    if key in pool._initial_exclusions or key in pool._local_exclusions:
                        continue
                    view = pool._seat_views.get(key)
                    if view is None or not view.available or view.suspended or view.probe_unavailable:
                        continue
                    # Found a healthy, free seat
                    return seat

                # No healthy free seat available - check if we should wait
                # Check if any healthy seat is busy (worth waiting for)
                has_busy_healthy = False
                for seat in pool._seats:
                    from parrot.flows.dev_loop.sdd_coder.pool import _effective_key

                    if seat.kind == "native":
                        continue
                    key = _effective_key(seat)
                    if key is None or seat.label in tried_seats:
                        continue
                    if eligible_labels is not None and seat.label not in eligible_labels:
                        continue
                    if key in pool._busy_seats:
                        view = pool._seat_views.get(key)
                        if view and view.available and not view.suspended and not view.probe_unavailable:
                            has_busy_healthy = True
                            break

                if not has_busy_healthy:
                    # Pool exhausted - no point waiting
                    return None

                # Wait for a seat to be released or suspended
                await pool._condition.wait()

    async def _run_task(
        self,
        ctx: _FeatureCtx,
        task: PlannedTask,
        seat: RosterSeat,
        *,
        job_id: str,
        execution_id: Optional[str] = None,
        pool: Optional["ExecutionPool"] = None,
    ) -> TaskResult:
        """Run up to two attempts, retrying dispatch and dirty-worktree failures on another MCP seat.

        A clean dispatcher response is not sufficient for success: an agent can
        return ``DevelopmentOutput`` after exhausting its turn budget while
        leaving its changes uncommitted. Treat that first-attempt
        ``dirty_task_worktree`` outcome as retryable, but preserve fidelity
        violations and merge conflicts for the orchestrator to handle.

        FEAT-559: When execution_id/pool are provided, uses pool-based admission
        gating, failure classification, and healthy-model retry selection.
        """
        attempts: List[AttemptRecord] = []
        tried_seats: set[str] = {seat.label}  # Track seats we've already tried

        rec, out, err, manager, branch, path = await self._run_attempt(
            ctx, task, seat, attempt=1, job_id=job_id, execution_id=execution_id, pool=pool
        )
        attempts.append(rec)

        if not err:
            result = await self._consolidate(ctx, manager, task, branch=branch, path=path)
            if not (result.outcome == "failed" and result.diagnostics.startswith("dirty_task_worktree:")):
                final_result = result.model_copy(update={"attempts": attempts, "development_output": out})
                self._latest_attempt[task.task_id] = rec
                await self._emit_outcome(
                    ctx,
                    attempt_rec=rec,
                    task_id=task.task_id,
                    outcome=result.outcome,
                    conflict_file_count=len(result.conflict_files),
                    unexpected_file_count=len(result.unexpected_files),
                )
                return final_result

            err = result.diagnostics
            rec = rec.model_copy(update={"error": err, "error_class": "dirty_task_worktree"})
            attempts[-1] = rec

        if err:
            # FEAT-559: Classify failure and suspend model if qualifying
            if pool is not None and execution_id is not None:
                await self._classify_and_suspend(
                    ctx=ctx,
                    pool=pool,
                    execution_id=execution_id,
                    task=task,
                    seat=seat,
                    attempt_rec=rec,
                    error=err,
                    job_id=job_id,
                )

            # FEAT-561: a restricted (complex/unknown) task's retry must stay
            # within the same strong-model eligible set as attempt 1 (spec:
            # "a failed strong-model attempt cannot retry through a weak
            # seat"). `None` means unrestricted (standard classification).
            eligible_labels = await self._eligible_retry_labels(ctx, task, execution_id=execution_id)

            # FEAT-559: Select retry from healthy not-yet-tried seats,
            # additionally restricted to `eligible_labels` when given.
            retry = await self._select_retry_seat(pool, seat.label, tried_seats, eligible_labels=eligible_labels)
            if retry is None and eligible_labels is not None:
                # Restricted task, no eligible retry seat left: make the block
                # explicit rather than silently falling through with attempt
                # 1's unrelated dispatch error as the only diagnostic (spec:
                # "if none exists return a visible blocked/failed result with
                # complex_model_unavailable diagnostic, preserving previous
                # attempts").
                no_retry_error = f"complex_model_unavailable: no eligible retry seat for {task.task_id}"
                rec = rec.model_copy(
                    update={"error": f"{rec.error}\n{no_retry_error}" if rec.error else no_retry_error}
                )
                attempts[-1] = rec
                err = rec.error

            if retry is not None:
                tried_seats.add(retry.label)
                # Emit attempt 1's own outcome NOW, before running the
                # retry: `_run_task` only returns ONE `TaskResult`, so if
                # attempt 2 succeeds below, attempt 1's failure would
                # otherwise never get an outcome row at all — the exact
                # "failed-then-merged" scenario AC-19 names, "attributed
                # per attempt, never to both". (If no retry seat is
                # available, `rec` — still attempt 1 — falls through to the
                # single emission below instead, avoiding a double-emit.)
                await self._emit_outcome(ctx, attempt_rec=rec, task_id=task.task_id, outcome="failed")
                rec, out, err, manager, branch, path = await self._run_attempt(
                    ctx, task, retry, attempt=2, job_id=job_id, execution_id=execution_id, pool=pool
                )
                attempts.append(rec)

        if err:
            # FEAT-559: Classify failure for attempt 2 if it also failed. `retry`
            # (the RosterSeat attempt 2 actually ran on) is bound here: this branch
            # only runs when `len(attempts) > 1`, which only happens after the
            # `if retry is not None:` branch above appended attempt 2 -- passing
            # `attempts[-1].seat_label` (a str, not a RosterSeat) here raised
            # AttributeError inside `_classify_and_suspend`/`_effective_key` on
            # every second-attempt failure, silently swallowed by run_chunk's
            # `return_exceptions=True` gather into an opaque "failed" outcome.
            if pool is not None and execution_id is not None and len(attempts) > 1:
                await self._classify_and_suspend(
                    ctx=ctx,
                    pool=pool,
                    execution_id=execution_id,
                    task=task,
                    seat=retry,
                    attempt_rec=rec,
                    error=err,
                    job_id=job_id,
                )

            # Both attempts failed, or no retry seat was ever available:
            # `rec` is the one attempt whose outcome has NOT been emitted
            # yet (attempt 1 already got its row above if a retry ran).
            await self._emit_outcome(ctx, attempt_rec=rec, task_id=task.task_id, outcome="failed")
            self._latest_attempt[task.task_id] = rec
            return TaskResult(
                task_id=task.task_id,
                outcome="failed",
                branch=branch,
                worktree_path=path,
                attempts=attempts,
                diagnostics="\n".join(a.error for a in attempts if a.error),
            )

        result = await self._consolidate(ctx, manager, task, branch=branch, path=path)
        final_result = result.model_copy(update={"attempts": attempts, "development_output": out})

        last_attempt = attempts[-1]  # the attempt that produced the result
        self._latest_attempt[task.task_id] = last_attempt
        await self._emit_outcome(
            ctx,
            attempt_rec=last_attempt,
            task_id=task.task_id,
            outcome=result.outcome,
            conflict_file_count=len(result.conflict_files),
            unexpected_file_count=len(result.unexpected_files),
        )

        return final_result

    async def run_chunk(
        self,
        feature: str,
        worktree: str,
        task_ids: List[str],
        execution_id: Optional[str] = None,
    ) -> CoderJob:
        """Validate, register, RETURN. Everything slow happens inside the job (S4, AC-21).

        Args:
            feature: Feature identifier.
            worktree: Absolute path to the feature worktree.
            task_ids: List of task IDs to dispatch.
            execution_id: Optional execution ID for FEAT-559 pools. When provided,
                validates against the execution pool and carries execution ownership.

        Raises:
            CoderFailure with codes:
                - plan_stale: cached plan's pool_generation doesn't match current pool
                - execution_not_found: execution_id provided but no matching pool
        """
        ctx = await self._resolve_feature(feature, worktree)

        # FEAT-559: Validate execution_id and pool generation before plan validation
        pool: Optional[ExecutionPool] = None
        pool_generation = 0
        if execution_id is not None:
            if execution_id not in self._executions:
                raise CoderFailure(
                    "execution_not_found",
                    f"no execution found with id {execution_id}; call begin_execution first",
                )
            pool = self._executions[execution_id]
            pool_generation = pool.generation

        plan = await self._cached_plan(feature, worktree, ctx, execution_id=execution_id)

        # FEAT-559: Reject stale plan before job/worktree creation
        if execution_id is not None and plan.pool_generation != pool_generation:
            raise CoderFailure(
                "plan_stale",
                f"cached plan generation {plan.pool_generation} does not match pool generation {pool_generation}",
                pool_generation=pool_generation,
                plan_generation=plan.pool_generation,
            )

        first = {t.task_id: t for t in (plan.chunks[0].tasks if plan.chunks else [])}

        # Scope the running-task check to THIS execution (jobs.py's own
        # documented contract): unscoped, two unrelated executions/features
        # that happen to dispatch the same task_id could spuriously block
        # each other, violating AC-6/AC-11 execution isolation.
        running = self._jobs.running_task_ids(execution_id)
        for task_id in task_ids:
            if task_id in running:
                raise CoderFailure("task_already_running", f"{task_id} already has a running job")
            planned = first.get(task_id)
            if planned is None:
                raise CoderFailure("task_not_in_plan", f"{task_id} is not in the current chunk plan")
            if planned.native:
                raise CoderFailure("task_not_in_plan", f"{task_id} is a native task — use coder_prepare_native")
            # Admission (spec: "revalidate ... before run_chunk and prepare_native
            # side effects"): a stale assessment blocks BEFORE any worktree is
            # allocated or job registered -- `_assessment_for` raises
            # `complexity_plan_stale` rather than silently reusing an assignment
            # this displayed plan no longer matches.
            await self._assessment_for(ctx, planned, planned.task_file, execution_id=execution_id)

        # FEAT-559: Use execution pool's seats when available
        if pool is not None:
            seats = {s.label: s for s in pool._seats}
        else:
            seats = {s.label: s for s in self.seats}

        async def runner() -> List[TaskResult]:
            raw_results = await asyncio.gather(
                *(
                    self._run_task(
                        ctx,
                        first[tid],
                        seats[first[tid].seat_label],
                        job_id=job.job_id,
                        execution_id=execution_id,
                        pool=pool,
                    )
                    for tid in task_ids
                ),
                return_exceptions=True,
            )
            results: List[TaskResult] = []
            for tid, raw in zip(task_ids, raw_results, strict=True):
                if isinstance(raw, TaskResult):
                    results.append(raw)
                elif isinstance(raw, BaseException):
                    results.append(TaskResult(task_id=tid, outcome="failed", diagnostics=str(raw)))
            snapshot = self._jobs.snapshot(job.job_id)
            await self._journal(ctx.worktree, snapshot.model_copy(update={"tasks": results}))
            return results

        job = self._jobs.create(ctx.feature_id, list(task_ids), runner, execution_id=execution_id or "")
        self._job_worktrees[job.job_id] = ctx.worktree
        await self._journal(ctx.worktree, job)
        return job

    async def wait(self, job_id: str, timeout_seconds: int) -> CoderJob:
        try:
            job = await self._jobs.wait(job_id, min(timeout_seconds, self.roster.wait_timeout_max_s))
        except KeyError as exc:
            raise CoderFailure("job_not_found", f"unknown job {job_id}") from exc
        job_worktree = self._job_worktrees.get(job_id)
        if job_worktree is not None:
            await self._journal(job_worktree, job)
            # Flush any pending execution snapshots after job completion (TASK-3282)
            await self.status(job_id)
        return job
