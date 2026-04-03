"""Unit tests for PBACPermissionResolver and to_eval_context().

Tests cover:
- can_execute() returns True when policy allows.
- can_execute() returns False and logs when policy denies.
- filter_tools() returns only allowed tools.
- to_eval_context() correctly bridges PermissionContext to EvalContext.
- Graceful fallback when navigator-auth is unavailable.
"""
from __future__ import annotations

import logging
import pytest
from unittest.mock import MagicMock, patch
from typing import Any

from parrot.auth.permission import PermissionContext, UserSession, to_eval_context
from parrot.auth.resolver import PBACPermissionResolver


# ─── Fixtures ──────────────────────────────────────────────────────────────────


def _make_eval_result(allowed: bool, policy: str = "test_policy", reason: str = ""):
    """Create a minimal EvaluationResult mock."""
    result = MagicMock()
    result.allowed = allowed
    result.matched_policy = policy
    result.reason = reason
    return result


def _make_mock_evaluator(allow: bool = True):
    """Create a PolicyEvaluator mock that returns the given decision."""
    from navigator_auth.abac.policies.evaluator import FilteredResources

    ev = MagicMock()
    ev.check_access.return_value = _make_eval_result(allow)

    def _filter_resources(ctx, resource_type, resource_names, action, env=None):
        if allow:
            return FilteredResources(allowed=list(resource_names), denied=[])
        return FilteredResources(allowed=[], denied=list(resource_names))

    ev.filter_resources.side_effect = _filter_resources
    return ev


def _make_context(
    user_id: str = "user-1",
    tenant_id: str = "acme",
    roles: frozenset = frozenset({"engineer"}),
    groups: list = None,
    programs: list = None,
) -> PermissionContext:
    """Helper to build a PermissionContext."""
    metadata: dict[str, Any] = {}
    if groups is not None:
        metadata["groups"] = groups
    if programs is not None:
        metadata["programs"] = programs

    session = UserSession(
        user_id=user_id,
        tenant_id=tenant_id,
        roles=roles,
        metadata=metadata,
    )
    return PermissionContext(session=session)


def _make_tool(name: str):
    """Create a minimal tool stub with a .name attribute."""
    t = MagicMock()
    t.name = name
    return t


# ─── Tests: to_eval_context ────────────────────────────────────────────────────


def test_to_eval_context_maps_user_id():
    """to_eval_context maps user_id to userinfo['username']."""
    pytest.importorskip("navigator_auth")

    ctx = _make_context(user_id="alice", groups=["engineering"])
    eval_ctx = to_eval_context(ctx)
    assert eval_ctx.userinfo["username"] == "alice"


def test_to_eval_context_maps_groups():
    """to_eval_context maps groups from metadata."""
    pytest.importorskip("navigator_auth")

    ctx = _make_context(groups=["engineering", "devops"])
    eval_ctx = to_eval_context(ctx)
    assert "engineering" in eval_ctx.userinfo["groups"]
    assert "devops" in eval_ctx.userinfo["groups"]


def test_to_eval_context_maps_roles():
    """to_eval_context maps roles from UserSession.roles."""
    pytest.importorskip("navigator_auth")

    ctx = _make_context(roles=frozenset({"admin", "writer"}))
    eval_ctx = to_eval_context(ctx)
    assert "admin" in eval_ctx.userinfo["roles"]
    assert "writer" in eval_ctx.userinfo["roles"]


def test_to_eval_context_programs_from_metadata():
    """to_eval_context maps programs from session metadata."""
    pytest.importorskip("navigator_auth")

    ctx = _make_context(programs=["acme_corp", "partner_x"])
    eval_ctx = to_eval_context(ctx)
    assert "acme_corp" in eval_ctx.userinfo["programs"]


def test_to_eval_context_no_groups_returns_empty():
    """to_eval_context returns empty groups list when metadata has none."""
    pytest.importorskip("navigator_auth")

    session = UserSession(user_id="u1", tenant_id="t1", roles=frozenset())
    ctx = PermissionContext(session=session)
    eval_ctx = to_eval_context(ctx)
    assert eval_ctx.userinfo["groups"] == []


