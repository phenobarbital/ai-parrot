"""Unit tests for the ``device_code`` credential resolver factory branch."""

import pytest

from parrot.auth.broker import CredentialBroker, CredentialResolverFactory
from parrot.auth.credentials import ProviderCredentialConfig
from parrot.auth.oauth2.o365_devicecode_provider import O365DeviceCodeCredentialResolver


def _config():
    return ProviderCredentialConfig(provider="o365", auth="device_code")


def test_broker_device_code_deps_without_vault():
    o365 = object()
    manager = object()
    resolver = CredentialResolverFactory(deps={"o365_client": o365, "o365_oauth_manager": manager}).build(_config())

    assert isinstance(resolver, O365DeviceCodeCredentialResolver)
    assert resolver._legacy_vault is None

    legacy_vault = object()
    resolver_with_legacy = CredentialResolverFactory(
        deps={"o365_client": o365, "o365_oauth_manager": manager, "vault": legacy_vault}
    ).build(_config())
    assert resolver_with_legacy._legacy_vault is legacy_vault

    with pytest.raises(KeyError):
        CredentialResolverFactory(deps={"o365_client": o365}).build(_config())


def test_factory_builds_device_code_via_o365_interface_alias():
    resolver = CredentialResolverFactory(deps={"o365_interface": object(), "o365_oauth_manager": object()}).build(
        _config()
    )

    assert isinstance(resolver, O365DeviceCodeCredentialResolver)


def test_broker_from_config_registers_device_code_auth_kind():
    broker = CredentialBroker.from_config(
        [_config()],
        o365_client=object(),
        o365_oauth_manager=object(),
    )

    resolver, auth_kind = broker._resolvers["o365"]
    assert isinstance(resolver, O365DeviceCodeCredentialResolver)
    assert auth_kind == "device_code"


def test_existing_dispatch_unaffected():
    factory = CredentialResolverFactory(deps={"oauth_manager": object()})
    resolver = factory.build(ProviderCredentialConfig(provider="jira", auth="oauth2"))

    from parrot.auth.credentials import OAuthCredentialResolver

    assert isinstance(resolver, OAuthCredentialResolver)


def test_unknown_kind_message_lists_device_code():
    factory = CredentialResolverFactory(deps={})
    cfg = _config()
    cfg.auth = "bogus"

    with pytest.raises(ValueError, match="device_code"):
        factory.build(cfg)
