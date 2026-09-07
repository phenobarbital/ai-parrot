"""Tests for the SecretStore port, in-memory backend and vault adapter."""
from __future__ import annotations

import logging

import pytest

from parrot.security.audit_ledger import derive_key_fingerprint
from parrot.security.secrets import (
    InMemorySecretStore,
    SecretMeta,
    SecretStoreVault,
)

SECRET = "sk-ant-super-secret-value-do-not-log"


@pytest.fixture
def store() -> InMemorySecretStore:
    """A fresh in-memory store."""
    return InMemorySecretStore()


async def test_put_get_roundtrip(store: InMemorySecretStore) -> None:
    """A stored value comes back verbatim."""
    meta = await store.put("bar-pepe", "anthropic:api_key", SECRET)

    assert meta.tenant_id == "bar-pepe"
    assert meta.key == "anthropic:api_key"
    assert meta.fingerprint == derive_key_fingerprint(SECRET)
    assert await store.get("bar-pepe", "anthropic:api_key") == SECRET


async def test_get_missing_returns_none(store: InMemorySecretStore) -> None:
    """A missing key is None, not an exception."""
    assert await store.get("bar-pepe", "nope") is None


async def test_secrets_are_tenant_scoped(store: InMemorySecretStore) -> None:
    """Two tenants may hold the same key name without collision."""
    await store.put("bar-pepe", "anthropic:api_key", "value-a")
    await store.put("hotel-x", "anthropic:api_key", "value-b")

    assert await store.get("bar-pepe", "anthropic:api_key") == "value-a"
    assert await store.get("hotel-x", "anthropic:api_key") == "value-b"


async def test_list_keys_never_carries_a_value(
    store: InMemorySecretStore,
) -> None:
    """SecretMeta must be structurally incapable of leaking a secret.

    This is the guarantee the HTTP layer relies on when it serialises a
    listing, so it is asserted structurally rather than by inspecting output.
    """
    await store.put("bar-pepe", "anthropic:api_key", SECRET)

    listing = await store.list_keys("bar-pepe")

    assert [m.key for m in listing] == ["anthropic:api_key"]
    assert "value" not in SecretMeta.__dataclass_fields__
    assert "secret" not in SecretMeta.__dataclass_fields__
    assert SECRET not in repr(listing)


async def test_list_keys_is_tenant_scoped_and_sorted(
    store: InMemorySecretStore,
) -> None:
    """A listing shows only the asked-for tenant, ordered by key."""
    await store.put("bar-pepe", "google:api_key", "g")
    await store.put("bar-pepe", "anthropic:api_key", "a")
    await store.put("hotel-x", "google:api_key", "other")

    assert [m.key for m in await store.list_keys("bar-pepe")] == [
        "anthropic:api_key",
        "google:api_key",
    ]


async def test_put_preserves_created_at_and_moves_updated_at(
    store: InMemorySecretStore,
) -> None:
    """Overwriting a secret is an update, not a new creation."""
    first = await store.put("bar-pepe", "k", "one")
    second = await store.put("bar-pepe", "k", "two")

    assert second.created_at == first.created_at
    assert second.updated_at >= first.updated_at
    assert second.fingerprint != first.fingerprint


async def test_delete_reports_whether_anything_was_removed(
    store: InMemorySecretStore,
) -> None:
    """delete() is honest about whether it did anything."""
    await store.put("bar-pepe", "k", SECRET)

    assert await store.delete("bar-pepe", "k") is True
    assert await store.delete("bar-pepe", "k") is False
    assert await store.get("bar-pepe", "k") is None


async def test_aclose_drops_values(store: InMemorySecretStore) -> None:
    """Closing clears plaintext rather than leaving it resident."""
    await store.put("bar-pepe", "k", SECRET)
    await store.aclose()

    assert await store.get("bar-pepe", "k") is None


async def test_async_context_manager_closes(
    store: InMemorySecretStore,
) -> None:
    """The store works as an async context manager."""
    async with store as opened:
        await opened.put("bar-pepe", "k", SECRET)
    assert await store.get("bar-pepe", "k") is None


# ---------------------------------------------------------------------------
# Vault adapter — the broker contract
# ---------------------------------------------------------------------------


async def test_vault_adapter_read_tokens(store: InMemorySecretStore) -> None:
    """read_tokens returns a flat mapping keyed as stored."""
    await store.put("bar-pepe", "anthropic:api_key", SECRET)
    await store.put("bar-pepe", "google:api_key", "g-key")

    tokens = await SecretStoreVault(store).read_tokens("bar-pepe")

    assert tokens == {"anthropic:api_key": SECRET, "google:api_key": "g-key"}


async def test_vault_adapter_read_tokens_empty_subject(
    store: InMemorySecretStore,
) -> None:
    """An unknown subject yields an empty mapping, not an error."""
    assert await SecretStoreVault(store).read_tokens("nobody") == {}


async def test_vault_adapter_store_and_delete(
    store: InMemorySecretStore,
) -> None:
    """store_tokens writes through; delete_tokens removes selectively."""
    vault = SecretStoreVault(store)
    await vault.store_tokens("bar-pepe", {"a:k": "1", "b:k": "2"})

    assert await store.get("bar-pepe", "a:k") == "1"

    await vault.delete_tokens("bar-pepe", ["a:k"])
    assert await store.get("bar-pepe", "a:k") is None
    assert await store.get("bar-pepe", "b:k") == "2"

    await vault.delete_tokens("bar-pepe")
    assert await store.list_keys("bar-pepe") == []


async def test_vault_adapter_satisfies_broker_static_key_resolver(
    store: InMemorySecretStore,
) -> None:
    """The adapter is accepted by the real broker resolver.

    This is the point of the adapter: BYOK must reuse the FEAT-264 credential
    path rather than growing a parallel one. Asserting against the actual
    private resolver keeps that coupling honest — if the broker's expected
    vault protocol changes, this test fails instead of production.
    """
    from parrot.auth.broker import _VaultStaticKeyResolver

    await store.put("bar-pepe", "anthropic:api_key", SECRET)
    resolver = _VaultStaticKeyResolver(
        vault=SecretStoreVault(store),
        vault_key="anthropic:api_key",
        capture_url="https://example.invalid/capture",
    )

    resolved = await resolver.resolve("saas", "bar-pepe")

    assert resolved == SECRET


async def test_vault_adapter_never_logs_secret_values(
    store: InMemorySecretStore, caplog: pytest.LogCaptureFixture
) -> None:
    """Debug logging may name keys but never their values."""
    caplog.set_level(logging.DEBUG)
    vault = SecretStoreVault(store)

    await vault.store_tokens("bar-pepe", {"anthropic:api_key": SECRET})
    await vault.read_tokens("bar-pepe")
    await vault.delete_tokens("bar-pepe")

    combined = "\n".join(r.getMessage() for r in caplog.records)
    assert SECRET not in combined
    assert "anthropic:api_key" in combined
