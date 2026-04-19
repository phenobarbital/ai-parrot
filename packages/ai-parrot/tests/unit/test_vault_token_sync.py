"""Unit tests for VaultTokenSync (FEAT-108 / TASK-761)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.services.vault_token_sync import (
    VaultTokenSync,
    _coerce_user_id,
    _synth_session_uuid,
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


class TestHelpers:
    def test_synth_session_uuid_is_stable(self):
        assert _synth_session_uuid("u1") == _synth_session_uuid("u1")
        assert _synth_session_uuid("u1") != _synth_session_uuid("u2")

    def test_coerce_user_id_int(self):
        assert _coerce_user_id(42) == 42

    def test_coerce_user_id_numeric_string(self):
        assert _coerce_user_id("42") == 42

    def test_coerce_user_id_uuid_passthrough(self):
        uid = "a9e31c08-5bb2-4fcf-bf52-11111"
        assert _coerce_user_id(uid) == uid

    def test_coerce_user_id_none(self):
        assert _coerce_user_id(None) is None


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


@pytest.fixture
def mock_db_pool():
    return AsyncMock()


@pytest.fixture
def mock_redis():
    return AsyncMock()


@pytest.fixture
def fake_vault():
    """Stand-in SessionVault with in-memory backing dict."""
    vault = MagicMock()
    store = {}

    async def _set(key, value):
        store[key] = value

    async def _get(key, default=None):
        return store.get(key, default)

    async def _delete(key):
        store.pop(key, None)

    async def _keys():
        return list(store.keys())

    vault.set = AsyncMock(side_effect=_set)
    vault.get = AsyncMock(side_effect=_get)
    vault.delete = AsyncMock(side_effect=_delete)
    vault.keys = AsyncMock(side_effect=_keys)
    vault._store = store  # expose for test assertions
    return vault


@pytest.fixture
def sync(mock_db_pool, mock_redis):
    return VaultTokenSync(mock_db_pool, mock_redis)


# ----------------------------------------------------------------------
# store_tokens
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_tokens_stores_flat_keys(sync, fake_vault):
    tokens = {
        "access_token": "at-123",
        "refresh_token": "rt-456",
        "cloud_id": "cloud-abc",
        "site_url": "https://site.atlassian.net",
        "account_id": "acc-789",
    }
    with patch(
        "parrot.services.vault_token_sync.SessionVault"
    ) as mock_sv:
        mock_sv.load_for_session = AsyncMock(return_value=fake_vault)
        await sync.store_tokens("user-123", "jira", tokens)

    assert fake_vault._store == {
        "jira:access_token": "at-123",
        "jira:refresh_token": "rt-456",
        "jira:cloud_id": "cloud-abc",
        "jira:site_url": "https://site.atlassian.net",
        "jira:account_id": "acc-789",
    }


@pytest.mark.asyncio
async def test_store_skips_none_values(sync, fake_vault):
    with patch(
        "parrot.services.vault_token_sync.SessionVault"
    ) as mock_sv:
        mock_sv.load_for_session = AsyncMock(return_value=fake_vault)
        await sync.store_tokens(
            "u", "jira", {"access_token": "at", "email": None}
        )
    assert "jira:access_token" in fake_vault._store
    assert "jira:email" not in fake_vault._store


@pytest.mark.asyncio
async def test_store_empty_tokens_noop(sync, fake_vault):
    with patch(
        "parrot.services.vault_token_sync.SessionVault"
    ) as mock_sv:
        mock_sv.load_for_session = AsyncMock(return_value=fake_vault)
        await sync.store_tokens("u", "jira", {})
    # vault.set should never have been awaited
    fake_vault.set.assert_not_called()
    mock_sv.load_for_session.assert_not_called()


@pytest.mark.asyncio
async def test_store_tokens_failure_is_swallowed(sync, caplog):
    with patch(
        "parrot.services.vault_token_sync.SessionVault"
    ) as mock_sv:
        mock_sv.load_for_session = AsyncMock(
            side_effect=RuntimeError("DB unavailable")
        )
        with caplog.at_level("ERROR"):
            # Must NOT raise.
            await sync.store_tokens("u", "jira", {"access_token": "at"})
    # The load_vault path logs an "exception" when load_for_session blows up.
    assert any("failed to load vault" in rec.message.lower()
               for rec in caplog.records)


@pytest.mark.asyncio
async def test_store_tokens_vault_unavailable_swallowed(mock_db_pool, mock_redis):
    sync_ = VaultTokenSync(mock_db_pool, mock_redis)
    with patch("parrot.services.vault_token_sync.SessionVault", None):
        # Must not raise; logs a warning.
        await sync_.store_tokens("u", "jira", {"access_token": "at"})


# ----------------------------------------------------------------------
# read_tokens
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_tokens_returns_stripped_keys(sync, fake_vault):
    fake_vault._store.update({
        "jira:access_token": "at-123",
        "jira:cloud_id": "cloud-abc",
        "github:access_token": "gh-1",  # different provider, should be ignored
    })
    with patch(
        "parrot.services.vault_token_sync.SessionVault"
    ) as mock_sv:
        mock_sv.load_for_session = AsyncMock(return_value=fake_vault)
        result = await sync.read_tokens("u", "jira")

    assert result == {"access_token": "at-123", "cloud_id": "cloud-abc"}


@pytest.mark.asyncio
async def test_read_tokens_missing_returns_none(sync, fake_vault):
    with patch(
        "parrot.services.vault_token_sync.SessionVault"
    ) as mock_sv:
        mock_sv.load_for_session = AsyncMock(return_value=fake_vault)
        result = await sync.read_tokens("u", "jira")
    assert result is None


@pytest.mark.asyncio
async def test_read_tokens_vault_unavailable(mock_db_pool, mock_redis):
    sync_ = VaultTokenSync(mock_db_pool, mock_redis)
    with patch("parrot.services.vault_token_sync.SessionVault", None):
        result = await sync_.read_tokens("u", "jira")
    assert result is None


@pytest.mark.asyncio
async def test_read_tokens_failure_returns_none(sync, fake_vault):
    fake_vault.keys = AsyncMock(side_effect=RuntimeError("redis down"))
    with patch(
        "parrot.services.vault_token_sync.SessionVault"
    ) as mock_sv:
        mock_sv.load_for_session = AsyncMock(return_value=fake_vault)
        result = await sync.read_tokens("u", "jira")
    assert result is None


# ----------------------------------------------------------------------
# delete_tokens
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_tokens_removes_only_provider_keys(sync, fake_vault):
    fake_vault._store.update({
        "jira:access_token": "at-123",
        "jira:cloud_id": "cloud-abc",
        "github:access_token": "gh-1",
    })
    with patch(
        "parrot.services.vault_token_sync.SessionVault"
    ) as mock_sv:
        mock_sv.load_for_session = AsyncMock(return_value=fake_vault)
        await sync.delete_tokens("u", "jira")

    assert fake_vault._store == {"github:access_token": "gh-1"}


@pytest.mark.asyncio
async def test_delete_tokens_swallows_failures(sync, fake_vault):
    fake_vault.keys = AsyncMock(side_effect=RuntimeError("boom"))
    with patch(
        "parrot.services.vault_token_sync.SessionVault"
    ) as mock_sv:
        mock_sv.load_for_session = AsyncMock(return_value=fake_vault)
        # Must NOT raise.
        await sync.delete_tokens("u", "jira")
