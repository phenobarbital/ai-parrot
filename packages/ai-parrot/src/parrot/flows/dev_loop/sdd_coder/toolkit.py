"""`parrot mcp-local sdd-coder` — MCP surface of the sdd_coder kernel (FEAT-549, spec §3 M5)."""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Dict, List, Optional, Union

from pydantic import BaseModel, ValidationError

from parrot.tools.toolkit import AbstractToolkit  # verified: parrot/tools/toolkit.py:206
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.models import (
    CoderCleanupArgs,
    CoderEndExecutionArgs,
    CoderError,
    CoderFeedbackReportArgs,
    CoderJob,
    CoderJobView,
    CoderMergeArgs,
    CoderPlanArgs,
    CoderPrepareNativeArgs,
    CoderRecordFeedbackArgs,
    CoderRecordReviewArgs,
    CoderResult,
    CoderRunChunkArgs,
    CoderStatusArgs,
    CoderWaitArgs,
    RosterConfig,
    SuspendModelArgs,
)


def _with_seats(job: CoderJob) -> CoderJobView:
    """Attach the per-seat roll-up to a job snapshot (read-time only, never journaled)."""
    from parrot.flows.dev_loop.sdd_coder.summary import summarize_job_seats

    return CoderJobView(**job.model_dump(), seats=summarize_job_seats([job]))


def _is_missing_execution_id(exc: ValidationError) -> bool:
    """True when `execution_id` is the (or one of the) field(s) missing entirely.

    Only a `type == "missing"` error at exactly `("execution_id",)` counts -- an
    invalid UUID, an extra field or any other malformed input is still the
    generic `invalid_arguments` path.
    """
    return any(err["type"] == "missing" and err["loc"] == ("execution_id",) for err in exc.errors())


