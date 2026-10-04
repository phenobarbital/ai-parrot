"""Telegram /add_mcp persistence is opt-in via ``USE_DOCUMENTDB``.

With the flag off (the default) no code path may open a DocumentDB (or the
DocumentDB-backed Vault) connection: servers still work for the session.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Chat, Message, User

from parrot.integrations.telegram.mcp_commands import (
    add_mcp_handler,
    list_mcp_handler,
    rehydrate_user_mcp_servers,
    remove_mcp_handler,
)
from parrot.integrations.telegram.mcp_persistence import (
    TelegramMCPPersistenceService,
    TelegramMCPPublicParams,
    documentdb_enabled,
)

_PERSISTENCE = "parrot.integrations.telegram.mcp_persistence"
_COMMANDS = "parrot.integrations.telegram.mcp_commands"


@pytest.fixture
def documentdb_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``USE_DOCUMENTDB=False`` regardless of the local environment."""
    monkeypatch.setattr("parrot.conf.USE_DOCUMENTDB", False, raising=False)


@pytest.fixture
def documentdb_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``USE_DOCUMENTDB=True``."""
    monkeypatch.setattr("parrot.conf.USE_DOCUMENTDB", True, raising=False)


def _message(text: str) -> MagicMock:
    """Build a private-chat aiogram Message mock."""
    msg = MagicMock(spec=Message)
    msg.text = text
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = 12345
    msg.chat = MagicMock(spec=Chat)
    msg.chat.type = "private"
    msg.reply = AsyncMock()
    msg.delete = AsyncMock()
    return msg


def _tool_manager() -> MagicMock:
    """Build a ToolManager mock that registers two tools."""
    tm = MagicMock()
    tm.add_mcp_server = AsyncMock(return_value=["tool1", "tool2"])
    tm.remove_mcp_server = AsyncMock(return_value=True)
    return tm


def test_documentdb_enabled_follows_setting(documentdb_on: None) -> None:
    """``documentdb_enabled()`` reads the setting at call time."""
    assert documentdb_enabled() is True


class TestServiceWhenDisabled:
    """Every service method is a no-op and never constructs ``DocumentDb``."""

    @pytest.mark.asyncio
    async def test_crud_never_touches_documentdb(self, documentdb_off: None) -> None:
        """save/list/read_one/remove return their empty results without a connection."""
        params = TelegramMCPPublicParams(name="fireflies", url="https://api.fireflies.ai/mcp")
        with patch(f"{_PERSISTENCE}.DocumentDb") as MockDb:
            svc = TelegramMCPPersistenceService()
            assert await svc.save("tg:1", "fireflies", params, None) is None
            assert await svc.list("tg:1") == []
            assert await svc.read_one("tg:1", "fireflies") is None
            assert await svc.remove("tg:1", "fireflies") == (False, None)
            MockDb.assert_not_called()

    @pytest.mark.asyncio
    async def test_enabled_opens_documentdb(self, documentdb_on: None) -> None:
        """With the flag on, ``list`` goes through ``DocumentDb``."""
        with patch(f"{_PERSISTENCE}.DocumentDb") as MockDb:
            db = AsyncMock()
            db.read = AsyncMock(return_value=[])
            MockDb.return_value.__aenter__ = AsyncMock(return_value=db)
            MockDb.return_value.__aexit__ = AsyncMock(return_value=False)
            assert await TelegramMCPPersistenceService().list("tg:1") == []
            MockDb.assert_called_once()
            db.read.assert_awaited_once()


class TestHandlersWhenDisabled:
    """Handlers work for the session and skip DocumentDB and the Vault."""

    @pytest.mark.asyncio
    async def test_rehydrate_skips_without_connecting(self, documentdb_off: None) -> None:
        """Login-time rehydration returns 0 without building the service."""
        with patch(f"{_COMMANDS}.TelegramMCPPersistenceService") as MockSvc:
            assert await rehydrate_user_mcp_servers(_tool_manager(), "tg:12345") == 0
            MockSvc.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_mcp_session_only(self, documentdb_off: None) -> None:
        """/add_mcp registers live tools, skips the Vault and says it is session-only."""
        payload = {
            "name": "fireflies",
            "url": "https://api.fireflies.ai/mcp",
            "auth_scheme": "bearer",
            "token": "sk-test-0123456789",
        }
        msg = _message(f"/add_mcp {json.dumps(payload)}")
        tm = _tool_manager()
        with (
            patch(f"{_PERSISTENCE}.DocumentDb") as MockDb,
            patch(f"{_COMMANDS}.store_vault_credential") as mock_store,
        ):
            await add_mcp_handler(msg, AsyncMock(return_value=tm))
            MockDb.assert_not_called()
            mock_store.assert_not_called()
        tm.add_mcp_server.assert_awaited_once()
        reply = msg.reply.call_args[0][0]
        assert "Connected" in reply
        assert "session only" in reply

    @pytest.mark.asyncio
    async def test_list_mcp_reports_disabled(self, documentdb_off: None) -> None:
        """/list_mcp explains that saved servers are unavailable."""
        msg = _message("/list_mcp")
        with patch(f"{_COMMANDS}.TelegramMCPPersistenceService") as MockSvc:
            await list_mcp_handler(msg)
            MockSvc.assert_not_called()
        assert "persistence is disabled" in msg.reply.call_args[0][0]

    @pytest.mark.asyncio
    async def test_remove_mcp_live_only(self, documentdb_off: None) -> None:
        """/remove_mcp disconnects the live server without touching DocumentDB or the Vault."""
        msg = _message("/remove_mcp fireflies")
        tm = _tool_manager()
        with (
            patch(f"{_PERSISTENCE}.DocumentDb") as MockDb,
            patch(f"{_COMMANDS}.delete_vault_credential") as mock_delete,
        ):
            await remove_mcp_handler(msg, AsyncMock(return_value=tm))
            MockDb.assert_not_called()
            mock_delete.assert_not_called()
        tm.remove_mcp_server.assert_awaited_once_with("fireflies")
        assert "Removed" in msg.reply.call_args[0][0]
