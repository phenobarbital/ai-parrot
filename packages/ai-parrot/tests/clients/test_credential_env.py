"""PA-2: ``AbstractClient.credential_env`` / ``has_server_credentials`` — the declarative "is a server key set?"."""
from __future__ import annotations

import inspect

import pytest

from parrot.clients.base import AbstractClient
from parrot.clients.factory import LLMFactory


def _classes() -> dict[str, type[AbstractClient]]:
    out: dict[str, type[AbstractClient]] = {}
    for provider, value in LLMFactory.supported_clients().items():
        try:
            out[provider] = value() if callable(value) and not isinstance(value, type) else value
        except Exception:  # an extra that is not installed: nothing to declare
            continue
    return out


def test_default_is_unknown_and_never_claims_a_server_key():
    assert AbstractClient.credential_env is None
    assert AbstractClient.has_server_credentials() is False


def test_has_server_credentials_follows_the_environment_live(monkeypatch):
    class _Keyed(AbstractClient):
        credential_env = ("PA2_FIRST_KEY", "PA2_SECOND_KEY")

    monkeypatch.delenv("PA2_FIRST_KEY", raising=False)
    monkeypatch.delenv("PA2_SECOND_KEY", raising=False)
    assert _Keyed.has_server_credentials() is False
    monkeypatch.setenv("PA2_SECOND_KEY", "x")
    assert _Keyed.has_server_credentials() is True  # any of the names
    monkeypatch.delenv("PA2_SECOND_KEY")
    assert _Keyed.has_server_credentials() is False  # live: no cache


@pytest.mark.parametrize("provider", sorted(_classes()))
def test_declared_names_are_the_ones_the_client_reads(provider):
    cls = _classes()[provider]
    if cls.credential_env is None:
        return
    source = inspect.getsource(inspect.getmodule(cls))
    assert all(name in source for name in cls.credential_env), (provider, cls.credential_env)


def test_the_flagship_satellites_declare_their_key():
    classes = _classes()
    assert classes["anthropic"].credential_env == ("ANTHROPIC_API_KEY",)
    assert classes["google"].credential_env == ("GOOGLE_API_KEY",)
    assert set(classes["google-compat"].credential_env) == {"GEMINI_API_KEY", "GOOGLE_API_KEY"}
    assert classes["openai"].credential_env == ("OPENAI_API_KEY",)
