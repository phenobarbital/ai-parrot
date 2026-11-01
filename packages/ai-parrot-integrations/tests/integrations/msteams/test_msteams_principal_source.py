"""FEAT-775 M1: Teams principal source."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.principal import Principal
from parrot.integrations.msteams.auth import MSTeamsUserSession
from parrot.integrations.msteams.connections import MSTeamsPrincipalSource, build_msteams_permission_context


@pytest.fixture
def teams_session() -> MSTeamsUserSession:
    """Return an authenticated Teams session with a Navigator identity."""
    return MSTeamsUserSession(
        user_key="aad-1",
        teams_user_id="29:x",
        aad_object_id="aad-1",
        tenant_id="t-1",
        nav_user_id="42",
        authenticated=True,
    )


def _store(session: MSTeamsUserSession, expired: bool = False) -> MagicMock:
    """Build a session-store mock for a turn."""
    store = MagicMock()
    store.get_or_create = AsyncMock(return_value=session)
    store.is_expired = MagicMock(return_value=expired)
    return store


@pytest.mark.asyncio
async def test_principal_for_turn_authenticated(teams_session: MSTeamsUserSession) -> None:
    """An authenticated, unexpired session maps to the FEAT-773 principal."""
    principal = await MSTeamsPrincipalSource(_store(teams_session)).principal_for_turn(MagicMock())

    assert principal == Principal(
        user_id="42",
        canonical_identity="aad-1",
        tenant_id="t-1",
        channel="msteams",
        channel_user_id="aad-1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("session_kwargs", "expired"),
    [
        ({"authenticated": False}, False),
        ({}, True),
        ({"nav_user_id": None}, False),
        ({"aad_object_id": None}, False),
    ],
)
async def test_principal_for_turn_unauthenticated_or_expired_is_none(
    teams_session: MSTeamsUserSession,
    session_kwargs: dict[str, object],
    expired: bool,
) -> None:
    """Any missing or invalid authentication state fails closed."""
    for name, value in session_kwargs.items():
        setattr(teams_session, name, value)

    source = MSTeamsPrincipalSource(_store(teams_session, expired=expired))

    assert await source.principal_for_turn(MagicMock()) is None
    assert await MSTeamsPrincipalSource(None).principal_for_turn(MagicMock()) is None


def test_build_msteams_permission_context(teams_session: MSTeamsUserSession) -> None:
    """The permission context uses Navigator identity and carries the AAD oid separately."""
    context = build_msteams_permission_context(teams_session)

    assert context.user_id == "42"
    assert context.tenant_id == "t-1"
    assert context.channel == "msteams"
    assert context.channel_user_id == "aad-1"
    assert context.roles == frozenset()
