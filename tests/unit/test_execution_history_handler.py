"""Unit tests for CrewExecutionHistoryHandler (FEAT-307, FEAT-446).

Since FEAT-446 (TASK-2323) the handler is decorated with
``@is_authenticated()`` + ``@user_session()`` and resolves the tenant from the
authenticated session (``handlers/crew/_tenancy.py``), never from the request
body/query. These tests therefore mark the mocked request as authenticated and
feed a fake session through ``get_session`` (patched at both lookup sites) —
no live auth backend, Redis or session middleware is required.
"""
import json
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from navigator.views.base import JSONContent

import parrot.conf
from parrot.handlers.crew.execution_history_handler import CrewExecutionHistoryHandler

try:
    from navigator_auth.conf import AUTH_SESSION_OBJECT as _AUTH_SESSION
except ImportError:  # pragma: no cover - mirrors _tenancy.py's fallback
    _AUTH_SESSION = "userinfo"


class _FakeSession(dict):
    """Dict-backed stand-in for navigator_session's ``SessionData``."""

    def decode(self, key: str) -> Any:
        return self.get(key)


def _session(tenant: Optional[str] = None, user_id: Optional[str] = None) -> _FakeSession:
    """Build a session whose userinfo carries an optional tenant / user id."""
    userinfo: Dict[str, Any] = {}
    if tenant:
        userinfo["tenant_id"] = tenant
    if user_id is not None:
        # BaseHandler.get_userid() reads session["session"]["user_id"] when a
        # "session" (AUTH_SESSION_OBJECT) key exists, else session["user_id"].
        userinfo["user_id"] = user_id
    data = _FakeSession()
    data[_AUTH_SESSION] = userinfo
    if user_id is not None and _AUTH_SESSION != "session":
        data["user_id"] = user_id
    return data


@pytest.fixture
def set_session(monkeypatch):
    """Patch ``get_session`` everywhere the handler stack reads it.

    ``@user_session`` resolves it from ``navigator_auth.decorators``; the
    tenancy resolver and ``BaseView.session()`` import it from
    ``navigator_session``. Legacy (non-SaaS) mode is pinned so the ``"global"``
    fallback is deterministic regardless of the local environment.
    """
    import navigator.views.base as _nav_base
    import navigator_auth.decorators as _auth_decorators
    import navigator_session

    monkeypatch.setattr(parrot.conf, "PARROT_SAAS_MODE", False)

    def _set(session: Optional[_FakeSession]) -> None:
        getter = AsyncMock(return_value=session)
        monkeypatch.setattr(_auth_decorators, "get_session", getter)
        monkeypatch.setattr(navigator_session, "get_session", getter)
        if hasattr(_nav_base, "get_session"):
            monkeypatch.setattr(_nav_base, "get_session", getter)

    _set(_session())
    return _set


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
    # Satisfy @is_authenticated() without an auth backend (the auth
    # middleware sets this flag on real, authenticated requests).
    request["authenticated"] = True
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


