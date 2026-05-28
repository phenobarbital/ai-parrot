"""Tests for TelegramBotsConfig.validate() multi-auth rules (TASK-784).

Verifies:
- Multi-auth configs with valid setup pass validation.
- Missing login_multi.html reference raises error.
- Per-method oauth2/azure validation fires for auth_methods list entries.
- Legacy single-method configs still pass.
"""
import pytest

from parrot.integrations.telegram.models import (
    TelegramAgentConfig,
    TelegramBotsConfig,
)

MULTI_URL = "https://nav.example.com/static/telegram/login_multi.html"
BASIC_URL = "https://nav.example.com/static/telegram/login.html"
AUTH_URL  = "https://nav.example.com/api/v1/login"
AZURE_URL = "https://nav.example.com/api/v1/auth/azure/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(**overrides) -> TelegramAgentConfig:
    base = dict(
        name="bot",
        chatbot_id="b",
        bot_token="tok",
        auth_url=AUTH_URL,
        auth_methods=["basic", "azure"],
        azure_auth_url=AZURE_URL,
        login_page_url=MULTI_URL,
    )
    base.update(overrides)
    return TelegramAgentConfig(**base)


def _bots(cfg: TelegramAgentConfig) -> TelegramBotsConfig:
    return TelegramBotsConfig(agents={"bot": cfg})


# ---------------------------------------------------------------------------
# Valid configs
# ---------------------------------------------------------------------------

def test_multi_auth_valid_passes():
    """basic + azure with login_multi.html → no errors."""
    bots = _bots(_cfg())
    assert bots.validate() == []


def test_single_basic_valid():
    """Single basic auth (legacy form) → no errors."""
    cfg = TelegramAgentConfig(
        name="bot", chatbot_id="b", bot_token="tok",
        auth_method="basic",
        auth_url=AUTH_URL,
        login_page_url=BASIC_URL,
    )
    assert _bots(cfg).validate() == []


def test_single_azure_valid():
    """Single azure auth → no errors."""
    cfg = TelegramAgentConfig(
        name="bot", chatbot_id="b", bot_token="tok",
        auth_method="azure",
        auth_url=AUTH_URL,
        azure_auth_url=AZURE_URL,
        login_page_url=BASIC_URL,
    )
    assert _bots(cfg).validate() == []


def test_no_auth_configured_valid():
    """Bot without auth → no errors (auth is optional)."""
    cfg = TelegramAgentConfig(
        name="bot", chatbot_id="b", bot_token="tok",
        auth_method="",
        auth_methods=[],
    )
    assert _bots(cfg).validate() == []


# ---------------------------------------------------------------------------
# Multi-auth login_page_url constraint
# ---------------------------------------------------------------------------

def test_multi_auth_missing_login_page_url_errors():
    """auth_methods >= 2 with no login_page_url → error."""
    cfg = _cfg(login_page_url=None)
    errors = _bots(cfg).validate()
    assert any("login_page_url is unset" in e for e in errors)


def test_multi_auth_wrong_login_page_url_errors():
    """auth_methods >= 2 with login_page_url not referencing login_multi.html → error."""
    cfg = _cfg(login_page_url=BASIC_URL)
    errors = _bots(cfg).validate()
    assert any("login_multi.html" in e for e in errors)


def test_multi_auth_login_page_url_case_insensitive():
    """login_multi.html check is case-insensitive."""
    cfg = _cfg(login_page_url="https://nav.example.com/static/telegram/LOGIN_MULTI.HTML")
    assert _bots(cfg).validate() == []


# ---------------------------------------------------------------------------
# Per-method OAuth2 validation
# ---------------------------------------------------------------------------

def test_oauth2_in_multi_missing_client_id_errors():
    """auth_methods includes 'oauth2' without oauth2_client_id → error."""
    cfg = _cfg(
        auth_methods=["basic", "oauth2"],
        oauth2_client_id=None,
        oauth2_client_secret="csecret",
        oauth2_redirect_uri="https://nav.example.com/oauth2/callback",
        azure_auth_url=None,
    )
    errors = _bots(cfg).validate()
    assert any("oauth2_client_id" in e for e in errors)


def test_oauth2_in_multi_missing_client_secret_errors():
    """auth_methods includes 'oauth2' without oauth2_client_secret → error."""
    cfg = _cfg(
        auth_methods=["basic", "oauth2"],
        oauth2_client_id="cid",
        oauth2_client_secret=None,
        oauth2_redirect_uri="https://nav.example.com/oauth2/callback",
        azure_auth_url=None,
    )
    errors = _bots(cfg).validate()
    assert any("oauth2_client_secret" in e for e in errors)


# ---------------------------------------------------------------------------
# Per-method Azure validation
# ---------------------------------------------------------------------------

def test_azure_in_multi_missing_both_urls_errors():
    """auth_methods includes 'azure' without azure_auth_url or auth_url → error."""
    cfg = TelegramAgentConfig(
        name="bot", chatbot_id="b", bot_token="tok",
        auth_methods=["basic", "azure"],
        auth_url=None,
        azure_auth_url=None,
        login_page_url=MULTI_URL,
    )
    errors = _bots(cfg).validate()
    assert any("'azure' requires" in e or "azure_auth_url" in e for e in errors)


def test_azure_in_multi_with_auth_url_passes():
    """auth_url present allows derivation → no azure error."""
    cfg = _cfg(azure_auth_url=None)  # auth_url present → derivable
    errors = _bots(cfg).validate()
    # No azure-specific error; maybe other errors for something else
    assert all("'azure' requires" not in e for e in errors)


# ---------------------------------------------------------------------------
# Missing required base fields
# ---------------------------------------------------------------------------

def test_missing_chatbot_id_errors():
    cfg = _cfg(chatbot_id="")
    errors = _bots(cfg).validate()
    assert any("chatbot_id" in e for e in errors)


def test_missing_bot_token_errors():
    cfg = TelegramAgentConfig(
        name="bot", chatbot_id="b",
        bot_token=None,
        auth_methods=["basic"],
        auth_url=AUTH_URL,
    )
    errors = _bots(cfg).validate()
    assert any("bot_token" in e for e in errors)
