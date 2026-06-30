"""Unit tests for the `device_code` branch of `CredentialResolverFactory` (FEAT-266)."""
import pytest

from parrot.auth.broker import CredentialResolverFactory, CredentialBroker
from parrot.auth.credentials import ProviderCredentialConfig
from parrot.auth.oauth2.o365_devicecode_provider import O365DeviceCodeCredentialResolver


@pytest.fixture
def fake_o365():
    return object()


@pytest.fixture
def fake_manager():
    return object()


@pytest.fixture
def fake_vault():
    return object()


def test_factory_builds_device_code(fake_o365, fake_manager, fake_vault):
    factory = CredentialResolverFactory(deps={
        "o365_client": fake_o365,
        "o365_oauth_manager": fake_manager,
        "vault": fake_vault,
    })
    resolver = factory.build(
        ProviderCredentialConfig(provider="o365", auth="device_code")
    )
    assert isinstance(resolver, O365DeviceCodeCredentialResolver)


def test_factory_builds_device_code_via_o365_interface_alias(fake_o365, fake_manager, fake_vault):
    """Accepts the `o365_interface` dep key as a fallback for `o365_client`."""
    factory = CredentialResolverFactory(deps={
        "o365_interface": fake_o365,
        "o365_oauth_manager": fake_manager,
        "vault": fake_vault,
    })
    resolver = factory.build(
        ProviderCredentialConfig(provider="o365", auth="device_code")
    )
    assert isinstance(resolver, O365DeviceCodeCredentialResolver)


def test_factory_device_code_missing_dep_raises():
    factory = CredentialResolverFactory(deps={})
    with pytest.raises(KeyError):
        factory.build(ProviderCredentialConfig(provider="o365", auth="device_code"))


def test_factory_device_code_partial_deps_raises(fake_o365):
    factory = CredentialResolverFactory(deps={"o365_client": fake_o365})
    with pytest.raises(KeyError):
        factory.build(ProviderCredentialConfig(provider="o365", auth="device_code"))


def test_broker_from_config_registers_device_code_auth_kind(fake_o365, fake_manager, fake_vault):
    broker = CredentialBroker.from_config(
        [ProviderCredentialConfig(provider="o365", auth="device_code")],
        o365_client=fake_o365,
        o365_oauth_manager=fake_manager,
        vault=fake_vault,
    )
    resolver, auth_kind = broker._resolvers["o365"]
    assert isinstance(resolver, O365DeviceCodeCredentialResolver)
    assert auth_kind == "device_code"


def test_existing_dispatch_unaffected(fake_manager):
    """obo/oauth2/static_key/mcp dispatch still resolves (no device_code regressions)."""
    factory = CredentialResolverFactory(deps={"oauth_manager": fake_manager})
    resolver = factory.build(
        ProviderCredentialConfig(provider="jira", auth="oauth2")
    )
    from parrot.auth.credentials import OAuthCredentialResolver
    assert isinstance(resolver, OAuthCredentialResolver)


def test_unknown_kind_message_lists_device_code():
    factory = CredentialResolverFactory(deps={})
    cfg = ProviderCredentialConfig(provider="o365", auth="device_code")
    cfg.auth = "bogus"  # bypass Literal validation to exercise the dispatch fallthrough
    with pytest.raises(ValueError, match="device_code"):
        factory.build(cfg)