class SddCoderToolkit(AbstractToolkit):
    """Orchestration and correction feedback for sdd-worker; every result is a CoderResult."""

    llm_dependent_tools: frozenset = frozenset()
    auto_open: bool = True  # probe on FIRST tool call (toolkit.py:169-172); no server startup hook exists (S12)
    arg_models: Dict[str, type[BaseModel]] = {
        "coder_plan": CoderPlanArgs,
        "coder_run_chunk": CoderRunChunkArgs,
        "coder_prepare_native": CoderPrepareNativeArgs,
        "coder_merge": CoderMergeArgs,
        "coder_wait": CoderWaitArgs,
        "coder_status": CoderStatusArgs,
        "coder_cleanup": CoderCleanupArgs,
        "coder_record_feedback": CoderRecordFeedbackArgs,
        "coder_record_review": CoderRecordReviewArgs,
        # FEAT-559: split from CoderPlanArgs -- the repository-wide feedback report
        # is read-only and never starts or requires an execution (CoderPlanArgs
        # itself now REQUIRES execution_id, so reusing it here would be a bug).
        "coder_feedback_report": CoderFeedbackReportArgs,
        # FEAT-559 M4: the three new execution lifecycle/suspension tools.
        # `coder_begin_execution` reuses CoderPlanArgs: identical
        # (feature, worktree, execution_id) shape, no new class needed.
        "coder_begin_execution": CoderPlanArgs,
        "coder_end_execution": CoderEndExecutionArgs,
        "coder_suspend_model": SuspendModelArgs,
    }

    def __init__(
        self,
        *,
        roster: Union[List[Dict[str, Any]], RosterConfig],
        redis_url: Optional[str] = None,
        worktree_base_path: Optional[str] = None,
        telemetry_dir: Optional[str] = None,
        lint: Optional[Dict[str, Any]] = None,
        feedback: Optional[Dict[str, Any]] = None,
        complexity: Optional[Dict[str, Any]] = None,
        suspension_policy: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.logger = logging.getLogger(__name__)
        cfg = (
            roster
            if isinstance(roster, RosterConfig)
            else RosterConfig(
                seats=roster,
                lint=lint or {},
                feedback=feedback or {},
                suspension_policy=suspension_policy or {},
            )  # type: ignore[arg-type]  # yaml kwargs arrive as list[dict]; pydantic coerces at runtime
        )
        # Forward complexity configuration to the engine
        if complexity is not None:
            # Validate and override the policy with explicit complexity config
            # Use model_copy to avoid mutating the caller's input
            cfg = cfg.model_copy(update={"complexity": cfg.complexity.model_validate(complexity)})
        self._engine = SddCoderEngine(
            roster=cfg,
            redis_url=redis_url,
            worktree_base_path=worktree_base_path,
            telemetry_dir=telemetry_dir,
        )

    async def _pre_execute(self, tool_name: str, /, **kwargs: Any) -> None:
        """Validate against arg_models (extra='forbid'); adapter.py:79 does not validate (S6).

        FEAT-559: a validation failure caused SOLELY by a missing `execution_id`
        maps to the dedicated `execution_required` error code (spec: "before any
        model work, not generic internal_error or silent fallback") -- every
        other validation failure (bad UUID, extra field, wrong type, ...) still
        maps to the existing generic `invalid_arguments`.
        """
        model = self.arg_models.get(tool_name)
        if model is None:
            return
        kwargs.pop("_permission_context", None)
        try:
            model(**kwargs)
        except ValidationError as exc:
            if _is_missing_execution_id(exc):
                raise CoderFailure("execution_required", "execution_id is required for this tool") from exc
            raise CoderFailure("invalid_arguments", "invalid tool arguments", errors=exc.errors()) from exc

    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs: Any) -> Any:
        """adapter.py's 'direct result' branch does `str(result)` (a Python repr, NOT JSON) for
        anything that isn't a `ToolResult`; serialise `CoderResult` to a JSON string here so an
        MCP client receives parseable JSON in the text content block (verified: adapter.py:79-95
        has no Pydantic-aware serialisation)."""
        if isinstance(result, BaseModel):
            return result.model_dump_json()
        return result

    async def _open(self) -> None:
        try:
            await self._engine.open()
        except CoderFailure as exc:  # roster_empty: let coder_plan report it, do not break the server
            self.logger.warning("sdd-coder probe: %s", exc.message)

    async def _close(self) -> None:
        """Best-effort: cancel any still-running jobs and journal their last-known snapshot.

        Nothing in `parrot/mcp/` calls this today (S12 — no server shutdown
        hook exists); it only runs if a future host wires it up (spec §8 Q4).
        """
        jobs = getattr(self._engine, "_jobs", None)
        if jobs is None:
            return
        for job_id, task in list(getattr(jobs, "_tasks", {}).items()):
            if not task.done():
                task.cancel()
            worktree = self._engine._job_worktrees.get(job_id)  # noqa: SLF001 — same-package internal bookkeeping
            if worktree:
                try:
                    await self._engine._journal(worktree, jobs.get(job_id))  # noqa: SLF001
                except KeyError:
                    continue

    async def _run(self, operation: str, coro: Awaitable[BaseModel]) -> CoderResult:
        t0 = time.monotonic()
        try:
            data = await coro
            return CoderResult(
                status="ok", operation=operation, data=data.model_dump(), elapsed_ms=int((time.monotonic() - t0) * 1000)
            )
        except CoderFailure as exc:
            return CoderResult(
                status="error",
                operation=operation,
                error=CoderError(code=exc.code, message=exc.message, details=exc.details),
                elapsed_ms=int((time.monotonic() - t0) * 1000),
            )
        except Exception as exc:  # noqa: BLE001 — every unexpected crash still returns a CoderResult
            self.logger.exception("sdd-coder %s crashed", operation)
            return CoderResult(
                status="error",
                operation=operation,
                error=CoderError(code="internal_error", message=str(exc)),
                elapsed_ms=int((time.monotonic() - t0) * 1000),
            )

    async def coder_plan(self, feature: str, worktree: str, execution_id: str) -> CoderResult:
        """Next wave of `feature` sliced into distinct-seat chunks; roster availability; orphan branches.

        Returns a CoderPlan containing:
        - assessments: ComplexityAssessment for each task in the wave
        - routing_blocks: ComplexityBlock entries for tasks that cannot be dispatched
        - Standard tasks use configured roster rotation; complex/unknown tasks are restricted to strong-model seats
        """
        return await self._run("coder_plan", self._engine.plan(feature, worktree, execution_id=execution_id))

    async def coder_run_chunk(self, feature: str, worktree: str, task_ids: List[str], execution_id: str) -> CoderResult:
        """Dispatch the MCP-seat tasks of the current chunk in parallel; returns a job id immediately."""
        return await self._run(
            "coder_run_chunk", self._engine.run_chunk(feature, worktree, task_ids, execution_id=execution_id)
        )

    async def coder_prepare_native(self, feature: str, worktree: str, task_id: str, execution_id: str) -> CoderResult:
        """Create the sub-worktree for a native (haiku) task; the orchestrator launches the agent itself."""
        return await self._run(
            "coder_prepare_native", self._engine.prepare_native(feature, worktree, task_id, execution_id=execution_id)
        )

    async def coder_merge(self, feature: str, worktree: str, task_id: str, execution_id: str) -> CoderResult:
        """Clean-status check, fidelity check and merge of the task's latest attempt branch."""
        return await self._run("coder_merge", self._engine.merge(feature, worktree, task_id, execution_id=execution_id))

    async def coder_record_feedback(
        self, feature: str, worktree: str, feedback: Dict[str, Any], execution_id: str
    ) -> CoderResult:
        """Record a confirmed defect corrected by the worker in one coder delivery.

        Supply source (review_fix_commit or code_review), lesson_scope=model,
        task_id, attempt_uid, backend, actual model, stable pattern slug,
        repository-relative files, defect, evidence, correction and verification.
        Use the attempt's resolved_model when present, otherwise model; native
        identity comes from coder_prepare_native. Call after each verified fix,
        before dispatching the next chunk. Never file infrastructure failures or
        speculative findings or engine lint fixes. Repo-wide lessons belong in
        conventions or the Codebase Contract. Records survive issue closure and cleanup.
        """
        from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedback

        return await self._run(
            "coder_record_feedback",
            self._engine.record_feedback(feature, worktree, CoderFeedback(**feedback), execution_id=execution_id),
        )

    async def coder_record_review(
        self, feature: str, worktree: str, review: Dict[str, Any], execution_id: str
    ) -> CoderResult:
        """Record EVERY completed coder handoff review, including zero corrections.

        Supply task_id, attempt_uid, backend, actual model, fix_commits (full
        SHAs of all fix(...) TASK-N review fixes commits, [] when none), and
        review_evidence. Exclude engine lint commits. The engine attaches actual
        feedback exposure so before/after rates include clean deliveries too.
        """
        from parrot.knowledge.wiki.ledger.coder_reviews import CoderReview

        return await self._run(
            "coder_record_review",
            self._engine.record_review(feature, worktree, CoderReview(**review), execution_id=execution_id),
        )

    async def coder_feedback_report(self, feature: str, worktree: str) -> CoderResult:
        """Read repository-wide review correction commits per task/model, grouped by feedback exposure.

        Read-only and repository-wide: never starts, resumes or requires an execution.
        """
        return await self._run("coder_feedback_report", self._engine.feedback_report(feature, worktree))

    async def coder_begin_execution(self, feature: str, worktree: str, execution_id: str) -> CoderResult:
        """Begin (or idempotently resume) this worker's execution pool.

        Reads durable suspension history for the canonical feature worktree
        BEFORE probing any seat, then binds `execution_id` to that worktree for
        the rest of this call chain (`coder_plan`/`coder_run_chunk`/
        `coder_prepare_native`/`coder_merge`/`coder_cleanup`/
        `coder_record_feedback`/`coder_record_review`/`coder_suspend_model` all
        require the SAME id). Only one active execution may own a canonical
        worktree at a time -- a second id gets `execution_in_progress`.
        """
        return await self._run("coder_begin_execution", self._engine.begin_execution(feature, worktree, execution_id))

    async def coder_end_execution(self, execution_id: str) -> CoderResult:
        """End an execution, releasing worktree ownership once all admitted work has settled.

        Refuses (`execution_busy`) while known attempts/native reservations/jobs
        are still in flight -- an error report alone never unlocks this; only
        explicit settlement (a real `coder_merge`) does.
        """
        return await self._run("coder_end_execution", self._engine.end_execution(execution_id))

    async def coder_suspend_model(
        self, execution_id: str, attempt_uid: str, reason: str, evidence_ref: str
    ) -> CoderResult:
        """Report a worker-observed failure for ONE OF ITS OWN admitted attempts.

        Valid only for a native attempt (any reason) or a confirmed critical
        review defect on any attempt (`reason='review_critical'`) -- every
        other MCP-seat failure is classified and suspended internally by the
        engine itself, never reported through this tool. The target model is
        resolved server-side from `attempt_uid`; the caller cannot name or
        invent a model directly.
        """
        return await self._run(
            "coder_suspend_model", self._engine.suspend_model(execution_id, attempt_uid, reason, evidence_ref)
        )

    async def coder_wait(self, job_id: str, timeout_seconds: int = 120) -> CoderResult:
        """Block up to timeout_seconds (≤ 300) and return the job snapshot plus its per-seat `seats` roll-up."""

        async def _w() -> BaseModel:
            return _with_seats(await self._engine.wait(job_id, timeout_seconds))

        return await self._run("coder_wait", _w())

    async def coder_status(self, job_id: str) -> CoderResult:
        """Non-blocking job snapshot plus its per-seat `seats` roll-up (tasks, retries, duration, tokens).

        FEAT-559: `status()` is now async (TASK-3282) -- it retries any pending
        suspension persistence idempotently before returning, so a degraded
        write becomes durable as soon as possible without a separate flush call.
        """

        async def _s() -> BaseModel:
            return _with_seats(await self._engine.status(job_id))

        return await self._run("coder_status", _s())

    async def coder_cleanup(
        self, feature: str, worktree: str, execution_id: str, keep_conflicted: bool = True
    ) -> CoderResult:
        """Remove merged sub-worktrees THIS execution created; keep conflicted ones unless told otherwise.

        Never enumerates or deletes another execution's managers, native
        reservations or worktrees, even on the same engine instance.
        """
        return await self._run(
            "coder_cleanup", self._engine.cleanup(feature, worktree, keep_conflicted, execution_id=execution_id)
        )
