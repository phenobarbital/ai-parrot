"""Tests for user-store backend settings."""

import asyncio
import os

import pytest

from parrot.userstore import settings
from parrot.userstore import (
    SWITCHES,
    UserStoreMisconfigured,
    close_user_store_redis,
    default_result_storage,
    get_user_store_redis,
    implicit_redis_stores,
    key_prefix,
    redis_url,
    resolve_store_backend,
    store_backend_source,
    validate_user_store_settings,
)

ALL_KEYS = [
    *SWITCHES,
    "PARROT_USER_STORE",
    "CREW_RESULT_STORAGE",
    "DOCUMENTDB_HOSTNAME",
    "DOCUMENTDB_DBNAME",
    "PARROT_USER_STORE_REDIS_URL",
    "PARROT_USER_STORE_REDIS_DB",
    "PARROT_USER_STORE_REDIS_PREFIX",
    "REDIS_HOST",
    "REDIS_PORT",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Clear configuration values that influence user-store settings."""
    for key in ALL_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(settings.config, "get", lambda key, fallback=None: os.getenv(key, fallback))


def test_resolve_default_is_redis():
    """All store switches default to Redis."""
    assert {resolve_store_backend(switch) for switch in SWITCHES} == {"redis"}


def test_resolve_precedence(monkeypatch):
    """A store-specific switch overrides the global switch."""
    monkeypatch.setenv("PARROT_USER_STORE", "documentdb")
    monkeypatch.setenv("VAULT_STORE", "redis")

    assert resolve_store_backend("VAULT_STORE") == "redis"
    assert store_backend_source("VAULT_STORE") == "switch"
    assert resolve_store_backend("BYOK_STORE") == "documentdb"
    assert store_backend_source("BYOK_STORE") == "global"


@pytest.mark.parametrize(
    ("key", "value"),
    [("VAULT_STORE", "mongo"), ("PARROT_USER_STORE", "postgres")],
)
def test_resolve_invalid_value_raises(monkeypatch, key, value):
    """Invalid per-store and global backends fail closed."""
    monkeypatch.setenv(key, value)
    with pytest.raises(UserStoreMisconfigured):
        resolve_store_backend("VAULT_STORE")


def test_postgres_only_where_allowed(monkeypatch):
    """Postgres is available only for the three existing Postgres-backed stores."""
    monkeypatch.setenv("MCP_CONFIGS_STORE", "postgres")
    with pytest.raises(UserStoreMisconfigured):
        resolve_store_backend("MCP_CONFIGS_STORE")

    monkeypatch.delenv("MCP_CONFIGS_STORE")
    monkeypatch.setenv("VAULT_STORE", "postgres")
    assert resolve_store_backend("VAULT_STORE") == "postgres"


def test_guard_implicit_redis_with_documentdb(monkeypatch):
    """DocumentDB installations must explicitly choose a migration direction."""
    monkeypatch.setenv("DOCUMENTDB_HOSTNAME", "localhost")
    with pytest.raises(UserStoreMisconfigured) as error:
        validate_user_store_settings()

    message = str(error.value)
    assert all(store in message for store in implicit_redis_stores())
    assert "PARROT_USER_STORE=documentdb" in message
    assert "PARROT_USER_STORE=redis" in message


@pytest.mark.parametrize("backend", ["redis", "documentdb"])
def test_guard_cleared_by_explicit_switch(monkeypatch, backend):
    """An explicit global backend clears the DocumentDB migration guard."""
    monkeypatch.setenv("DOCUMENTDB_HOSTNAME", "localhost")
    monkeypatch.setenv("PARROT_USER_STORE", backend)
    assert set(validate_user_store_settings().values()) == {backend}


def test_guard_absent_without_documentdb_config():
    """Redis defaults do not require a DocumentDB installation."""
    assert set(validate_user_store_settings().values()) == {"redis"}


def test_default_result_storage_follows_global(monkeypatch):
    """Unconfigured crew results follow the global backend choice."""
    assert default_result_storage() == "redis"
    monkeypatch.setenv("PARROT_USER_STORE", "documentdb")
    assert default_result_storage() == "documentdb"


def test_redis_url_default_db6(monkeypatch):
    """The default user-store client has its own logical Redis database."""
    monkeypatch.setenv("REDIS_HOST", "h")
    monkeypatch.setenv("REDIS_PORT", "1234")
    assert redis_url() == "redis://h:1234/6"


def test_redis_url_override_and_key_prefix(monkeypatch):
    """Explicit URLs win and prefixes remain safe for key composition."""
    monkeypatch.setenv("PARROT_USER_STORE_REDIS_URL", "redis://example.test:6380/0")
    monkeypatch.setenv("PARROT_USER_STORE_REDIS_PREFIX", "custom::")
    assert redis_url() == "redis://example.test:6380/0"
    assert key_prefix() == "custom"


def test_client_per_event_loop():
    """Clients are reused per loop and closed without connecting to Redis."""

    async def create_and_close():
        client = get_user_store_redis()
        assert get_user_store_redis() is client
        await close_user_store_redis()
        return client

    first_loop = asyncio.new_event_loop()
    second_loop = asyncio.new_event_loop()
    try:
        first = first_loop.run_until_complete(create_and_close())
        second = second_loop.run_until_complete(create_and_close())
    finally:
        first_loop.close()
        second_loop.close()

    assert second is not first
