"""FEAT-791: Jira provider registration at BotManager setup time."""

from unittest.mock import Mock

import pytest
from aiohttp import web

from parrot.auth.jira_oauth import JiraOAuthManager
from parrot.auth.oauth2.jira_provider import JiraOAuth2Provider
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.manager.manager import BotManager


def _manager() -> BotManager:
    manager = object.__new__(BotManager)
    manager.logger = Mock()
    return manager


@pytest.fixture(autouse=True)
def reset_oauth2_provider_registry():
    """Isolate the process-wide provider registry between tests."""
    OAuth2ProviderRegistry._reset()
    yield
    OAuth2ProviderRegistry._reset()


def _configure_jira(monkeypatch) -> None:
    monkeypatch.setattr("parrot.conf.JIRA_CLIENT_ID", "client-id")
    monkeypatch.setattr("parrot.conf.JIRA_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr("parrot.conf.JIRA_REDIRECT_URI", "https://example.test/api/auth/jira/callback")


def test_jira_provider_registered_when_configured(monkeypatch):
    """Configured Jira builds a manager, registers one provider, mounts routes."""
    _configure_jira(monkeypatch)
    app = web.Application()

    _manager()._register_jira_oauth2_provider(app)

    provider = OAuth2ProviderRegistry().get("jira")
    assert isinstance(provider, JiraOAuth2Provider)

    registered_manager = app["jira_oauth_manager"]
    assert isinstance(registered_manager, JiraOAuthManager)
    assert provider.manager is registered_manager
    # setup() publishes the manager under both keys.
    assert app["oauth2_manager_jira"] is registered_manager
    assert app["_jira_oauth2_provider_registered"] is True
    # The Jira callback route is mounted while the app is still mutable.
    assert list(app.router.routes())


def test_jira_provider_not_registered_when_unconfigured(monkeypatch):
    """An unset Jira client id registers no provider and mounts no route."""
    monkeypatch.setattr("parrot.conf.JIRA_CLIENT_ID", None)
    app = web.Application()

    _manager()._register_jira_oauth2_provider(app)

    assert OAuth2ProviderRegistry().get("jira") is None
    assert "jira_oauth_manager" not in app
    assert "oauth2_manager_jira" not in app
    assert not list(app.router.routes())


def test_jira_provider_reuses_existing_manager(monkeypatch):
    """A manager already built by the Slack/Teams path is reused, not replaced."""
    _configure_jira(monkeypatch)
    app = web.Application()
    existing_manager = Mock()
    app["jira_oauth_manager"] = existing_manager

    _manager()._register_jira_oauth2_provider(app)

    provider = OAuth2ProviderRegistry().get("jira")
    assert isinstance(provider, JiraOAuth2Provider)
    assert provider.manager is existing_manager
    assert app["jira_oauth_manager"] is existing_manager
    # Reusing must not re-run setup() — it raises when the key holds another instance.
    existing_manager.setup.assert_not_called()


def test_jira_provider_reuses_manager_under_oauth2_key(monkeypatch):
    """The alternate app key set by JiraOAuthManager.setup() is honoured too."""
    _configure_jira(monkeypatch)
    app = web.Application()
    existing_manager = Mock()
    app["oauth2_manager_jira"] = existing_manager

    _manager()._register_jira_oauth2_provider(app)

    assert OAuth2ProviderRegistry().get("jira").manager is existing_manager
    existing_manager.setup.assert_not_called()


def test_jira_provider_registration_is_idempotent(monkeypatch):
    """Calling the registrar twice leaves exactly one provider in place."""
    _configure_jira(monkeypatch)
    app = web.Application()
    manager = _manager()

    manager._register_jira_oauth2_provider(app)
    provider = OAuth2ProviderRegistry().get("jira")
    manager._register_jira_oauth2_provider(app)

    assert OAuth2ProviderRegistry().get("jira") is provider
    assert len([p for p in OAuth2ProviderRegistry().all() if p.provider_id == "jira"]) == 1


@pytest.mark.asyncio
async def test_startup_does_not_double_register(monkeypatch):
    """_register_oauth2_providers finds the manager already set and re-registers once."""
    _configure_jira(monkeypatch)
    app = web.Application()
    manager = _manager()

    manager._register_jira_oauth2_provider(app)
    registered_manager = app["jira_oauth_manager"]

    await manager._register_oauth2_providers(app)

    providers = [p for p in OAuth2ProviderRegistry().all() if p.provider_id == "jira"]
    assert len(providers) == 1
    assert providers[0].manager is registered_manager


def test_jira_provider_never_raises_on_bad_config(monkeypatch):
    """A construction failure is logged, not propagated — startup must not break."""
    _configure_jira(monkeypatch)
    monkeypatch.setattr(
        "parrot.auth.jira_oauth.JiraOAuthManager.setup",
        Mock(side_effect=RuntimeError("boom")),
    )
    app = web.Application()
    manager = _manager()

    manager._register_jira_oauth2_provider(app)

    assert OAuth2ProviderRegistry().get("jira") is None
    assert "_jira_oauth2_provider_registered" not in app
    manager.logger.exception.assert_called_once()
