"""Lifecycle tests for staged Telegram combined login."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.oauth2.events import ConnectionEvent
from parrot.integrations.core.auth.post_auth import PostAuthRegistry
from parrot.integrations.telegram.auth import TelegramUserSession
from parrot.integrations.telegram.models import PostAuthAction, TelegramAgentConfig
from parrot.integrations.telegram.post_auth_connection import PendingLoginCoordinator
from parrot.integrations.telegram.wrapper import TelegramAgentWrapper, principal_for_session


def _wrapper(*, required: bool = True) -> TelegramAgentWrapper:
    """Build a wrapper double around the real staged-login methods."""
    wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
    wrapper.config = TelegramAgentConfig(
        name="bot",
        chatbot_id="bot",
        tenant="tenant-a",
        post_auth_actions=[PostAuthAction(provider="jira", required=required)],
    )
    wrapper.app = None
    wrapper.agent = MagicMock()
    wrapper.bot = MagicMock()
    wrapper.bot.send_message = AsyncMock()
    wrapper.logger = MagicMock()
    wrapper._bot_id = "7001"
    wrapper._user_sessions = {}
    wrapper._post_auth_registry = PostAuthRegistry()
    wrapper._auth_strategy = MagicMock()
    wrapper._persist_principal_link = AsyncMock(return_value=True)
    wrapper._initialize_user_context = AsyncMock()
    wrapper._connection_permission_context = MagicMock(return_value=MagicMock())
    wrapper._login_coordinator = PendingLoginCoordinator(
        finalize=wrapper._finalize_login_attempt,
        on_failed=wrapper._fail_login_attempt,
    )
    return wrapper


def _message(telegram_id: int = 88123):
    """Return a minimal private Telegram message double."""
    message = MagicMock()
    message.chat.id = telegram_id
    message.from_user.id = telegram_id
    message.from_user.username = "alice"
    message.from_user.first_name = "Alice"
    message.from_user.last_name = None
    message.answer = AsyncMock()
    return message


def _candidate(telegram_id: int = 88123) -> TelegramUserSession:
    """Return a primary-authenticated candidate."""
    candidate = TelegramUserSession(telegram_id=telegram_id, telegram_username="alice")
    candidate.set_authenticated("nav-42", "signed-primary-token", "Alice", "alice@example.com")
    return candidate


def _provider(url: str = "https://jira.example/authorize") -> MagicMock:
    """Return a URL authorization provider double."""
    provider = MagicMock(provider_name="jira")
    provider.build_auth_url = AsyncMock(return_value=url)
    return provider


def _event() -> ConnectionEvent:
    """Return a correlated Jira completion event."""
    return ConnectionEvent(
        kind="connection.completed",
        user_id="nav-42",
        provider="jira",
        channel="telegram",
        occurred_at=1.0,
    )


@pytest.mark.asyncio
async def test_combined_login_required_failure() -> None:
    """Required denial discards the candidate and publishes no identity link."""
    wrapper = _wrapper()
    candidate = _candidate()

    await wrapper._start_login_attempt(_message(), candidate)

    wrapper._persist_principal_link.assert_not_awaited()
    assert wrapper._user_sessions == {}
    sent = wrapper.bot.send_message.await_args.kwargs
    assert sent["text"] == "Login requires authorization for jira. Please try again with /login."
    assert sent["parse_mode"] is None


@pytest.mark.asyncio
async def test_pending_login_never_backfills() -> None:
    """A coordinator-owned candidate is invisible to active-session principal lookup."""
    wrapper = _wrapper()
    provider = _provider()
    wrapper._post_auth_registry.register(provider)
    candidate = _candidate()

    await wrapper._start_login_attempt(_message(), candidate)

    assert wrapper._user_sessions == {}
    active = TelegramUserSession(telegram_id=candidate.telegram_id)
    assert await principal_for_session(active) is None
    wrapper._persist_principal_link.assert_not_awaited()
    wrapper._initialize_user_context.assert_not_awaited()


@pytest.mark.asyncio
async def test_e2e_combined_login_from_unauthenticated() -> None:
    """Primary success stages a candidate and callback completion publishes it once."""
    wrapper = _wrapper()
    provider = _provider()
    wrapper._post_auth_registry.register(provider)
    message = _message()
    active = TelegramUserSession(telegram_id=message.from_user.id, telegram_username="alice")

    async def validate_primary(data, candidate):
        assert data["token"] == "signed-primary-token"
        candidate.set_authenticated("nav-42", data["token"], "Alice", "alice@example.com")
        return True

    wrapper._auth_strategy.handle_callback = AsyncMock(side_effect=validate_primary)
    await wrapper._handle_combined_auth(
        message,
        {"user_id": "nav-42", "token": "signed-primary-token"},
        active,
    )
    attempt = provider.build_auth_url.await_args.args[0]

    assert not active.authenticated
    assert wrapper._user_sessions == {}
    assert await wrapper._login_coordinator.on_provider_completed(
        _event(),
        {"extra": {"attempt_id": attempt.attempt_id, "bot_id": "7001", "combined": True}},
    )

    wrapper._persist_principal_link.assert_awaited_once_with(attempt.candidate)
    assert wrapper._user_sessions[88123].nav_user_id == "nav-42"
    wrapper._initialize_user_context.assert_awaited_once()


@pytest.mark.asyncio
async def test_e2e_combined_required_failure_no_link() -> None:
    """A required failure preserves the unrelated active session and writes no link."""
    wrapper = _wrapper()
    existing = TelegramUserSession(telegram_id=88123)
    existing.set_authenticated("old-owner", "old-token", "Old Owner")
    wrapper._user_sessions[88123] = existing
    candidate = _candidate()
    provider = _provider()
    provider.build_auth_url = AsyncMock(side_effect=PermissionError("denied"))
    wrapper._post_auth_registry.register(provider)

    await wrapper._start_login_attempt(_message(), candidate)

    assert wrapper._user_sessions[88123] is existing
    assert wrapper._user_sessions[88123].nav_user_id == "old-owner"
    wrapper._persist_principal_link.assert_not_awaited()


@pytest.mark.asyncio
async def test_login_persists_link_both_paths() -> None:
    """The combined half publishes its link exactly once at final success."""
    wrapper = _wrapper()
    provider = _provider()
    wrapper._post_auth_registry.register(provider)
    candidate = _candidate()

    await wrapper._start_login_attempt(_message(), candidate)
    attempt = provider.build_auth_url.await_args.args[0]
    state = {"extra": {"attempt_id": attempt.attempt_id, "bot_id": "7001", "combined": True}}
    assert await wrapper._login_coordinator.on_provider_completed(_event(), state)
    assert not await wrapper._login_coordinator.on_provider_completed(_event(), state)

    wrapper._persist_principal_link.assert_awaited_once_with(candidate)
