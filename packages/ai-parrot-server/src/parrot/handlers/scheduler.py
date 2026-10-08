"""REST handlers for Parrot scheduler management."""

from __future__ import annotations

from typing import Any

from aiohttp import web
from asyncdb.exceptions import NoDataFound
from navconfig.logging import logging
from navigator.views import BaseHandler, BaseView

from ..scheduler import ScheduleType
from ..scheduler.functions import list_supported_callbacks
from ..scheduler.base import (
    NotEditableError,
    SchedulerRunNowConflictError,
    SchedulerUnavailableError,
    TargetMissingError,
)
from ..scheduler.sanitize import SchedulerConfigError

_POST_REQUIRED = frozenset({"target_kind", "target_name", "schedule_type", "schedule_config"})
_POST_OPTIONAL = (
    "backend",
    "target_id",
    "tenant",
    "prompt",
    "method_name",
    "created_by",
    "created_email",
    "metadata",
    "send_result",
    "callbacks",
    "misfire_grace_time",
)
_POST_FIELDS = _POST_REQUIRED | frozenset(_POST_OPTIONAL)


class _SchedulerErrorMixin:
    """Translate scheduler exceptions into the REST API error contract."""

    def _error_response(self, message: str, status: int = 400) -> web.Response:
        return self.json_response({"status": "error", "message": message}, status=status)

    def _map_error(self, exc: Exception) -> web.Response:
        """Return the HTTP response for a typed scheduler failure."""
        if isinstance(exc, (NoDataFound, TargetMissingError)):
            status = 404
        elif isinstance(exc, (NotEditableError, SchedulerRunNowConflictError)):
            status = 409
        elif isinstance(exc, SchedulerUnavailableError):
            status = 503
        elif isinstance(exc, (SchedulerConfigError, ValueError)):
            status = 400
        else:
            self.logger.error("Scheduler request failed: %s", exc, exc_info=True)
            status = 500
        return self._error_response(str(exc), status=status)


class SchedulerCatalogHelper(BaseHandler):
    """Helper for scheduler metadata exposed through REST endpoints."""

    @staticmethod
    def list_schedule_types() -> list[str]:
        return [member.value for member in ScheduleType]

    @staticmethod
    def list_backends(app: web.Application) -> list[str]:
        manager = app.get("scheduler_manager")
        backends = ["db"]
        scheduler = getattr(manager, "scheduler", None) if manager is not None else None
        if scheduler is not None and "redis" in getattr(
            scheduler, "_jobstores", {}
        ):  # pylint: disable=protected-access
            backends.append("redis")
        return backends

    @staticmethod
    def list_callbacks() -> list[dict[str, Any]]:
        return list_supported_callbacks()


class SchedulerCallbacksHandler(BaseView):
    """List supported scheduler callbacks and scheduler types."""

    _logger_name = "Parrot.SchedulerCallbacksHandler"

    def post_init(self, *args, **kwargs):
        self.logger = logging.getLogger(self._logger_name)
        self.helper = SchedulerCatalogHelper()

    async def get(self) -> web.Response:
        return self.json_response(
            {
                "callbacks": self.helper.list_callbacks(),
                "schedule_types": self.helper.list_schedule_types(),
                "backends": self.helper.list_backends(self.request.app),
            }
        )


