"""EvalRunner + EvalReport for the Generic Agent Evaluation Harness.

FEAT-217 — Module 9.

``EvalRunner`` orchestrates the full evaluation loop:
  - Runs ``k`` attempts per task.
  - For each attempt: acquire sandbox → reset → bind agent → rollout →
    snapshot → evaluate → release.
  - Aggregates ``pass^k`` (all-k-pass fraction) and ``pass@1`` (attempt-1
    mean) plus per-tag breakdowns and latency/cost percentiles.
  - Retains raw ``Trajectory`` per attempt (spec D5).
  - Emits eval lifecycle events via ``EventBus`` when configured.
  - Persists the report via ``EvalReportSink`` when configured.
"""
from __future__ import annotations

import asyncio
import logging
import statistics
import time
import uuid
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from parrot.eval.evaluators.base import AbstractEvaluator
from parrot.eval.models import EvalDataset, EvalResult, EvalTask, Trajectory
from parrot.eval.rollout import RolloutStrategy
from parrot.eval.sandbox.base import AgentFactory, Sandbox, SandboxProvider, SandboxSpec

if TYPE_CHECKING:
    from navigator_eventbus import EventBus
    from parrot.core.events.lifecycle import EventRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# EvalRunConfig
# ---------------------------------------------------------------------------


class EvalRunConfig(BaseModel):
    """Configuration for a single evaluation run.

    Attributes:
        k: Number of attempts per task.  ``pass^k`` = all-k-pass fraction.
            Use ``k=1`` locally; ``k=4`` for CI release gates.
        max_concurrency: Maximum concurrent (task, attempt) pairs.
        sandbox_pool_size: Pool size for pooled sandboxes (e.g. Docker).
            Not used for ``InMemoryStateSandbox`` (always fresh per attempt).
        fail_fast: Stop the run on the first failed task.
        seed: Optional RNG seed for task ordering and user simulator.
            Best-effort; does not guarantee agent output determinism.
    """

    k: int = 1
    max_concurrency: int = 8
    sandbox_pool_size: int = 4
    fail_fast: bool = False
    seed: int | None = None


# ---------------------------------------------------------------------------
# EvalReport
# ---------------------------------------------------------------------------


