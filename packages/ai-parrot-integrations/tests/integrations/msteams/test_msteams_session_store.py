"""Tests for MS Teams per-user session persistence."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.msteams.auth import (
    MSTeamsSessionStore,
    MSTeamsUserSession,
    user_key,
)

TEAMS_OID = "7c8f1d2e-3b4a-5c6d-7e8f-9a0b1c2d3e4f"


@pytest.fixture
def teams_activity() -> MagicMock:
    """Return a minimal Teams turn context with Entra user identity."""
    context = MagicMock()
    context.activity.from_property.id = "teams-user-123"
    context.activity.from_property.aad_object_id = TEAMS_OID
    context.activity.from_property.name = "Teams User"
    context.activity.channel_data = SimpleNamespace(tenant=SimpleNamespace(id="tenant-123"))
    return context


class TestUserKey:
    """Tests for Teams identity key precedence."""

    def test_prefers_aad_object_id(self, teams_activity: MagicMock) -> None:
        """user_key returns the Entra oid when present."""
        assert user_key(teams_activity) == TEAMS_OID

    def test_falls_back_to_from_id(self) -> None:
        """With aad_object_id None, the Teams-scoped id is used."""
        context = MagicMock()
        context.activity.from_property.id = "teams-user-123"
        context.activity.from_property.aad_object_id = None
        assert user_key(context) == "teams-user-123"


class TestSessionStore:
    """Tests for serialization, expiry, and store lifecycle behavior."""

    @pytest.mark.asyncio
    async def test_payload_excludes_isolation_slots(self) -> None:
        """The three live-object slots never serialize."""
        session = MSTeamsUserSession(user_key="oid", teams_user_id="teams-user")
        session.tool_manager = object()
        session.user_agent = object()
        session.post_login_ran = True

        payload = MSTeamsSessionStore._to_payload(session)

        assert not set(payload) & {"tool_manager", "user_agent", "post_login_ran"}

    @pytest.mark.asyncio
    async def test_expiry_follows_external_token(self) -> None:
        """is_expired reads external_expires_at, not session age."""
        store = MSTeamsSessionStore("assistant")
        session = MSTeamsUserSession(
            user_key="oid",
            teams_user_id="teams-user",
            external_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )

        assert store.is_expired(session) is True

        session.external_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        assert store.is_expired(session) is False

    @pytest.mark.asyncio
    async def test_clear_missing_key_is_quiet(self) -> None:
        """clear() on an unknown key does not raise."""
        store = MSTeamsSessionStore("assistant")

        await store.clear("unknown")

    @pytest.mark.asyncio
    async def test_save_rehydrates_round_trip_with_token_ttl(self, teams_activity: MagicMock) -> None:
        """A cold store rehydrates serializable fields and retains no live slots."""
        backend = MagicMock()
        backend.set = AsyncMock()
        backend.get = AsyncMock()
        backend.delete = AsyncMock()
        store = MSTeamsSessionStore("assistant", store=backend)
        expiry = datetime.now(timezone.utc) + timedelta(seconds=120)
        session = MSTeamsUserSession(user_key=TEAMS_OID, teams_user_id="teams-user-123")
        session.set_authenticated("nav-user", "session-token", email="user@example.test", external_expires_at=expiry)

        await store.save(session)

        stored_payload = backend.set.await_args.args[1]
        stored_ttl = backend.set.await_args.kwargs["expire"]
        assert 0 < stored_ttl <= 120
        backend.get.return_value = stored_payload
        rehydrated_store = MSTeamsSessionStore("assistant", store=backend)
        rehydrated = await rehydrated_store.get_or_create(teams_activity)

        assert rehydrated is await rehydrated_store.get_or_create(teams_activity)
        assert rehydrated.user_key == TEAMS_OID
        assert rehydrated.nav_user_id == "nav-user"
        assert rehydrated.nav_session_token == "session-token"
        assert rehydrated.nav_email == "user@example.test"
        assert rehydrated.authenticated_at is not None
        assert rehydrated.authenticated_at.tzinfo is not None
        assert rehydrated.tool_manager is None
        assert rehydrated.user_agent is None
        assert rehydrated.post_login_ran is False

    @pytest.mark.asyncio
    async def test_expired_rehydrated_session_is_unauthenticated(self, teams_activity: MagicMock) -> None:
        """An expired payload remains available but loses authenticated state."""
        session = MSTeamsUserSession(
            user_key=TEAMS_OID,
            teams_user_id="teams-user-123",
            authenticated=True,
            external_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        backend = MagicMock()
        backend.get = AsyncMock(return_value=json.dumps(MSTeamsSessionStore._to_payload(session)))
        store = MSTeamsSessionStore("assistant", store=backend)

        rehydrated = await store.get_or_create(teams_activity)

        assert rehydrated.authenticated is False
