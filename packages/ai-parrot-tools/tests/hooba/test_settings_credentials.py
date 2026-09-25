"""FEAT-602 TASK-3734 — settings, env resolver, broker registration, login hook."""

import logging
from types import SimpleNamespace

import pytest
from parrot.auth.broker import CredentialBroker
from parrot.auth.credentials import NeedsAuth, ResolvedCredential
from parrot_tools.hooba.credentials import (
    EnvCredentialResolver,
    HoobaAuthError,
    make_login_hook,
    register_hooba_provider,
)
from parrot_tools.hooba.settings import HoobaSettings

ENV = {"HOOBA_ACCOUNT_ID": "23549", "HOOBA_USERNAME": "user@example.test", "HOOBA_PASSWORD": "s3cret"}


class FakeHTTP:
    """Records _request kwargs and returns a scripted httpx-like response."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    async def _request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response, None


def test_settings_from_env_and_headers():
    settings = HoobaSettings.from_env(
        {
            **ENV,
            "HOOBA_BASE_URL": "https://example.test/api",
            "HOOBA_MEMBER_ID": "61296",
            "HOOBA_USER_ID": "23725",
            "HOOBA_SUBSCRIPTION_ID": "1",
            "HOOBA_LANGUAGE": "ca",
            "HOOBA_ORIGIN": "https://app.example.test",
            "HOOBA_CATALOG_DIR": "/tmp/catalog",
            "HOOBA_SPEC_PATH": "/tmp/spec.json",
            "HOOBA_INCLUDE_TAGS": " Account, Invoice, ,Contact ",
        }
    )
    assert settings.account_id == 23549
    assert settings.member_id == 61296
    assert settings.user_id == 23725
    assert settings.subscription_id == 1
    assert settings.include_tags == ["Account", "Invoice", "Contact"]
    assert settings.default_headers() == {
        "origin": "https://app.example.test",
        "x-hooba-language": "ca",
        "ngsw-bypass": "true",
        "accept": "application/json, text/plain, */*",
    }


def test_settings_missing_account_id_raises():
    with pytest.raises(ValueError, match="HOOBA_ACCOUNT_ID"):
        HoobaSettings.from_env({})


async def test_env_resolver_and_broker_registration():
    resolver = EnvCredentialResolver(env=ENV)
    assert await resolver.resolve("hooba", "hooba") == {
        "username": ENV["HOOBA_USERNAME"],
        "password": ENV["HOOBA_PASSWORD"],
    }

    broker = CredentialBroker()
    register_hooba_provider(broker, resolver=resolver)
    result = await broker.resolve("hooba", "hooba", "hooba")
    assert isinstance(result, ResolvedCredential)
    assert result.secret == {"username": ENV["HOOBA_USERNAME"], "password": ENV["HOOBA_PASSWORD"]}

    missing_broker = CredentialBroker()
    register_hooba_provider(missing_broker, resolver=EnvCredentialResolver(env={}))
    missing = await missing_broker.resolve("hooba", "hooba", "hooba")
    assert isinstance(missing, NeedsAuth)


async def test_login_hook_extracts_sid(caplog):
    settings = HoobaSettings(account_id=23549)
    response = SimpleNamespace(status_code=200, cookies={}, history=[SimpleNamespace(cookies={"sid": "abc"})])
    http = FakeHTTP(response)
    broker = CredentialBroker()
    register_hooba_provider(broker, resolver=EnvCredentialResolver(env=ENV))

    with caplog.at_level(logging.INFO):
        result = await make_login_hook(settings, broker)(http)

    assert result == {"sid": "abc"}
    assert http.calls[0][1]["data"] == {"username": ENV["HOOBA_USERNAME"], "password": ENV["HOOBA_PASSWORD"]}
    assert ENV["HOOBA_PASSWORD"] not in caplog.text


async def test_login_hook_non_200_raises():
    settings = HoobaSettings(account_id=23549)
    http = FakeHTTP(SimpleNamespace(status_code=401, cookies={}, history=[]))
    broker = CredentialBroker()
    register_hooba_provider(broker, resolver=EnvCredentialResolver(env=ENV))

    with pytest.raises(HoobaAuthError, match="HTTP 401"):
        await make_login_hook(settings, broker)(http)


async def test_login_hook_fails_closed_before_network():
    settings = HoobaSettings(account_id=23549)
    http = FakeHTTP(SimpleNamespace(status_code=200, cookies={"sid": "abc"}, history=[]))

    with pytest.raises(HoobaAuthError):
        await make_login_hook(settings, CredentialBroker())(http)
    assert not http.calls

    broker = CredentialBroker()
    register_hooba_provider(broker, resolver=EnvCredentialResolver(env={}))
    with pytest.raises(HoobaAuthError):
        await make_login_hook(settings, broker, user_id="")(http)
    assert not http.calls

    register_hooba_provider(broker, resolver=EnvCredentialResolver(env={"HOOBA_USERNAME": "u", "HOOBA_PASSWORD": "p"}))
    with pytest.raises(HoobaAuthError):
        await make_login_hook(settings, broker)(http)
    assert not http.calls
