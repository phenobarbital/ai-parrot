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
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from parrot import conf
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
from parrot.flows.dev_loop.sdd_coder.jobs import JobTable
from parrot.flows.dev_loop.sdd_coder.models import (
    AttemptRecord,
    CleanupReport,
    CoderJob,
    CoderPlan,
    NativePrep,
    OrphanBranch,
    PlannedTask,
    RosterConfig,
    RosterSeat,
    SeatProbeResult,
    TaskResult,
)
from parrot.flows.dev_loop.sdd_coder.roster import ChunkAssigner, RosterProbe, available_seats
from parrot.flows.dev_loop.models.telemetry import AttemptTelemetry
from parrot.flows.dev_loop.sdd_coder.telemetry import (
    CoderTelemetrySink,
    OutcomeRow,
    build_attempt_row,
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
        self, *, attempt: int, seat: RosterSeat, attempt_uid: Optional[str] = None, job_id: Optional[str] = None
    ) -> None:
        self.attempt, self.seat = attempt, seat
        self.attempt_uid = attempt_uid or ""
        self.job_id = job_id or ""
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
        """Probe once; cache seats/assigner. Idempotent. Raises roster_empty when nothing is available."""
        if self._opened:
            return
        self.probe_results = await self._probe.probe(self.roster)
        self.seats = available_seats(self.roster, self.probe_results)
        if not self.seats:
            raise CoderFailure(
                "roster_empty", "no roster seat is available", probe=[r.model_dump() for r in self.probe_results]
            )
        self._assigner, self._opened = ChunkAssigner(self.seats), True

    async def _resolve_feature(self, feature: str, worktree: str) -> _FeatureCtx:
        """Match sdd/tasks/index/*.json headers in the sdd-worker.md §1 order.

        Order (first match wins): feature_id exact -> feature exact ->
        feature_id numeric/any suffix -> feature substring -> spec filename.
        """
        wt = os.path.realpath(worktree)
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

    async def plan(self, feature: str, worktree: str) -> CoderPlan:
        await self.open()
        ctx = await self._resolve_feature(feature, worktree)
        sched = await self._scheduler_for(ctx)
        wave = sorted(sched.next_wave(), key=lambda t: t.id)  # S3
        assert self._assigner is not None
        chunks = self._assigner.assign(wave, {t.id: t.file for t in wave})
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
            roster=self.probe_results,
            orphan_branches=orphans,
        )
        # Code-review fix (FEAT-549, CRITICAL): cache the computed plan, keyed by feature_id.
        # `ChunkAssigner.assign()` mutates rotation state (`self._start`) on EVERY call — with a
        # roster that mixes mcp and native seats (the shipped `examples/sdd-coder-mcp.yaml`
        # reference roster does), a task's mcp/native classification can flip between the
        # display `coder_plan()` call the orchestrator loop makes first and a SECOND, internal
        # `plan()` re-computation `run_chunk`/`prepare_native` used to do as their first step —
        # causing a correctly-classified task to spuriously fail with `task_not_in_plan`
        # (or the reverse) purely because rotation advanced again in between. `run_chunk`/
        # `prepare_native` now consult this cache via `_cached_plan()` instead of recomputing.
        self._plan_cache[ctx.feature_id] = result
        return result

    async def _cached_plan(self, feature: str, worktree: str, ctx: _FeatureCtx) -> CoderPlan:
        """Reuse the most recently computed plan for this feature instead of recomputing.

        `run_chunk`/`prepare_native` must see EXACTLY the chunk `coder_plan` most recently
        returned to the caller — recomputing would advance `ChunkAssigner`'s rotation state
        again and could reclassify a task from mcp to native or vice versa (see `plan()`).
        Falls back to a fresh `plan()` (which populates the cache) when nothing is cached yet
        — e.g. a `coder_prepare_native`/`coder_run_chunk` call with no preceding `coder_plan`.
        """
        cached = self._plan_cache.get(ctx.feature_id)
        if cached is not None:
            return cached
        return await self.plan(feature, worktree)

    def _manager_for(self, ctx: _FeatureCtx, task_id: str, attempt: int) -> SubWorktreeManager:
        key = f"{task_id}.a{attempt}"
        if key not in self._managers:
            self._managers[key] = SubWorktreeManager(
                base_worktree=ctx.worktree, feature_branch=ctx.feature_branch, worktree_base_path=self._base_path
            )
        return self._managers[key]

    async def prepare_native(self, feature: str, worktree: str, task_id: str) -> NativePrep:
        """Sub-worktree for a `native` planned task (attempt 1); branch <feature_branch>--<TASK-NNN>-a1."""
        ctx = await self._resolve_feature(feature, worktree)
        plan = await self._cached_plan(feature, worktree, ctx)
        planned = next((t for c in plan.chunks for t in c.tasks if t.task_id == task_id), None)
        if planned is None or not planned.native:
            raise CoderFailure("task_not_in_plan", f"{task_id} is not a native task of the current chunk plan")
        path = await self._manager_for(ctx, task_id, 1).create(f"{task_id}.a1")
        self._native_inflight.add(f"{task_id}.a1")
        return NativePrep(
            task_id=task_id,
            task_file=planned.task_file,
            branch=f"{ctx.feature_branch}--{task_id}-a1",
            worktree_path=path,
            seat_label=planned.seat_label,
        )

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
        task_md_path = Path(ctx.worktree, task.task_file).resolve()
        worktree_root = Path(ctx.worktree).resolve()
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
            )
        return TaskResult(task_id=task.task_id, outcome="merged", branch=branch, worktree_path=path)

    async def merge(self, feature: str, worktree: str, task_id: str) -> TaskResult:
        """Consolidate the task's LATEST attempt branch (native tasks; re-merge after Sonnet fixed a conflict)."""
        ctx = await self._resolve_feature(feature, worktree)
        attempts = sorted(
            (int(key.rsplit(".a", 1)[1]) for key in self._managers if key.startswith(f"{task_id}.a")),
            reverse=True,
        )
        if not attempts:
            raise CoderFailure("branch_not_found", f"no known attempt worktree for {task_id}")
        attempt = attempts[0]
        manager = self._manager_for(ctx, task_id, attempt)
        branch = f"{ctx.feature_branch}--{task_id}-a{attempt}"
        path = str(Path(self._base_path) / f"{ctx.feature_branch}--pool" / f"{task_id}-a{attempt}")

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
        self._native_inflight.discard(f"{task_id}.a{attempt}")

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

    async def cleanup(self, feature: str, worktree: str, keep_conflicted: bool = True) -> CleanupReport:
        """Remove finished sub-worktrees this engine created; never touches orphan branches it never adopted."""
        await self._resolve_feature(feature, worktree)
        removed: List[str] = []
        kept: List[str] = []
        for key, manager in self._managers.items():
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
            suffix = branch[len(prefix) :]  # e.g. "TASK-0001-a1"
            task_id, sep, _attempt = suffix.rpartition("-a")
            if not sep or not task_id:
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

    def status(self, job_id: str) -> CoderJob:
        try:
            return self._jobs.get(job_id)
        except KeyError as exc:
            raise CoderFailure("job_not_found", f"unknown job {job_id}") from exc

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
        self, ctx: _FeatureCtx, task: PlannedTask, seat: RosterSeat, *, attempt: int, job_id: str
    ) -> Tuple[AttemptRecord, Optional[DevelopmentOutput], str, SubWorktreeManager, str, str]:
        """ONE dispatch in ONE fresh sub-worktree. Returns (record, output|None, error, manager, branch, path)."""
        assert seat.backend is not None, "_run_attempt is only called for mcp seats; native tasks use prepare_native"
        manager = self._manager_for(ctx, task.task_id, attempt)
        branch = f"{ctx.feature_branch}--{task.task_id}-a{attempt}"
        # Computed the same way `SubWorktreeManager.create()` derives it internally
        # (`_branch_suffix` replaces "." with "-"), so `path`/`branch` are always
        # defined even if `manager.create()` itself raises below — see the
        # code-review fix note on the `try:` block having moved to cover
        # worktree-creation and dispatcher-construction too.
        path = str(Path(self._base_path) / f"{ctx.feature_branch}--pool" / f"{task.task_id}-a{attempt}")
        # A unique id per attempt: `attempt` restarts at 1 on every _run_task
        # invocation (line 592) and both attempts of a task share `job_id`, so
        # neither can key the telemetry join (spec §10 R3).
        attempt_uid = uuid.uuid4().hex
        collector = AttemptTelemetryCollector(attempt=attempt, seat=seat, attempt_uid=attempt_uid, job_id=job_id)
        # Read `task.task_file` and count `parse_task_files(...)` NOW,
        # while the worktree still exists — set declared_files /
        # declared_files_known on the collector. An unreadable file means
        # known=False, never 0.
        try:
            task_md_path = Path(ctx.worktree, task.task_file).resolve()
            worktree_root = Path(ctx.worktree).resolve()
            if task_md_path == worktree_root or str(task_md_path).startswith(str(worktree_root) + os.sep):
                task_md = await asyncio.to_thread(task_md_path.read_text, "utf-8")
                collector.declared_files = len(parse_task_files(task_md))
                collector.declared_files_known = True
        except Exception:
            # File unreadable or parsing failed - set known=False
            collector.declared_files_known = False
        output: Optional[DevelopmentOutput] = None
        error = ""
        try:
            # Code-review fix (FEAT-549, IMPORTANT): sub-worktree creation and dispatcher
            # construction used to happen BEFORE this try block — a `git worktree add`
            # failure or a `build_dispatcher` error would propagate raw out of
            # `_run_attempt`/`_run_task`, landing in `run_chunk`'s outer
            # `asyncio.gather(..., return_exceptions=True)` as a bare "failed" TaskResult
            # with an EMPTY `attempts` list, bypassing the attempt-2-on-a-different-seat
            # retry ladder entirely. Moved inside so every failure mode becomes a proper
            # attempt error the ladder can act on.
            await manager.create(f"{task.task_id}.a{attempt}")
            dispatcher, profile = self._dispatcher_builder(
                DevAgentSpec(agent=seat.backend, model=seat.model),
                redis_url=self._redis_url,
                max_concurrent=1,
                stream_ttl_seconds=self._stream_ttl,
            )
            profile = profile.model_copy(update={"subagent": "sdd-coder"})  # S7 — every profile defaults to sdd-worker
            output = await dispatcher.dispatch(
                brief=TaskScopedBrief(
                    research=self._research_for(ctx, worktree_path=path),
                    task_id=task.task_id,
                    task_file=task.task_file,
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

    async def _run_task(self, ctx: _FeatureCtx, task: PlannedTask, seat: RosterSeat, *, job_id: str) -> TaskResult:
        """Attempt 1 on the assigned seat; on failure attempt 2 on a different seat in a NEW sub-worktree;
        a second failure yields `outcome="failed"` with both attempts' errors (spec G6, AC-6, AC-20)."""
        attempts: List[AttemptRecord] = []
        rec, out, err, manager, branch, path = await self._run_attempt(ctx, task, seat, attempt=1, job_id=job_id)
        attempts.append(rec)

        if err:
            assert self._assigner is not None
            retry = self._assigner.retry_seat(seat.label, {seat.label})
            if retry is not None:
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
                    ctx, task, retry, attempt=2, job_id=job_id
                )
                attempts.append(rec)

        if err:
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

    async def run_chunk(self, feature: str, worktree: str, task_ids: List[str]) -> CoderJob:
        """Validate, register, RETURN. Everything slow happens inside the job (S4, AC-21)."""
        ctx = await self._resolve_feature(feature, worktree)
        plan = await self._cached_plan(feature, worktree, ctx)
        first = {t.task_id: t for t in (plan.chunks[0].tasks if plan.chunks else [])}

        running = self._jobs.running_task_ids()
        for task_id in task_ids:
            if task_id in running:
                raise CoderFailure("task_already_running", f"{task_id} already has a running job")
            planned = first.get(task_id)
            if planned is None:
                raise CoderFailure("task_not_in_plan", f"{task_id} is not in the current chunk plan")
            if planned.native:
                raise CoderFailure("task_not_in_plan", f"{task_id} is a native task — use coder_prepare_native")

        seats = {s.label: s for s in self.seats}

        async def runner() -> List[TaskResult]:
            raw_results = await asyncio.gather(
                *(self._run_task(ctx, first[tid], seats[first[tid].seat_label], job_id=job.job_id) for tid in task_ids),
                return_exceptions=True,
            )
            results: List[TaskResult] = []
            for tid, raw in zip(task_ids, raw_results):
                if isinstance(raw, TaskResult):
                    results.append(raw)
                elif isinstance(raw, BaseException):
                    results.append(TaskResult(task_id=tid, outcome="failed", diagnostics=str(raw)))
            snapshot = self._jobs.snapshot(job.job_id)
            await self._journal(ctx.worktree, snapshot.model_copy(update={"tasks": results}))
            return results

        job = self._jobs.create(ctx.feature_id, list(task_ids), runner)
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
        return job
