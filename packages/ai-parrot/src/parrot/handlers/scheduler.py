"""REST handlers for Parrot scheduler management."""
from __future__ import annotations

from typing import Any, Dict, Optional

from aiohttp import web
from navconfig.logging import logging
from navigator.views import BaseHandler, BaseView

from ..scheduler import ScheduleType
from ..scheduler.functions import list_supported_callbacks


class SchedulerCatalogHelper(BaseHandler):
    """Helper for scheduler metadata exposed through REST endpoints."""

    @staticmethod
    def list_schedule_types() -> list[str]:
        return [member.value for member in ScheduleType]

    @staticmethod
    def list_scheduler_types(app: web.Application) -> list[str]:
        manager = app.get("scheduler_manager")
        if manager is None:
            return ["default"]
        return sorted(manager.scheduler._jobstores.keys())  # pylint: disable=protected-access

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
                "scheduler_types": self.helper.list_scheduler_types(self.request.app),
            }
        )


class SchedulerJobsHandler(BaseView):
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

    def _error_response(self, message: str, status: int = 400) -> web.Response:
        return self.json_response({"status": "error", "message": message}, status=status)

    async def get(self) -> web.Response:
        schedule_id = self.request.match_info.get("schedule_id")
        try:
            if schedule_id:
                schedule = await self.manager.get_schedule(schedule_id)
                return self.json_response({"status": "success", "schedule": self.manager._serialize_job(schedule)})  # pylint: disable=protected-access

            schedules = await self.manager.list_schedules()
            payload = [self.manager._serialize_job(schedule) for schedule in schedules]  # pylint: disable=protected-access
            return self.json_response({"status": "success", "count": len(payload), "schedules": payload})
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Scheduler GET failed: %s", exc, exc_info=True)
            return self._error_response(str(exc), status=500)

    async def post(self) -> web.Response:
        try:
            data = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            return self._error_response("Invalid JSON body", status=400)

        try:
            schedule = await self.manager.add_schedule(
                agent_name=data["agent_name"],
                schedule_type=data["schedule_type"],
                schedule_config=data["schedule_config"],
                prompt=data.get("prompt"),
                method_name=data.get("method_name"),
                created_by=data.get("created_by"),
                created_email=data.get("created_email"),
                metadata=data.get("metadata", {}),
                agent_id=data.get("agent_id"),
                is_crew=bool(data.get("is_crew", False)),
                send_result=data.get("send_result"),
                scheduler_type=data.get("scheduler_type", "default"),
                callbacks=data.get("callbacks", []),
            )
            return self.json_response({"status": "success", "schedule": self.manager._serialize_job(schedule)}, status=201)  # pylint: disable=protected-access
        except KeyError as exc:
            return self._error_response(f"Missing required field: {exc.args[0]}", status=400)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Scheduler POST failed: %s", exc, exc_info=True)
            return self._error_response(str(exc), status=500)

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
            else:
                schedule = await self.manager.update_schedule(schedule_id, payload)
            return self.json_response({"status": "success", "schedule": self.manager._serialize_job(schedule)})  # pylint: disable=protected-access
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Scheduler PATCH failed: %s", exc, exc_info=True)
            return self._error_response(str(exc), status=500)

    async def delete(self) -> web.Response:
        schedule_id = self.request.match_info.get("schedule_id")
        if not schedule_id:
            return self._error_response("schedule_id required", status=400)
        try:
            await self.manager.delete_schedule(schedule_id)
            return self.json_response({"status": "success", "message": f"Schedule {schedule_id} deleted"})
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Scheduler DELETE failed: %s", exc, exc_info=True)
            return self._error_response(str(exc), status=500)
