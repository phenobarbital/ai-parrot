"""Handler tests for the target-agnostic scheduler HTTP surface."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from asyncdb.exceptions import NoDataFound

from parrot.handlers.scheduler import SchedulerJobsHandler, SchedulerLastResultHandler
from parrot.scheduler.base import NotEditableError, SchedulerUnavailableError
from parrot.scheduler.models import RunState


def _handler(handler_class, app: web.Application, match_info: dict | None = None):
    """Build a handler with the request and response methods under test."""
    handler = handler_class.__new__(handler_class)
    handler.logger = MagicMock()
    handler._request = MagicMock()
    handler.request.app = app
    handler.request.match_info = match_info or {}
    handler.json_response = MagicMock(
        side_effect=lambda data, **kwargs: SimpleNamespace(body=data, status=kwargs.get("status", 200))
    )
    return handler


def _app(manager) -> web.Application:
    """Create an application carrying the scheduler manager dependency."""
    app = web.Application()
    app["scheduler_manager"] = manager
    return app


@pytest.mark.asyncio
async def test_post_rejects_legacy_fields():
    """Legacy scheduler payload keys are rejected before manager dispatch."""
    manager = MagicMock()
    handler = _handler(SchedulerJobsHandler, _app(manager))
    handler.request.json = AsyncMock(
        return_value={
            "target_kind": "service",
            "target_name": "reports",
            "schedule_type": "daily",
            "schedule_config": {},
            "agent_name": "legacy",
        }
    )

    response = await handler.post()

    assert response.status == 400
    assert response.body["message"] == "unknown field: agent_name"
    manager.add_schedule.assert_not_called()


@pytest.mark.asyncio
async def test_post_redis_backend_without_jobstore_503():
    """Unavailable scheduler backends map to HTTP 503."""
    manager = MagicMock()
    manager.add_schedule = AsyncMock(side_effect=SchedulerUnavailableError("Redis unavailable"))
    manager._serialize_job = MagicMock()
    handler = _handler(SchedulerJobsHandler, _app(manager))
    handler.request.json = AsyncMock(
        return_value={
            "target_kind": "service",
            "target_name": "reports",
            "schedule_type": "daily",
            "schedule_config": {},
            "backend": "redis",
        }
    )

    response = await handler.post()

    assert response.status == 503


@pytest.mark.asyncio
async def test_patch_code_job_update_409():
    """Code-declared jobs cannot be edited through the HTTP surface."""
    manager = MagicMock()
    manager.update_schedule = AsyncMock(side_effect=NotEditableError("code-declared schedules cannot be edited"))
    handler = _handler(SchedulerJobsHandler, _app(manager), {"schedule_id": "code-job"})
    handler.request.json = AsyncMock(return_value={"schedule_type": "daily"})

    response = await handler.patch()

    assert response.status == 409


@pytest.mark.asyncio
async def test_get_unknown_404():
    """Unknown schedule ids map the manager's not-found error to HTTP 404."""
    manager = MagicMock()
    manager._locate = AsyncMock(side_effect=NoDataFound("missing"))
    handler = _handler(SchedulerJobsHandler, _app(manager), {"schedule_id": "missing"})

    response = await handler.get()

    assert response.status == 404


@pytest.mark.asyncio
async def test_last_result_from_run_state():
    """Last-result responses contain JSON-mode RunState timestamps and fields."""
    manager = MagicMock()
    manager.get_last_result = AsyncMock(
        return_value=RunState(
            schedule_id="job-1",
            backend="db",
            enabled=True,
            last_error_at="2026-10-08T10:00:00+00:00",
            consecutive_failures=2,
        )
    )
    handler = _handler(SchedulerLastResultHandler, _app(manager), {"schedule_id": "job-1"})

    response = await handler.get()

    assert response.status == 200
    assert response.body["status"] == "success"
    assert response.body["last_error_at"] == "2026-10-08T10:00:00+00:00"
    assert response.body["consecutive_failures"] == 2
