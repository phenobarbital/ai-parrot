"""Dev-agent pool: round-robin dispatch, retry, and aggregation (FEAT-323).

``DevAgentPool`` materializes a :class:`DevAgentPoolConfig` into concrete
dispatcher instances (via the Module 3 builder), assigns each wave's tasks
to workers round-robin, dispatches them in parallel with a synthetic
``node_id="development.wN"`` (so each sub-agent gets its own Redis stream —
see ``FlowStreamMultiplexer``), retries a failed task exactly once on a
*different* worker, and aggregates the per-worker outputs into a single
:class:`DevelopmentOutput`.

See ``sdd/specs/dev-loop-multiple-dev-agents.spec.md`` §2 "New Public
Interfaces" and §3 "Module 4" for the authoritative design.

NOTE: unlike ``agent_builder.py``, this module imports directly from the
``.dispatcher``/``.models`` submodules rather than the ``parrot.flows.dev_loop``
package. ``agent_pool`` is imported transitively by
``nodes/development.py`` (reached via the package's own
``__init__.py -> flow.py -> factories.py -> nodes/development.py`` chain),
so importing the *package* here — while it is still mid-initialization —
would raise ``ImportError: cannot import name ... from partially
initialized module``. Submodule-direct imports avoid that cycle.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel

from parrot.flows.dev_loop.dispatcher import (
    DevLoopCodeDispatcher,
    DispatchExecutionError,
    DispatchOutputValidationError,
)
from parrot.flows.dev_loop.models import (
    DevAgentPoolConfig,
    DevAgentSpec,
    DevelopmentOutput,
    ResearchOutput,
    TaskScopedBrief,
    WorkerSummary,
)
from parrot.flows.dev_loop.task_scheduler import TaskRef

logger = logging.getLogger(__name__)

# ``(task_id, worker_id, output_or_None, error_message_or_None)``.
_DispatchAttempt = Tuple[str, str, Optional[DevelopmentOutput], Optional[str]]


@dataclass
class PoolWorker:
    """A single materialized dev-agent slot in the pool.

    Attributes:
        worker_id: Synthetic node id, e.g. ``"development.w1"``. Stable for
            the lifetime of the pool.
        spec: The :class:`DevAgentSpec` this worker was built from.
        dispatcher: The concrete dispatcher instance for ``spec.agent``.
        profile: The dispatch profile instance for ``spec.agent``.
    """

    worker_id: str
    spec: DevAgentSpec
    dispatcher: DevLoopCodeDispatcher
    profile: BaseModel


@dataclass
class WaveResult:
    """Outcome of dispatching one wave of tasks across the pool.

    Attributes:
        completed: ``task_id -> DevelopmentOutput`` for every task that
            eventually succeeded (first try or retry).
        failed: TASK-NNN ids that failed twice (original + retry).
        worker_summaries: One :class:`WorkerSummary` per worker that
            participated in this wave.
    """

    completed: Dict[str, DevelopmentOutput] = field(default_factory=dict)
    failed: List[str] = field(default_factory=list)
    worker_summaries: List[WorkerSummary] = field(default_factory=list)


class DevAgentPool:
    """Materializes a dev-agent pool and dispatches waves of tasks across it."""

    def __init__(
        self, *, config: DevAgentPoolConfig, workers: List[PoolWorker], pool_max: int
    ) -> None:
        """Initialise the pool from an already-materialized worker list.

        Prefer :meth:`build` to construct a pool from a
        :class:`DevAgentPoolConfig` and a dispatcher-builder callable.

        Args:
            config: The pool configuration this pool was built from.
            workers: Materialized workers, in stable ``worker_id`` order.
            pool_max: The effective cap applied when this pool was built.
        """
        self.config = config
        self.workers = workers
        self.pool_max = pool_max
        self.logger = logging.getLogger(__name__)

    @classmethod
    def build(
        cls,
        config: DevAgentPoolConfig,
        dispatcher_builder: Callable[[DevAgentSpec], Tuple[DevLoopCodeDispatcher, BaseModel]],
        pool_max: int,
    ) -> "DevAgentPool":
        """Expand ``config.agents`` by ``count``, cap at ``pool_max``, and build workers.

        Args:
            config: The pool configuration (backends + replica counts).
            dispatcher_builder: A ``(DevAgentSpec) -> (dispatcher, profile)``
                callable — typically ``functools.partial(build_dispatcher,
                redis_url=..., max_concurrent=..., stream_ttl_seconds=...)``.
            pool_max: Hard cap on the total number of workers (across all
                specs combined). Excess replicas are dropped with a warning.

        Returns:
            A new :class:`DevAgentPool` with workers numbered
            ``development.w1..wN`` in expansion order (specs in declared
            order, replicas of the same spec consecutive).
        """
        expanded: List[DevAgentSpec] = []
        for spec in config.agents:
            expanded.extend([spec] * spec.count)

        total = len(expanded)
        if total > pool_max:
            logger.warning(
                "DevAgentPoolConfig requests %d total worker(s); capping to "
                "pool_max=%d (dropping %d).",
                total,
                pool_max,
                total - pool_max,
            )
            expanded = expanded[:pool_max]

        workers: List[PoolWorker] = []
        for i, spec in enumerate(expanded, start=1):
            worker_id = f"development.w{i}"
            dispatcher, profile = dispatcher_builder(spec)
            workers.append(
                PoolWorker(
                    worker_id=worker_id, spec=spec, dispatcher=dispatcher, profile=profile
                )
            )

        return cls(config=config, workers=workers, pool_max=pool_max)

    def _next_worker(self, failed_worker: PoolWorker) -> PoolWorker:
        """Return the next worker after ``failed_worker`` (wraps around).

        With a single-worker pool, retries land on the same worker (there
        is nowhere else to send them).

        Args:
            failed_worker: The worker whose dispatch just failed.

        Returns:
            The worker to retry the task on.
        """
        if len(self.workers) <= 1:
            return self.workers[0]
        idx = next(i for i, w in enumerate(self.workers) if w is failed_worker)
        return self.workers[(idx + 1) % len(self.workers)]

    async def _dispatch_one(
        self,
        task: TaskRef,
        worker: PoolWorker,
        *,
        research: ResearchOutput,
        run_id: str,
        cwd_for: Callable[[str], str],
    ) -> _DispatchAttempt:
        """Dispatch a single task to a single worker, never raising.

        Args:
            task: The task to dispatch.
            worker: The worker to dispatch it to.
            research: Shared research output wrapped into the task-scoped brief.
            run_id: The flow run id (forwarded to ``dispatch()``).
            cwd_for: ``worker_id -> cwd`` resolver (shared worktree in
                'shared' mode, sub-worktree path in 'isolated' mode).

        Returns:
            A ``(task_id, worker_id, output, error)`` tuple. Exactly one of
            ``output``/``error`` is non-``None``.

        Note:
            A dispatch that commits partial work and *then* fails leaves that
            commit behind; the single retry re-runs the whole task (on another
            worker in 'shared' mode, against the same worktree). Sub-agents are
            expected to make each task's commit atomic (all-or-nothing) so a
            retry starts clean — the pool does not attempt to unwind partial
            commits itself.
        """
        brief = TaskScopedBrief(research=research, task_id=task.id)
        try:
            output = await worker.dispatcher.dispatch(
                brief=brief,
                profile=worker.profile,
                output_model=DevelopmentOutput,
                run_id=run_id,
                node_id=worker.worker_id,
                cwd=cwd_for(worker.worker_id),
            )
            return task.id, worker.worker_id, output, None
        except (DispatchExecutionError, DispatchOutputValidationError) as exc:
            self.logger.warning(
                "Task %s failed on %s (%s): %s",
                task.id,
                worker.worker_id,
                type(exc).__name__,
                exc,
            )
            return task.id, worker.worker_id, None, str(exc)
        except Exception as exc:  # noqa: BLE001 - a single dispatch must never kill the wave
            self.logger.warning(
                "Task %s failed on %s (unexpected %s): %s",
                task.id,
                worker.worker_id,
                type(exc).__name__,
                exc,
            )
            return task.id, worker.worker_id, None, str(exc)

    async def run_wave(
        self,
        tasks: List[TaskRef],
        *,
        research: ResearchOutput,
        run_id: str,
        cwd_for: Callable[[str], str],
    ) -> WaveResult:
        """Dispatch one wave of tasks across the pool, round-robin, with retry.

        Args:
            tasks: The dispatchable tasks for this wave (see
                ``TaskScheduler.next_wave()``).
            research: Shared research output (wrapped per-task in a
                :class:`TaskScopedBrief`).
            run_id: The flow run id.
            cwd_for: ``worker_id -> cwd`` resolver.

        Returns:
            A :class:`WaveResult` with completed/failed tasks and one
            :class:`WorkerSummary` per worker that took part in this wave.

        Raises:
            ValueError: If the pool has no workers.
        """
        if not self.workers:
            raise ValueError("DevAgentPool has no workers to dispatch to")
        if not tasks:
            return WaveResult()

        assignments: Dict[str, PoolWorker] = {
            t.id: self.workers[i % len(self.workers)] for i, t in enumerate(tasks)
        }

        first_attempts = await asyncio.gather(
            *(
                self._dispatch_one(t, assignments[t.id], research=research, run_id=run_id, cwd_for=cwd_for)
                for t in tasks
            )
        )

        completed: Dict[str, DevelopmentOutput] = {}
        per_worker_completed: Dict[str, List[str]] = {w.worker_id: [] for w in self.workers}
        per_worker_failed: Dict[str, List[str]] = {w.worker_id: [] for w in self.workers}
        retry_targets: List[Tuple[TaskRef, PoolWorker]] = []
        tasks_by_id = {t.id: t for t in tasks}

        for task_id, worker_id, output, _error in first_attempts:
            if output is not None:
                completed[task_id] = output
                per_worker_completed[worker_id].append(task_id)
            else:
                retry_targets.append((tasks_by_id[task_id], assignments[task_id]))

        failed: List[str] = []
        if retry_targets:
            retry_workers = [self._next_worker(fw) for _task, fw in retry_targets]
            retry_attempts = await asyncio.gather(
                *(
                    self._dispatch_one(
                        task,
                        retry_worker,
                        research=research,
                        run_id=run_id,
                        cwd_for=cwd_for,
                    )
                    for (task, _fw), retry_worker in zip(retry_targets, retry_workers)
                )
            )
            for (_task, failed_worker), retry_worker, (task_id, worker_id, output, _error) in zip(
                retry_targets, retry_workers, retry_attempts
            ):
                # Attribute the first-attempt failure to the original worker
                # — unless the retry landed on that same worker (single-worker
                # pool), where the retry outcome below already records it and
                # a second entry would just be a duplicate.
                if failed_worker is not retry_worker:
                    per_worker_failed[failed_worker.worker_id].append(task_id)
                if output is not None:
                    completed[task_id] = output
                    per_worker_completed[worker_id].append(task_id)
                else:
                    failed.append(task_id)
                    per_worker_failed[worker_id].append(task_id)

        worker_summaries = [
            WorkerSummary(
                worker_id=w.worker_id,
                agent=w.spec.agent,
                model=getattr(w.profile, "model", "") or getattr(w.profile, "llm", ""),
                tasks_completed=per_worker_completed[w.worker_id],
                tasks_failed=per_worker_failed[w.worker_id],
                summary=(
                    f"completed={len(per_worker_completed[w.worker_id])} "
                    f"failed={len(per_worker_failed[w.worker_id])}"
                ),
            )
            for w in self.workers
        ]

        return WaveResult(completed=completed, failed=failed, worker_summaries=worker_summaries)


def aggregate_outputs(
    results: List[WaveResult], incomplete: List[str]
) -> DevelopmentOutput:
    """Merge every wave's outputs into a single :class:`DevelopmentOutput`.

    Args:
        results: One :class:`WaveResult` per wave dispatched by the pool.
        incomplete: TASK-NNN ids that never completed (failed twice, or
            were transitively skipped by the scheduler).

    Returns:
        The aggregated output: ``files_changed`` deduplicated preserving
        first-seen order, ``commit_shas`` in arrival order, ``summary``
        built from per-worker summaries (one merged :class:`WorkerSummary`
        per ``worker_id`` across all waves), plus ``incomplete_tasks``.
    """
    files_changed: List[str] = []
    seen_files: Set[str] = set()
    commit_shas: List[str] = []
    merged: Dict[str, WorkerSummary] = {}

    for wave in results:
        for output in wave.completed.values():
            for changed_file in output.files_changed:
                if changed_file not in seen_files:
                    seen_files.add(changed_file)
                    files_changed.append(changed_file)
            commit_shas.extend(output.commit_shas)

        for ws in wave.worker_summaries:
            if ws.worker_id not in merged:
                merged[ws.worker_id] = WorkerSummary(
                    worker_id=ws.worker_id,
                    agent=ws.agent,
                    model=ws.model,
                    tasks_completed=list(ws.tasks_completed),
                    tasks_failed=list(ws.tasks_failed),
                    summary=ws.summary,
                )
            else:
                existing = merged[ws.worker_id]
                existing.tasks_completed.extend(ws.tasks_completed)
                existing.tasks_failed.extend(ws.tasks_failed)
                if ws.summary:
                    existing.summary = (
                        f"{existing.summary}; {ws.summary}" if existing.summary else ws.summary
                    )

    worker_summaries = list(merged.values())
    summary = "\n".join(
        f"[{ws.worker_id}/{ws.agent}] {ws.summary}" for ws in worker_summaries if ws.summary
    )

    return DevelopmentOutput(
        files_changed=files_changed,
        commit_shas=commit_shas,
        summary=summary,
        incomplete_tasks=list(incomplete),
        worker_summaries=worker_summaries,
    )