class SchedulerJobsHandler(_SchedulerErrorMixin, BaseView):
    """CRUD handler for scheduler jobs persisted in APScheduler and Postgres."""

    _logger_name = "Parrot.SchedulerJobsHandler"

    def post_init(self, *args, **kwargs):
        self.logger = logging.getLogger(self._logger_name)

    @property
    def manager(self):
        manager = self.request.app.get("scheduler_manager")
        if manager is None:
            raise RuntimeError("scheduler_manager is not configured in app")
        return manager

    async def get(self) -> web.Response:
        schedule_id = self.request.match_info.get("schedule_id")
        try:
            if schedule_id:
                source, definition, job = await self.manager._locate(schedule_id)  # pylint: disable=protected-access
                entry = self.manager._serialize_job(definition, job, source=source)  # pylint: disable=protected-access
                return self.json_response({"status": "success", "schedule": entry})

            payload = await self.manager.list_jobs()
            return self.json_response({"status": "success", "count": len(payload), "schedules": payload})
        except Exception as exc:  # pylint: disable=broad-except
            return self._map_error(exc)

    async def post(self) -> web.Response:
        try:
            data = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            return self._error_response("Invalid JSON body", status=400)

        try:
            unknown = sorted(set(data) - _POST_FIELDS)
            if unknown:
                return self._error_response(f"unknown field: {unknown[0]}", status=400)
            schedule = await self.manager.add_schedule(
                data["target_kind"],
                data["target_name"],
                data["schedule_type"],
                data["schedule_config"],
                **{key: data[key] for key in _POST_OPTIONAL if key in data},
            )
            return self.json_response(
                {"status": "success", "schedule": self.manager._serialize_job(schedule, source=schedule.backend)},
                status=201,
            )  # pylint: disable=protected-access
        except KeyError as exc:
            return self._error_response(f"Missing required field: {exc.args[0]}", status=400)
        except Exception as exc:  # pylint: disable=broad-except
            return self._map_error(exc)

    async def patch(self) -> web.Response:
        schedule_id = self.request.match_info.get("schedule_id")
        if not schedule_id:
            return self._error_response("schedule_id required", status=400)
        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            return self._error_response("Invalid JSON body", status=400)

        action = str(payload.get("action", "update")).lower()
        try:
            if action == "pause":
                schedule = await self.manager.pause_schedule(schedule_id)
            elif action == "resume":
                schedule = await self.manager.update_schedule(schedule_id, {"enabled": True})
            elif action == "run_now":
                # FEAT-467 TASK-2520: trigger one immediate, out-of-band
                # execution WITHOUT touching schedule_config/enabled/trigger.
                schedule = await self.manager.run_schedule_now(schedule_id)
            else:
                schedule = await self.manager.update_schedule(schedule_id, payload)
            return self.json_response(
                {"status": "success", "schedule": self.manager._serialize_job(schedule, source=schedule.backend)}
            )  # pylint: disable=protected-access
        except Exception as exc:  # pylint: disable=broad-except
            return self._map_error(exc)

    async def delete(self) -> web.Response:
        schedule_id = self.request.match_info.get("schedule_id")
        if not schedule_id:
            return self._error_response("schedule_id required", status=400)
        try:
            await self.manager.delete_schedule(schedule_id)
            return self.json_response({"status": "success", "message": f"Schedule {schedule_id} deleted"})
        except Exception as exc:  # pylint: disable=broad-except
            return self._map_error(exc)


class SchedulerLastResultHandler(_SchedulerErrorMixin, BaseView):
    """``GET /api/v1/parrot/scheduler/schedules/{schedule_id}/last-result``.

    Read-only view of a schedule's last execution: ``last_run``,
    ``next_run``, ``run_count``, and the result/error metadata stamped
    by :meth:`AgentSchedulerManager._update_schedule_run` (FEAT-467
    TASK-2520) — populated after either a normally scheduled run or a
    ``PATCH action="run_now"`` (both go through the same completion
    path, so this endpoint reflects whichever ran most recently).
    """

    _logger_name = "Parrot.SchedulerLastResultHandler"

    def post_init(self, *args, **kwargs):
        self.logger = logging.getLogger(self._logger_name)

    @property
    def manager(self):
        manager = self.request.app.get("scheduler_manager")
        if manager is None:
            raise RuntimeError("scheduler_manager is not configured in app")
        return manager

    async def get(self) -> web.Response:
        schedule_id = self.request.match_info.get("schedule_id")
        if not schedule_id:
            return self._error_response("schedule_id required", status=400)
        try:
            result = await self.manager.get_last_result(schedule_id)
            return self.json_response({"status": "success", **result.model_dump(mode="json")})
        except Exception as exc:  # pylint: disable=broad-except
            return self._map_error(exc)
