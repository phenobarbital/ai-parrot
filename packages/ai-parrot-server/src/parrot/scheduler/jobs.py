"""Picklable APScheduler entrypoints for the agent scheduler (FEAT-631).

APScheduler persists a job's callable as a textual ``module:function`` reference.
A bound method of :class:`AgentSchedulerManager` cannot be persisted (it pickles the
manager, which holds the scheduler), so every job points at one of the module-level
coroutines below. They carry only ``str`` kwargs and resolve the live manager from a
process-local registry at fire time.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Final

if TYPE_CHECKING:
    from .manager import AgentSchedulerManager

logger = logging.getLogger("Parrot.Scheduler.jobs")


class _Skipped:
    """Type of :data:`SKIPPED`; a readable repr helps in logs."""

    def __repr__(self) -> str:
        return "<SKIPPED>"


SKIPPED: Final[object] = _Skipped()
"""Returned by a trampoline when a fire was intentionally skipped (row gone, disabled or
rescheduled). ``AgentSchedulerManager.job_success`` treats it as a no-op."""

_MANAGERS: Dict[str, "AgentSchedulerManager"] = {}


def register_manager(manager: "AgentSchedulerManager") -> None:
    """Register ``manager`` under ``manager.registered_name``; the last registration wins."""
    previous = _MANAGERS.get(manager.registered_name)
    if previous is not None and previous is not manager:
        logger.debug("Replacing registered AgentSchedulerManager named %r", manager.registered_name)
    _MANAGERS[manager.registered_name] = manager


def unregister_manager(name: str) -> None:
    """Remove the registration for ``name``; a missing name is not an error."""
    _MANAGERS.pop(name, None)


def get_manager(name: str) -> "AgentSchedulerManager":
    """Return the manager registered under ``name``.

    Raises:
        LookupError: no manager with that name is registered in this process.
    """
    try:
        return _MANAGERS[name]
    except KeyError as error:
        raise LookupError(f"No AgentSchedulerManager registered as {name!r} in this process") from error


async def run_db_schedule(manager_name: str, schedule_id: str, fingerprint: str) -> Any:
    """Entrypoint for DB-backed schedules (delegates to ``_run_db_schedule``)."""
    return await get_manager(manager_name)._run_db_schedule(schedule_id, fingerprint)


async def run_db_schedule_now(manager_name: str, schedule_id: str) -> Any:
    """Entrypoint for run-now one-shots; always releases the cross-worker run-now guard."""
    manager = get_manager(manager_name)
    try:
        return await manager._run_db_schedule(schedule_id, None, run_now=True)
    finally:
        await manager._fire_coordinator.release_running(str(schedule_id))


async def run_auto_schedule(manager_name: str, job_id: str) -> Any:
    """Entrypoint for decorator-registered ``auto_*`` jobs (delegates to ``_run_auto_task``)."""
    return await get_manager(manager_name)._run_auto_task(job_id)
