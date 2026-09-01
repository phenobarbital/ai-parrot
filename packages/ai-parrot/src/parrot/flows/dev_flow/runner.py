"""DevFlowRunner — hosts the single dev-flow topology (FEAT-412).

``DevLoopRunner`` switches topology per brief kind (the bug graph in
:meth:`run`, feature-mode via ``_run_feature``, the revision graph via
``run_revision``). The dev-flow has exactly ONE topology, so this subclass
pins it and overrides only :meth:`run` — brief typing, context seeding and
graph selection. Everything else is inherited untouched:

* the concurrency cap and its park-aware manual acquire/release,
* the per-run ``SessionHost`` registry, envelope sink and actions stream,
* gates, park/resume (``resume_run``), ``resolve_gate``, ``cancel_run``,
* the gate-expiry / retention sweep,
* ``_close_host``'s bundle + report persistence.

The base class's ``_feature_flow`` cache and ``_run_feature`` are left
untouched and unused: a dev-flow ``FeatureBrief`` runs the **dev-flow**
graph (whose ``dev_intake`` routes it straight to ``planner``), not the
FEAT-378 feature-mode graph.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Any, Literal

from parrot.bots.flows import AgentsFlow
from parrot.bots.flows.core.context import FlowContext

# Same module the base runner imports FlowResult from (runner.py:36).
from parrot.bots.flows.core.result import FlowResult
from parrot.flows.dev_flow.flow import build_dev_flow
from parrot.flows.dev_flow.model_plan import DevFlowModelPlan
from parrot.flows.dev_flow.models import DevRequestBrief
from parrot.flows.dev_loop.models import FeatureBrief
from parrot.flows.dev_loop.runner import DevLoopRunner
from parrot.flows.dev_loop.session_state import RunAdded, RunCreated


class DevFlowRunner(DevLoopRunner):
    """Hosts ``dev-flow`` runs behind the shared global concurrency cap.

    Construct exactly like :class:`DevLoopRunner`, passing the flow built by
    :func:`parrot.flows.dev_flow.flow.build_dev_flow`::

        runner = DevFlowRunner(
            build_dev_flow(dispatcher=..., redis_url=...),
            dispatcher=..., redis_url=...,
        )
    """

    #: Own checkpoint namespace — ``dev-flow/<run_id>``, disjoint from the
    #: base class's ``dev-loop/<run_id>`` (FEAT-480 spec §2 step 1).
    CHECKPOINT_WORKFLOW = "dev-flow"

    def _recovery_supported(self, brief: Any) -> bool:
        """Both dev-flow brief kinds run the recovery path.

        The base class excludes ``FeatureBrief`` because dev-loop routes it
        to ``_run_feature()``, which never reaches the coordinator. dev-flow
        has ONE topology: :meth:`run` serves a ``FeatureBrief`` itself and
        checkpoints it exactly like a ``DevRequestBrief``.

        Args:
            brief: The brief a caller intends to run.

        Returns:
            ``True`` for a dev-flow brief kind, ``False`` otherwise (a
            bug-mode ``WorkBrief`` this topology cannot serve at all).
        """
        return isinstance(brief, (DevRequestBrief, FeatureBrief))

    # Deliberate Liskov narrowing: the base accepts ``WorkBrief |
    # FeatureBrief``, but the dev-flow graph cannot serve a bug-mode
    # ``WorkBrief`` (there is no bug_intake/research node in it). Narrowing the
    # annotation documents the real contract, and ``_summary_for`` raises
    # TypeError for anything else BEFORE a host is registered or a slot
    # acquired — so the substitution fails loudly rather than half-running.
    async def run(  # type: ignore[override]
        self,
        brief: DevRequestBrief | FeatureBrief,
        *,
        run_id: str | None = None,
        initial_task: str = "",
        extra_shared: dict[str, Any] | None = None,
        model_plan: DevFlowModelPlan | None = None,
    ) -> FlowResult:
        """Execute one dev-flow run for *brief*, respecting the run cap.

        Accepts the ``DevFlowBrief`` union. Both kinds run the SAME graph —
        which brief was supplied only decides where ``dev_intake``'s
        conditional edges send it:

        * :class:`DevRequestBrief` (``enhancement``/``new_feature``) →
          ``ideation`` first (the SDD document does not exist yet).
        * :class:`FeatureBrief` (``feature``) → straight to ``planner``.
          Ideation is skipped **by routing**, never by this runner.

        Args:
            brief: The validated :class:`DevRequestBrief` or
                :class:`FeatureBrief` to process.
            run_id: Optional externally-minted run identifier; one is
                generated (``run-<hex8>``) when omitted.
            initial_task: Optional human-readable task line stored as the
                context's ``initial_task``. Defaults to a per-kind summary.
            extra_shared: Extra entries merged into ``shared_data`` — this is
                how the server passes per-run knobs such as
                ``require_plan_approval`` and ``skip_qa``.
            model_plan: FEAT-490 — optional per-run ideation model / review
                pair selection. Reaches ``build_dev_flow`` for THIS run only
                on the fresh (cache-miss) checkpoint path, via the TASK-2685
                overrides seam — never stored on ``self``, so concurrent
                runs never leak seats into each other. On a resumed run
                (``mode == "resumed"``) this is not applied; the run keeps
                the seats it was created with (spec §8 Q1). ``None`` (the
                default) leaves every existing caller byte-identical.

        Returns:
            The aggregated :class:`FlowResult` for the run.

        Raises:
            TypeError: *brief* is neither a ``DevRequestBrief`` nor a
                ``FeatureBrief`` (e.g. a bug-mode ``WorkBrief``, which this
                topology cannot serve).
        """
        summary = self._summary_for(brief)
        rid = run_id or f"run-{uuid.uuid4().hex[:8]}"
        # FEAT-480 spec §8 OQ1 / §3 Module 5: same recovery gate as the base
        # class's run() (TASK-2626) — a caller-supplied stable run_id with
        # dev_loop_flow_kwargs configured is the recovery identity; an
        # auto-generated one never reaches the coordinator at all.
        recovery_enabled = run_id is not None and self._dev_loop_flow_kwargs is not None

        # AHP-style host: created + registered BEFORE the flow runs and seeded
        # into shared state, so nodes resolve it per-run (IdeationNode reads
        # shared["session_host"] to open its open_questions gates; it never
        # imports the runner).
        host = self._register_host(rid)
        self._create_run_registry(rid)  # FEAT-479 M5 — see TASK-2620 Completion Note
        host.apply(
            RunCreated(
                run_id=rid,
                revision=False,
                work_kind=self._work_kind_for(brief),
                summary=summary,
            )
        )
        self._apply_root_action(RunAdded(summary=self._run_summary_from_host(host)))

        shared: dict[str, Any] = {
            # Canonical dev-flow key, read by DevIntakeNode and IdeationNode.
            "dev_brief": brief,
            "run_id": rid,
            "session_host": host,
        }
        if isinstance(brief, FeatureBrief):
            # Pre-seed the key PlannerNode reads. DevIntakeNode would publish
            # it anyway; seeding here keeps the pre-intake context honest for
            # any observer (and for a resumed/replayed run).
            shared["feature_brief"] = brief
        # NOTE: the bug-mode keys ("bug_brief" / "work_brief") stay unset —
        # dev-flow never populates them.
        if extra_shared:
            shared.update(extra_shared)

        ctx = FlowContext(
            initial_task=initial_task or summary,
            shared_data=shared,
        )

        # FEAT-490: a per-run plan travels as a call argument into the
        # per-call factory closure below — never assigned to `self`, so
        # concurrent runs with different plans never leak seats into each
        # other (spec §2 Overview step 2, §7 "Concurrency leak" risk).
        flow_kwargs_overrides = {"model_plan": model_plan} if model_plan is not None else None

        # spec §8 Q1 / §3 Module 3: a run that never enters the checkpoint
        # coordinator at all (recovery disabled) is inherently a plain fresh
        # run — "fresh" is the correct default here, not "unknown", so the
        # metadata recorded below is accurate even off the recovery path.
        mode: Literal["fresh", "resumed"] = "fresh"
        flow = self.flow
        if recovery_enabled:
            flow, mode = await self._checkpoint_coordinator.prepare(
                workflow=self.CHECKPOINT_WORKFLOW,
                run_id=rid,
                brief=brief,
                live_context=ctx,
                flow_factory=self._dev_loop_flow_factory(flow_kwargs_overrides),
                execution_policy=self._execution_policy_for_fingerprint(),
            )
            # spec §5: recovered runs must be distinguishable in session
            # timeline events — same structured-logging approach as the
            # base class's run() (TASK-2626).
            self.logger.info(
                "Dev-flow run %s: %s execution (checkpoint recovery enabled)",
                rid,
                mode,
            )

        # spec §8 Q1 (resolved: "keep the original"): a resumed run must
        # keep the seats it was created with. CORRECTED (post-review):
        # DevCheckpointCoordinator.prepare()'s resume branch does NOT skip
        # flow_factory — AgentsFlow.resume() calls the SAME closure
        # (`flow_factory(checkpoint.definition)`) to rebuild the topology
        # of every not-yet-completed node. The rule above is therefore
        # enforced INSIDE `_dev_loop_flow_factory()`'s closure — it only
        # merges `flow_kwargs_overrides` when invoked with `_definition is
        # None` (the cache-miss/fresh signal), never when AgentsFlow.resume()
        # calls it with a real definition. `mode` (computed by `prepare()`
        # itself, using the SAME signal) is what makes that guarantee
        # correctly reportable here.
        #
        # CORRECTED (post-review, 2nd finding): `recovery_enabled` must
        # gate this too. When it is False, `flow = self.flow` above reuses
        # the pre-built construction-time flow untouched — the recovery
        # coordinator (and therefore `_dev_loop_flow_factory`/`build_dev_flow`)
        # is never even called, so a submitted `model_plan` silently never
        # reaches anything. `mode` stays at its "fresh" default in that
        # branch (line ~182) — a leftover value, not evidence the plan
        # applied — so `mode != "resumed"` alone is not sufficient here.
        model_plan_applied = model_plan is not None and recovery_enabled and mode != "resumed"

        # Same manual acquire/park-aware structure as the base class's run()
        # (FEAT-377 TASK-1917 / G6), and mandatory here: an ideation
        # open_questions gate can park the run for hours, releasing the slot
        # from deep inside IdeationNode while run_flow() is still in flight —
        # which `async with self._semaphore` cannot express. Registering
        # _run_completion[rid] is what lets resume_run() await the SAME
        # eventual FlowResult.
        loop = asyncio.get_running_loop()
        completion: asyncio.Future[FlowResult] = loop.create_future()
        self._run_completion[rid] = completion
        await self._semaphore.acquire()
        self._active.add(rid)
        # Point the flow's event publisher at this run's stream.
        holder = getattr(flow, "_run_id_holder", None)
        if isinstance(holder, dict):
            holder["run_id"] = rid
        self.logger.info(
            "Starting dev-flow run %s kind=%s (%d/%d active)",
            rid,
            getattr(brief, "kind", "?"),
            len(self._active),
            self.max_concurrent_runs,
        )
        try:
            result = await flow.run_flow(ctx)
        except BaseException as exc:
            # Propagate to any resume_run() awaiter too — a future that never
            # resolves would hang them forever. Popped here (not in `finally`)
            # so it happens BEFORE the exception keeps propagating.
            if not completion.done():
                completion.set_exception(exc)
            self._run_completion.pop(rid, None)
            self._discard_run_registry(rid)  # FEAT-479 M5
            self._retire_actions_writer(rid)
            raise
        finally:
            # Exactly-once release: only if this run is STILL holding its slot
            # (never parked, or parked and already resumed by the time
            # run_flow() returned/raised). A run that finishes while still
            # parked releases nothing here — _park already released its slot.
            if rid in self._active:
                self._active.discard(rid)
                self._semaphore.release()
            else:
                self._parked.discard(rid)
            self._pending_gate_count.pop(rid, None)

        self.logger.info("Dev-flow run %s finished status=%s", rid, result.status)
        # FEAT-490 spec §8 Q1/Q4: record what was requested AND what was
        # actually effective, so a caller (or an embedder reusing a stable
        # run_id) can tell what ran without guessing from the flow's build
        # kwargs. On a resumed run the newly submitted plan is reported as
        # NOT applied — the run kept the seats it was created with.
        result.metadata["model_plan_requested"] = model_plan.model_dump(mode="json") if model_plan is not None else None
        result.metadata["model_plan_effective"] = (
            model_plan.model_dump(mode="json") if model_plan_applied else None
        )
        result.metadata["run_mode"] = mode
        await self._close_host(host, result, ctx)
        if not completion.done():
            completion.set_result(result)
        self._run_completion.pop(rid, None)
        self._discard_run_registry(rid)  # FEAT-479 M5
        return result

    # ------------------------------------------------------------------
    # Internal — brief projections
    # ------------------------------------------------------------------

    @staticmethod
    def _summary_for(brief: DevRequestBrief | FeatureBrief) -> str:
        """Human-readable one-liner for the run registry and initial task.

        Args:
            brief: The dev-flow brief.

        Returns:
            The request title for a natural-language brief, or
            ``"Feature: <document_path>"`` for a document brief (matching
            ``_run_feature``'s wording).

        Raises:
            TypeError: The brief is not a dev-flow brief kind.
        """
        if isinstance(brief, DevRequestBrief):
            return brief.title
        if isinstance(brief, FeatureBrief):
            return f"Feature: {brief.document_path}"
        raise TypeError("DevFlowRunner.run expects a DevRequestBrief or FeatureBrief; " f"got {type(brief).__name__}.")

    @staticmethod
    def _work_kind_for(
        brief: DevRequestBrief | FeatureBrief,
    ) -> Literal["bug", "enhancement", "new_feature"]:
        """Map the brief onto ``RunCreated.work_kind``.

        ``work_kind`` is a closed ``Literal["bug", "enhancement",
        "new_feature"]`` deliberately NOT extended with ``"feature"``
        (TASK-1918) — ``FeatureBrief`` carries its own ``kind`` instead. A
        ``DevRequestBrief``'s kind maps directly onto two of those values; a
        document brief reuses ``"bug"`` as the structural placeholder, exactly
        as ``_run_feature`` does (never read on this path — dev-flow has no
        ResearchNode and no Jira issue-type selection).

        Args:
            brief: The dev-flow brief.

        Returns:
            A valid ``work_kind`` literal value.
        """
        if isinstance(brief, DevRequestBrief):
            return brief.kind
        return "bug"

    # ------------------------------------------------------------------
    # FEAT-480 — checkpoint recovery: dev-flow-specific factory/policy
    # ------------------------------------------------------------------
    #
    # The base class's DevLoopRunner._dev_loop_flow_factory()/
    # _execution_policy_for_fingerprint() (TASK-2626) are hardcoded to
    # `build_dev_loop_flow` and its kwarg shape — overridden here to call
    # `build_dev_flow` instead, reusing the SAME inherited
    # `self._dev_loop_flow_kwargs`/`self._checkpoint_store` state (the
    # attribute name stays generic across both workflows; only the
    # factory function it is applied to differs).

    def _dev_loop_flow_factory(self, overrides: dict[str, Any] | None = None) -> Callable[[Any], AgentsFlow]:
        """Build the ``flow_factory`` closure for ``DevCheckpointCoordinator.prepare()``.

        See ``DevLoopRunner._dev_loop_flow_factory()`` for the full
        rationale — identical here except it calls ``build_dev_flow``.

        FEAT-490 correction (post-review): ``AgentsFlow.resume()`` calls
        THIS closure — ``flow_factory(checkpoint.definition)`` — to rebuild
        a RESUMED run's topology too, not only ``prepare()``'s cache-miss
        branch (``flow_factory(None)``). ``overrides`` (e.g. a per-run
        ``model_plan``) must therefore only apply when ``_definition is
        None`` — otherwise a resumed run's not-yet-completed nodes would
        silently adopt a newly submitted ``model_plan`` instead of keeping
        the one the run was created with (spec §8 Q1). See the base
        class's docstring for the full explanation of this signal.

        Args:
            overrides: FEAT-490 — optional per-run overrides (e.g.
                ``{"model_plan": ...}``) merged over
                ``self._dev_loop_flow_kwargs`` for THIS call only, and
                ONLY on the fresh (cache-miss) path. Captured in the
                closure and re-evaluated per invocation — never assigned
                to ``self``.

        Returns:
            A ``(definition) -> AgentsFlow`` callable.

        Raises:
            ValueError: If ``dev_loop_flow_kwargs`` was never supplied to
                ``__init__``.
        """
        if self._dev_loop_flow_kwargs is None:
            raise ValueError(
                "DevCheckpointCoordinator recovery requires dev_loop_flow_kwargs "
                "to have been passed to DevFlowRunner.__init__()."
            )
        base_kwargs = self._dev_loop_flow_kwargs

        def _factory(_definition: Any) -> AgentsFlow:
            kwargs = dict(base_kwargs)
            if _definition is None and overrides:
                kwargs.update(overrides)
            return build_dev_flow(
                **kwargs,
                checkpoint=True,
                checkpoint_required=True,
                checkpoint_store=self._checkpoint_store,
            )

        return _factory

    def _execution_policy_for_fingerprint(self) -> dict[str, Any]:
        """Routing-relevant policy dict for the checkpoint input fingerprint.

        See ``DevLoopRunner._execution_policy_for_fingerprint()`` for the
        full rationale — identical here except derived from
        ``build_dev_flow``'s kwarg shape (no ``development_pool_config``/
        ``repos`` — dev-flow's builder does not accept either; FEAT-486's
        ``model_plan`` carries the pool instead).

        FEAT-486: only the plan fields that actually shape execution join
        the fingerprint — how many workers of which backend the pool
        deploys, which backend reviews, and whether the research partner
        seat runs at all. Pure model strings for seats that do not change
        the graph or the worker count (the ideation primary's model, a
        pool worker's model, the counter-reviewer's model) stay OUT, so
        swapping a model mid-resume is a cache hit rather than a forced
        fresh run. The whole ``model_plan`` key is omitted when no plan
        was supplied, which keeps pre-FEAT-486 fingerprints stable.

        Returns:
            The policy dict passed to ``DevCheckpointCoordinator.prepare(
            execution_policy=...)``.
        """
        kwargs = self._dev_loop_flow_kwargs or {}
        policy: dict[str, Any] = {
            "skip_qa": kwargs.get("skip_qa", False),
            "require_plan_approval": kwargs.get("require_plan_approval", False),
            "development_pool_max": kwargs.get("development_pool_max", 4),
            "ideation_max_rounds": kwargs.get("ideation_max_rounds"),
        }
        model_plan = kwargs.get("model_plan")
        if model_plan is not None:
            policy["model_plan"] = {
                "dev_pool": [{"agent": spec.agent, "count": spec.count} for spec in model_plan.dev_pool],
                "review_primary_agent": model_plan.review.primary.agent,
                "research_partner_enabled": model_plan.research_partner.enabled,
            }
        return policy


__all__ = ["DevFlowRunner"]
