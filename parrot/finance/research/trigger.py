"""
Deliberation Trigger
=====================

Monitors research briefing freshness and triggers the full trading
pipeline when sufficient data is available.

The trigger subscribes to the ``briefings:updated`` Redis pub/sub channel.
On each event, it evaluates whether enough crews have fresh data to
justify a deliberation cycle. When conditions are met, it invokes
``run_trading_pipeline()`` — the existing end-to-end pipeline from
deliberation through execution.

Trigger modes:
    - ``quorum``:    Fire when ≥ N of 5 crews have fresh data (default N=4).
    - ``all_fresh``: Fire only when ALL 5 crews have fresh data.
    - ``scheduled``: Fire at fixed times (via external cron), ignore freshness.
    - ``manual``:    Only fire via explicit ``force_trigger()`` call.

Safety:
    - Debounce: at most 1 cycle per ``min_cycle_interval`` (default 2h).
    - Lock: Redis-based lock prevents concurrent cycles in multi-process.
    - Circuit breaker: respects the pipeline's own circuit breaker logic.
    - Dry-run mode: logs what would happen without executing.

Architecture::

    Redis pub/sub                    DeliberationTrigger
    ─────────────                    ───────────────────
    briefings:updated ──subscribe──▶ on_briefing_event()
                                          │
                                     check_freshness()
                                          │
                                     quorum met?
                                       │     │
                                      YES    NO → wait
                                       │
                                     debounce?
                                       │
                                     acquire lock?
                                       │
                                     _run_cycle()
                                       │
                                     run_trading_pipeline()

Usage::

    trigger = DeliberationTrigger(
        briefing_store=store,
        redis=redis_client,
        mode="quorum",
    )
    await trigger.start()   # begins listening
    # ... runs autonomously
    await trigger.stop()
"""
from __future__ import annotations
from typing import Any, Callable, Coroutine, Optional, TYPE_CHECKING
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from enum import Enum
import redis.asyncio as aioredis
from navconfig.logging import logging

if TYPE_CHECKING:
    from parrot.finance.research.briefing_store import ResearchBriefingStore

# =============================================================================
# CONFIGURATION
# =============================================================================

class TriggerMode(str, Enum):
    """How the trigger decides when to fire."""
    QUORUM = "quorum"
    ALL_FRESH = "all_fresh"
    SCHEDULED = "scheduled"
    MANUAL = "manual"


class CycleResult:
    """Record of a single deliberation cycle execution."""

    __slots__ = (
        "cycle_id", "started_at", "finished_at", "success",
        "trigger_reason", "briefings_available", "orders_generated",
        "orders_executed", "error", "logger"
    )

    def __init__(self, cycle_id: str, trigger_reason: str):
        self.cycle_id = cycle_id
        self.trigger_reason = trigger_reason
        self.started_at = datetime.now(timezone.utc)
        self.finished_at: Optional[datetime] = None
        self.success: bool = False
        self.briefings_available: dict[str, bool] = {}
        self.orders_generated: int = 0
        self.orders_executed: int = 0
        self.error: Optional[str] = None
        self.logger = logging.getLogger(
            "parrot.finance.research.trigger"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "success": self.success,
            "trigger_reason": self.trigger_reason,
            "briefings_available": self.briefings_available,
            "orders_generated": self.orders_generated,
            "orders_executed": self.orders_executed,
            "error": self.error,
        }


# =============================================================================
# DEFAULT STALENESS WINDOWS
# =============================================================================

DEFAULT_STALENESS_WINDOWS: dict[str, timedelta] = {
    "macro": timedelta(hours=8),
    "equity": timedelta(hours=6),
    "crypto": timedelta(hours=4),
    "sentiment": timedelta(hours=6),
    "risk": timedelta(hours=8),
}


# =============================================================================
# DELIBERATION TRIGGER
# =============================================================================

