"""Unit tests for `UserinfoTool` (FEAT-406 / TASK-2113).

Covers session-only identity resolution (via `AbstractTool._current_pctx`,
set by `execute()` from `_permission_context` — never from an LLM-supplied
kwarg), JSON output matching `EmployeeProfile`, missing-profile handling,
and the no-session case.
"""
from unittest.mock import AsyncMock

import pytest

from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.userinfo import EmployeeProfile, ManagerRef
from parrot.tools.userinfo import UserinfoTool


def _make_permission_context(user_id: str = "user-1") -> PermissionContext:
    session = UserSession(user_id=user_id, tenant_id="acme", roles=frozenset())
    return PermissionContext(session=session)


def _make_profile(user_id="user-1") -> EmployeeProfile:
    return EmployeeProfile(
        user_id=user_id,
        username="jlara",
        display_name="Jesus Lara",
        email="jlara@example.com",
        job_code="ENG-3",
        title="Sr Engineer",
        department_code="TECH",
        groups=["engineering"],
        programs=["ai-parrot"],
        worker_type="FTE",
        manager=ManagerRef(user_id="mgr-1", display_name="Manager Name", email="mgr@example.com"),
    )


class TestUserinfoToolDirectExecute:
    """Unit-level tests calling `_execute()` directly against `_current_pctx`."""

    @pytest.mark.asyncio
    async def test_userinfo_tool_json_output(self):
        service = AsyncMock()
        service.get_profile.return_value = _make_profile()
        tool = UserinfoTool(service=service)
        tool._current_pctx = _make_permission_context("user-1")

        result = await tool._execute()

        service.get_profile.assert_awaited_once_with("user-1")
        assert result["user_id"] == "user-1"
        assert result["username"] == "jlara"
        assert result["manager"]["user_id"] == "mgr-1"
        assert result["manager"]["display_name"] == "Manager Name"
        # Round-trips through EmployeeProfile's own schema.
        EmployeeProfile(**result)

    @pytest.mark.asyncio
    async def test_userinfo_tool_missing_profile(self):
        service = AsyncMock()
        service.get_profile.return_value = None
        tool = UserinfoTool(service=service)
        tool._current_pctx = _make_permission_context("ghost-user")

        result = await tool._execute()

        assert result == {"status": "unavailable", "message": "Profile not found"}

    @pytest.mark.asyncio
    async def test_userinfo_tool_no_session(self):
        service = AsyncMock()
        tool = UserinfoTool(service=service)
        tool._current_pctx = None

        result = await tool._execute()

        assert result["status"] == "unavailable"
        service.get_profile.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_userinfo_tool_ignores_llm_supplied_kwargs(self):
        """Even if _execute() is (incorrectly) called with an identity-shaped
        kwarg directly, only self._current_pctx is consulted."""
        service = AsyncMock()
        service.get_profile.return_value = _make_profile("user-1")
        tool = UserinfoTool(service=service)
        tool._current_pctx = _make_permission_context("user-1")

        result = await tool._execute(user_id="attacker-supplied-id")

        service.get_profile.assert_awaited_once_with("user-1")
        assert result["user_id"] == "user-1"


class TestUserinfoToolFullExecute:
    """Integration-style tests through the real `AbstractTool.execute()` wrapper."""

    @pytest.mark.asyncio
    async def test_userinfo_tool_session_identity_only(self):
        """Session identity comes from _permission_context; an LLM-supplied
        argument (e.g. user_id) never reaches _execute() at all — the
        default args_schema strips all kwargs (see corrected Codebase
        Contract, Module 5)."""
        service = AsyncMock()
        service.get_profile.return_value = _make_profile("user-1")
        tool = UserinfoTool(service=service)
        pctx = _make_permission_context("user-1")

        tool_result = await tool.execute(
            user_id="attacker-supplied-id", _permission_context=pctx
        )

        service.get_profile.assert_awaited_once_with("user-1")
        assert tool_result.success is True
        assert tool_result.result["user_id"] == "user-1"

    @pytest.mark.asyncio
    async def test_userinfo_tool_no_session_via_execute(self):
        service = AsyncMock()
        tool = UserinfoTool(service=service)

        tool_result = await tool.execute()

        service.get_profile.assert_not_awaited()
        assert tool_result.result["status"] == "unavailable"