class EvalReport(BaseModel):
    """Aggregated results of one evaluation run.

    Attributes:
        run_id: Unique identifier for this run (set by ``EvalRunner`` or
            the persistence sink).
        dataset_name: Name of the evaluated ``EvalDataset``.
        config: ``EvalRunConfig`` used for the run.
        pass_k: ``pass^k`` — fraction of tasks where ALL k attempts passed.
            This is the headline reliability metric.
        pass_at_1: ``pass@1`` — mean of (attempt-1 passed) across all tasks.
        results: All ``EvalResult`` objects (one per (task, attempt) pair).
        per_tag: Per-tag ``pass^k`` breakdown.
        p50_latency_ms: Median rollout latency across all attempts.
        p95_latency_ms: 95th-percentile rollout latency across all attempts.
        p50_setup_latency_ms: Median agent setup latency.
        p95_setup_latency_ms: 95th-percentile agent setup latency.
        p50_cost_usd: Median cost per attempt.
        p95_cost_usd: 95th-percentile cost per attempt.
        total_tasks: Total number of tasks in the dataset.
        total_attempts: Total number of (task, attempt) pairs executed.
        errors: Mapping of ``task_id`` → list of error messages.
    """

    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    dataset_name: str
    config: EvalRunConfig
    pass_k: float | None = None
    pass_at_1: float | None = None
    results: list[EvalResult] = Field(default_factory=list)
    per_tag: dict[str, float] = Field(default_factory=dict)
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    p50_setup_latency_ms: float | None = None
    p95_setup_latency_ms: float | None = None
    p50_cost_usd: float | None = None
    p95_cost_usd: float | None = None
    total_tasks: int = 0
    total_attempts: int = 0
    errors: dict[str, list[str]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# EvalRunner
# ---------------------------------------------------------------------------


class EvalRunner:
    """Orchestrates an evaluation run across all tasks in a dataset.

    Each (task, attempt) pair is executed under a ``asyncio.Semaphore``
    with bound concurrency.  ``pass^k`` and ``pass@1`` are computed from
    the aggregated results.

    Args:
        dataset: The ``EvalDataset`` to evaluate.
        agent_factory: Callable that receives a ``Sandbox`` and returns a
            bound ``AbstractBot`` instance (fresh per attempt).
        rollout: ``RolloutStrategy`` to drive the agent.
        evaluator: ``AbstractEvaluator`` to score the trajectory.
        sandbox_provider: ``SandboxProvider`` that acquires sandboxes.
        config: ``EvalRunConfig`` controlling concurrency and ``k``.
        event_bus: Optional ``EventBus`` for lifecycle events (TASK-1426).
        sink: Optional ``EvalReportSink`` for persistence (TASK-1427).
    """

    def __init__(
        self,
        *,
        dataset: EvalDataset,
        agent_factory: AgentFactory,
        rollout: RolloutStrategy,
        evaluator: AbstractEvaluator,
        sandbox_provider: SandboxProvider,
        config: EvalRunConfig,
        event_bus: "EventBus | None" = None,
        event_registry: "EventRegistry | None" = None,
        sink: Any | None = None,
    ) -> None:
        self._dataset = dataset
        self._agent_factory = agent_factory
        self._rollout = rollout
        self._evaluator = evaluator
        self._sandbox_provider = sandbox_provider
        self._config = config
        self._event_bus = event_bus
        self._event_registry = event_registry
        self._sink = sink
        self.logger = logging.getLogger(__name__)

    async def run(self) -> EvalReport:
        """Execute the full evaluation run.

        Returns:
            ``EvalReport`` with all results, aggregated metrics, and
            retained raw trajectories.
        """
        report = EvalReport(
            dataset_name=self._dataset.name,
            config=self._config,
            total_tasks=len(self._dataset.tasks),
        )

        semaphore = asyncio.Semaphore(self._config.max_concurrency)
        all_results: list[EvalResult] = []

        # Optional seed for task ordering
        tasks = list(self._dataset.tasks)
        if self._config.seed is not None:
            import random
            rng = random.Random(self._config.seed)
            rng.shuffle(tasks)

        # Create a root trace context for this run
        trace_ctx = self._make_trace_context()

        # Emit run-started lifecycle event
        await self._emit_lifecycle_event(
            "EvalRunStarted",
            trace_ctx,
            run_id=report.run_id,
            dataset_name=self._dataset.name,
            k=self._config.k,
            total_tasks=len(tasks),
        )
        # Legacy hook for EventBus
        await self._emit_event("run_started", {"dataset": self._dataset.name})

        # Gather all (task, attempt) pairs
        coroutines = []
        for task in tasks:
            for attempt in range(1, self._config.k + 1):
                coroutines.append(
                    self._run_attempt(task, attempt, semaphore, all_results)
                )

        await asyncio.gather(*coroutines, return_exceptions=True)

        # Populate report
        report.results = all_results
        report.total_attempts = len(all_results)
        self._aggregate(report, tasks)

        # Persist if sink configured
        if self._sink is not None:
            try:
                run_id = await self._sink.persist(report)
                report.run_id = run_id
            except Exception as exc:
                self.logger.warning("EvalReportSink.persist failed: %s", exc)

        # Emit run-completed lifecycle event
        await self._emit_lifecycle_event(
            "EvalRunCompleted",
            trace_ctx,
            run_id=report.run_id,
            dataset_name=self._dataset.name,
            pass_k=report.pass_k,
            pass_at_1=report.pass_at_1,
            total_tasks=report.total_tasks,
            total_attempts=report.total_attempts,
        )
        # Legacy hook for EventBus
        await self._emit_event(
            "run_completed",
            {"dataset": self._dataset.name, "pass_k": report.pass_k},
        )

        return report

    async def _run_attempt(
        self,
        task: EvalTask,
        attempt: int,
        semaphore: asyncio.Semaphore,
        results: list[EvalResult],
    ) -> None:
        """Run a single (task, attempt) pair.

        Args:
            task: The task to evaluate.
            attempt: Attempt index (1-based).
            semaphore: Concurrency gate.
            results: Shared list to append the ``EvalResult`` to.
        """
        async with semaphore:
            spec = task.sandbox_spec or SandboxSpec(kind="noop")

            sandbox: Sandbox | None = None
            try:
                # Step 1: Acquire sandbox
                sandbox = await self._sandbox_provider.acquire(spec)

                # Step 2: Reset sandbox state
                seed_state = (
                    spec.seed_state
                    if hasattr(spec, "seed_state")
                    else None
                )
                await sandbox.reset(seed_state)

                # Step 3: Create agent (bind toolkit → sandbox)
                t_setup = time.perf_counter()
                bot = await self._agent_factory(sandbox)
                setup_latency_ms = (time.perf_counter() - t_setup) * 1000.0

                # Step 4: Rollout
                rollout_trace = self._make_trace_context()
                await self._emit_lifecycle_event(
                    "EvalRolloutStarted",
                    rollout_trace,
                    run_id=None,
                    task_id=task.task_id,
                    attempt=attempt,
                )
                await self._emit_event(
                    "rollout_started",
                    {"task_id": task.task_id, "attempt": attempt},
                )
                trajectory = await self._rollout.run(bot, task, sandbox)
                trajectory = trajectory.model_copy(
                    update={
                        "attempt": attempt,
                        "setup_latency_ms": setup_latency_ms,
                    }
                )

                # Step 5: Capture final state
                trajectory = trajectory.model_copy(
                    update={"final_state": await sandbox.snapshot()}
                )

                # Step 6: Evaluate
                result = await self._evaluator.evaluate(task, trajectory, sandbox)
                result = result.model_copy(update={"attempt": attempt})

                results.append(result)
                await self._emit_lifecycle_event(
                    "EvalRolloutCompleted",
                    rollout_trace,
                    run_id=None,
                    task_id=task.task_id,
                    attempt=attempt,
                    passed=result.passed,
                    latency_ms=trajectory.latency_ms,
                    setup_latency_ms=trajectory.setup_latency_ms,
                )
                await self._emit_event(
                    "rollout_completed",
                    {"task_id": task.task_id, "attempt": attempt, "passed": result.passed},
                )

            except Exception as exc:
                self.logger.error(
                    "Attempt %d for task %s failed: %s", attempt, task.task_id, exc
                )
                error_trajectory = Trajectory(
                    task_id=task.task_id,
                    attempt=attempt,
                    error=str(exc),
                )
                from parrot.eval.models import EvalResult
                failed_result = EvalResult(
                    task_id=task.task_id,
                    attempt=attempt,
                    scores=[],
                    passed=False,
                    trajectory=error_trajectory,
                )
                results.append(failed_result)
                await self._emit_lifecycle_event(
                    "EvalRolloutFailed",
                    self._make_trace_context(),
                    run_id=None,
                    task_id=task.task_id,
                    attempt=attempt,
                    error=str(exc),
                )
                await self._emit_event(
                    "rollout_failed",
                    {"task_id": task.task_id, "attempt": attempt, "error": str(exc)},
                )

                if self._config.fail_fast:
                    raise

            finally:
                if sandbox is not None:
                    try:
                        await self._sandbox_provider.release(sandbox)
                    except Exception as exc:
                        self.logger.warning("sandbox release failed: %s", exc)

    def _aggregate(
        self, report: EvalReport, tasks: list[EvalTask]
    ) -> None:
        """Compute aggregated metrics from all results.

        Populates ``pass_k``, ``pass_at_1``, ``per_tag``, and percentiles
        on the report in-place.

        Args:
            report: The report to populate.
            tasks: The ordered task list (for per-tag breakdown).
        """
        k = self._config.k
        results_by_task: dict[str, list[EvalResult]] = {}
        for r in report.results:
            results_by_task.setdefault(r.task_id, []).append(r)

        # pass^k: fraction of tasks where ALL k attempts passed
        pass_k_count = 0
        pass_at_1_values: list[float] = []

        for task in tasks:
            task_results = sorted(
                results_by_task.get(task.task_id, []),
                key=lambda r: r.attempt,
            )
            if not task_results:
                continue

            # pass@1: attempt-1 result
            attempt_1 = next(
                (r for r in task_results if r.attempt == 1), task_results[0]
            )
            pass_at_1_values.append(1.0 if attempt_1.passed else 0.0)

            # pass^k: all attempts must pass
            if len(task_results) >= k and all(r.passed for r in task_results[:k]):
                pass_k_count += 1

        n_tasks = len(tasks)
        if n_tasks > 0:
            report.pass_k = pass_k_count / n_tasks
            report.pass_at_1 = (
                statistics.mean(pass_at_1_values) if pass_at_1_values else 0.0
            )

        # Per-tag breakdown (pass^k per tag)
        tag_results: dict[str, list[EvalResult]] = {}
        for task in tasks:
            task_results = results_by_task.get(task.task_id, [])
            for tag in task.tags:
                tag_results.setdefault(tag, []).extend(task_results)

        for tag, tag_res in tag_results.items():
            # Group by task for pass^k
            tag_by_task: dict[str, list[EvalResult]] = {}
            for r in tag_res:
                tag_by_task.setdefault(r.task_id, []).append(r)
            tag_pass_k = sum(
                1 for task_res in tag_by_task.values()
                if len(task_res) >= k and all(r.passed for r in task_res[:k])
            )
            tag_total = len(tag_by_task)
            report.per_tag[tag] = tag_pass_k / tag_total if tag_total > 0 else 0.0

        # Latency / cost percentiles
        latencies = [r.trajectory.latency_ms for r in report.results]
        setup_latencies = [r.trajectory.setup_latency_ms for r in report.results]
        costs = [r.trajectory.cost_usd for r in report.results]

        if latencies:
            report.p50_latency_ms = statistics.median(latencies)
            report.p95_latency_ms = _percentile(latencies, 95)
        if setup_latencies:
            report.p50_setup_latency_ms = statistics.median(setup_latencies)
            report.p95_setup_latency_ms = _percentile(setup_latencies, 95)
        if costs:
            report.p50_cost_usd = statistics.median(costs)
            report.p95_cost_usd = _percentile(costs, 95)

    def _make_trace_context(self) -> Any:
        """Create a new root ``TraceContext`` for a run or rollout.

        Returns:
            ``TraceContext.new_root()`` if the module is importable,
            otherwise a simple sentinel object (for environments where
            core.events is not available).
        """
        try:
            from parrot.core.events.lifecycle import TraceContext
            return TraceContext.new_root()
        except Exception:
            return None

    async def _emit_lifecycle_event(
        self,
        event_class_name: str,
        trace_ctx: Any,
        **kwargs: Any,
    ) -> None:
        """Emit a typed ``LifecycleEvent`` via the ``EventRegistry``.

        Falls back silently if the registry is not configured or if the
        event class cannot be imported.

        Args:
            event_class_name: Name of the event class in
                ``parrot.eval.events``.
            trace_ctx: ``TraceContext`` for the event.
            kwargs: Additional fields for the event dataclass.
        """
        if self._event_registry is None:
            return
        try:
            import parrot.eval.events as _ev_module
            event_cls = getattr(_ev_module, event_class_name, None)
            if event_cls is None:
                return
            from parrot.core.events.lifecycle import TraceContext
            tc = trace_ctx if isinstance(trace_ctx, TraceContext) else TraceContext.new_root()
            # Filter kwargs to only those accepted by the dataclass
            import dataclasses
            field_names = {f.name for f in dataclasses.fields(event_cls)}
            filtered = {k: v for k, v in kwargs.items() if k in field_names and v is not None}
            event = event_cls(trace_context=tc, **filtered)
            await self._event_registry.emit(event)
        except Exception as exc:
            self.logger.debug(
                "Lifecycle event %s emission failed (non-fatal): %s",
                event_class_name, exc,
            )

    async def _emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Emit a raw payload to the event bus (if configured).

        Args:
            event_type: Short event name.
            payload: Event payload dict.
        """
        if self._event_bus is None:
            return
        try:
            await self._event_bus.emit(f"lifecycle.eval.{event_type}", payload)
        except Exception as exc:
            self.logger.debug("Event bus emission failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _percentile(values: list[float], pct: float) -> float:
    """Compute the *pct*-th percentile of *values*.

    Args:
        values: List of numeric values.
        pct: Percentile (0–100).

    Returns:
        Percentile value.
    """
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = (pct / 100) * (len(sorted_vals) - 1)
    lo = int(idx)
    hi = lo + 1
    if hi >= len(sorted_vals):
        return sorted_vals[-1]
    frac = idx - lo
    return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])
