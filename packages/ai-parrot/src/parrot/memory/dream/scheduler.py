"""DreamScheduler — in-process periodic execution with catch-up (FEAT-390).

Asyncio background-task lifecycle for the dream cycle: persisted state
(JSON sidecar), catch-up at start when a scheduled run was missed, a
stale/fresh lock pair for crash detection (single-process assumption —
two live processes sharing one state file is unsupported, spec §7), and
failure backoff when a cycle aborts.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import DreamConfig, DreamCycleReport, DreamState, load_state, save_state
from .runner import DreamCycleRunner

logger = logging.getLogger(__name__)


class DreamScheduler:
    """Drives a ``DreamCycleRunner`` on a periodic, in-process schedule.

    Attributes:
        logger: Standard module logger.

    Args:
        runner: The pipeline to invoke each cycle.
        state_path: Path to the ``DreamState`` JSON sidecar.
        interval_hours: Interval between cycles (default 24h).
        config: Tunables (jitter, failure backoff divisor); defaults to
            ``DreamConfig()``.
    """

    def __init__(
        self,
        runner: DreamCycleRunner,
        state_path: Path,
        interval_hours: float = 24.0,
        config: DreamConfig | None = None,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self._runner = runner
        self._state_path = Path(state_path)
        self._interval_hours = interval_hours
        self._config = config or DreamConfig()
        # No public accessor on DreamCycleRunner exposes the namespace;
        # reach through to it the same way runner.py reaches into
        # EpisodicMemoryStore._backend (documented pattern in this feature).
        self._agent_id = runner._namespace.agent_id
        self._state: DreamState | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Load state, handle stale locks, catch up if overdue, start the loop.

        - A stale lock (``running_since`` older than 2x interval) is
          cleared with a WARNING.
        - A fresh lock means a cycle is genuinely in progress elsewhere
          in this process; ``start()`` persists state and returns without
          spawning a second loop.
        - ``next_due is None`` (first run) schedules one interval out with
          no immediate cycle.
        - ``next_due <= now`` runs one catch-up cycle (after a random
          0..``startup_jitter_seconds`` jitter) before scheduling the loop.
        """
        state = load_state(self._state_path, agent_id=self._agent_id)
        state.interval_hours = self._interval_hours
        self._state = state

        now = datetime.now(UTC)

        if state.running and state.running_since is not None:
            stale_after = timedelta(hours=2 * self._interval_hours)
            if now - state.running_since > stale_after:
                self.logger.warning(
                    "DreamScheduler: stale lock for agent %s (running_since=%s); "
                    "ignoring and proceeding",
                    self._agent_id,
                    state.running_since,
                )
                state.running = False
                state.running_since = None
            else:
                self.logger.info(
                    "DreamScheduler: fresh lock already held for agent %s; "
                    "not starting a second loop",
                    self._agent_id,
                )
                save_state(state, self._state_path)
                return

        if state.next_due is None:
            state.next_due = now + timedelta(hours=self._interval_hours)
            save_state(state, self._state_path)
        elif state.next_due <= now:
            jitter = random.uniform(0, self._config.startup_jitter_seconds)
            if jitter:
                await asyncio.sleep(jitter)
            await self._run_locked_cycle()

        self._task = asyncio.create_task(
            self._loop(), name=f"dream-{self._agent_id}"
        )

    async def stop(self) -> None:
        """Cancel the loop task cleanly and persist the final state."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

        if self._state is not None:
            self._state.running = False
            self._state.running_since = None
            save_state(self._state, self._state_path)

    async def run_now(self) -> DreamCycleReport:
        """Explicitly trigger a cycle, respecting the lock.

        Loads state on demand if ``start()`` was never called. Refuses to
        run when a fresh (non-stale) lock is already held, returning an
        aborted report instead of running concurrently.

        Returns:
            The cycle's report (or an aborted stub report if refused).
        """
        if self._state is None:
            self._state = load_state(self._state_path, agent_id=self._agent_id)
        state = self._state

        now = datetime.now(UTC)
        if state.running and state.running_since is not None:
            stale_after = timedelta(hours=2 * self._interval_hours)
            if now - state.running_since <= stale_after:
                self.logger.warning(
                    "DreamScheduler.run_now: a cycle is already running for "
                    "agent %s; refusing concurrent run",
                    self._agent_id,
                )
                return DreamCycleReport(
                    started_at=now,
                    finished_at=now,
                    aborted=True,
                    abort_reason="cycle already running",
                )

        return await self._run_locked_cycle()

    async def _run_locked_cycle(self) -> DreamCycleReport:
        """Acquire the lock, run one cycle, release the lock, reschedule.

        Persists state at both lock-acquire and lock-release so a crash
        mid-cycle leaves a detectable stale lock.

        Returns:
            The cycle's report.
        """
        state = self._state
        assert state is not None  # narrows type; start()/run_now() set it

        now = datetime.now(UTC)
        state.running = True
        state.running_since = now
        save_state(state, self._state_path)

        try:
            report = await self._runner.run_cycle(state)
        except Exception as e:  # noqa: BLE001 - scheduler must never raise
            self.logger.warning(
                "DreamScheduler: cycle raised unexpectedly for agent %s: %s",
                self._agent_id,
                e,
            )
            report = DreamCycleReport(
                started_at=now,
                finished_at=datetime.now(UTC),
                aborted=True,
                abort_reason=str(e),
            )

        state.running = False
        state.running_since = None

        reschedule_now = datetime.now(UTC)
        if report.aborted:
            state.next_due = reschedule_now + timedelta(
                hours=self._interval_hours / self._config.failure_backoff_divisor
            )
        else:
            state.next_due = reschedule_now + timedelta(hours=self._interval_hours)

        save_state(state, self._state_path)

        self.logger.info(
            "DreamScheduler cycle (agent=%s): collected=%d groups=%d "
            "distilled=%d skipped=%d pages=%d promoted=%d aborted=%s next_due=%s",
            self._agent_id,
            report.episodes_collected,
            report.groups_formed,
            report.groups_distilled,
            report.groups_skipped,
            len(report.pages_written),
            len(report.pages_promoted),
            report.aborted,
            state.next_due,
        )
        return report

    async def _loop(self) -> None:
        """Background loop: sleep until due, run a cycle, repeat.

        Never raises: any per-iteration failure logs a WARNING and the
        loop continues (cancellation still propagates cleanly).
        """
        while True:
            try:
                state = self._state
                assert state is not None
                now = datetime.now(UTC)
                wait_seconds = self._seconds_until_due(state, now)
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)
                await self._run_locked_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - loop must never die
                self.logger.warning("DreamScheduler loop iteration failed: %s", e)
                await asyncio.sleep(1)

    @staticmethod
    def _seconds_until_due(state: DreamState, now: datetime) -> float:
        """Compute seconds to sleep before the next due cycle.

        Args:
            state: Current dream state.
            now: Current time (injectable for tests).

        Returns:
            Non-negative number of seconds to sleep.
        """
        if state.next_due is None:
            return 0.0
        return max(0.0, (state.next_due - now).total_seconds())
