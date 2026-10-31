"""FEAT-777 M3: O365 provider registration at BotManager setup time."""

from unittest.mock import Mock

import pytest
from aiohttp import web

from parrot.auth.oauth2.o365_provider import O365OAuth2Provider
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


def _configure_o365(monkeypatch) -> None:
    monkeypatch.setattr("parrot.conf.O365_CLIENT_ID", "client-id")
    monkeypatch.setattr("parrot.conf.O365_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr("parrot.conf.O365_REDIRECT_URI", "https://example.test/oauth/callback")
    monkeypatch.setattr("parrot.conf.O365_TENANT_ID", "tenant-id")


@pytest.mark.asyncio
async def test_o365_provider_registered_when_configured(monkeypatch):
    """Configured O365 registers one provider and backfills its event publisher."""
    _configure_o365(monkeypatch)
    app = web.Application()
    app["redis"] = Mock()
    manager = _manager()

    manager._register_o365_oauth2_provider(app)
    provider = OAuth2ProviderRegistry().get("o365")
    registered_manager = app["oauth2_manager_o365"]

    assert isinstance(provider, O365OAuth2Provider)
    assert provider.manager is registered_manager
    assert registered_manager._events is None

    publisher = Mock()
    app["connection_event_publisher"] = publisher
    await manager._register_oauth2_providers(app)
    assert registered_manager._events is publisher

    manager._register_o365_oauth2_provider(app)
    assert OAuth2ProviderRegistry().get("o365") is provider


def test_o365_provider_absent_when_unconfigured(monkeypatch):
    """An unset O365 client id registers no provider or callback route."""
    monkeypatch.setattr("parrot.conf.O365_CLIENT_ID", None)
    app = web.Application()

    _manager()._register_o365_oauth2_provider(app)

    assert OAuth2ProviderRegistry().get("o365") is None
    assert "oauth2_manager_o365" not in app
    assert not list(app.router.routes())


def test_o365_provider_reuses_existing_manager(monkeypatch):
    """A pre-existing app O365 manager is reused without replacement."""
    _configure_o365(monkeypatch)
    app = web.Application()
    existing_manager = Mock()
    app["oauth2_manager_o365"] = existing_manager

    _manager()._register_o365_oauth2_provider(app)

    provider = OAuth2ProviderRegistry().get("o365")
    assert isinstance(provider, O365OAuth2Provider)
    assert provider.manager is existing_manager
    assert app["oauth2_manager_o365"] is existing_manager
    existing_manager.setup.assert_not_called()
