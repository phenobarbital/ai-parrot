"""Redis persistence and backend-gate tests for Telegram /add_mcp configs."""

from __future__ import annotations

import pytest

from parrot.integrations.telegram import mcp_persistence
from parrot.integrations.telegram.mcp_persistence import (
    TelegramMCPPersistenceService,
    TelegramMCPPublicParams,
    persistence_enabled,
)
from parrot.userstore.testing import redis_test_settings


@pytest.fixture
async def svc(monkeypatch: pytest.MonkeyPatch):
    """Provide a service using the isolated Redis test database."""
    monkeypatch.delenv("TELEGRAM_MCP_STORE", raising=False)
    monkeypatch.delenv("PARROT_USER_STORE", raising=False)
    monkeypatch.setattr("parrot.conf.USE_DOCUMENTDB", False, raising=False)
    monkeypatch.setattr(mcp_persistence, "_REDIS_STORE", None)
    async with redis_test_settings(monkeypatch):
        yield TelegramMCPPersistenceService()


def test_telegram_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default Redis backend is enabled; DocumentDB remains opt-in; invalid settings fail closed."""
    monkeypatch.delenv("TELEGRAM_MCP_STORE", raising=False)
    monkeypatch.delenv("PARROT_USER_STORE", raising=False)
    monkeypatch.setattr("parrot.conf.USE_DOCUMENTDB", False, raising=False)
    assert persistence_enabled() is True

    monkeypatch.setenv("TELEGRAM_MCP_STORE", "documentdb")
    assert persistence_enabled() is False
    monkeypatch.setattr("parrot.conf.USE_DOCUMENTDB", True, raising=False)
    assert persistence_enabled() is True

    monkeypatch.setenv("TELEGRAM_MCP_STORE", "bogus")
    assert persistence_enabled() is False


@pytest.mark.asyncio
async def test_telegram_redis_roundtrip(svc: TelegramMCPPersistenceService) -> None:
    """Redis persists, reads, and soft-deletes a Telegram MCP configuration."""
    params = TelegramMCPPublicParams(name="srv", url="https://example.test/mcp")
    await svc.save("tg:1", "srv", params, "tg_mcp_srv")

    configs = await svc.list("tg:1")
    assert [config.name for config in configs] == ["srv"]
    assert (await svc.read_one("tg:1", "srv")) == configs[0]
    assert await svc.remove("tg:1", "srv") == (True, "tg_mcp_srv")
    assert await svc.list("tg:1") == []
    assert await svc.read_one("tg:1", "srv") is None
