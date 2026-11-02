"""Unit tests for staged Telegram combined authentication."""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.integrations.core.auth.post_auth import PostAuthRegistry
from parrot.integrations.telegram.auth import TelegramUserSession
from parrot.integrations.telegram.models import PostAuthAction, TelegramAgentConfig
from parrot.integrations.telegram.post_auth_connection import PendingLoginCoordinator


@pytest.fixture
def wrapper_cls():
    """Return the wrapper class."""
    from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

    return TelegramAgentWrapper


@pytest.fixture
def config_with_jira() -> TelegramAgentConfig:
    """Return a basic-login configuration with required Jira authorization."""
    return TelegramAgentConfig(
        name="bot",
        chatbot_id="bot",
        auth_url="https://nav.example/api/login",
        login_page_url="https://nav.example/login",
        post_auth_actions=[PostAuthAction(provider="jira", required=True)],
    )


def _blank_wrapper(cls, config: TelegramAgentConfig, app=None):
    """Construct only the wrapper state used by staged-login methods."""
    wrapper = cls.__new__(cls)
    wrapper.config = config
    wrapper.app = app
    wrapper.agent = MagicMock()
    wrapper.bot = MagicMock()
    wrapper.bot.send_message = AsyncMock()
    wrapper.logger = MagicMock()
    wrapper._bot_id = "7001"
    wrapper._user_sessions = {}
    wrapper._auth_strategy = MagicMock()
    wrapper._post_auth_registry = PostAuthRegistry()
    wrapper._identity_service_cache = MagicMock() if app else None
    wrapper._login_coordinator = PendingLoginCoordinator(
        finalize=wrapper._finalize_login_attempt,
        on_failed=wrapper._fail_login_attempt,
    )
    wrapper._initialize_user_context = AsyncMock()
    wrapper._persist_principal_link = AsyncMock(return_value=True)
    wrapper._connection_permission_context = MagicMock(return_value=MagicMock())
    return wrapper


def _message(telegram_id: int = 41):
    """Return a minimal private-message double."""
    message = MagicMock()
    message.chat.id = telegram_id
    message.answer = AsyncMock()
    return message


@contextlib.contextmanager
def _registered_jira_provider():
    """Temporarily register a connectable Jira OAuth2 provider."""
    OAuth2ProviderRegistry._reset()
    OAuth2ProviderRegistry().register(
        SimpleNamespace(provider_id="jira", display_name="Jira", icon=None, default_scopes=[], manager=MagicMock())
    )
    try:
        yield
    finally:
        OAuth2ProviderRegistry._reset()


def test_jira_registered_when_services_available(wrapper_cls, config_with_jira) -> None:
    """The generic registry supplies Jira when the app services are available."""
    with _registered_jira_provider():
        wrapper = _blank_wrapper(wrapper_cls, config_with_jira, app={"authdb": MagicMock()})
        wrapper._integrations_service = MagicMock(return_value=MagicMock())
        wrapper._init_post_auth_providers()
    assert "jira" in wrapper._post_auth_registry


def test_jira_registered_when_db_key_is_database(wrapper_cls, config_with_jira) -> None:
    """The legacy database app key remains compatible with provider registration."""
    with _registered_jira_provider():
        wrapper = _blank_wrapper(wrapper_cls, config_with_jira, app={"database": MagicMock()})
        wrapper._integrations_service = MagicMock(return_value=MagicMock())
        wrapper._init_post_auth_providers()
    assert "jira" in wrapper._post_auth_registry


@pytest.mark.asyncio
async def test_combined_callback_uses_separate_candidate(wrapper_cls, config_with_jira) -> None:
    """Primary callback state never mutates the active unauthenticated session."""
    wrapper = _blank_wrapper(wrapper_cls, config_with_jira)
    active = TelegramUserSession(telegram_id=41, telegram_username="user")

    async def authenticate(data, candidate):
        assert data == {"user_id": "nav-1", "token": "signed"}
        assert candidate is not active
        candidate.set_authenticated("nav-1", "signed", "Alice", "alice@example.com")
        return True

    wrapper._auth_strategy.handle_callback = AsyncMock(side_effect=authenticate)
    wrapper._start_login_attempt = AsyncMock()

    await wrapper._handle_combined_auth(
        _message(),
        {"user_id": "nav-1", "token": "signed"},
        active,
    )

    assert not active.authenticated
    candidate = wrapper._start_login_attempt.await_args.args[1]
    assert candidate.authenticated
    assert candidate.nav_user_id == "nav-1"


@pytest.mark.asyncio
async def test_invalid_primary_never_starts_provider_state(wrapper_cls, config_with_jira) -> None:
    """Rejected primary credentials cannot mint secondary provider state."""
    wrapper = _blank_wrapper(wrapper_cls, config_with_jira)
    wrapper._auth_strategy.handle_callback = AsyncMock(return_value=False)
    wrapper._start_login_attempt = AsyncMock()
    message = _message()

    await wrapper._handle_combined_auth(message, {"user_id": "forged"}, TelegramUserSession(telegram_id=41))

    wrapper._start_login_attempt.assert_not_awaited()
    assert "Login failed" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_start_attempt_builds_url_from_pending_candidate(wrapper_cls, config_with_jira) -> None:
    """Secondary state is built only from the coordinator-owned pending attempt."""
    wrapper = _blank_wrapper(wrapper_cls, config_with_jira)
    provider = MagicMock(provider_name="jira")
    provider.build_auth_url = AsyncMock(return_value="https://jira.example/authorize")
    wrapper._post_auth_registry.register(provider)
    candidate = TelegramUserSession(telegram_id=41)
    candidate.set_authenticated("nav-1", "signed", "Alice")
    message = _message()

    await wrapper._start_login_attempt(message, candidate)

    attempt = provider.build_auth_url.await_args.args[0]
    assert attempt.candidate is candidate
    assert attempt.principal.user_id == "nav-1"
    assert wrapper._user_sessions == {}
    assert message.answer.await_args.kwargs["parse_mode"] is None


@pytest.mark.asyncio
async def test_required_missing_provider_discards_candidate(wrapper_cls, config_with_jira) -> None:
    """A required missing provider reports failure without publishing the candidate."""
    wrapper = _blank_wrapper(wrapper_cls, config_with_jira)
    candidate = TelegramUserSession(telegram_id=41)
    candidate.set_authenticated("nav-1", "signed", "Alice")

    await wrapper._start_login_attempt(_message(), candidate)

    assert wrapper._user_sessions == {}
    wrapper._persist_principal_link.assert_not_awaited()
    assert wrapper.bot.send_message.await_args.kwargs["parse_mode"] is None


@pytest.mark.asyncio
async def test_finalize_publishes_candidate_after_link_attempt(wrapper_cls, config_with_jira) -> None:
    """Final success links once, promotes once, then initializes user context."""
    wrapper = _blank_wrapper(wrapper_cls, config_with_jira)
    candidate = TelegramUserSession(telegram_id=41)
    candidate.set_authenticated("nav-1", "signed", "Alice")
    attempt = wrapper._login_coordinator.create(
        telegram_id=41,
        chat_id=41,
        bot_id="7001",
        principal=MagicMock(user_id="nav-1"),
        permission_context=MagicMock(),
        candidate=candidate,
        actions=config_with_jira.post_auth_actions,
        expires_at=10**12,
    )
    attempt.completed.add("jira")

    await wrapper._finalize_login_attempt(attempt)

    wrapper._persist_principal_link.assert_awaited_once_with(candidate)
    assert wrapper._user_sessions[41] is candidate
    wrapper._initialize_user_context.assert_awaited_once_with(candidate)
