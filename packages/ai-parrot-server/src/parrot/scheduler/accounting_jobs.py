"""Daily live validation of accounting models (FEAT-713 M9). The host registers it on its scheduler."""

from __future__ import annotations

import logging
from typing import Any, Callable

from parrot.scheduler.base import ScheduleType, SchedulerManager
from parrot.scheduler.manager import schedule


class AccountingValidationJobs:
    """Scheduler target; the factory must return the SAME toolkit instance that serves queries."""

    def __init__(self, toolkit_factory: Callable[[], Any]) -> None:
        self.toolkit_factory = toolkit_factory
        self.logger = logging.getLogger(__name__)

    @schedule(ScheduleType.DAILY, hour=6, minute=0)
    async def validate_accounting_models(self) -> dict:
        """Run live validation on the served toolkit and return the report as a dict.

        Lazily imports ``parrot.semantic.accounting.live`` so the server imports
        without ``ai-parrot-semantic`` installed.
        """
        from parrot.semantic.accounting.live import run_live_validation

        report = await run_live_validation(self.toolkit_factory())
        models = getattr(report, "models", ())
        failures = sum(1 for status in models if getattr(status, "error", None))
        self.logger.info("accounting live validation finished: models=%d failures=%d", len(models), failures)
        return report.model_dump(mode="json")


def register_accounting_schedules(scheduler: SchedulerManager, toolkit_factory: Callable[[], Any]) -> int:
    """Register the daily accounting validation job on *scheduler*.

    Args:
        scheduler: The host's scheduler manager.
        toolkit_factory: Returns the toolkit instance that serves queries.

    Returns:
        Number of jobs registered.
    """
    return scheduler.register_object_schedules(AccountingValidationJobs(toolkit_factory), "accounting")
