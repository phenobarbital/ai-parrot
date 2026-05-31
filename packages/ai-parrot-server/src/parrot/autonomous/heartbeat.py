"""Autonomous Agent Heartbeat.

Provides a per-agent async heartbeat loop that implements the
``wake → assess → maybe act`` cycle on top of
:class:`~parrot.autonomous.orchestrator.AutonomousOrchestrator`.

Heartbeat is **not** a cron scheduler: the :class:`HeartbeatStrategy`
assess step (``should_act``) decides whether the agent acts on each tick.
Persistence / replay across restarts is handled by the ledger (feature #4).
App wiring (``on_startup`` / ``on_shutdown``) is deferred to feature #6.

Usage example (manual wiring)::

    from parrot.autonomous.heartbeat import (
        HeartbeatConfig,
        HeartbeatManager,
        DefaultHeartbeatStrategy,
    )

    async def has_work():
        return await queue.qsize() > 0

    strategy = DefaultHeartbeatStrategy(has_pending_work=has_work)
    manager = HeartbeatManager(orchestrator, strategy=strategy)
    manager.register(HeartbeatConfig(
        agent_name="my-agent",
        interval=60.0,
        jitter=5.0,
        mission="Check inbox and summarise new messages.",
    ))

    # In on_startup:
    await manager.start()

    # In on_shutdown:
    await manager.stop()
"""

from __future__ import annotations

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional, TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from parrot.autonomous.orchestrator import AutonomousOrchestrator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class HeartbeatConfig(BaseModel):
    """Configuration for a single agent's heartbeat loop.

    Attributes:
        agent_name: Name of the registered agent (must match orchestrator
            registry).
        interval: Seconds between ticks. Must be > 0.
        jitter: Maximum random seconds added to ``interval`` on each tick.
            Set to 0 to disable jitter.
        enabled: When False the agent is skipped during
            :meth:`HeartbeatManager.start`.
        max_consecutive_errors: Number of back-to-back tick errors after
            which the agent's loop is paused automatically.
        mission: Default prompt seed forwarded to the act step. May be
            ``None`` if the strategy builds its own prompt.
    """

    agent_name: str
    interval: float = Field(60.0, gt=0, description="Seconds between ticks.")
    jitter: float = Field(
        0.0, ge=0, description="Max random seconds added to interval."
    )
    enabled: bool = True
    max_consecutive_errors: int = Field(5, ge=1)
    mission: Optional[str] = Field(
        default=None, description="Default prompt seed for act step."
    )


class HeartbeatState(BaseModel):
    """Runtime state for a single agent's heartbeat loop.

    All fields are in-memory only; reset on restart.

    Attributes:
        agent_name: Identifies the agent this state belongs to.
        running: True while the heartbeat loop task is active.
        tick_count: Total number of completed ticks (sleep + assess cycle).
        action_count: Number of ticks where ``execute_agent`` was called.
        last_tick_at: UTC timestamp of the most recent tick completion.
        last_action_at: UTC timestamp of the most recent act.
        consecutive_errors: Current run of back-to-back errors; reset on
            success.
        last_error: String representation of the most recent caught
            exception, or ``None``.
    """

    agent_name: str
    running: bool = False
    tick_count: int = 0
    action_count: int = 0
    last_tick_at: Optional[datetime] = None
    last_action_at: Optional[datetime] = None
    consecutive_errors: int = 0
    last_error: Optional[str] = None


# ---------------------------------------------------------------------------
# Strategy ABC
# ---------------------------------------------------------------------------


class HeartbeatStrategy(ABC):
    """Pluggable assess step for the heartbeat loop.

    Implementations define the ``wake → assess → maybe act`` decision:

    1. :meth:`build_context` — gather signals (queue depth, memory, etc.)
       into a plain dict.
    2. :meth:`should_act` — inspect context, return True if the agent
       should act this tick.
    3. :meth:`build_prompt` — construct the mission/task string forwarded
       to ``execute_agent``.
    """

    @abstractmethod
    async def build_context(self, cfg: HeartbeatConfig) -> dict[str, Any]:
        """Build a context dict for the current tick.

        Args:
            cfg: The agent's heartbeat configuration.

        Returns:
            A dict with at least ``{"tick_count": int, "config":
            HeartbeatConfig}``.
        """

    @abstractmethod
    async def should_act(self, ctx: dict[str, Any]) -> bool:
        """Decide whether to act this tick.

        Args:
            ctx: Context built by :meth:`build_context`.

        Returns:
            True if ``execute_agent`` should be called.
        """

    @abstractmethod
    async def build_prompt(self, ctx: dict[str, Any]) -> str:
        """Construct the task/prompt string for ``execute_agent``.

        Args:
            ctx: Context built by :meth:`build_context`.

        Returns:
            A string suitable for ``AutonomousOrchestrator.execute_agent``'s
            ``task`` positional parameter.
        """


