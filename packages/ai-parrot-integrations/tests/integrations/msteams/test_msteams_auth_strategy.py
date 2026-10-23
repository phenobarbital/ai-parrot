"""Unit tests for the classic Bot Framework Teams authentication strategy."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest
from botbuilder.core import BotFrameworkAdapter
from botframework.connector.token_api.models import TokenExchangeRequest

from parrot.auth.token_exchange import ExchangeResult
from parrot.integrations.msteams.auth import (
    MSTeamsAuthStrategy,
    MSTeamsSessionStore,
    MSTeamsUserSession,
    user_key,
)


@pytest.fixture
def fake_adapter() -> MagicMock:
    """Return an adapter stub matching BotFrameworkAdapter's used methods."""
    adapter = create_autospec(BotFrameworkAdapter, instance=True)
    adapter.get_user_token = AsyncMock(return_value=None)
    adapter.exchange_token = AsyncMock(return_value=None)
    adapter.get_oauth_sign_in_link = AsyncMock(return_value="https://signin.example.test")
    adapter.sign_out_user = AsyncMock()
    return adapter


@pytest.fixture
def turn_context(fake_adapter: MagicMock) -> MagicMock:
    """Return a minimal Teams context with a stable Entra object id."""
    context = MagicMock()
    context.adapter = fake_adapter
    context.activity.from_property.id = "teams-user-123"
    context.activity.from_property.aad_object_id = "entra-oid-456"
    context.activity.from_property.name = "Teams User"
    context.activity.channel_data = SimpleNamespace(tenant=SimpleNamespace(id="tenant-123"))
    context.activity.name = None
    context.activity.value = None
    context.send_activity = AsyncMock()
    return context


@pytest.fixture
def store() -> MSTeamsSessionStore:
    """Return a process-local session store."""
    return MSTeamsSessionStore("assistant")


@pytest.fixture
def exchange() -> MagicMock:
    """Return a successful Navigator token exchange stub."""
    client = MagicMock()
    client.exchange = AsyncMock(
        return_value=ExchangeResult(
            ok=True,
            nav_user_id="35",
            session_token="navigator-session",
            email="user@example.test",
            expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        )
    )
    return client


@pytest.fixture
def strategy(store: MSTeamsSessionStore, exchange: MagicMock) -> MSTeamsAuthStrategy:
    """Return a strategy configured with an OAuth connection."""
    return MSTeamsAuthStrategy(SimpleNamespace(oauth_connection_name="teams-oauth"), store, exchange)


