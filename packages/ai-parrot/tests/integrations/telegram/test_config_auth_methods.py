"""Tests for TelegramAgentConfig auth_methods list field (TASK-780).

Verifies:
- Legacy auth_method singleton normalizes to auth_methods list.
- Explicit auth_methods list is preserved.
- String form in from_dict normalizes to list.
- Unknown method raises ValueError.
- Env-var derivation fires for every method in the list.
"""
import pytest
from unittest.mock import patch

from parrot.integrations.telegram.models import TelegramAgentConfig


def _cfg(**kwargs) -> TelegramAgentConfig:
    """Minimal TelegramAgentConfig factory without env-var side-effects."""
    defaults = {
        "name": "bot",
        "chatbot_id": "b",
        "bot_token": "tok",
        "auth_url": "https://nav.example.com/api/v1/login",
    }
    defaults.update(kwargs)
    return TelegramAgentConfig(**defaults)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def test_legacy_single_method_normalizes_to_list():
    """auth_method='azure' (no auth_methods) → auth_methods=['azure']."""
    cfg = _cfg(auth_method="azure", azure_auth_url="https://nav.example.com/api/v1/azure/")
    assert cfg.auth_methods == ["azure"]


def test_legacy_basic_method_normalizes_to_list():
    """auth_method='basic' (default) → auth_methods=['basic']."""
    cfg = _cfg()
    assert cfg.auth_methods == ["basic"]


def test_explicit_list_preserved():
    """Explicit auth_methods list is left unchanged."""
    cfg = _cfg(
        auth_methods=["basic", "azure"],
        azure_auth_url="https://nav.example.com/api/v1/azure/",
    )
    assert cfg.auth_methods == ["basic", "azure"]


def test_explicit_list_takes_priority_over_auth_method():
    """When both auth_method and auth_methods are set, auth_methods wins."""
    cfg = _cfg(
        auth_method="basic",
        auth_methods=["azure"],
        azure_auth_url="https://nav.example.com/api/v1/azure/",
    )
    assert cfg.auth_methods == ["azure"]


def test_no_auth_leaves_empty():
    """No auth_method and no auth_methods → auth_methods stays empty."""
    cfg = TelegramAgentConfig(
        name="bot",
        chatbot_id="b",
        bot_token="tok",
        auth_url="https://nav.example.com/api/v1/login",
        auth_method="",
        auth_methods=[],
    )
    assert cfg.auth_methods == []


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_unknown_method_raises():
    """Unknown auth_methods entry raises ValueError."""
    with pytest.raises(ValueError, match="unknown"):
        _cfg(auth_methods=["linkedin"])


def test_unknown_method_in_mixed_list_raises():
    """Even one unknown method in a list raises."""
    with pytest.raises(ValueError, match="unknown"):
        _cfg(auth_methods=["basic", "linkedin"])


# ---------------------------------------------------------------------------
# Env-var derivation — generalised to auth_methods list
# ---------------------------------------------------------------------------

def test_azure_env_derivation_fires_with_list():
    """Azure URL derivation fires when 'azure' is in auth_methods list."""
    cfg = _cfg(
        auth_methods=["basic", "azure"],
        # auth_url has /login suffix → azure URL derived by replacing it
    )
    assert cfg.azure_auth_url == "https://nav.example.com/api/v1/azure/"


def test_azure_env_derivation_fires_without_explicit_auth_method():
    """Derivation fires even when auth_method is 'basic' (singleton)."""
    cfg = _cfg(
        auth_method="basic",
        auth_methods=["basic", "azure"],
    )
    assert cfg.azure_auth_url == "https://nav.example.com/api/v1/azure/"


@patch("parrot.integrations.telegram.models.config")
def test_oauth2_env_derivation_fires_with_list(mock_config):
    """OAuth2 env-var lookup fires when 'oauth2' is in auth_methods list."""
    mock_config.get.side_effect = lambda key: (
        "client-id" if key == "BOT_OAUTH2_CLIENT_ID" else
        "client-secret" if key == "BOT_OAUTH2_CLIENT_SECRET" else
        None
    )
    cfg = TelegramAgentConfig(
        name="bot",
        chatbot_id="b",
        bot_token="tok",
        auth_url="https://nav.example.com/api/v1/login",
        auth_method="basic",
        auth_methods=["basic", "oauth2"],
        oauth2_redirect_uri="https://nav.example.com/oauth/callback",
    )
    assert cfg.oauth2_client_id == "client-id"
    assert cfg.oauth2_client_secret == "client-secret"


# ---------------------------------------------------------------------------
# from_dict — accept string or list form
# ---------------------------------------------------------------------------

def test_from_dict_accepts_list():
    """from_dict with auth_methods as a list preserves it."""
    cfg = TelegramAgentConfig.from_dict(
        "bot",
        {
            "chatbot_id": "b",
            "bot_token": "tok",
            "auth_methods": ["basic", "azure"],
            "auth_url": "https://nav.example.com/api/v1/login",
        },
    )
    assert cfg.auth_methods == ["basic", "azure"]


def test_from_dict_accepts_string():
    """from_dict with auth_methods as a string normalizes to list."""
    cfg = TelegramAgentConfig.from_dict(
        "bot",
        {
            "chatbot_id": "b",
            "bot_token": "tok",
            "auth_methods": "azure",
            "auth_url": "https://nav.example.com/api/v1/login",
        },
    )
    assert cfg.auth_methods == ["azure"]


def test_from_dict_without_auth_methods_uses_auth_method():
    """from_dict with only auth_method normalizes via __post_init__."""
    cfg = TelegramAgentConfig.from_dict(
        "bot",
        {
            "chatbot_id": "b",
            "bot_token": "tok",
            "auth_method": "basic",
            "auth_url": "https://nav.example.com/api/v1/login",
        },
    )
    assert cfg.auth_methods == ["basic"]
