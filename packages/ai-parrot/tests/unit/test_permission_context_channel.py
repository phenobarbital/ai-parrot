"""Unit tests for :attr:`PermissionContext.channel` (TASK-749, FEAT-107).

The ``channel`` field carries the originating channel (telegram, agentalk,
teams, api, …) so per-user credential resolvers can scope token storage.
It must default to ``None`` to remain fully backward compatible.
"""
from __future__ import annotations

import pytest

from parrot.auth.permission import PermissionContext, UserSession


@pytest.fixture
def session() -> UserSession:
    return UserSession(
        user_id="user-123",
        tenant_id="acme",
        roles=frozenset({"jira.write"}),
    )


class TestPermissionContextChannel:
    def test_channel_default_is_none(self, session: UserSession) -> None:
        ctx = PermissionContext(session=session)
        assert ctx.channel is None

    def test_channel_can_be_set_to_telegram(self, session: UserSession) -> None:
        ctx = PermissionContext(session=session, channel="telegram")
        assert ctx.channel == "telegram"

    def test_channel_can_be_set_to_agentalk(self, session: UserSession) -> None:
        ctx = PermissionContext(session=session, channel="agentalk")
        assert ctx.channel == "agentalk"

    def test_channel_accepts_teams_and_api(self, session: UserSession) -> None:
        ctx_teams = PermissionContext(session=session, channel="teams")
        ctx_api = PermissionContext(session=session, channel="api")
        assert ctx_teams.channel == "teams"
        assert ctx_api.channel == "api"

    def test_backward_compat_no_channel(self, session: UserSession) -> None:
        """Constructing without ``channel`` must still populate the rest."""
        ctx = PermissionContext(session=session, request_id="req-1")
        assert ctx.user_id == "user-123"
        assert ctx.tenant_id == "acme"
        assert ctx.request_id == "req-1"
        assert ctx.channel is None

    def test_channel_with_extra(self, session: UserSession) -> None:
        """channel and extra coexist without clashing."""
        ctx = PermissionContext(
            session=session,
            channel="telegram",
            extra={"ip": "127.0.0.1"},
        )
        assert ctx.channel == "telegram"
        assert ctx.extra == {"ip": "127.0.0.1"}

    def test_channel_is_mutable(self, session: UserSession) -> None:
        """PermissionContext is a regular dataclass — channel can be reassigned."""
        ctx = PermissionContext(session=session)
        ctx.channel = "api"
        assert ctx.channel == "api"
