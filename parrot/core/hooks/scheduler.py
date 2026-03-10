"""Scheduler hook — periodic agent triggers via APScheduler."""
import asyncio
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .base import BaseHook
from .models import HookType, SchedulerHookConfig


class SchedulerHook(BaseHook):
    """Periodically fires events using APScheduler (cron or interval)."""

    hook_type = HookType.SCHEDULER

    def __init__(self, config: SchedulerHookConfig, **kwargs) -> None:
        super().__init__(
            name=config.name,
            enabled=config.enabled,
            target_type=config.target_type,
            target_id=config.target_id,
            metadata=config.metadata,
            **kwargs,
        )
        self._config = config
        self._scheduler = AsyncIOScheduler()

    async def start(self) -> None:
        trigger = self._build_trigger()
        if trigger is None:
            self.logger.warning(
                f"SchedulerHook '{self.name}': no cron or interval configured"
            )
            return

        self._scheduler.add_job(
            self._fire,
            trigger=trigger,
            id=f"hook_{self.hook_id}",
            name=f"Hook: {self.name}",
            replace_existing=True,
        )
        self._scheduler.start()
        self.logger.info(f"SchedulerHook '{self.name}' started")

    async def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            self.logger.info(f"SchedulerHook '{self.name}' stopped")

    def _build_trigger(self) -> Optional[CronTrigger | IntervalTrigger]:
        if self._config.cron_expression:
            return CronTrigger.from_crontab(self._config.cron_expression)
        if self._config.interval_seconds:
            return IntervalTrigger(seconds=self._config.interval_seconds)
        return None

    async def _fire(self) -> None:
        event = self._make_event(
            event_type="heartbeat",
            payload={
                "prompt_template": self._config.prompt_template,
            },
            task=self._config.prompt_template,
        )
        await self.on_event(event)
