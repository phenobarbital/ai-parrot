"""Heartbeat scheduler for periodic agent wake-ups.

APScheduler is an optional dependency — install with: pip install ai-parrot[scheduler]
"""
from __future__ import annotations
import asyncio
from typing import Callable, Coroutine, Optional

from navconfig.logging import logging
from parrot._imports import lazy_import

from .models import AgentTask, DeliveryConfig, HeartbeatConfig, TaskPriority


class HeartbeatScheduler:
    """Schedules periodic agent heartbeats via APScheduler.

    On each trigger, creates an ``AgentTask`` and submits it via the
    provided callback (typically ``AgentService.submit_task``).

    Requires ``pip install ai-parrot[scheduler]``.
    """

    def __init__(
        self,
        task_callback: Callable[[AgentTask], Coroutine],
    ):
        # Lazy-import AsyncIOScheduler (optional dep: pip install ai-parrot[scheduler])
        _sched = lazy_import(
            "apscheduler.schedulers.asyncio", package_name="apscheduler", extra="scheduler"
        )
        self._scheduler = _sched.AsyncIOScheduler()
        self._task_callback = task_callback
        self._configs: dict[str, HeartbeatConfig] = {}
        self.logger = logging.getLogger("parrot.services.heartbeat")

    def register(self, config: HeartbeatConfig) -> Optional[str]:
        """Register a heartbeat for an agent.

        Args:
            config: Heartbeat configuration with cron or interval.

        Returns:
            APScheduler job ID, or None if config is disabled.
        """
        if not config.enabled:
            self.logger.debug(f"Heartbeat disabled for {config.agent_name}")
            return None

        _cron = lazy_import(
            "apscheduler.triggers.cron", package_name="apscheduler", extra="scheduler"
        )
        _interval = lazy_import(
            "apscheduler.triggers.interval", package_name="apscheduler", extra="scheduler"
        )

        # Build trigger
        if config.cron_expression:
            trigger = _cron.CronTrigger.from_crontab(config.cron_expression)
            trigger_desc = f"cron={config.cron_expression}"
        elif config.interval_seconds:
            trigger = _interval.IntervalTrigger(seconds=config.interval_seconds)
            trigger_desc = f"interval={config.interval_seconds}s"
        else:
            self.logger.warning(
                f"Heartbeat for {config.agent_name} has no cron or interval"
            )
            return None

        job_id = f"heartbeat_{config.agent_name}"

        self._scheduler.add_job(
            self._fire_heartbeat,
            trigger=trigger,
            id=job_id,
            name=f"Heartbeat: {config.agent_name}",
            kwargs={"config": config},
            replace_existing=True,
        )

        self._configs[config.agent_name] = config
        self.logger.info(
            f"Registered heartbeat for '{config.agent_name}' ({trigger_desc})"
        )
        return job_id

    async def _fire_heartbeat(self, config: HeartbeatConfig) -> None:
        """Create and submit a heartbeat task."""
        task = AgentTask(
            agent_name=config.agent_name,
            prompt=config.prompt_template,
            priority=TaskPriority.LOW,
            delivery=config.delivery or DeliveryConfig(),
            metadata={
                "source": "heartbeat",
                "agent_name": config.agent_name,
                **config.metadata,
            },
        )
        self.logger.debug(
            f"Heartbeat fired for '{config.agent_name}' → task {task.task_id}"
        )
        try:
            await self._task_callback(task)
        except Exception as exc:
            self.logger.error(
                f"Heartbeat callback failed for {config.agent_name}: {exc}"
            )

    def start(self) -> None:
        """Start the APScheduler."""
        if self._configs:
            self._scheduler.start()
            self.logger.info(
                f"Heartbeat scheduler started with {len(self._configs)} heartbeat(s)"
            )
        else:
            self.logger.debug("No heartbeats registered, scheduler not started")

    def stop(self) -> None:
        """Stop the APScheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            self.logger.info("Heartbeat scheduler stopped")

    @property
    def registered_count(self) -> int:
        """Number of registered heartbeats."""
        return len(self._configs)