@pytest.mark.usefixtures("set_session")
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
        assert args[0] == "global"  # legacy mode: unresolvable tenant -> global

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
    async def test_replay_success(self, set_session):
        """POST /{id}/replay triggers replay under the session's tenant."""
        set_session(_session(tenant="acme"))
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
    async def test_replay_crew_not_found(self, set_session):
        """POST /{id}/replay returns 404 for deleted crew."""
        from parrot.handlers.crew.saved_execution_service import CrewNotFoundError

        set_session(_session(tenant="acme"))
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
        service.replay_execution.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_replay_no_prompt(self, set_session):
        """POST /{id}/replay returns 400 for missing prompt."""
        from parrot.handlers.crew.saved_execution_service import ReplayValidationError

        set_session(_session(tenant="acme"))
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
        service.replay_execution.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_schedule_success(self, set_session):
        """POST /{id}/schedule creates APScheduler job."""
        set_session(_session(tenant="acme"))
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
    async def test_schedule_invalid_request_returns_400(self, set_session):
        """POST /{id}/schedule returns 400 when schedule_type/schedule_config missing."""
        set_session(_session(tenant="acme"))
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
    async def test_post_tenant_comes_from_session_not_body(self, set_session):
        """POST /{id}/replay with no body tenant uses the session's tenant
        (FEAT-446: tenant identity is session-derived, never body-supplied)."""
        set_session(_session(tenant="acme"))
        service = AsyncMock()
        service.replay_execution.return_value = {"job_id": "job-1"}
        handler = _make_handler(
            method="POST",
            path="/api/v1/crew/executions/abc/replay",
            match_info={"execution_id": "abc", "action": "replay"},
            json_body={},
            service=service,
        )

        resp = await _call(handler.post())

        assert resp.status == 200
        service.replay_execution.assert_awaited_once_with("acme", None, "abc")

    @pytest.mark.asyncio
    async def test_post_declared_tenant_mismatch_returns_400(self, set_session):
        """POST with a body tenant that conflicts with the session's tenant is
        rejected before any service call."""
        set_session(_session(tenant="acme"))
        service = AsyncMock()
        handler = _make_handler(
            method="POST",
            path="/api/v1/crew/executions/abc/replay",
            match_info={"execution_id": "abc", "action": "replay"},
            json_body={"tenant": "other-tenant"},
            service=service,
        )

        resp = await _call(handler.post())

        assert resp.status == 400
        service.replay_execution.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_post_unresolvable_tenant_in_saas_mode_returns_403(self, set_session, monkeypatch):
        """Under PARROT_SAAS_MODE a mutating call with no session tenant is
        denied (no silent 'global' fallback)."""
        monkeypatch.setattr(parrot.conf, "PARROT_SAAS_MODE", True)
        set_session(_session())
        service = AsyncMock()
        handler = _make_handler(
            method="POST",
            path="/api/v1/crew/executions/abc/replay",
            match_info={"execution_id": "abc", "action": "replay"},
            json_body={},
            service=service,
        )

        resp = await _call(handler.post())

        assert resp.status == 403
        service.replay_execution.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_success(self, set_session):
        """DELETE /{id} removes execution."""
        set_session(_session(tenant="acme"))
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
    async def test_delete_not_found(self, set_session):
        """DELETE /{id} returns 404 for missing execution."""
        set_session(_session(tenant="acme"))
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
        service.delete_execution.assert_awaited_once_with("acme", None, "missing")

    @pytest.mark.asyncio
    async def test_delete_declared_tenant_mismatch_returns_400(self, set_session):
        """DELETE with a query tenant that conflicts with the session's tenant
        is rejected (same rule as POST)."""
        set_session(_session(tenant="acme"))
        service = AsyncMock()
        handler = _make_handler(
            method="DELETE",
            path="/api/v1/crew/executions/abc",
            match_info={"execution_id": "abc"},
            query={"tenant": "other-tenant"},
            service=service,
        )

        resp = await _call(handler.delete())

        assert resp.status == 400
        service.delete_execution.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_post_unknown_action_returns_400(self, set_session):
        """POST /{id}/{action} with an unrecognised action returns 400."""
        set_session(_session(tenant="acme"))
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
        service.replay_execution.assert_not_awaited()
        service.schedule_execution.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_session_user_id_overrides_body_supplied_user_id(self, set_session):
        """When an authenticated session is present, its user id is used
        instead of a client-supplied user_id — closes the IDOR gap where any
        caller could assert an arbitrary identity via the request body."""
        set_session(_session(tenant="acme", user_id="real-session-user"))
        service = AsyncMock()
        service.list_executions.return_value = ([], 0)
        handler = _make_handler(
            method="GET",
            query={"tenant": "acme", "user_id": "attacker-supplied"},
            service=service,
        )

        resp = await _call(handler.get())

        assert resp.status == 200
        args = service.list_executions.await_args.args
        assert args[1] == "real-session-user"

    @pytest.mark.asyncio
    async def test_no_session_falls_back_to_body_user_id(self, set_session):
        """When no session is available (no middleware configured / anonymous
        caller), the explicit user_id from the request is used as a fallback."""
        set_session(None)
        service = AsyncMock()
        service.list_executions.return_value = ([], 0)
        handler = _make_handler(
            method="GET",
            query={"user_id": "explicit-user"},
            service=service,
        )

        resp = await _call(handler.get())

        assert resp.status == 200
        args = service.list_executions.await_args.args
        assert args[0] == "global"
        assert args[1] == "explicit-user"
