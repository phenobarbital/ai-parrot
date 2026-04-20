"""Tests for AzureAuthStrategy post-auth chain compatibility (TASK-778).

Verifies:
- build_login_keyboard embeds next_auth_url / next_auth_required in the URL.
- handle_callback invokes the post_auth chain via injected registry.
- supports_post_auth_chain is True after TASK-778.
- Backward-compat: strategy works without a registry (no chain).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json
import base64

from parrot.integrations.telegram.auth import AzureAuthStrategy, TelegramUserSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session() -> TelegramUserSession:
    return TelegramUserSession(
        telegram_id=42,
        telegram_username="azureuser",
    )


def _make_jwt(payload: dict) -> str:
    """Build a minimal fake JWT (unsigned) for testing."""
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    body_bytes = json.dumps(payload).encode()
    body = base64.urlsafe_b64encode(body_bytes).rstrip(b"=").decode()
    return f"{header}.{body}.fakesig"


# ---------------------------------------------------------------------------
# Capability flag
# ---------------------------------------------------------------------------

def test_capability_flag_is_true():
    """AzureAuthStrategy.supports_post_auth_chain must be True after TASK-778."""
    assert AzureAuthStrategy.supports_post_auth_chain is True


# ---------------------------------------------------------------------------
# build_login_keyboard — next_auth_url propagation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_login_keyboard_embeds_next_auth_url():
    """next_auth_url and next_auth_required are embedded in the WebApp URL."""
    strategy = AzureAuthStrategy(
        auth_url="https://nav.example.com/api/v1/login",
        azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
        login_page_url="https://nav.example.com/static/telegram/azure_login.html",
    )
    config = MagicMock()
    config.login_page_url = None

    kb = await strategy.build_login_keyboard(
        config=config,
        state="nonce123",
        next_auth_url="https://jira.example.com/oauth/authorize?x=y",
        next_auth_required=True,
    )

    url = kb.keyboard[0][0].web_app.url
    assert "next_auth_url=" in url
    assert "next_auth_required=true" in url


@pytest.mark.asyncio
async def test_build_login_keyboard_no_next_auth_url():
    """Without next_auth_url, the URL only contains azure_auth_url."""
    strategy = AzureAuthStrategy(
        auth_url="https://nav.example.com/api/v1/login",
        azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
        login_page_url="https://nav.example.com/static/telegram/azure_login.html",
    )
    config = MagicMock()
    config.login_page_url = None

    kb = await strategy.build_login_keyboard(config=config, state="s")
    url = kb.keyboard[0][0].web_app.url

    assert "azure_auth_url=" in url
    assert "next_auth_url" not in url
    assert "next_auth_required" not in url


@pytest.mark.asyncio
async def test_build_login_keyboard_next_auth_required_false():
    """next_auth_required=False embeds 'next_auth_required=false'."""
    strategy = AzureAuthStrategy(
        auth_url="https://nav.example.com/api/v1/login",
        azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
        login_page_url="https://nav.example.com/static/telegram/azure_login.html",
    )
    config = MagicMock()
    config.login_page_url = None

    kb = await strategy.build_login_keyboard(
        config=config,
        state="s",
        next_auth_url="https://jira.example.com/oauth",
        next_auth_required=False,
    )
    url = kb.keyboard[0][0].web_app.url
    assert "next_auth_required=false" in url


# ---------------------------------------------------------------------------
# handle_callback — post_auth chain invocation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_callback_triggers_post_auth_chain():
    """When a registry is injected, handle_callback invokes the chain."""
    registry = MagicMock()
    registry.__len__ = MagicMock(return_value=1)
    registry.providers = ["jira"]
    jira_provider = MagicMock()
    jira_provider.handle_result = AsyncMock(return_value=True)
    registry.get = MagicMock(return_value=jira_provider)

    strategy = AzureAuthStrategy(
        auth_url="https://nav.example.com/api/v1/login",
        azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
        post_auth_registry=registry,
    )
    session = _make_session()

    jwt = _make_jwt({"user_id": "u1", "email": "u1@example.com", "name": "Alice"})
    ok = await strategy.handle_callback(
        {"auth_method": "azure", "token": jwt},
        session,
    )

    assert ok is True
    assert session.authenticated is True
    jira_provider.handle_result.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_callback_no_registry_still_succeeds():
    """Without a registry, handle_callback succeeds without chain."""
    strategy = AzureAuthStrategy(
        auth_url="https://nav.example.com/api/v1/login",
        azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
        # No post_auth_registry
    )
    session = _make_session()
    jwt = _make_jwt({"user_id": "u2", "email": "u2@example.com", "name": "Bob"})
    ok = await strategy.handle_callback(
        {"auth_method": "azure", "token": jwt},
        session,
    )
    assert ok is True
    assert session.authenticated is True


@pytest.mark.asyncio
async def test_handle_callback_chain_failure_does_not_roll_back():
    """Post-auth chain failure is logged but does NOT invalidate the session."""
    registry = MagicMock()
    registry.__len__ = MagicMock(return_value=1)
    registry.providers = ["jira"]
    jira_provider = MagicMock()
    jira_provider.handle_result = AsyncMock(return_value=False)
    registry.get = MagicMock(return_value=jira_provider)

    strategy = AzureAuthStrategy(
        auth_url="https://nav.example.com/api/v1/login",
        azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
        post_auth_registry=registry,
    )
    session = _make_session()
    jwt = _make_jwt({"user_id": "u3", "email": "u3@example.com", "name": "Carol"})
    ok = await strategy.handle_callback(
        {"auth_method": "azure", "token": jwt},
        session,
    )
    # Primary auth should still succeed even if the chain fails.
    assert ok is True
    assert session.authenticated is True


@pytest.mark.asyncio
async def test_handle_callback_chain_exception_does_not_roll_back():
    """Exceptions in a chain provider are swallowed; primary auth persists."""
    registry = MagicMock()
    registry.__len__ = MagicMock(return_value=1)
    registry.providers = ["jira"]
    jira_provider = MagicMock()
    jira_provider.handle_result = AsyncMock(side_effect=RuntimeError("boom"))
    registry.get = MagicMock(return_value=jira_provider)

    strategy = AzureAuthStrategy(
        auth_url="https://nav.example.com/api/v1/login",
        azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
        post_auth_registry=registry,
    )
    session = _make_session()
    jwt = _make_jwt({"user_id": "u4", "email": "u4@example.com", "name": "Dave"})
    ok = await strategy.handle_callback(
        {"auth_method": "azure", "token": jwt},
        session,
    )
    assert ok is True
    assert session.authenticated is True
