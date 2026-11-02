"""Tests for generic Telegram connection post-auth providers (FEAT-776 M9)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.principal import Principal
from parrot.integrations.core.auth.post_auth import PostAuthRegistry
from parrot.integrations.telegram.models import PostAuthAction
from parrot.integrations.telegram.post_auth_connection import ConnectionPostAuthProvider, PendingLoginAttempt
from parrot.integrations.telegram.post_auth_jira import JiraPostAuthProvider
from parrot.integrations.telegram.wrapper import TelegramAgentWrapper


@pytest.fixture(autouse=True)
def reset_provider_registry() -> None:
    """Keep singleton provider registrations isolated across tests."""
    OAuth2ProviderRegistry._reset()
    yield
    OAuth2ProviderRegistry._reset()


def _attempt() -> PendingLoginAttempt:
    principal = Principal(
        user_id="1042",
        channel="telegram",
        channel_user_id="88123",
    )
    permission_context = PermissionContext(
        session=UserSession(user_id="1042", tenant_id="tenant-a", roles=frozenset()),
        channel="telegram",
        channel_user_id="88123",
    )
    return PendingLoginAttempt(
        attempt_id="attempt-1",
        telegram_id=88123,
        chat_id=88123,
        bot_id="7001",
        principal=principal,
        permission_context=permission_context,
        candidate=MagicMock(),
        actions=[PostAuthAction(provider="o365", required=True)],
        expires_at=1000.0,
    )


async def test_connection_post_auth_build_and_handle() -> None:
    """Build trusted state, then consume a retained callback exactly once."""
    service = MagicMock()
    service.start_connect = AsyncMock(return_value=SimpleNamespace(auth_url="https://provider.example/authorize"))
    manager = MagicMock()
    manager.handle_callback = AsyncMock(
        side_effect=[
            (
                MagicMock(),
                {
                    "nav_user_id": "1042",
                    "extra": {
                        "attempt_id": "attempt-1",
                        "bot_id": "7001",
                        "combined": True,
                    },
                },
            ),
            ValueError("Invalid or expired state nonce."),
        ]
    )
    OAuth2ProviderRegistry().register(SimpleNamespace(provider_id="o365", manager=manager))
    provider = ConnectionPostAuthProvider("o365", service=service, app={})
    attempt = _attempt()

    assert await provider.build_auth_url(attempt, MagicMock(), "https://callback.example") == (
        "https://provider.example/authorize"
    )
    service.start_connect.assert_awaited_once_with(
        "1042",
        "o365",
        channel="telegram",
        principal=attempt.principal,
        extra_state={
            "chat_id": 88123,
            "bot_id": "7001",
            "attempt_id": "attempt-1",
            "combined": True,
        },
        permission_context=attempt.permission_context,
    )

    payload = {"code": "code-1", "state": "state-1"}
    assert await provider.handle_result(payload, attempt, {}) is True
    assert await provider.handle_result(payload, attempt, {}) is False
    manager.handle_callback.assert_awaited_once_with("code-1", "state-1")


async def test_build_auth_url_refuses_non_attempt_session() -> None:
    """Provider state cannot be minted from an active or unauthenticated session."""
    service = MagicMock()
    service.start_connect = AsyncMock()
    provider = ConnectionPostAuthProvider("o365", service=service, app={})

    with pytest.raises(ValueError, match="verified pending login attempt"):
        await provider.build_auth_url(MagicMock(), MagicMock(), "https://callback.example")

    service.start_connect.assert_not_awaited()


async def test_required_start_failure_raises() -> None:
    """PBAC denial remains a required-step failure for the coordinator."""
    service = MagicMock()
    service.start_connect = AsyncMock(side_effect=PermissionError("denied"))
    provider = ConnectionPostAuthProvider("o365", service=service, app={})

    with pytest.raises(PermissionError, match="denied"):
        await provider.build_auth_url(_attempt(), MagicMock(), "https://callback.example")


async def test_unsupported_authorization_mode_raises() -> None:
    """A provider without a browser URL cannot be silently skipped."""
    service = MagicMock()
    service.start_connect = AsyncMock(return_value=SimpleNamespace(auth_url=None))
    provider = ConnectionPostAuthProvider("o365", service=service, app={})

    with pytest.raises(ValueError, match="does not support URL authorization"):
        await provider.build_auth_url(_attempt(), MagicMock(), "https://callback.example")


def _wrapper(actions: list[PostAuthAction], service: object) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(post_auth_actions=actions),
        app={},
        logger=MagicMock(),
        _post_auth_registry=PostAuthRegistry(),
        _integrations_service=MagicMock(return_value=service),
    )


def test_post_auth_any_registered_provider() -> None:
    """Any startup provider with a manager is exposed through the generic preset."""
    service = MagicMock()
    OAuth2ProviderRegistry().register(SimpleNamespace(provider_id="o365", manager=MagicMock()))
    wrapper = _wrapper([PostAuthAction(provider="o365", required=True)], service)

    TelegramAgentWrapper._init_post_auth_providers(wrapper)

    provider = wrapper._post_auth_registry.get("o365")
    assert isinstance(provider, ConnectionPostAuthProvider)
    assert not isinstance(provider, JiraPostAuthProvider)
    assert provider._service is service


def test_jira_registered_through_preset() -> None:
    """Jira retains its YAML-compatible preset while using generic behavior."""
    OAuth2ProviderRegistry().register(SimpleNamespace(provider_id="jira", manager=MagicMock()))
    wrapper = _wrapper([PostAuthAction(provider="jira", required=True)], MagicMock())

    TelegramAgentWrapper._init_post_auth_providers(wrapper)

    assert isinstance(wrapper._post_auth_registry.get("jira"), JiraPostAuthProvider)


def test_unknown_provider_warns_and_is_skipped() -> None:
    """Unregistered startup providers are soft failures."""
    wrapper = _wrapper([PostAuthAction(provider="unknown")], MagicMock())

    TelegramAgentWrapper._init_post_auth_providers(wrapper)

    assert len(wrapper._post_auth_registry) == 0
    wrapper.logger.warning.assert_called_once_with(
        "post_auth_actions provider '%s' is not a registered provider at startup; skipping.",
        "unknown",
    )