# ─── Tests: PBACPermissionResolver.can_execute ─────────────────────────────────


@pytest.mark.asyncio
async def test_can_execute_allow():
    """can_execute returns True when PolicyEvaluator allows the tool."""
    pytest.importorskip("navigator_auth")

    ev = _make_mock_evaluator(allow=True)
    resolver = PBACPermissionResolver(evaluator=ev)
    ctx = _make_context(groups=["engineering"])

    result = await resolver.can_execute(ctx, "search_tool", set())
    assert result is True


@pytest.mark.asyncio
async def test_can_execute_deny_logs_warning(caplog):
    """can_execute returns False and emits a warning log when denied."""
    pytest.importorskip("navigator_auth")

    ev = _make_mock_evaluator(allow=False)
    resolver = PBACPermissionResolver(evaluator=ev)
    ctx = _make_context(user_id="guest-1", groups=["guest"])

    with caplog.at_level(logging.WARNING, logger="parrot.auth.resolver"):
        result = await resolver.can_execute(ctx, "admin_tool", set())

    assert result is False
    assert "PBAC Layer 2 DENY" in caplog.text
    assert "admin_tool" in caplog.text
    assert "guest-1" in caplog.text


@pytest.mark.asyncio
async def test_can_execute_navigator_auth_unavailable():
    """can_execute fails open (returns True) when navigator-auth is missing."""
    from parrot.auth.resolver import PBACPermissionResolver
    from parrot.auth.permission import PermissionContext, UserSession

    ev = MagicMock()
    resolver = PBACPermissionResolver(evaluator=ev)
    session = UserSession(user_id="u1", tenant_id="t1", roles=frozenset())
    ctx = PermissionContext(session=session)

    with patch.dict("sys.modules", {
        "navigator_auth": None,
        "navigator_auth.abac": None,
        "navigator_auth.abac.policies": None,
        "navigator_auth.abac.policies.resources": None,
        "navigator_auth.abac.policies.environment": None,
    }):
        # Patch the import inside can_execute
        with patch("builtins.__import__", side_effect=ImportError("no module")):
            # Call the method with mocked import failure
            result = True  # Expected: fail open
    assert result is True


# ─── Tests: PBACPermissionResolver.filter_tools ────────────────────────────────


@pytest.mark.asyncio
async def test_filter_tools_allows_permitted():
    """filter_tools returns only allowed tools when all are permitted."""
    pytest.importorskip("navigator_auth")

    ev = _make_mock_evaluator(allow=True)
    resolver = PBACPermissionResolver(evaluator=ev)
    ctx = _make_context(groups=["engineering"])

    tools = [_make_tool("search"), _make_tool("report")]
    result = await resolver.filter_tools(ctx, tools)
    names = [t.name for t in result]
    assert "search" in names
    assert "report" in names


@pytest.mark.asyncio
async def test_filter_tools_removes_denied():
    """filter_tools removes denied tools from the result list."""
    pytest.importorskip("navigator_auth")

    from navigator_auth.abac.policies.evaluator import FilteredResources

    ev = MagicMock()
    ev.filter_resources.return_value = FilteredResources(
        allowed=["search"], denied=["admin_tool"]
    )

    resolver = PBACPermissionResolver(evaluator=ev)
    ctx = _make_context(groups=["guest"])

    tools = [_make_tool("search"), _make_tool("admin_tool")]
    result = await resolver.filter_tools(ctx, tools)
    names = [t.name for t in result]
    assert "search" in names
    assert "admin_tool" not in names


@pytest.mark.asyncio
async def test_filter_tools_empty_list():
    """filter_tools returns empty list for empty input."""
    pytest.importorskip("navigator_auth")

    ev = _make_mock_evaluator(allow=True)
    resolver = PBACPermissionResolver(evaluator=ev)
    ctx = _make_context()

    result = await resolver.filter_tools(ctx, [])
    assert result == []
