"""Unit tests for CrewExecutionHistoryHandler (FEAT-307)."""
import json
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from navigator.views.base import JSONContent

from parrot.handlers.crew.execution_history_handler import CrewExecutionHistoryHandler


def _make_handler(
    method: str = "GET",
    path: str = "/api/v1/crew/executions",
    match_info: Optional[Dict[str, str]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    query: Optional[Dict[str, str]] = None,
    service=None,
) -> CrewExecutionHistoryHandler:
    """Create a CrewExecutionHistoryHandler with a mocked request + service."""
    full_path = path
    if query:
        qs = "&".join(f"{k}={v}" for k, v in query.items())
        full_path = f"{path}?{qs}"

    request = make_mocked_request(
        method,
        full_path,
        match_info=match_info or {},
    )
    if json_body is not None:
        request.json = AsyncMock(return_value=json_body)
    elif method == "POST":
        request.json = AsyncMock(return_value={})

    handler = CrewExecutionHistoryHandler.__new__(CrewExecutionHistoryHandler)
    # `request` is a read-only property (aiohttp.abc.AbstractView.request)
    # backed by `_request` — only the private attribute is settable.
    handler._request = request
    handler.logger = MagicMock()
    # BaseView.error() needs `_json` (normally set in BaseHandler.__init__,
    # skipped here since we bypass __init__ via __new__).
    handler._json = JSONContent()
    handler._service = service if service is not None else AsyncMock()
    return handler


def _parse_body(resp: web.Response) -> dict:
    return json.loads(resp.body)


async def _call(coro):
    """Call a handler coroutine, normalizing BaseView.error()'s raised
    HTTPException into a returned response (HTTPException is itself a
    web.Response subclass, matching aiohttp's own dispatch convention)."""
    try:
        return await coro
    except web.HTTPException as exc:
        return exc


class TestCrewExecutionHistoryHandler:
    @pytest.mark.asyncio
    async def test_list_executions(self):
        """GET / returns paginated list."""
        service = AsyncMock()
        service.list_executions.return_value = (
            [{"id": "abc", "crew_name": "test"}], 1
        )
        handler = _make_handler(method="GET", service=service)

        resp = await _call(handler.get())
        data = _parse_body(resp)

        assert resp.status == 200
        assert data["total"] == 1
        assert data["items"] == [{"id": "abc", "crew_name": "test"}]
        service.list_executions.assert_awaited_once()
        args = service.list_executions.await_args.args
        assert args[0] == "global"  # tenant defaults to global

    @pytest.mark.asyncio
    async def test_get_execution_detail(self):
        """GET /{id} returns full execution."""
        service = AsyncMock()
        service.get_execution.return_value = {"id": "abc", "crew_name": "test", "payload": {}}
        handler = _make_handler(
            method="GET",
            path="/api/v1/crew/executions/abc",
            match_info={"execution_id": "abc"},
            service=service,
        )

        resp = await _call(handler.get())
        data = _parse_body(resp)

        assert resp.status == 200
        assert data["id"] == "abc"
        service.get_execution.assert_awaited_once_with("global", None, "abc")

    @pytest.mark.asyncio
    async def test_get_not_found(self):
        """GET /{id} returns 404 for missing execution."""
        service = AsyncMock()
        service.get_execution.return_value = None
        handler = _make_handler(
            method="GET",
            path="/api/v1/crew/executions/missing",
            match_info={"execution_id": "missing"},
            service=service,
        )

        resp = await _call(handler.get())

        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_replay_success(self):
        """POST /{id}/replay triggers replay."""
        service = AsyncMock()
        service.replay_execution.return_value = {
            "job_id": "job-1", "crew_name": "test", "method": "run_sequential", "status": "submitted"
        }
        handler = _make_handler(
            method="POST",
            path="/api/v1/crew/executions/abc/replay",
            match_info={"execution_id": "abc", "action": "replay"},
            json_body={"tenant": "acme", "user_id": "u1"},
            service=service,
        )

        resp = await _call(handler.post())
        data = _parse_body(resp)

        assert resp.status == 200
        assert data["job_id"] == "job-1"
        service.replay_execution.assert_awaited_once_with("acme", "u1", "abc")

    @pytest.mark.asyncio
    async def test_replay_crew_not_found(self):
        """POST /{id}/replay returns 404 for deleted crew."""
        from parrot.handlers.crew.saved_execution_service import CrewNotFoundError

        service = AsyncMock()
        service.replay_execution.side_effect = CrewNotFoundError("Crew 'x' no longer exists")
        handler = _make_handler(
            method="POST",
            path="/api/v1/crew/executions/abc/replay",
            match_info={"execution_id": "abc", "action": "replay"},
            json_body={"tenant": "acme"},
            service=service,
        )

        resp = await _call(handler.post())

        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_replay_no_prompt(self):
        """POST /{id}/replay returns 400 for missing prompt."""
        from parrot.handlers.crew.saved_execution_service import ReplayValidationError

        service = AsyncMock()
        service.replay_execution.side_effect = ReplayValidationError(
            "Cannot replay: original prompt not available"
        )
        handler = _make_handler(
            method="POST",
            path="/api/v1/crew/executions/abc/replay",
            match_info={"execution_id": "abc", "action": "replay"},
            json_body={"tenant": "acme"},
            service=service,
        )

        resp = await _call(handler.post())

        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_schedule_success(self):
        """POST /{id}/schedule creates APScheduler job."""
        service = AsyncMock()
        service.schedule_execution.return_value = {"schedule_id": "sched-1"}
        handler = _make_handler(
            method="POST",
            path="/api/v1/crew/executions/abc/schedule",
            match_info={"execution_id": "abc", "action": "schedule"},
            json_body={
                "tenant": "acme",
                "schedule_type": "DAILY",
                "schedule_config": {"hour": 9, "minute": 0},
            },
            service=service,
        )

        resp = await _call(handler.post())
        data = _parse_body(resp)

        assert resp.status == 200
        assert data["schedule_id"] == "sched-1"
        service.schedule_execution.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_schedule_invalid_request_returns_400(self):
        """POST /{id}/schedule returns 400 when schedule_type/schedule_config missing."""
        service = AsyncMock()
        handler = _make_handler(
            method="POST",
            path="/api/v1/crew/executions/abc/schedule",
            match_info={"execution_id": "abc", "action": "schedule"},
            json_body={"tenant": "acme"},
            service=service,
        )

        resp = await _call(handler.post())

        assert resp.status == 400
        service.schedule_execution.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_post_missing_tenant_returns_400(self):
        """POST /{id}/{replay|schedule} rejects requests with no tenant (FEAT-307
        security fix: mutating actions must not silently default to 'global',
        matching CrewExecutionHandler.execute_crew()'s convention)."""
        service = AsyncMock()
        handler = _make_handler(
            method="POST",
            path="/api/v1/crew/executions/abc/replay",
            match_info={"execution_id": "abc", "action": "replay"},
            json_body={},
            service=service,
        )

        resp = await _call(handler.post())
        data = _parse_body(resp)

        assert resp.status == 400
        assert "tenant" in data["message"].lower()
        service.replay_execution.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_success(self):
        """DELETE /{id} removes execution."""
        service = AsyncMock()
        service.delete_execution.return_value = True
        handler = _make_handler(
            method="DELETE",
            path="/api/v1/crew/executions/abc",
            match_info={"execution_id": "abc"},
            query={"tenant": "acme"},
            service=service,
        )

        resp = await _call(handler.delete())
        data = _parse_body(resp)

        assert resp.status == 200
        assert data["deleted"] is True
        service.delete_execution.assert_awaited_once_with("acme", None, "abc")

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        """DELETE /{id} returns 404 for missing execution."""
        service = AsyncMock()
        service.delete_execution.return_value = False
        handler = _make_handler(
            method="DELETE",
            path="/api/v1/crew/executions/missing",
            match_info={"execution_id": "missing"},
            query={"tenant": "acme"},
            service=service,
        )

        resp = await _call(handler.delete())

        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_delete_missing_tenant_returns_400(self):
        """DELETE /{id} rejects requests with no tenant (same fix as POST)."""
        service = AsyncMock()
        handler = _make_handler(
            method="DELETE",
            path="/api/v1/crew/executions/abc",
            match_info={"execution_id": "abc"},
            service=service,
        )

        resp = await _call(handler.delete())

        assert resp.status == 400
        service.delete_execution.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_post_unknown_action_returns_400(self):
        """POST /{id}/{action} with an unrecognised action returns 400."""
        service = AsyncMock()
        handler = _make_handler(
            method="POST",
            path="/api/v1/crew/executions/abc/bogus",
            match_info={"execution_id": "abc", "action": "bogus"},
            json_body={"tenant": "acme"},
            service=service,
        )

        resp = await _call(handler.post())

        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_session_user_id_overrides_body_supplied_user_id(self, monkeypatch):
        """When an authenticated session is present, its user id is used
        instead of a client-supplied user_id — closes the IDOR gap where any
        caller could assert an arbitrary identity via the request body."""
        service = AsyncMock()
        service.list_executions.return_value = ([], 0)
        handler = _make_handler(
            method="GET",
            query={"tenant": "acme", "user_id": "attacker-supplied"},
            service=service,
        )
        monkeypatch.setattr(handler, "session", AsyncMock(return_value={"user_id": "real-session-user"}))
        monkeypatch.setattr(handler, "get_userid", AsyncMock(return_value="real-session-user"))

        await _call(handler.get())

        args = service.list_executions.await_args.args
        assert args[1] == "real-session-user"

    @pytest.mark.asyncio
    async def test_no_session_falls_back_to_body_user_id(self, monkeypatch):
        """When no session is available (no middleware configured / anonymous
        caller), the explicit user_id from the request is used as a fallback."""
        service = AsyncMock()
        service.list_executions.return_value = ([], 0)
        handler = _make_handler(
            method="GET",
            query={"tenant": "acme", "user_id": "explicit-user"},
            service=service,
        )
        monkeypatch.setattr(handler, "session", AsyncMock(return_value=None))

        await _call(handler.get())

        args = service.list_executions.await_args.args
        assert args[1] == "explicit-user"
