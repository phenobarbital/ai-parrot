"""DevLoopRunner — orchestrator-side hosting for the dev-loop flow.

Closes spec G5's orchestrator half: the dispatcher already caps
concurrent Claude Code dispatches (``CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES``);
this runner caps concurrent *flow runs* with an ``asyncio.Semaphore``
sized by ``FLOW_MAX_CONCURRENT_RUNS``.

Responsibilities:

- mint (or accept) the ``run_id`` and seed the :class:`FlowContext`
  (``shared_data['bug_brief']`` / ``['work_brief']`` / ``['run_id']``);
- bind the run_id to the flow's :class:`FlowEventPublisher` so
  node-lifecycle events land on ``flow:{run_id}:flow``;
- track active runs (``active_runs`` / ``is_active``).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, Optional, Set

from navconfig.logging import logging

from parrot import conf
from parrot.bots.flows import AgentsFlow
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.result import FlowResult
from parrot.flows.dev_loop.models import WorkBrief


class DevLoopRunner:
    """Hosts dev-loop flow runs behind a global concurrency cap.

    Args:
        flow: The :class:`AgentsFlow` built by ``build_dev_loop_flow``.
        max_concurrent_runs: Cap on simultaneously executing runs.
            Defaults to ``conf.FLOW_MAX_CONCURRENT_RUNS``.
    """

    def __init__(
        self,
        flow: AgentsFlow,
        *,
        max_concurrent_runs: Optional[int] = None,
    ) -> None:
        self.flow = flow
        self.max_concurrent_runs = int(
            max_concurrent_runs
            if max_concurrent_runs is not None
            else conf.FLOW_MAX_CONCURRENT_RUNS
        )
        self._semaphore = asyncio.Semaphore(self.max_concurrent_runs)
        self._active: Set[str] = set()
        self.logger = logging.getLogger("parrot.dev_loop.runner")

    # ── Introspection ─────────────────────────────────────────────────────

    @property
    def active_runs(self) -> Set[str]:
        """Run IDs currently executing (copy)."""
        return set(self._active)

    def is_active(self, run_id: str) -> bool:
        """True while *run_id* is executing."""
        return run_id in self._active

    # ── Execution ─────────────────────────────────────────────────────────

    async def run(
        self,
        brief: WorkBrief,
        *,
        run_id: Optional[str] = None,
        initial_task: str = "",
        extra_shared: Optional[Dict[str, Any]] = None,
    ) -> FlowResult:
        """Execute one dev-loop run for *brief*, respecting the run cap.

        Blocks (cooperatively) while ``max_concurrent_runs`` runs are
        already in flight.

        Args:
            brief: The validated :class:`WorkBrief` / ``BugBrief`` to process.
            run_id: Optional externally-minted run identifier; one is
                generated (``run-<hex8>``) when omitted.
            initial_task: Optional human-readable task line stored as the
                context's ``initial_task``.
            extra_shared: Extra entries merged into ``shared_data``.

        Returns:
            The aggregated :class:`FlowResult` for the run.
        """
        rid = run_id or f"run-{uuid.uuid4().hex[:8]}"
        shared: Dict[str, Any] = {
            "bug_brief": brief,    # legacy key — nodes read this
            "work_brief": brief,   # forward-compat name
            "run_id": rid,
        }
        if extra_shared:
            shared.update(extra_shared)

        ctx = FlowContext(
            initial_task=initial_task or brief.summary,
            shared_data=shared,
        )

        async with self._semaphore:
            self._active.add(rid)
            # Point the flow's event publisher at this run's stream.
            holder = getattr(self.flow, "_run_id_holder", None)
            if isinstance(holder, dict):
                holder["run_id"] = rid
            self.logger.info(
                "Starting dev-loop run %s (%d/%d active)",
                rid, len(self._active), self.max_concurrent_runs,
            )
            try:
                result = await self.flow.run_flow(ctx)
            finally:
                self._active.discard(rid)

        self.logger.info(
            "Dev-loop run %s finished status=%s", rid, result.status
        )
        return result


__all__ = ["DevLoopRunner"]
