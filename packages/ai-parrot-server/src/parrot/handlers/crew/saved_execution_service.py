"""SavedExecutionService — orchestration layer for execution history,
replay, and scheduling (FEAT-307).

Framework-agnostic: does NOT import aiohttp or any HTTP concern. The HTTP
handler (``CrewExecutionHistoryHandler``) is responsible for translating the
exceptions raised here into HTTP responses.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from navconfig.logging import logging

from parrot.bots.flows.core.storage.backends.base import ResultStorage
from parrot.handlers.crew.models import ExecutionFilter, ScheduleRequest

# Method-to-parameter mapping for replay (FEAT-307).
#
# NOTE: corrected against the verified ``AgentCrew`` signatures (TASK-1771)
# rather than the original task contract, which had two stale entries:
# ``run_loop``'s persisted-query parameter is ``initial_task`` (not
# ``query``), and ``run``'s parameter is ``task`` (not ``prompt``).
METHOD_PARAM_MAP: dict[str, str] = {
    "run_sequential": "query",
    "run_loop": "initial_task",
    "run_flow": "initial_task",
    "run_parallel": "tasks",  # special-cased in replay_execution — see below
    "run": "task",
    "ask": "question",
}

# run_loop requires a `condition` positional argument that is never
# persisted (ResultStorage documents have no such field) — replay of
# run_loop executions is not supported. Documented in the Completion Note.
_UNSUPPORTED_REPLAY_METHODS = frozenset(("run_loop",))


class SavedExecutionError(ValueError):
    """Base exception for SavedExecutionService errors.

    Subclasses ``ValueError`` for backward compatibility with existing
    ``except ValueError`` callers/tests, while giving the HTTP handler a
    typed hierarchy to map to status codes instead of fragile substring
    matching on the exception message.
    """


class ExecutionNotFoundError(SavedExecutionError):
    """The requested execution record doesn't exist (or isn't owned by the
    caller — ownership failures are indistinguishable from "not found" by
    design, to avoid leaking the existence of other tenants'/users' records).
    """


class CrewNotFoundError(SavedExecutionError):
    """The crew referenced by a saved execution no longer exists (or no
    ``bot_manager`` is configured to resolve it)."""


class ReplayValidationError(SavedExecutionError):
    """The replay/schedule request fails validation for reasons other than
    "not found" (missing prompt, unsupported method, unknown method)."""


class SchedulerUnavailableError(SavedExecutionError):
    """No ``scheduler_manager`` is configured on the service."""


class SavedExecutionService:
    """Orchestration layer for execution history, replay, and scheduling.

    Thin coordination layer between the HTTP handler and the storage /
    bot-manager / scheduler-manager backends. Contains no HTTP-specific
    logic — callers (handlers) translate raised exceptions into responses.

    Attributes:
        storage: The ``ResultStorage`` backend used for read/delete.
        bot_manager: Resolves crews by name/id for replay (``get_crew()``).
        scheduler_manager: Creates APScheduler jobs for scheduling.
    """

    def __init__(
        self,
        storage: ResultStorage,
        bot_manager: Any = None,
        scheduler_manager: Any = None,
    ) -> None:
        """Initialise the service.

        Args:
            storage: The ``ResultStorage`` backend to read/delete executions.
            bot_manager: Object exposing ``async def get_crew(identifier,
                as_new=False, tenant=None) -> tuple[AgentCrew | None,
                CrewDefinition | None]``.
            scheduler_manager: Object exposing ``AgentSchedulerManager
                .add_schedule()``.
        """
        self.storage = storage
        self.bot_manager = bot_manager
        self.scheduler_manager = scheduler_manager
        self.logger = logging.getLogger("parrot.SavedExecutionService")
        self._collection = "crew_executions"

    async def list_executions(
        self,
        tenant: str,
        user_id: str,
        filters: Optional[ExecutionFilter] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """List saved executions for a tenant/user, with optional filters.

        Args:
            tenant: Tenant identifier — always enforced as a storage filter.
            user_id: User identifier — always enforced as a storage filter.
            filters: Optional additional filters (crew_name, method, date range).
            limit: Maximum number of items to return.
            offset: Number of items to skip (pagination).

        Returns:
            A tuple of ``(items, total)``.
        """
        storage_filters: dict[str, Any] = {"tenant": tenant, "user_id": user_id}
        if filters is not None:
            storage_filters.update(filters.model_dump(exclude_none=True))

        items = await self.storage.list(self._collection, storage_filters, limit, offset)
        total = await self.storage.count(self._collection, storage_filters)
        return items, total

    async def get_execution(
        self,
        tenant: str,
        user_id: str,
        execution_id: str,
    ) -> Optional[dict]:
        """Retrieve a single saved execution by id.

        Args:
            tenant: Tenant identifier.
            user_id: User identifier.
            execution_id: Storage-layer record id.

        Returns:
            The execution document if found AND it belongs to the given
            tenant/user, ``None`` otherwise.

        Note:
            The current ``ResultStorage.get()`` signature (TASK-1765) takes
            only ``record_id`` — it has no ``tenant``/``user_id`` parameters.
            Ownership is therefore verified here, in the service layer,
            after the fetch. See TASK-1768's Completion Note for the same
            documented limitation at the storage layer.
        """
        record = await self.storage.get(self._collection, execution_id)
        if not record:
            return None
        if not self._belongs_to(record, tenant, user_id):
            return None
        return record

    async def replay_execution(
        self,
        tenant: str,
        user_id: str,
        execution_id: str,
    ) -> dict:
        """Re-run a saved execution's prompt against the crew's current config.

        Args:
            tenant: Tenant identifier.
            user_id: User identifier.
            execution_id: Storage-layer record id of the execution to replay.

        Returns:
            A job dict: ``{"job_id", "crew_name", "method", "status", "result"}``.

        Raises:
            ExecutionNotFoundError: If the execution is not found (or not
                owned by ``tenant``/``user_id``).
            ReplayValidationError: If the original prompt is unavailable or
                the saved method cannot be replayed (see
                ``_UNSUPPORTED_REPLAY_METHODS``).
            CrewNotFoundError: If the crew no longer exists (or no
                ``bot_manager`` is configured).
        """
        record = await self.get_execution(tenant, user_id, execution_id)
        if not record:
            raise ExecutionNotFoundError(f"Execution {execution_id} not found")

        prompt = record.get("prompt")
        if not prompt:
            raise ReplayValidationError("Cannot replay: original prompt not available")

        crew_name = record["crew_name"]
        method_name = record.get("method") or "run_sequential"

        if method_name in _UNSUPPORTED_REPLAY_METHODS:
            raise ReplayValidationError(
                f"Cannot replay method '{method_name}': required parameters "
                "for this method are not persisted with the execution"
            )
        if method_name not in METHOD_PARAM_MAP:
            raise ReplayValidationError(f"Unknown replay method '{method_name}'")

        if self.bot_manager is None:
            raise CrewNotFoundError(f"Crew '{crew_name}' no longer exists")

        crew, crew_def = await self.bot_manager.get_crew(
            crew_name, as_new=True, tenant=tenant
        )
        if not crew or not crew_def:
            raise CrewNotFoundError(f"Crew '{crew_name}' no longer exists")

        method = getattr(crew, method_name, None)
        if method is None:
            raise CrewNotFoundError(
                f"Crew '{crew_name}' no longer supports method '{method_name}'"
            )

        if method_name == "run_parallel":
            # The saved `prompt` is a single string (the first task's query
            # at save time — see TASK-1771), not the original multi-agent
            # task list. Best-effort reconstruction: broadcast the saved
            # prompt to every agent currently on the crew.
            tasks = [
                {"agent_id": agent_id, "query": prompt}
                for agent_id in crew.agents
            ]
            result = await method(tasks=tasks, user_id=user_id)
        else:
            param_name = METHOD_PARAM_MAP[method_name]
            result = await method(**{param_name: prompt}, user_id=user_id)

        return {
            "job_id": str(uuid.uuid4()),
            "crew_name": crew_name,
            "method": method_name,
            "status": "submitted",
            "result": (
                result.to_dict() if hasattr(result, "to_dict") else str(result)
            ),
        }

    async def schedule_execution(
        self,
        tenant: str,
        user_id: str,
        execution_id: str,
        schedule_config: ScheduleRequest,
    ) -> dict:
        """Create a recurring/one-off schedule from a saved execution.

        Args:
            tenant: Tenant identifier.
            user_id: User identifier.
            execution_id: Storage-layer record id of the execution to schedule.
            schedule_config: Schedule type + config + metadata.

        Returns:
            The created ``AgentSchedule`` serialised via ``.to_dict()``.

        Raises:
            ExecutionNotFoundError: If the execution is not found (or not
                owned by ``tenant``/``user_id``).
            ReplayValidationError: If the original prompt is unavailable.
            SchedulerUnavailableError: If no scheduler manager is configured.
        """
        record = await self.get_execution(tenant, user_id, execution_id)
        if not record:
            raise ExecutionNotFoundError(f"Execution {execution_id} not found")

        prompt = record.get("prompt")
        if not prompt:
            raise ReplayValidationError("Cannot schedule: original prompt not available")

        if self.scheduler_manager is None:
            raise SchedulerUnavailableError("No scheduler manager configured")

        crew_name = record["crew_name"]
        method_name = record.get("method") or "run_sequential"

        schedule = await self.scheduler_manager.add_schedule(
            crew_name,
            schedule_config.schedule_type,
            schedule_config.schedule_config,
            prompt=prompt,
            method_name=method_name,
            created_by=schedule_config.created_by,
            created_email=schedule_config.created_email,
            metadata=schedule_config.metadata,
            is_crew=True,
            callbacks=schedule_config.callbacks,
        )
        return schedule.to_dict() if hasattr(schedule, "to_dict") else schedule

    async def delete_execution(
        self,
        tenant: str,
        user_id: str,
        execution_id: str,
    ) -> bool:
        """Delete a saved execution.

        Args:
            tenant: Tenant identifier.
            user_id: User identifier.
            execution_id: Storage-layer record id.

        Returns:
            ``True`` if a record belonging to this tenant/user was deleted,
            ``False`` otherwise.

        Note:
            Same ownership-verification approach as :meth:`get_execution` —
            ``ResultStorage.delete()`` has no ``tenant``/``user_id``
            parameters, so ownership is checked here before deleting.
        """
        record = await self.get_execution(tenant, user_id, execution_id)
        if not record:
            return False
        return await self.storage.delete(self._collection, execution_id)

    @staticmethod
    def _belongs_to(record: dict, tenant: str, user_id: str) -> bool:
        """Check that *record* belongs to the given tenant/user.

        Legacy records with no ``tenant`` field are treated as ``"global"``
        (matching the storage backends' COALESCE-equivalent behaviour).

        Args:
            record: The execution document fetched from storage.
            tenant: Expected tenant.
            user_id: Expected user id.

        Returns:
            ``True`` if the record's tenant/user_id match.
        """
        record_tenant = record.get("tenant") or "global"
        return record_tenant == tenant and record.get("user_id") == user_id
