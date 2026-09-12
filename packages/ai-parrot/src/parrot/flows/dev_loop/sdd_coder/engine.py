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

    def __init__(self, *, attempt: int, seat: RosterSeat) -> None:
        self.attempt, self.seat = attempt, seat
        self.started = time.monotonic()
        self.started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.usage: Dict[str, Any] = {}
        self.error = ""

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
        return AttemptRecord(
            attempt=self.attempt,
            seat_label=self.seat.label,
            backend=self.seat.backend or "native",
            model=self.seat.model,
            started_at=self.started_at,
            ended_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            duration_s=round(time.monotonic() - self.started, 3),
            usage=self.usage,
            error=self.error,
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
        # Triple-dot (merge-base-relative), NOT double-dot (direct tree comparison): `git diff
        # A..B` is a literal two-tree diff, so if `ctx.feature_branch` has advanced since `branch`
        # was created (e.g. a sibling task's attempt merged first, under the SAME `_merge_lock`
        # but in an EARLIER `_consolidate` call), a two-dot diff would list every file the other
        # merge introduced too — this branch would then fail fidelity for files it never touched.
        # `A...B` restricts the diff to `branch`'s own changes since it forked from `feature_branch`.
        _rc, diff, _err = await _git("diff", "--name-only", f"{ctx.feature_branch}...{branch}", cwd=ctx.worktree)
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
        return await self._consolidate(ctx, manager, planned, branch=branch, path=path)

    async def cleanup(self, feature: str, worktree: str, keep_conflicted: bool = True) -> CleanupReport:
        """Remove finished sub-worktrees this engine created; never touches orphan branches it never adopted."""
        await self._resolve_feature(feature, worktree)
        removed: List[str] = []
        kept: List[str] = []
        for manager in self._managers.values():
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
        collector = AttemptTelemetryCollector(attempt=attempt, seat=seat)
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
            self.logger.warning("attempt %d of %s on %s failed: %s", attempt, task.task_id, seat.label, error)
        return collector.record(), output, error, manager, branch, path

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
                rec, out, err, manager, branch, path = await self._run_attempt(
                    ctx, task, retry, attempt=2, job_id=job_id
                )
                attempts.append(rec)
        if err:
            return TaskResult(
                task_id=task.task_id,
                outcome="failed",
                branch=branch,
                worktree_path=path,
                attempts=attempts,
                diagnostics="\n".join(a.error for a in attempts if a.error),
            )
        result = await self._consolidate(ctx, manager, task, branch=branch, path=path)
        return result.model_copy(update={"attempts": attempts, "development_output": out})

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