class TestEnsureAuthenticated:
    """Tests for pure session resolution."""

    @pytest.mark.asyncio
    async def test_returns_unauthenticated_without_token(
        self,
        strategy: MSTeamsAuthStrategy,
        turn_context: MagicMock,
        exchange: MagicMock,
    ) -> None:
        """No Token Service token returns quietly without sending a card."""
        session = await strategy.ensure_authenticated(turn_context)

        assert session.authenticated is False
        turn_context.send_activity.assert_not_awaited()
        exchange.exchange.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cached_session_skips_adapter(
        self,
        strategy: MSTeamsAuthStrategy,
        store: MSTeamsSessionStore,
        turn_context: MagicMock,
        fake_adapter: MagicMock,
        exchange: MagicMock,
    ) -> None:
        """An unexpired cached session short-circuits all external calls."""
        session = MSTeamsUserSession(
            user_key=user_key(turn_context),
            teams_user_id="teams-user-123",
            authenticated=True,
            external_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        store._local[session.user_key] = session

        assert await strategy.ensure_authenticated(turn_context) is session
        fake_adapter.get_user_token.assert_not_awaited()
        exchange.exchange.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_expired_cached_session_becomes_unauthenticated_without_token(
        self,
        strategy: MSTeamsAuthStrategy,
        store: MSTeamsSessionStore,
        turn_context: MagicMock,
    ) -> None:
        """An expired cached credential cannot remain authenticated after reacquisition fails."""
        session = MSTeamsUserSession(
            user_key=user_key(turn_context),
            teams_user_id="teams-user-123",
            authenticated=True,
            external_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        store._local[session.user_key] = session

        assert await strategy.ensure_authenticated(turn_context) is session
        assert session.authenticated is False

    @pytest.mark.asyncio
    async def test_successful_exchange_authenticates_session(
        self,
        strategy: MSTeamsAuthStrategy,
        turn_context: MagicMock,
        fake_adapter: MagicMock,
        exchange: MagicMock,
    ) -> None:
        """A provider token drives one Navigator exchange and saves its identity."""
        fake_adapter.get_user_token.return_value = SimpleNamespace(token="provider-token")

        session = await strategy.ensure_authenticated(turn_context)

        assert session.authenticated is True
        assert session.nav_user_id == "35"
        exchange.exchange.assert_awaited_once_with("provider-token", provider="azure", id_token=None)

    @pytest.mark.asyncio
    async def test_failed_exchange_records_reason(
        self,
        strategy: MSTeamsAuthStrategy,
        turn_context: MagicMock,
        fake_adapter: MagicMock,
        exchange: MagicMock,
    ) -> None:
        """The verbatim unsuccessful exchange reason is retained for commands."""
        fake_adapter.get_user_token.return_value = SimpleNamespace(token="provider-token")
        exchange.exchange.return_value = ExchangeResult(ok=False, reason="user_not_found")

        session = await strategy.ensure_authenticated(turn_context)

        assert session.authenticated is False
        assert session.metadata["auth_reason"] == "user_not_found"


class TestSsoPath:
    """Tests for the Bot Framework Teams SSO exchange seam."""

    @pytest.mark.asyncio
    async def test_exchange_sso_passes_user_key(
        self,
        strategy: MSTeamsAuthStrategy,
        turn_context: MagicMock,
        fake_adapter: MagicMock,
    ) -> None:
        """exchange_token receives the stable Teams user key."""
        request = TokenExchangeRequest(uri="api://resource", token="sso-token")

        await strategy.exchange_sso_token(turn_context, request)

        fake_adapter.exchange_token.assert_awaited_once_with(
            turn_context, "teams-oauth", user_key(turn_context), request
        )

    @pytest.mark.asyncio
    async def test_invoke_uses_sso_token_when_no_cached_token(
        self,
        strategy: MSTeamsAuthStrategy,
        turn_context: MagicMock,
        fake_adapter: MagicMock,
        exchange: MagicMock,
    ) -> None:
        """A tokenExchange invoke falls back to the adapter SSO exchange path."""
        turn_context.activity.name = "signin/tokenExchange"
        turn_context.activity.value = {"uri": "api://resource", "token": "sso-token"}
        fake_adapter.exchange_token.return_value = SimpleNamespace(token="provider-token")

        session = await strategy.ensure_authenticated(turn_context)

        assert session.authenticated is True
        request = fake_adapter.exchange_token.await_args.args[3]
        assert request.uri == "api://resource"
        assert request.token == "sso-token"
        exchange.exchange.assert_awaited_once_with("provider-token", provider="azure", id_token=None)


class TestPromptAndSignOut:
    """Tests for caller-owned prompts and clear-first logout."""

    @pytest.mark.asyncio
    async def test_send_signin_card_builds_native_oauth_card(
        self,
        strategy: MSTeamsAuthStrategy,
        turn_context: MagicMock,
    ) -> None:
        """A caller can request an OAuthCard after resolution reports no token."""
        await strategy.send_signin_card(turn_context)

        sent = turn_context.send_activity.await_args.args[0]
        assert sent.attachments[0].content_type == "application/vnd.microsoft.card.oauth"
        assert sent.attachments[0].content.connection_name == "teams-oauth"

    @pytest.mark.asyncio
    async def test_sign_out_clears_session_when_adapter_fails(
        self,
        strategy: MSTeamsAuthStrategy,
        store: MSTeamsSessionStore,
        turn_context: MagicMock,
        fake_adapter: MagicMock,
    ) -> None:
        """Store cleanup precedes a failing Token Service sign-out call."""
        key = user_key(turn_context)
        store._local[key] = MSTeamsUserSession(user_key=key, teams_user_id="teams-user-123")
        fake_adapter.sign_out_user.side_effect = RuntimeError("Token service unavailable")

        with pytest.raises(RuntimeError, match="Token service unavailable"):
            await strategy.sign_out(turn_context)

        assert key not in store._local
