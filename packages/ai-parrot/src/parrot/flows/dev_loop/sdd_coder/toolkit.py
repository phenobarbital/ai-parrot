"""`parrot mcp-local sdd-coder` — MCP surface of the sdd_coder kernel (FEAT-549, spec §3 M5)."""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ValidationError

from parrot.tools.toolkit import AbstractToolkit  # verified: parrot/tools/toolkit.py:206
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.models import (
    CoderBgStatusArgs,
    CoderCleanupArgs,
    CoderDeliveryReportArgs,
    CoderEndExecutionArgs,
    CoderError,
    CoderFeedbackReportArgs,
    CoderJob,
    CoderJobView,
    CoderMergeArgs,
    CoderPlanArgs,
    CoderPlanRequestArgs,
    CoderPrepareNativeArgs,
    CoderReadArtifactArgs,
    CoderRecordFeedbackArgs,
    CoderRecordNativeObservationArgs,
    CoderRecordReviewArgs,
    CoderResult,
    CoderRunChunkArgs,
    CoderRunValidationArgs,
    CoderStatusArgs,
    CoderTaskContextArgs,
    CoderWaitArgs,
    RosterConfig,
    SuspendModelArgs,
)
from parrot.flows.dev_loop.sdd_coder.views import project_response


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
        "coder_plan": CoderPlanRequestArgs,
        "coder_run_chunk": CoderRunChunkArgs,
        "coder_prepare_native": CoderPrepareNativeArgs,
        "coder_merge": CoderMergeArgs,
        "coder_wait": CoderWaitArgs,
        "coder_status": CoderStatusArgs,
        # FEAT-584 M3/R2: recover a paginated/durable artifact `coder_plan`,
        # `coder_wait` or `coder_status` referenced in `compact` response_mode.
        "coder_read_artifact": CoderReadArtifactArgs,
        "coder_cleanup": CoderCleanupArgs,
        "coder_record_feedback": CoderRecordFeedbackArgs,
        "coder_record_review": CoderRecordReviewArgs,
        # FEAT-584 M2/R3: worker-reported native observation (no acceptance, no release).
        "coder_record_native_observation": CoderRecordNativeObservationArgs,
        # FEAT-584 M1b/R1b: purposeful, side-effect-free reads (same shape as prepare_native).
        "coder_task_context": CoderTaskContextArgs,
        "coder_delivery_report": CoderDeliveryReportArgs,
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
        # FEAT-584 M8/R8: deterministic background status + protected validation.
        "coder_bg_status": CoderBgStatusArgs,
        "coder_run_validation": CoderRunValidationArgs,
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

    async def _run(self, operation: str, coro: Awaitable[Union[BaseModel, Dict[str, Any]]]) -> CoderResult:
        t0 = time.monotonic()
        try:
            data = await coro
            # FEAT-584 M1b: `coder_task_context`/`coder_delivery_report` resolve to a plain
            # bounded dict (`inspection.py`'s own return type), not a `CoderResult`-nested
            # BaseModel like every other tool here -- accept both rather than forcing a
            # throwaway wrapper model onto a read-only projection.
            payload = data.model_dump() if isinstance(data, BaseModel) else dict(data)
            return CoderResult(
                status="ok", operation=operation, data=payload, elapsed_ms=int((time.monotonic() - t0) * 1000)
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

    async def _project(self, payload: BaseModel, mode: Literal["full", "compact"], execution_id: str) -> Dict[str, Any]:
        """Apply `response_mode` (FEAT-584 M3/R2) via `views.project_response`.

        `full` never touches the evidence store (unmodified prior contract).
        `compact` requires both a durably bound `execution_id` (a legacy job
        journaled before FEAT-559 can carry an empty one) and a configured
        evidence store -- either gap is reported, never silently downgraded
        to `full`.
        """
        if mode == "full":
            return await project_response(
                payload, mode="full", execution_id=execution_id, store=self._engine._evidence_store  # noqa: SLF001
            )
        if not execution_id:
            raise CoderFailure(
                "execution_required", "compact response_mode requires a job bound to a known execution_id"
            )
        if self._engine._evidence_store is None:  # noqa: SLF001 -- same-package internal bookkeeping (M2 pattern)
            raise CoderFailure("evidence_persistence_failed", "no durable evidence store is configured for this engine")
        return await project_response(
            payload, mode="compact", execution_id=execution_id, store=self._engine._evidence_store  # noqa: SLF001
        )

    async def coder_plan(
        self, feature: str, worktree: str, execution_id: str, response_mode: Literal["full", "compact"] = "full"
    ) -> CoderResult:
        """Next wave of `feature` sliced into distinct-seat chunks; roster availability; orphan branches.

        Returns a CoderPlan containing:
        - assessments: ComplexityAssessment for each task in the wave
        - routing_blocks: ComplexityBlock entries for tasks that cannot be dispatched
        - Standard tasks use configured roster rotation; complex/unknown tasks are restricted to strong-model seats

        `response_mode='compact'` (FEAT-584 M3/R2) projects the same plan into
        a <=16 KiB view instead, recoverable in full via `coder_read_artifact`.
        """

        async def _p() -> Dict[str, Any]:
            plan = await self._engine.plan(feature, worktree, execution_id=execution_id)
            return await self._project(plan, response_mode, execution_id)

        return await self._run("coder_plan", _p())

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

    async def coder_record_native_observation(
        self, feature: str, worktree: str, execution_id: str, observation: Dict[str, Any]
    ) -> CoderResult:
        """Persist host observations for an issued native attempt without accepting it.

        Reports agent linkage and observed dispatch/completion for a native
        attempt `coder_prepare_native` already issued in THIS execution.
        Supply event_id, task_id, attempt_uid, agent_id, observed_at,
        kind=dispatched|finished, evidence_ref; started_at/ended_at/terminal
        are optional -- leave the span null when only the arrival of the
        result is known, never infer it from an immediate dispatch tool_result.
        Never marks the task accepted, never releases the attempt's
        reservation and never substitutes for coder_merge; a repeated
        event_id reported with different content is rejected as a conflict,
        and an attempt/execution this engine did not itself issue is
        rejected as a foreign identity.
        """
        return await self._run(
            "coder_record_native_observation",
            self._engine.record_native_observation(feature, worktree, execution_id, observation),
        )

    async def coder_task_context(self, feature: str, worktree: str, task_id: str, execution_id: str) -> CoderResult:
        """Inspect task context and blockers without modifying SDD state.

        Snapshot of the task's index entry, dependency status (unmet
        dependencies are always listed in `blockers`, never treated as
        satisfied) and declared file contract, replacing a manual
        index -> task -> dependencies -> contract read chain. Never marks a
        task ready on trust and never converts an unaccepted dependency into
        ready.
        """
        return await self._run(
            "coder_task_context", self._engine.task_context(feature, worktree, task_id, execution_id)
        )

    async def coder_delivery_report(self, feature: str, worktree: str, task_id: str, execution_id: str) -> CoderResult:
        """Inspect delivery scope and known evidence; never validates, autofixes or merges.

        Reports the execution-owned attempt branch, commit count, diff stat,
        changed/out-of-scope files (per the existing file-fidelity contract)
        and the sub-worktree's own status. Never runs tests or a merge:
        lint/test/review evidence not already durably recorded is reported
        as `"unknown"`, never fabricated as a pass.
        """
        return await self._run(
            "coder_delivery_report", self._engine.delivery_report(feature, worktree, task_id, execution_id)
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

    async def coder_wait(
        self, job_id: str, timeout_seconds: int = 120, response_mode: Literal["full", "compact"] = "full"
    ) -> CoderResult:
        """Block up to timeout_seconds (≤ 300) and return the job snapshot plus its per-seat `seats` roll-up.

        `response_mode='compact'` (FEAT-584 M3/R2) projects the same snapshot
        into a <=16 KiB view; the owning `execution_id` is resolved from the
        job itself, server-side -- never accepted as a separate argument.
        """

        async def _w() -> Dict[str, Any]:
            job = _with_seats(await self._engine.wait(job_id, timeout_seconds))
            return await self._project(job, response_mode, job.execution_id)

        return await self._run("coder_wait", _w())

    async def coder_status(self, job_id: str, response_mode: Literal["full", "compact"] = "full") -> CoderResult:
        """Non-blocking job snapshot plus its per-seat `seats` roll-up (tasks, retries, duration, tokens).

        FEAT-559: `status()` is now async (TASK-3282) -- it retries any pending
        suspension persistence idempotently before returning, so a degraded
        write becomes durable as soon as possible without a separate flush call.

        `response_mode='compact'` (FEAT-584 M3/R2) projects the same snapshot
        into a <=16 KiB view; the owning `execution_id` is resolved from the
        job itself, server-side -- never accepted as a separate argument.
        """

        async def _s() -> Dict[str, Any]:
            job = _with_seats(await self._engine.status(job_id))
            return await self._project(job, response_mode, job.execution_id)

        return await self._run("coder_status", _s())

    async def coder_read_artifact(
        self, execution_id: str, artifact_id: str, offset: int = 0, limit: int = 8192
    ) -> CoderResult:
        """Read a bounded page from evidence emitted for this execution only.

        Recovers a full `coder_plan`/`coder_wait`/`coder_status` snapshot (or
        one of their paginated `pending`/`blocked` overflow pages) that a
        `compact` `response_mode` referenced by `evidence_ref`/
        `required_pages_remaining`. Confinement to one execution's own
        `artifacts/` directory happens inside `ExecutionEvidenceStore`
        (evidence.py) -- never here, and never from a caller-supplied path.

        Possible errors:
            - evidence_persistence_failed: no durable evidence store is configured for this engine
            - artifact_not_found: no evidence exists at `artifact_id` for `execution_id`
            - artifact_scope_mismatch: `artifact_id` does not resolve to a confined artifact
        """

        async def _r() -> Dict[str, Any]:
            store = self._engine._evidence_store  # noqa: SLF001 -- same-package internal bookkeeping (M2 pattern)
            if store is None:
                raise CoderFailure(
                    "evidence_persistence_failed", "no durable evidence store is configured for this engine"
                )
            try:
                return await store.read_artifact(execution_id, artifact_id, offset, limit)
            except FileNotFoundError as exc:
                raise CoderFailure("artifact_not_found", str(exc)) from exc
            except ValueError as exc:
                raise CoderFailure("artifact_scope_mismatch", str(exc)) from exc

        return await self._run("coder_read_artifact", _r())

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

    async def coder_bg_status(
        self, execution_id: str, handle: str, since_revision: Optional[int] = None, tail_bytes: int = 2048
    ) -> CoderResult:
        """Read authoritative known background state without waiting for termination.

        `handle` is opaque and only ever comes from a prior `coder_run_chunk`
        (`bg_handle`), `coder_prepare_native` (`bg_handle`) or
        `coder_run_validation` (`handle`) response -- never a PID, a log path
        or anything invented by the model. Never spawns a shell, `ps`, `tail`
        or `kill -0`, and never waits for the underlying process/job to
        finish: `state=finished` reports a real receipt, not test success or
        task acceptance -- check `outcome`/`exit_code` separately. `unknown`
        after this engine loses the launch's ownership (e.g. a restart) is
        never resurrected into `finished` from an absent PID or an empty log.
        """
        return await self._run(
            "coder_bg_status",
            self._engine.bg_status(execution_id, handle, since_revision=since_revision, tail_bytes=tail_bytes),
        )

    async def coder_run_validation(
        self,
        feature: str,
        worktree: str,
        execution_id: str,
        task_ids: List[str],
        tier: Literal["merge", "feature"],
        timeout_seconds: int,
        request_id: str,
    ) -> CoderResult:
        """Launch only a declared SDD validation and return a bg_handle without waiting for it.

        Admits exactly the existing test selector's own tier-scoped plan
        (`tier='merge'` for changed scope, `'feature'` for the full applicable
        set) inside the protected sandbox -- never an arbitrary argv/script,
        and never runs tests through this or any other read-only tool
        directly. `task_ids` must already be declared in the feature's
        per-spec index. `timeout_seconds` (1-7200) is mandatory and explicit
        -- no expected duration is claimed without history. `request_id` is
        stable idempotency: the SAME request/payload replays the SAME
        handle; a DIFFERENT payload under a reused `request_id` is rejected,
        never a second silent process. Every admitted validation must settle
        before `coder_end_execution`/`coder_cleanup` on this worktree.
        """
        return await self._run(
            "coder_run_validation",
            self._engine.run_validation(feature, worktree, execution_id, task_ids, tier, timeout_seconds, request_id),
        )