# ---------------------------------------------------------------------------
# Default strategy
# ---------------------------------------------------------------------------

_HasPendingWork = Callable[[], Awaitable[bool]]


class DefaultHeartbeatStrategy(HeartbeatStrategy):
    """Acts when ``has_pending_work()`` returns True, or every *N* ticks.

    This strategy provides two ways to trigger action:

    - **Callable gate**: an optional async ``has_pending_work`` callable is
      called on every tick. If it returns True, the agent acts.
    - **Fallback cadence**: if ``has_pending_work`` is not provided (or
      returns False), the agent acts every ``act_every_n_ticks`` ticks.

    This keeps the heartbeat semantically distinct from a cron job: it
    evaluates real signals and only fires when needed.

    Args:
        has_pending_work: Optional async callable with no arguments that
            returns ``True`` when the agent should act.
        act_every_n_ticks: Fallback cadence. The agent acts when
            ``tick_count % act_every_n_ticks == 0 and tick_count > 0``.
            Defaults to 10.
    """

    def __init__(
        self,
        *,
        has_pending_work: Optional[_HasPendingWork] = None,
        act_every_n_ticks: int = 10,
    ) -> None:
        self._has_pending_work = has_pending_work
        self._act_every_n_ticks = act_every_n_ticks

    async def build_context(self, cfg: HeartbeatConfig) -> dict[str, Any]:
        """Return base context with config and current tick_count placeholder.

        Args:
            cfg: The agent's heartbeat configuration.

        Returns:
            Dict with ``config`` and ``tick_count`` keys. The
            ``HeartbeatManager`` enriches ``tick_count`` before calling
            :meth:`should_act`.
        """
        return {"config": cfg, "tick_count": 0}

    async def should_act(self, ctx: dict[str, Any]) -> bool:
        """Decide whether to act this tick.

        Acts when ``has_pending_work()`` returns True, OR when
        ``tick_count % act_every_n_ticks == 0 and tick_count > 0``.

        Args:
            ctx: Context dict containing at least ``tick_count``.

        Returns:
            True if the agent should call ``execute_agent`` this tick.
        """
        if self._has_pending_work is not None:
            try:
                if await self._has_pending_work():
                    return True
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "DefaultHeartbeatStrategy.has_pending_work raised: %s", exc
                )

        tick_count: int = ctx.get("tick_count", 0)
        if tick_count > 0 and tick_count % self._act_every_n_ticks == 0:
            return True

        return False

    async def build_prompt(self, ctx: dict[str, Any]) -> str:
        """Return the mission from config, or a sensible default string.

        Args:
            ctx: Context dict containing ``config`` (a
                :class:`HeartbeatConfig` instance).

        Returns:
            The ``mission`` field from config, or
            ``"Perform periodic agent review."`` as a fallback.
        """
        cfg: Optional[HeartbeatConfig] = ctx.get("config")
        if cfg is not None and cfg.mission:
            return cfg.mission
        return "Perform periodic agent review."


# ---------------------------------------------------------------------------
# HeartbeatManager (added in TASK-1392)
# ---------------------------------------------------------------------------


