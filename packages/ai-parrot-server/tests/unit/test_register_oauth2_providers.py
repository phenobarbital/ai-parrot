"""Tests for BotManager OAuth2 provider startup registration."""

from unittest.mock import Mock

import pytest
from aiohttp import web

from parrot.manager.manager import BotManager


@pytest.mark.asyncio
async def test_register_oauth2_providers_from_descriptors(monkeypatch, tmp_path):
    """Register descriptor providers and the Identity principal resolver."""
    descriptor_file = tmp_path / "providers.yaml"
    descriptor_file.write_text("providers: []\n", encoding="utf-8")

    app = web.Application()
    app["authdb"] = object()
    app["connection_event_publisher"] = Mock()
    manager = object.__new__(BotManager)
    manager.logger = Mock()

    descriptors = [Mock(provider_id="example")]
    providers = [Mock(provider_id="example")]
    load_descriptors = Mock(return_value=descriptors)
    register_descriptors = Mock(return_value=providers)
    credential_store = Mock()
    resolver = Mock()
    set_resolver = Mock()

    monkeypatch.setattr("parrot.conf.OAUTH2_PROVIDERS_FILE", str(descriptor_file))
    monkeypatch.setattr("parrot.auth.oauth2.descriptor.load_provider_descriptors", load_descriptors)
    monkeypatch.setattr("parrot.auth.oauth2.descriptor.register_descriptor_providers", register_descriptors)
    monkeypatch.setattr("parrot.services.identity_credential_sink.IdentityVaultCredentialStore", credential_store)
    monkeypatch.setattr("parrot.services.identity_principal.IdentityPrincipalResolver", resolver)
    monkeypatch.setattr("parrot.auth.principal.set_principal_resolver", set_resolver)

    await manager._register_oauth2_providers(app)

    load_descriptors.assert_called_once_with(str(descriptor_file))
    credential_store.assert_called_once_with(app["authdb"])
    register_descriptors.assert_called_once_with(
        descriptors,
        app=app,
        credential_store=credential_store.return_value,
        event_publisher=app["connection_event_publisher"],
    )
    resolver.assert_called_once_with(app["authdb"])
    set_resolver.assert_called_once_with(resolver.return_value)


@pytest.mark.asyncio
async def test_bad_descriptor_file_does_not_break_startup(monkeypatch):
    """Descriptor loading failures are logged and do not escape startup."""
    app = web.Application()
    manager = object.__new__(BotManager)
    manager.logger = Mock()

    monkeypatch.setattr("parrot.conf.OAUTH2_PROVIDERS_FILE", "/missing/providers.yaml")
    monkeypatch.setattr(
        "parrot.auth.oauth2.descriptor.load_provider_descriptors",
        Mock(side_effect=ValueError("bad descriptor")),
    )

    await manager._register_oauth2_providers(app)

    manager.logger.exception.assert_called()