class DeliberationTrigger:
    """Monitor briefing freshness and trigger deliberation cycles.

    Args:
        briefing_store: ``ResearchBriefingStore`` for freshness checks.
        redis: Async Redis connection for pub/sub and distributed lock.
        mode: Trigger mode (``quorum``, ``all_fresh``, ``scheduled``, ``manual``).
        quorum_threshold: Minimum fresh crews needed (for ``quorum`` mode).
        staleness_windows: Max age per domain before data is considered stale.
        min_cycle_interval: Minimum time between cycles (debounce).
        lock_ttl: Redis lock TTL (seconds). Auto-releases if cycle hangs.
        dry_run: If True, log but don't execute the pipeline.
        pipeline_factory: Factory that returns the pipeline coroutine.
            Default uses ``_default_pipeline_factory`` which calls
            ``run_trading_pipeline``.
    """

    LOCK_KEY = "parrot:finance:deliberation_lock"
    LAST_CYCLE_KEY = "parrot:finance:last_cycle_ts"
    CYCLE_HISTORY_KEY = "parrot:finance:cycle_history"

    def __init__(
        self,
        briefing_store: "ResearchBriefingStore",
        redis: aioredis.Redis,
        *,
        mode: TriggerMode | str = TriggerMode.QUORUM,
        quorum_threshold: int = 4,
        staleness_windows: dict[str, timedelta] | None = None,
        min_cycle_interval: timedelta = timedelta(hours=2),
        lock_ttl: int = 1800,
        dry_run: bool = False,
        pipeline_factory: Optional[Callable[..., Coroutine]] = None,
    ):
        if isinstance(mode, str):
            mode = TriggerMode(mode)

        self.store = briefing_store
        self.redis = redis
        self.mode = mode
        self.quorum_threshold = quorum_threshold
        self.staleness_windows = {
            **DEFAULT_STALENESS_WINDOWS,
            **(staleness_windows or {}),
        }
        self.min_cycle_interval = min_cycle_interval
        self.lock_ttl = lock_ttl
        self.dry_run = dry_run
        self._pipeline_factory = pipeline_factory or _default_pipeline_factory

        # Runtime state
        self._running = False
        self._pubsub: Optional[aioredis.client.PubSub] = None
        self._listener_task: Optional[asyncio.Task] = None
        self._last_cycle_local: Optional[datetime] = None
        self._cycle_count = 0
        self._history: list[CycleResult] = []
        self.logger = logging.getLogger(
            "Parrot.finance.research.DeliberationTrigger"
        )

    # ─────────────────────────────────────────────────────────────────
    # LIFECYCLE
    # ─────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start listening for briefing events."""
        if self.mode == TriggerMode.MANUAL:
            self.logger.info("DeliberationTrigger started in MANUAL mode — no auto-listening")
            self._running = True
            return

        if self.mode == TriggerMode.SCHEDULED:
            self.logger.info("DeliberationTrigger in SCHEDULED mode — use force_trigger()")
            self._running = True
            return

        self._pubsub = self.redis.pubsub()
        await self._pubsub.subscribe(
            self.store.EVENT_CHANNEL,
        )
        self._running = True
        self._listener_task = asyncio.create_task(
            self._listen_loop(),
            name="deliberation_trigger_listener",
        )
        self.logger.info(
            "DeliberationTrigger started (mode=%s, quorum=%d, interval=%s, dry_run=%s)",
            self.mode.value, self.quorum_threshold,
            self.min_cycle_interval, self.dry_run,
        )

    async def stop(self) -> None:
        """Stop listening and clean up."""
        self._running = False
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await asyncio.wait_for(self._listener_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()
        self.logger.info("DeliberationTrigger stopped (cycles_run=%d)", self._cycle_count)

    # ─────────────────────────────────────────────────────────────────
    # PUB/SUB LISTENER
    # ─────────────────────────────────────────────────────────────────

    async def _listen_loop(self) -> None:
        """Main loop: listen for briefing events and evaluate triggers."""
        self.logger.debug("Trigger listener loop started")
        try:
            while self._running:
                try:
                    msg = await asyncio.wait_for(
                        self._pubsub.get_message(
                            ignore_subscribe_messages=True, timeout=1.0,
                        ),
                        timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    continue

                if msg is None:
                    continue

                if msg.get("type") == "message":
                    await self._on_briefing_event(msg.get("data", ""))

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.logger.error("Trigger listener error: %s", exc, exc_info=True)

    async def _on_briefing_event(self, data: str) -> None:
        """Handle a single ``briefings:updated`` event."""
        try:
            event = json.loads(data) if isinstance(data, str) else data
        except (json.JSONDecodeError, TypeError):
            event = {}

        crew_id = event.get("crew_id", "unknown")
        domain = event.get("domain", "unknown")
        self.logger.debug("Briefing event: crew=%s domain=%s", crew_id, domain)

        await self.check_and_trigger(reason=f"briefing_event:{domain}")

    # ─────────────────────────────────────────────────────────────────
    # TRIGGER EVALUATION
    # ─────────────────────────────────────────────────────────────────

    async def check_and_trigger(self, reason: str = "check") -> bool:
        """Evaluate conditions and trigger a cycle if appropriate.

        This is the main entry point, called either from the pub/sub
        listener or externally (e.g. from a cron job in SCHEDULED mode).

        Returns:
            True if a cycle was triggered.
        """
        # 1. Check freshness
        freshness = await self.store.check_freshness(self.staleness_windows)
        fresh_count = sum(1 for v in freshness.values() if v)
        fresh_domains = [d for d, v in freshness.items() if v]

        self.logger.debug(
            "Freshness check: %d/5 fresh %s", fresh_count, fresh_domains,
        )

        # 2. Evaluate trigger condition
        should_trigger = False
        if self.mode == TriggerMode.ALL_FRESH:
            should_trigger = fresh_count == 5
        elif self.mode == TriggerMode.QUORUM:
            should_trigger = fresh_count >= self.quorum_threshold
        elif self.mode in (TriggerMode.SCHEDULED, TriggerMode.MANUAL):
            # In these modes, check_and_trigger is called explicitly
            should_trigger = True

        if not should_trigger:
            self.logger.debug(
                "Trigger condition not met: mode=%s, fresh=%d/%d (need %d)",
                self.mode.value, fresh_count, 5,
                5 if self.mode == TriggerMode.ALL_FRESH else self.quorum_threshold,
            )
            return False

        # 3. Debounce
        if not await self._check_debounce():
            self.logger.debug("Debounce active — skipping trigger")
            return False

        # 4. Acquire distributed lock
        if not await self._acquire_lock():
            self.logger.debug("Lock not acquired — another instance running")
            return False

        # 5. Execute cycle
        try:
            await self._run_cycle(
                freshness=freshness,
                reason=reason,
            )
            return True
        finally:
            await self._release_lock()

    # ─────────────────────────────────────────────────────────────────
    # CYCLE EXECUTION
    # ─────────────────────────────────────────────────────────────────

    async def _run_cycle(
        self,
        freshness: dict[str, bool],
        reason: str,
    ) -> CycleResult:
        """Execute a full deliberation → execution cycle."""
        self._cycle_count += 1
        cycle_id = f"cycle_{self._cycle_count}_{int(time.time())}"
        result = CycleResult(cycle_id=cycle_id, trigger_reason=reason)
        result.briefings_available = freshness

        self.logger.info(
            "═" * 60 + "\n"
            "DELIBERATION CYCLE #%d [%s]\n"
            "Reason: %s\n"
            "Fresh briefings: %s\n"
            "═" * 60,
            self._cycle_count, cycle_id, reason,
            [d for d, v in freshness.items() if v],
        )

        if self.dry_run:
            self.logger.info("[DRY RUN] Would trigger pipeline — skipping")
            result.success = True
            result.finished_at = datetime.now(timezone.utc)
            self._history.append(result)
            return result

        try:
            # 1. Fetch briefings
            briefings = await self.store.get_latest_briefings()
            self.logger.info("Loaded %d briefings for cycle", len(briefings))

            # 2. Run the pipeline
            pipeline_result = await self._pipeline_factory(briefings=briefings)

            # 3. Record outcomes
            result.success = True
            result.orders_generated = pipeline_result.get(
                "summary", {}
            ).get("actionable_orders", 0)
            result.orders_executed = pipeline_result.get(
                "summary", {}
            ).get("executed", 0)

            self.logger.info(
                "Cycle %s completed: %d orders generated, %d executed",
                cycle_id, result.orders_generated, result.orders_executed,
            )

        except Exception as exc:
            result.success = False
            result.error = str(exc)
            self.logger.error(
                "Cycle %s FAILED: %s", cycle_id, exc, exc_info=True,
            )

        result.finished_at = datetime.now(timezone.utc)

        # Update timestamps
        self._last_cycle_local = datetime.now(timezone.utc)
        await self.redis.set(
            self.LAST_CYCLE_KEY,
            datetime.now(timezone.utc).isoformat(),
            ex=86400,
        )

        # Persist cycle record
        await self.redis.lpush(
            self.CYCLE_HISTORY_KEY,
            json.dumps(result.to_dict(), default=str),
        )
        await self.redis.ltrim(self.CYCLE_HISTORY_KEY, 0, 99)
        self._history.append(result)

        return result

    # ─────────────────────────────────────────────────────────────────
    # DEBOUNCE & LOCK
    # ─────────────────────────────────────────────────────────────────

    async def _check_debounce(self) -> bool:
        """Return True if enough time has passed since last cycle."""
        # Check local cache first (fast path)
        if self._last_cycle_local:
            elapsed = datetime.now(timezone.utc) - self._last_cycle_local
            if elapsed < self.min_cycle_interval:
                return False

        # Check Redis (cross-process)
        last_ts_str = await self.redis.get(self.LAST_CYCLE_KEY)
        if last_ts_str:
            try:
                last_ts = datetime.fromisoformat(last_ts_str)
                if last_ts.tzinfo is None:
                    last_ts = last_ts.replace(tzinfo=timezone.utc)
                elapsed = datetime.now(timezone.utc) - last_ts
                if elapsed < self.min_cycle_interval:
                    return False
            except (ValueError, TypeError):
                pass

        return True

    async def _acquire_lock(self) -> bool:
        """Acquire a Redis distributed lock for the cycle."""
        acquired = await self.redis.set(
            self.LOCK_KEY, "locked",
            nx=True, ex=self.lock_ttl,
        )
        return acquired is not None and acquired is not False

    async def _release_lock(self) -> None:
        """Release the distributed lock."""
        try:
            await self.redis.delete(self.LOCK_KEY)
        except Exception as exc:
            self.logger.warning("Failed to release lock: %s", exc)

    # ─────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────────

    async def force_trigger(self) -> CycleResult | None:
        """Force an immediate cycle regardless of mode or freshness.

        Bypasses quorum and debounce. Respects the distributed lock.
        """
        freshness = await self.store.check_freshness(self.staleness_windows)

        if not await self._acquire_lock():
            self.logger.warning("force_trigger: lock not available — cycle in progress")
            return None

        try:
            return await self._run_cycle(
                freshness=freshness,
                reason="manual_force",
            )
        finally:
            await self._release_lock()

    def get_status(self) -> dict[str, Any]:
        """Return current trigger status for monitoring."""
        return {
            "running": self._running,
            "mode": self.mode.value,
            "quorum_threshold": self.quorum_threshold,
            "min_cycle_interval_seconds": self.min_cycle_interval.total_seconds(),
            "dry_run": self.dry_run,
            "cycles_executed": self._cycle_count,
            "last_cycle": (
                self._last_cycle_local.isoformat()
                if self._last_cycle_local
                else None
            ),
            "recent_history": [
                r.to_dict() for r in self._history[-5:]
            ],
        }

    async def get_cycle_history(self, limit: int = 20) -> list[dict]:
        """Fetch cycle history from Redis."""
        raw_list = await self.redis.lrange(
            self.CYCLE_HISTORY_KEY, 0, limit - 1,
        )
        results = []
        for raw in raw_list:
            try:
                results.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
        return results


# =============================================================================
# DEFAULT PIPELINE FACTORY
# =============================================================================

async def _default_pipeline_factory(
    briefings: dict,
    **kwargs: Any,
) -> dict[str, Any]:
    """Default factory: calls ``run_trading_pipeline`` with sensible defaults.

    This function bridges the trigger with the existing pipeline by:
    1. Importing the pipeline and Agent class
    2. Building a default PortfolioSnapshot and ExecutorConstraints
    3. Creating write tool instances for Alpaca and Binance
    4. Calling run_trading_pipeline()

    In production, you would override ``pipeline_factory`` on the trigger
    to inject real portfolio state from your broker APIs.
    """
    from parrot.bots.agent import Agent  # pylint: disable=C0415
    from parrot.finance.execution import run_trading_pipeline  # pylint: disable=C0415
    from parrot.finance.schemas import (
        ExecutorConstraints,
        ConsensusLevel,
        PortfolioSnapshot,
    )  # pylint: disable=C0415

    # ── Portfolio snapshot ───────────────────────────────────────
    # TODO: Replace with real portfolio query from Alpaca + Binance
    portfolio = kwargs.get("portfolio") or PortfolioSnapshot(
        total_value_usd=10_000.0,
        cash_available_usd=10_000.0,
        exposure={},
        open_positions=[],
    )

    # ── Constraints ──────────────────────────────────────────────
    constraints = kwargs.get("constraints") or ExecutorConstraints(
        max_order_pct=2.0,
        max_order_value_usd=500.0,
        allowed_order_types=["limit"],
        max_daily_trades=10,
        max_daily_volume_usd=2000.0,
        max_positions=10,
        max_exposure_pct=70.0,
        max_asset_class_exposure_pct=40.0,
        min_consensus=ConsensusLevel.MAJORITY,
        max_daily_loss_pct=5.0,
        max_drawdown_pct=15.0,
    )

    # ── Write tools ──────────────────────────────────────────────
    stock_tools = kwargs.get("stock_tools")
    crypto_tools = kwargs.get("crypto_tools")

    if stock_tools is None:
        try:
            from parrot.finance.tools.alpaca_write import AlpacaWriteToolkit  # pylint: disable=C0415  # noqa
            stock_tools = AlpacaWriteToolkit().get_tools()
        except Exception as exc:
            print("AlpacaWriteToolkit not available: %s", exc)
            stock_tools = []

    if crypto_tools is None:
        try:
            from parrot.finance.tools.binance_write import BinanceWriteToolkit  # pylint: disable=C0415  # noqa
            crypto_tools = BinanceWriteToolkit().get_tools()
        except Exception as exc:
            print("BinanceWriteToolkit not available: %s", exc)
            crypto_tools = []

    # ── Run pipeline ─────────────────────────────────────────────
    return await run_trading_pipeline(
        agent_class=Agent,
        briefings=briefings,
        portfolio=portfolio,
        constraints=constraints,
        stock_tools=stock_tools,
        crypto_tools=crypto_tools,
    )