class HeartbeatManager:
    """Manages per-agent async heartbeat loops.

    Each registered agent gets its own ``asyncio.Task`` running
    :meth:`_heartbeat_loop`. The loop mirrors the ``_presence_loop``
    pattern from
    ``parrot.autonomous.transport.filesystem.transport._presence_loop``
    (transport.py:296).

    Observability:
        :meth:`get_state` / :meth:`get_all_states` return in-memory state
        for each agent. This state is the base for ``/health`` and the
        ledger (feature #4).

    Args:
        orchestrator: The :class:`~parrot.autonomous.orchestrator.
            AutonomousOrchestrator` instance used for the act step.
        strategy: Optional :class:`HeartbeatStrategy` to use for all
            agents. Defaults to :class:`DefaultHeartbeatStrategy`.
    """

    def __init__(
        self,
        orchestrator: "AutonomousOrchestrator",
        *,
        strategy: Optional[HeartbeatStrategy] = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._strategy: HeartbeatStrategy = (
            strategy if strategy is not None else DefaultHeartbeatStrategy()
        )
        self._configs: dict[str, HeartbeatConfig] = {}
        self._states: dict[str, HeartbeatState] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._running: bool = False
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, cfg: HeartbeatConfig) -> None:
        """Register an agent for heartbeat monitoring.

        Must be called **before** :meth:`start`. Calling ``register`` on
        an already-registered agent replaces the config and resets state.

        Args:
            cfg: The agent's heartbeat configuration.
        """
        self._configs[cfg.agent_name] = cfg
        self._states[cfg.agent_name] = HeartbeatState(agent_name=cfg.agent_name)
        self._locks[cfg.agent_name] = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Spawn one heartbeat loop task per enabled registered agent.

        Safe to call multiple times; already-running tasks are not
        duplicated.
        """
        self._running = True
        for name, cfg in self._configs.items():
            if not cfg.enabled:
                self.logger.debug("Heartbeat disabled for agent %s — skipping.", name)
                continue
            if name in self._tasks and not self._tasks[name].done():
                self.logger.debug("Heartbeat task for %s already running.", name)
                continue
            task = asyncio.create_task(
                self._heartbeat_loop(cfg), name=f"heartbeat:{name}"
            )
            self._tasks[name] = task
            self.logger.info("Heartbeat started for agent %s (interval=%.1fs).", name, cfg.interval)

    async def stop(self) -> None:
        """Cancel all running heartbeat tasks and wait for them to finish.

        Handles :exc:`asyncio.CancelledError` internally; does not raise.
        """
        self._running = False
        tasks = list(self._tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception) and not isinstance(
                    result, asyncio.CancelledError
                ):
                    self.logger.warning("Heartbeat task ended with error: %s", result)

        # Mark all agents as not running
        for state in self._states.values():
            state.running = False
        self.logger.info("All heartbeat tasks stopped.")

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def get_state(self, agent_name: str) -> Optional[HeartbeatState]:
        """Return the current state for the given agent.

        Args:
            agent_name: The agent identifier (matches
                :attr:`HeartbeatConfig.agent_name`).

        Returns:
            :class:`HeartbeatState` or ``None`` if the agent is not
            registered.
        """
        return self._states.get(agent_name)

    def get_all_states(self) -> list[HeartbeatState]:
        """Return a list of states for all registered agents.

        Returns:
            List of :class:`HeartbeatState` instances (one per registered
            agent).
        """
        return list(self._states.values())

    # ------------------------------------------------------------------
    # Inner loop (mirrors _presence_loop pattern from transport.py:296)
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self, cfg: HeartbeatConfig) -> None:
        """Run the heartbeat loop for a single agent.

        Pattern:
            ``while running: sleep → (skip if busy) → assess → maybe act``

        Mirrors :func:`_presence_loop` from
        ``parrot.autonomous.transport.filesystem.transport`` (line 296):
        ``CancelledError`` is always re-raised; other exceptions are caught,
        logged, and trigger backoff logic.

        Args:
            cfg: The agent's heartbeat configuration.
        """
        state = self._states[cfg.agent_name]
        lock = self._locks[cfg.agent_name]
        state.running = True

        while self._running:
            try:
                sleep_time = cfg.interval
                if cfg.jitter > 0:
                    sleep_time += random.uniform(0, cfg.jitter)
                await asyncio.sleep(sleep_time)

                # Skip if previous tick is still executing (per-agent lock).
                if lock.locked():
                    self.logger.debug(
                        "Heartbeat tick skipped for %s (previous tick still running).",
                        cfg.agent_name,
                    )
                    state.tick_count += 1
                    state.last_tick_at = datetime.now(tz=timezone.utc)
                    continue

                async with lock:
                    ctx = await self._strategy.build_context(cfg)
                    ctx["tick_count"] = state.tick_count

                    if await self._strategy.should_act(ctx):
                        prompt = await self._strategy.build_prompt(ctx)
                        result = await self._orchestrator.execute_agent(
                            cfg.agent_name, prompt
                        )
                        state.action_count += 1
                        state.last_action_at = datetime.now(tz=timezone.utc)
                        state.consecutive_errors = 0
                        state.last_error = None
                        self.logger.debug(
                            "Heartbeat action for %s: success=%s",
                            cfg.agent_name,
                            getattr(result, "success", None),
                        )

                state.tick_count += 1
                state.last_tick_at = datetime.now(tz=timezone.utc)

            except asyncio.CancelledError:
                # Always propagate cancellation — this is how stop() works.
                raise
            except Exception as exc:  # noqa: BLE001
                state.consecutive_errors += 1
                state.last_error = str(exc)
                state.tick_count += 1
                state.last_tick_at = datetime.now(tz=timezone.utc)
                self.logger.warning(
                    "Heartbeat tick error for %s (consecutive=%d): %s",
                    cfg.agent_name,
                    state.consecutive_errors,
                    exc,
                )

                if state.consecutive_errors >= cfg.max_consecutive_errors:
                    self.logger.error(
                        "Heartbeat paused for %s after %d consecutive errors.",
                        cfg.agent_name,
                        state.consecutive_errors,
                    )
                    state.running = False
                    return  # Exit loop; task completes naturally.

        state.running = False
