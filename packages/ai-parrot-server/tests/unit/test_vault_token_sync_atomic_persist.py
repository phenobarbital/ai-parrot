"""TASK-1688: VaultTokenSync.store_tokens write-ordering / partial-write handling (FEAT-267).

Verifies:
- `expires_at` is written first (before other fields) so a mid-loop failure
  cannot leave a token set that reads as permanently valid.
- A distinguishable warning log fires when not every expected key is
  persisted.
- No warning fires when the write completes fully.
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.services.vault_token_sync import VaultTokenSync


class FakeSessionVault:
    """Records the order of `set()` calls; can fail after N successful writes."""

    def __init__(self, fail_after: int | None = None):
        self.fail_after = fail_after
        self.calls: list[str] = []
        self.store: dict[str, object] = {}

    async def set(self, key: str, value: object) -> None:
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise RuntimeError("simulated vault write failure")
        self.calls.append(key)
        self.store[key] = value


@pytest.fixture
def sync_service(monkeypatch):
    """A VaultTokenSync with `_load_vault` patched to return a FakeSessionVault."""
    service = VaultTokenSync(db_pool=MagicMock(), redis=MagicMock())
    return service


@pytest.mark.asyncio
async def test_store_tokens_writes_expires_at_first(sync_service, monkeypatch):
    fake_vault = FakeSessionVault()
    monkeypatch.setattr(sync_service, "_load_vault", AsyncMock(return_value=fake_vault))

    await sync_service.store_tokens(
        "user-1",
        "o365",
        {
            "access_token": "tok",
            "refresh_token": "rt",
            "expires_at": 123456,
            "scope": "User.Read",
        },
    )

    assert fake_vault.calls[0] == "o365:expires_at"
    assert set(fake_vault.calls) == {
        "o365:expires_at", "o365:access_token", "o365:refresh_token", "o365:scope",
    }


@pytest.mark.asyncio
async def test_partial_store_tokens_failure_does_not_leave_forever_valid_token(
    sync_service, monkeypatch,
):
    """A write failure after expires_at but before access_token must not produce
    a token set that resolve() would treat as a valid cache-hit — access_token
    is simply never persisted in that case.
    """
    # expires_at is written first (fail_after=1 allows exactly 1 successful set).
    fake_vault = FakeSessionVault(fail_after=1)
    monkeypatch.setattr(sync_service, "_load_vault", AsyncMock(return_value=fake_vault))

    await sync_service.store_tokens(
        "user-1",
        "o365",
        {"access_token": "tok", "refresh_token": "rt", "expires_at": 123456},
    )

    # Only expires_at made it — access_token was never persisted, so a
    # subsequent read_tokens() cannot return a stale access_token at all.
    assert fake_vault.calls == ["o365:expires_at"]
    assert "o365:access_token" not in fake_vault.store


@pytest.mark.asyncio
async def test_partial_write_logs_distinguishable_warning(sync_service, monkeypatch, caplog):
    fake_vault = FakeSessionVault(fail_after=1)
    monkeypatch.setattr(sync_service, "_load_vault", AsyncMock(return_value=fake_vault))

    with caplog.at_level(logging.WARNING, logger="parrot.services.vault_token_sync"):
        await sync_service.store_tokens(
            "user-1",
            "o365",
            {"access_token": "tok", "expires_at": 123456},
        )

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("PARTIAL WRITE" in r.getMessage() for r in warnings)


@pytest.mark.asyncio
async def test_full_write_success_does_not_log_partial_warning(sync_service, monkeypatch, caplog):
    fake_vault = FakeSessionVault()
    monkeypatch.setattr(sync_service, "_load_vault", AsyncMock(return_value=fake_vault))

    with caplog.at_level(logging.WARNING, logger="parrot.services.vault_token_sync"):
        await sync_service.store_tokens(
            "user-1",
            "o365",
            {"access_token": "tok", "expires_at": 123456},
        )

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert not any("PARTIAL WRITE" in r.getMessage() for r in warnings)
