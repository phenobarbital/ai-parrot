"""FlowRecoveryService — graceful-shutdown suspend + dump (FEAT-399, TASK-2054).

Tracks active checkpointed `AgentsFlow` runs and suspends every one of
them in parallel on graceful shutdown, within a configurable deadline
(default `FLOW_CHECKPOINT_SHUTDOWN_DEADLINE`, 15s). Flows that miss the
deadline are logged ERROR with their flow_ids — their last Redis
checkpoint stays recoverable until its TTL expires (spec §3 Module 8).

Auto-resume-on-startup is an explicit spec Non-Goal — this service only
suspends on shutdown; it never scans for or relaunches suspended flows.
"""
from __future__ import annotations

import asyncio
import signal
from typing import TYPE_CHECKING

from navconfig.logging import logging

from parrot.conf import FLOW_CHECKPOINT_SHUTDOWN_DEADLINE

if TYPE_CHECKING:
    import aiohttp.web

    from parrot.bots.flows.flow.flow import AgentsFlow

logger = logging.getLogger("parrot.flows.checkpoint.recovery")


class FlowRecoveryService:
    """Registry of active checkpointed flows + graceful-shutdown suspend.

    A flow calls `register(self)` when it starts a checkpointed run and
    `unregister(self)` when that run ends (normally or on error) — see
    `AgentsFlow.run_flow()`'s checkpointer lifecycle. Registration is
    keyed by `flow.flow_id`; registering again with the same id simply
    overwrites the previous entry (no error).
    """

    def __init__(self) -> None:
        self._active: dict[str, AgentsFlow] = {}
        self.logger = logger

    def register(self, flow: AgentsFlow) -> None:
        """Register an active checkpointed flow.

        Args:
            flow: The `AgentsFlow` instance to track (keyed by `flow.flow_id`).
        """
        self._active[flow.flow_id] = flow

    def unregister(self, flow: AgentsFlow) -> None:
        """Unregister a flow. Idempotent — a no-op if not registered.

        Args:
            flow: The `AgentsFlow` instance to stop tracking.
        """
        self._active.pop(flow.flow_id, None)

    async def shutdown(
        self, deadline: float = FLOW_CHECKPOINT_SHUTDOWN_DEADLINE
    ) -> None:
        """Suspend every registered flow in parallel, within `deadline` seconds.

        Never raises — this is meant to run from an aiohttp `on_shutdown`
        hook or a signal handler, where an exception here would mask other
        shutdown work. Idempotent and safe to call with zero registered
        flows (no-op).

        Args:
            deadline: Seconds to wait for all suspends to finish before
                giving up on the stragglers. Defaults to
                `FLOW_CHECKPOINT_SHUTDOWN_DEADLINE` (15s).
        """
        flows = list(self._active.values())
        if not flows:
            return

        async def _suspend_one(flow: AgentsFlow) -> None:
            try:
                await flow.suspend()
            except Exception as exc:  # noqa: BLE001 - shutdown must never raise
                self.logger.warning(
                    "FlowRecoveryService: suspend() failed for flow_id=%s: %s",
                    flow.flow_id,
                    exc,
                )

        tasks: dict[str, asyncio.Task] = {
            flow.flow_id: asyncio.ensure_future(_suspend_one(flow)) for flow in flows
        }
        _done, pending = await asyncio.wait(tasks.values(), timeout=deadline)

        if pending:
            missed = [flow_id for flow_id, task in tasks.items() if task in pending]
            self.logger.error(
                "FlowRecoveryService: shutdown deadline (%.1fs) exceeded for "
                "flow_ids=%s; their last Redis checkpoint remains recoverable "
                "until TTL",
                deadline,
                missed,
            )
            for task in pending:
                task.cancel()

    def attach_to_app(self, app: aiohttp.web.Application) -> None:
        """Register `shutdown()` on an aiohttp `Application`'s `on_shutdown`.

        Args:
            app: The aiohttp `Application` to attach to.
        """

        async def _on_shutdown(_app: aiohttp.web.Application) -> None:
            await self.shutdown()

        app.on_shutdown.append(_on_shutdown)

    def install_signal_handlers(
        self, loop: asyncio.AbstractEventLoop | None = None
    ) -> None:
        """Best-effort SIGTERM/SIGINT handlers for standalone (non-aiohttp) runners.

        Skipped (logged as a warning) on platforms/loops without signal
        support (e.g. `add_signal_handler` is unavailable on the default
        Windows event loop) rather than raising.

        Args:
            loop: Event loop to install handlers on; defaults to the
                current running loop.
        """
        loop = loop or asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(
                    sig, lambda: asyncio.ensure_future(self.shutdown())
                )
            except (NotImplementedError, RuntimeError) as exc:
                self.logger.warning(
                    "FlowRecoveryService: cannot install signal handler for "
                    "%s: %s",
                    sig,
                    exc,
                )


_default_service: FlowRecoveryService | None = None


def get_recovery_service() -> FlowRecoveryService:
    """Return the process-wide default `FlowRecoveryService` instance.

    Lets `AgentsFlow` and HTTP handlers (TASK-2055) share one registry
    without a DI framework.

    Returns:
        The shared `FlowRecoveryService` singleton.
    """
    global _default_service
    if _default_service is None:
        _default_service = FlowRecoveryService()
    return _default_service
