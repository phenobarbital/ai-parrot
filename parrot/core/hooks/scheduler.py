"""Scheduler hook — periodic agent triggers via APScheduler.

APScheduler is an optional dependency — install with: pip install ai-parrot[scheduler]
"""
from __future__ import annotations
from typing import Optional

from parrot._imports import lazy_import

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
        # Lazy-import AsyncIOScheduler (optional dep: pip install ai-parrot[scheduler])
        _sched = lazy_import(
            "apscheduler.schedulers.asyncio", package_name="apscheduler", extra="scheduler"
        )
        self._scheduler = _sched.AsyncIOScheduler()

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

    def _build_trigger(self) -> Optional[object]:
        _cron = lazy_import(
            "apscheduler.triggers.cron", package_name="apscheduler", extra="scheduler"
        )
        _interval = lazy_import(
            "apscheduler.triggers.interval", package_name="apscheduler", extra="scheduler"
        )
        if self._config.cron_expression:
            return _cron.CronTrigger.from_crontab(self._config.cron_expression)
        if self._config.interval_seconds:
            return _interval.IntervalTrigger(seconds=self._config.interval_seconds)
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
