"""Heartbeat scheduler for periodic agent wake-ups."""
import asyncio
from typing import Callable, Coroutine, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from navconfig.logging import logging

from .models import AgentTask, DeliveryConfig, HeartbeatConfig, TaskPriority


class HeartbeatScheduler:
    """Schedules periodic agent heartbeats via APScheduler.

    On each trigger, creates an ``AgentTask`` and submits it via the
    provided callback (typically ``AgentService.submit_task``).
    """

    def __init__(
        self,
        task_callback: Callable[[AgentTask], Coroutine],
    ):
        self._scheduler = AsyncIOScheduler()
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

        # Build trigger
        if config.cron_expression:
            trigger = CronTrigger.from_crontab(config.cron_expression)
            trigger_desc = f"cron={config.cron_expression}"
        elif config.interval_seconds:
            trigger = IntervalTrigger(seconds=config.interval_seconds)
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
