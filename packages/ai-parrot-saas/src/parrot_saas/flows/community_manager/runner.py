"""Starting a Community Manager run, and recording what it did.

This is where a stored review becomes an execution: the ingest path hands over
a tenant, a review and a run id, and this module builds the flow for that
tenant, runs it, and writes down the outcome.

Four things here are load-bearing, and each exists because the obvious version
is wrong.

**The tenant is passed, never inferred.** ``AgentsFlow`` launches each node
with ``asyncio.create_task`` and a run happens on a background worker with no
request in sight, so a context variable would read ``None`` — and a ``None``
tenant is a data leak, not an error. The tenant is captured by the node
factories at build time and seeded into shared state.

**``_save_result`` needs ``tenant=`` spelled out.** ``AgentsFlow`` inherits
``PersistenceMixin`` but never calls it — only ``AgentCrew`` does — so flow
persistence has to be an explicit ``on_complete`` hook. And the mixin does
``data.setdefault("tenant", "global")``, so forgetting the keyword does not
fail: it silently files every tenant's runs under ``global``. There is a test
that asserts the keyword is passed.

**The runtime is leased for the duration.** Runtimes are evicted on an LRU and
a TTL, and the flow's nodes hold their agents by reference, so an eviction
mid-run would surface as a confusing client error. ``TenantRuntime.acquire()``
holds the lease and the per-tenant concurrency semaphore at once.

**A failed flow is still a recorded run.** The run row is written when the run
starts and updated when it ends, so a worker that dies leaves a ``running`` row
with no ``finished_at`` rather than no evidence at all.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from navconfig.logging import logging

from ... import conf
from ...runs.models import RunStatus
from ...tenancy.context import TenantContext
from .flow import build_community_manager_flow
from .models import ReviewIntake

logger = logging.getLogger("parrot_saas.flows.cm.runner")

#: Flow name recorded on every run this module starts.
FLOW_NAME = "community_manager"


class RunNotResumable(RuntimeError):
    """A run that finished cannot be continued.

    Distinct from "no checkpoint": that one means the deployment is not
    checkpointing, this one means the work is already done and re-entering
    the flow could publish a second reply.
    """


def review_to_intake(review: Any) -> ReviewIntake:
    """Convert a stored :class:`~parrot_saas.reviews.models.Review`.

    The two models carry the same facts under one different name — the stored
    row calls the body ``body`` in SQL and ``text`` in Python — so this is a
    field-by-field copy rather than a ``model_dump`` round trip, which would
    also drag ``raw`` (the platform's whole original payload) into the flow's
    shared state and from there into every checkpoint.

    Args:
        review: The stored review.

    Returns:
        The flow's own view of it.
    """
    if isinstance(review, ReviewIntake):
        return review
    return ReviewIntake(
        review_id=getattr(review, "review_id", "") or "",
        tenant_id=getattr(review, "tenant_id", "") or "",
        source=getattr(review, "source", "") or "",
        external_id=getattr(review, "external_id", "") or "",
        location_ref=getattr(review, "location_ref", "") or "",
        rating=getattr(review, "rating", 0) or 0,
        text=getattr(review, "text", "") or "",
        language=getattr(review, "language", "en") or "en",
        author_name=getattr(review, "author_name", "") or "",
        guest_id=getattr(review, "guest_id", "") or "",
    )


class CommunityManagerRunner:
    """Runs the Community Manager flow for whichever tenant a review belongs to.

    Instances are process-wide, not per tenant: everything tenant-specific is
    resolved per run, from the runtime cache. That is what lets one runner
    serve every tenant without holding any of their credentials itself.

    Args:
        runtimes: The tenant runtime cache, source of agents and rulesets.
        runs: Repository the run record is written to.
        reviews: Review repository, handed to the nodes that persist.
        guests: Guest repository, for contact capture.
        coupons: Coupon repository, for the eligibility counters.
        issuer: Coupon issuer.
        delivery: Coupon delivery service.
        review_sources: Mapping of source name to adapter, so the flow
            publishes back through the platform the review arrived from.
        checkpoint: Whether to checkpoint each node. Safe on this graph
            because every predicate is a CEL string — one Python callable
            would make ``to_definition()`` raise and the flow would refuse to
            start.
        checkpoint_store: Ephemeral checkpoint store (name or instance).
        durable: Whether to also write checkpoints through to a durable store.
        durable_store: The durable store (name or instance).
        result_storage: ``ResultStorage`` name or instance for the execution
            audit rows. ``AgentsFlow`` never sets one — only ``AgentCrew``
            does — so this has to be applied to the flow explicitly.
        executions_collection: Table those audit rows go to.
        node_timeout: Per-node wall-clock budget.
    """

    def __init__(
        self,
        *,
        runtimes: Any,
        runs: Optional[Any] = None,
        reviews: Optional[Any] = None,
        guests: Optional[Any] = None,
        coupons: Optional[Any] = None,
        issuer: Optional[Any] = None,
        delivery: Optional[Any] = None,
        review_sources: Optional[dict] = None,
        checkpoint: bool = False,
        checkpoint_store: Optional[Any] = None,
        durable: bool = False,
        durable_store: Optional[Any] = None,
        result_storage: Optional[Any] = None,
        executions_collection: str = conf.SAAS_EXECUTIONS_COLLECTION,
        node_timeout: float = conf.SAAS_CM_NODE_TIMEOUT,
    ) -> None:
        self._runtimes = runtimes
        self._runs = runs
        self._reviews = reviews
        self._guests = guests
        self._coupons = coupons
        self._issuer = issuer
        self._delivery = delivery
        self._sources = review_sources or {}
        self._checkpoint = checkpoint
        self._checkpoint_store = checkpoint_store
        self._durable = durable
        self._durable_store = durable_store
        self._result_storage = result_storage
        self._collection = executions_collection
        self._node_timeout = node_timeout

    async def __call__(
        self, tenant: TenantContext, review: Any, run_id: str
    ) -> dict:
        """Run the flow for one review. The ``RunLauncher`` entry point.

        Args:
            tenant: The tenant the review belongs to.
            review: The stored review.
            run_id: Identifier minted at ingest.

        Returns:
            A small summary of the run, which is what the job record keeps.
        """
        return await self.run(tenant, review, run_id)

    async def run(
        self, tenant: TenantContext, review: Any, run_id: str
    ) -> dict:
        """Execute the flow and record the outcome.

        Never raises. A run is started from a background job, so an exception
        here would be logged by the job manager and lost; recording the
        failure on the run row is what makes it findable.

        Args:
            tenant: The tenant the review belongs to.
            review: The stored review.
            run_id: Identifier minted at ingest.

        Returns:
            A summary of what happened.
        """
        intake = review_to_intake(review)
        await self._start_record(tenant, run_id, intake.review_id)

        started = time.monotonic()
        try:
            runtime = await self._runtimes.get(tenant)
            async with runtime.acquire():
                result, ctx = await self._execute(tenant, runtime, intake, run_id)
        except Exception as exc:  # noqa: BLE001 - recorded, never propagated
            logger.exception(
                "run %s for tenant %s failed before completing",
                run_id,
                tenant.tenant_id,
            )
            await self._finish_record(
                tenant,
                run_id,
                status=RunStatus.FAILED,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return {"run_id": run_id, "status": RunStatus.FAILED.value}

        return await self._record_outcome(
            tenant, run_id, result, ctx, int((time.monotonic() - started) * 1000)
        )

    async def resume_run(self, tenant: TenantContext, run_id: str) -> dict:
        """Continue a checkpointed run from where it stopped.

        The graph is rebuilt by :meth:`_build_flow` — the same builder that
        produced it originally — and handed to ``AgentsFlow.resume()`` as its
        ``flow_factory``. That is what keeps the live dependencies and the
        explicit-edge scheduler; see that method for why rebuilding from the
        checkpoint's definition instead would produce a flow that runs and
        routes wrongly.

        Args:
            tenant: The tenant that owns the run.
            run_id: The run to continue. Doubles as the checkpoint key.

        Returns:
            A summary of the resumed run.

        Raises:
            CheckpointNotFoundError: If there is no checkpoint for this run —
                which is the normal answer when the deployment runs without
                ``checkpoint_runs``, not a corruption.
            FlowLockedError: If another worker holds the resume lease.
            RunNotResumable: If the run already finished successfully.
        """
        from parrot.bots.flows.flow.flow import AgentsFlow

        record = await self._runs.get(tenant.tenant_id, run_id) if self._runs else None
        if record is not None and record.status == RunStatus.COMPLETED.value:
            # Resuming a finished run would re-enter the flow at its terminal
            # node and could publish a second reply or issue a second coupon.
            raise RunNotResumable(
                f"run {run_id} already completed ({record.outcome or 'no outcome'})"
            )

        started = time.monotonic()
        runtime = await self._runtimes.get(tenant)
        async with runtime.acquire():
            source_name = await self._source_for(tenant, record)
            flow = await AgentsFlow.resume(
                run_id,
                agent_registry=runtime.agent_registry,
                store=self._checkpoint_store,
                durable_store=self._durable_store if self._durable else None,
                flow_factory=lambda _definition: self._build_flow(
                    tenant, runtime, source_name, run_id
                ),
            )
            await self._start_record(
                tenant, run_id, getattr(record, "review_id", "") or ""
            )

            # Held onto now because ``run_flow`` consumes it — it takes the
            # seeded context, clears the attribute, and clears ``_active_ctx``
            # again in its ``finally``. This is the only reference that
            # survives the call, and the outcome is read off it.
            ctx = flow._resume_seed_context  # noqa: SLF001

            # The checkpoint carries the *previous* attempt's failure summary
            # in shared state. Left there, ``_record_outcome`` would read it
            # and file a successful resume as failed — the run would publish
            # the reply, close cleanly, and still be reported as broken. A new
            # attempt starts with no failure; if this one fails too, its own
            # failure handler writes a fresh one.
            if ctx is not None:
                ctx.shared_data.pop("failure", None)

            # Called with no ctx on purpose: ``run_flow`` uses the
            # checkpoint-seeded context only when it is given none. Passing a
            # fresh one would discard every completed node and re-run the whole
            # flow — publishing the reply a second time.
            result = await flow.run_flow(
                on_complete=(self._persist_execution(tenant, flow, run_id),)
            )

        logger.info("resumed run %s for tenant %s", run_id, tenant.tenant_id)
        return await self._record_outcome(
            tenant, run_id, result, ctx, int((time.monotonic() - started) * 1000)
        )

    async def _source_for(self, tenant: TenantContext, record: Any) -> str:
        """Name the review adapter a resumed run should publish through.

        The run row carries the review id rather than the source, so this
        reads it back. A run whose review has vanished resumes with no
        adapter, which means the publish node records the attempt without
        publishing — the same degradation as an unconfigured source, rather
        than a crash halfway through a resume.
        """
        review_id = getattr(record, "review_id", "") or ""
        if self._reviews is None or not review_id:
            return ""
        try:
            review = await self._reviews.get(tenant.tenant_id, review_id)
        except Exception as exc:  # noqa: BLE001 - degrade, do not abort
            logger.warning("could not read review %s: %s", review_id, exc)
            return ""
        return getattr(review, "source", "") or ""

    def _build_flow(
        self,
        tenant: TenantContext,
        runtime: Any,
        source_name: str,
        run_id: str,
    ) -> Any:
        """Assemble the flow for one tenant.

        Extracted so that :meth:`resume_run` can hand *this* to
        ``AgentsFlow.resume(flow_factory=...)``. Rebuilding a resumed run any
        other way loses two things at once: the live dependencies (the generic
        reconstruction path drops them silently rather than failing) and the
        explicit-edge scheduler, which ``run_flow()`` selects with
        ``self._definition is None`` — so a definition-rebuilt flow falls back
        to AND-join with no predicates, and this graph's ``close`` has six
        predecessors.

        Args:
            tenant: The tenant this instance serves.
            runtime: Its live runtime, source of agents and the ruleset.
            source_name: Which review adapter to publish through.
            run_id: Flow id, and the checkpoint key.

        Returns:
            The wired flow.
        """
        flow = build_community_manager_flow(
            tenant=tenant,
            run_id=run_id,
            checkpoint=self._checkpoint,
            checkpoint_store=self._checkpoint_store,
            durable=self._durable,
            durable_store=self._durable_store,
            agent_registry=runtime.agent_registry,
            triage_agent=runtime.agents.get("triage"),
            reply_agent=runtime.agents.get("reply_draft"),
            review_source=self._sources.get(source_name),
            review_repository=self._reviews,
            guest_repository=self._guests,
            coupon_repository=self._coupons,
            ruleset=runtime.ruleset,
            issuer=self._issuer,
            delivery=self._delivery,
            node_timeout=self._node_timeout,
        )
        # AgentsFlow's constructor forwards **kwargs to object.__init__, so a
        # result_storage= argument would be a TypeError. The mixin reads both
        # of these off the instance, which is why they are set rather than
        # passed.
        #
        # Turning persistence off when nothing is configured is not laziness:
        # ``get_result_storage(None)`` resolves to the DocumentDB backend, so
        # a deployment with no Mongo would attempt — and log — a failed
        # connection on every single run, for a row it was never going to
        # write. No storage configured means no audit row, said once.
        flow._persist_results = self._result_storage is not None  # noqa: SLF001
        if self._result_storage is not None:
            flow._result_storage_arg = self._result_storage  # noqa: SLF001
        return flow

    async def _execute(
        self,
        tenant: TenantContext,
        runtime: Any,
        intake: ReviewIntake,
        run_id: str,
    ) -> tuple[Any, Any]:
        """Build the flow for this tenant and run it."""
        from parrot.bots.flows.core import FlowContext

        flow = self._build_flow(tenant, runtime, intake.source, run_id)

        ctx = FlowContext(initial_task=f"community-manager:{intake.review_id}")
        ctx.shared_data.update(
            {
                "review": intake,
                "tenant_id": tenant.tenant_id,
                "timezone": tenant.timezone,
                "locale": tenant.locale,
                "run_id": run_id,
                "actor": "system",
            }
        )
        result = await flow.run_flow(
            ctx, on_complete=(self._persist_execution(tenant, flow, run_id),)
        )
        return result, ctx

    def _persist_execution(self, tenant: TenantContext, flow: Any, run_id: str):
        """Return the ``on_complete`` hook that writes the audit row.

        ``AgentsFlow`` inherits ``PersistenceMixin`` and never calls it, so
        without this hook a flow run leaves no execution row at all.

        Args:
            tenant: The tenant, whose slug must reach ``_save_result``.
            flow: The flow whose mixin does the writing.
            run_id: Doubles as the execution id, so the audit row, the job
                record and the checkpoint key all agree.

        Returns:
            An async ``(ctx, result) -> None`` hook.
        """

        async def _persist(ctx: Any, result: Any) -> None:
            await flow._save_result(  # noqa: SLF001 - the mixin's own API
                result,
                "run_flow",
                collection=self._collection,
                # Not optional. The mixin defaults this to "global", so
                # omitting it files one tenant's run under a shared bucket
                # with no error anywhere — see the module docstring.
                tenant=tenant.tenant_id,
                user_id=ctx.shared_data.get("actor", "system"),
                session_id=ctx.shared_data.get("review_id")
                or getattr(ctx.shared_data.get("review"), "review_id", ""),
                execution_id=run_id,
                prompt=ctx.initial_task,
            )

        return _persist

    async def _record_outcome(
        self,
        tenant: TenantContext,
        run_id: str,
        result: Any,
        ctx: Any,
        duration_ms: int,
    ) -> dict:
        """Write the terminal run row from the flow's own results."""
        shared = getattr(ctx, "shared_data", {}) or {}
        summary = shared.get("summary")
        failure = shared.get("failure")

        failed = failure is not None
        payload = {
            "status": RunStatus.FAILED if failed else RunStatus.COMPLETED,
            "outcome": getattr(summary, "outcome", "") or ("failed" if failed else ""),
            "replied": bool(getattr(summary, "replied", False)),
            "coupon_code": getattr(summary, "coupon_code", "") or "",
            "failed_node": getattr(failure, "failed_node", "") or "",
            "error": getattr(failure, "error", "") or "",
            "usage": dict(shared.get("usage") or {}),
            "nodes": _node_summary(result),
            "duration_ms": duration_ms,
        }
        await self._finish_record(tenant, run_id, **payload)

        logger.info(
            "run %s for tenant %s finished: %s (%d ms)",
            run_id,
            tenant.tenant_id,
            payload["outcome"] or payload["status"],
            duration_ms,
        )
        return {
            "run_id": run_id,
            "status": getattr(payload["status"], "value", payload["status"]),
            "outcome": payload["outcome"],
            "review_id": getattr(summary, "review_id", "")
            or getattr(failure, "review_id", ""),
            "coupon_code": payload["coupon_code"],
        }

    async def _start_record(
        self, tenant: TenantContext, run_id: str, review_id: str
    ) -> None:
        """Mark the run as running, tolerating a repository failure.

        The run itself is worth attempting even if its bookkeeping row cannot
        be written: an unanswered guest is a worse outcome than a missing row.
        """
        if self._runs is None:
            return
        try:
            await self._runs.start(
                tenant.tenant_id, run_id, review_id=review_id, flow=FLOW_NAME
            )
        except Exception as exc:  # noqa: BLE001 - bookkeeping, not the work
            logger.warning("could not open the run record %s: %s", run_id, exc)

    async def _finish_record(
        self, tenant: TenantContext, run_id: str, **fields: Any
    ) -> None:
        """Close the run record, tolerating a repository failure."""
        if self._runs is None:
            return
        fields.setdefault("status", RunStatus.COMPLETED)
        try:
            await self._runs.finish(tenant.tenant_id, run_id, **fields)
        except Exception as exc:  # noqa: BLE001 - the run already happened
            logger.warning("could not close the run record %s: %s", run_id, exc)


def _node_summary(result: Any) -> list[dict]:
    """Reduce a flow result's node records to what a run view needs.

    The full ``NodeExecutionInfo`` carries each node's whole response object,
    which for this flow means review text and draft replies. Those belong in
    the tables that already hold them, not duplicated into every run row.

    Args:
        result: The flow result.

    Returns:
        One small dict per node, in execution order.
    """
    summary: list[dict] = []
    for node in getattr(result, "nodes", []) or []:
        status = getattr(node, "status", "")
        summary.append(
            {
                "node_id": getattr(node, "node_id", ""),
                "status": getattr(status, "value", status) or "",
                "duration_ms": int((getattr(node, "execution_time", 0) or 0) * 1000),
            }
        )
    return summary


__all__ = (
    "FLOW_NAME",
    "CommunityManagerRunner",
    "RunNotResumable",
    "review_to_intake",
)
