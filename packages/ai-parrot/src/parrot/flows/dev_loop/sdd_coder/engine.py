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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from parrot import conf
from parrot.flows.dev_loop.agent_builder import build_dispatcher  # verified: agent_builder.py:135
from parrot.flows.dev_loop.task_scheduler import TaskScheduler  # verified: task_scheduler.py:53
from parrot.flows.dev_loop.worktree_manager import (  # verified: worktree_manager.py:75, :41
    SubWorktreeManager,
    SubWorktreeMergeError,
)
from parrot.flows.dev_loop.sdd_coder.fidelity import check_fidelity, parse_task_files
from parrot.flows.dev_loop.sdd_coder.jobs import JobTable
from parrot.flows.dev_loop.sdd_coder.models import (
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
        self._jobs = JobTable()
        self._merge_lock = asyncio.Lock()
        self._managers: Dict[str, SubWorktreeManager] = {}  # key: f"{task_id}.a{attempt}"
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
            raise CoderFailure(
                "feature_not_found", f"no per-spec index matches {feature!r}", candidates=candidates
            )

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
        return CoderPlan(
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

    def _manager_for(self, ctx: _FeatureCtx, task_id: str, attempt: int) -> SubWorktreeManager:
        key = f"{task_id}.a{attempt}"
        if key not in self._managers:
            self._managers[key] = SubWorktreeManager(
                base_worktree=ctx.worktree, feature_branch=ctx.feature_branch, worktree_base_path=self._base_path
            )
        return self._managers[key]

    async def prepare_native(self, feature: str, worktree: str, task_id: str) -> NativePrep:
        """Sub-worktree for a `native` planned task (attempt 1); branch <feature_branch>--<TASK-NNN>-a1."""
        plan = await self.plan(feature, worktree)
        ctx = await self._resolve_feature(feature, worktree)
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
        _rc, diff, _err = await _git("diff", "--name-only", f"{ctx.feature_branch}..{branch}", cwd=ctx.worktree)
        task_md = await asyncio.to_thread(
            Path(os.path.join(ctx.worktree, task.task_file)).read_text, "utf-8"
        )
        report = check_fidelity(parse_task_files(task_md), [p for p in diff.splitlines() if p.strip()])
        if not report.ok:
            return TaskResult(
                task_id=task.task_id,
                outcome="fidelity_violation",
                branch=branch,
                worktree_path=path,
                unexpected_files=report.unexpected + report.sdd_touched,
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
            suffix = branch[len(prefix):]  # e.g. "TASK-0001-a1"
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
                "diff", "--name-only", f"{ctx.feature_branch}..{branch}", cwd=ctx.worktree
            )
            files = [f for f in files_out.splitlines() if f.strip()]
            orphans.append(OrphanBranch(task_id=task_id, branch=branch, commits=commits, files=files))
        return orphans

    def _journal(self, worktree: str, job: CoderJob) -> None:
        """Write-only snapshot: <worktree>/.sdd-coder/jobs/<job_id>.json (dir is git-ignored, TASK-3122 adds the rule)."""
        d = Path(worktree) / ".sdd-coder" / "jobs"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{job.job_id}.json").write_text(job.model_dump_json(indent=2), encoding="utf-8")

    def status(self, job_id: str) -> CoderJob:
        try:
            return self._jobs.get(job_id)
        except KeyError as exc:
            raise CoderFailure("job_not_found", f"unknown job {job_id}") from exc

    # ---- TASK-3121 fills these (signatures fixed by spec §3 M4) ----
    async def run_chunk(self, feature: str, worktree: str, task_ids: List[str]) -> CoderJob:
        raise NotImplementedError("TASK-3121")

    async def wait(self, job_id: str, timeout_seconds: int) -> CoderJob:
        raise NotImplementedError("TASK-3121")

    async def _run_attempt(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("TASK-3121")

    def _research_for(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("TASK-3121")

    def _labels_for(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("TASK-3121")


class AttemptTelemetryCollector:
    """Duck-typed session-host stand-in that captures per-attempt usage/timing.

    Stubbed here; TASK-3121 implements `apply`/`record` against the
    `dispatch.completed` action shape (dispatchers/_shared.py:92-117).
    """

    def apply(self, action: Any, origin: Any = None) -> None:
        raise NotImplementedError("TASK-3121")

    def record(self) -> Any:
        raise NotImplementedError("TASK-3121")
