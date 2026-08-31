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
from typing import Any, Literal

from parrot.bots.flows.core.context import FlowContext

# Same module the base runner imports FlowResult from (runner.py:36).
from parrot.bots.flows.core.result import FlowResult
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

        Returns:
            The aggregated :class:`FlowResult` for the run.

        Raises:
            TypeError: *brief* is neither a ``DevRequestBrief`` nor a
                ``FeatureBrief`` (e.g. a bug-mode ``WorkBrief``, which this
                topology cannot serve).
        """
        summary = self._summary_for(brief)
        rid = run_id or f"run-{uuid.uuid4().hex[:8]}"

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
        holder = getattr(self.flow, "_run_id_holder", None)
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
            result = await self.flow.run_flow(ctx)
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


__all__ = ["DevFlowRunner"]
