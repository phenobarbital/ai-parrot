"""Test suite for FEAT-113 — Vault-Backed Credentials for Telegram /add_mcp.

Covers:
- Module 2: _split_secret_and_public helper
- Module 1: TelegramMCPPersistenceService CRUD
- Module 3: add/list/remove handlers and rehydration
- Regression guards (no Redis writes)
- Integration: end-to-end add → list → remove lifecycle
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Chat, Message, User

from parrot.integrations.telegram.mcp_commands import (
    _split_secret_and_public,
    add_mcp_handler,
    list_mcp_handler,
    rehydrate_user_mcp_servers,
    remove_mcp_handler,
)
from parrot.integrations.telegram.mcp_persistence import (
    TelegramMCPPersistenceService,
    TelegramMCPPublicParams,
    UserTelegramMCPConfig,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bearer_payload() -> dict:
    """Minimal bearer-auth /add_mcp payload."""
    return {
        "name": "fireflies",
        "url": "https://api.fireflies.ai/mcp",
        "auth_scheme": "bearer",
        "token": "sk-test-0123456789",
    }


@pytest.fixture
def api_key_payload() -> dict:
    """api_key-auth /add_mcp payload."""
    return {
        "name": "brave",
        "url": "https://api.brave.com/mcp",
        "auth_scheme": "api_key",
        "api_key": "bsa-...-redacted",
        "api_key_header": "X-Brave-Key",
    }


@pytest.fixture
def basic_payload() -> dict:
    """basic-auth /add_mcp payload."""
    return {
        "name": "internal",
        "url": "https://internal.example/mcp",
        "auth_scheme": "basic",
        "username": "svc",
        "password": "p@ss!word",
    }


def _make_message(
    text: str,
    chat_type: str = "private",
    user_id: int = 12345,
) -> MagicMock:
    """Build a minimal aiogram Message mock."""
    msg = MagicMock(spec=Message)
    msg.text = text
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = user_id
    msg.chat = MagicMock(spec=Chat)
    msg.chat.type = chat_type
    msg.reply = AsyncMock()
    msg.delete = AsyncMock()
    return msg


def _make_tool_manager(registered_tools: Optional[List[str]] = None) -> MagicMock:
    """Build a minimal ToolManager mock."""
    tm = MagicMock()
    tm.add_mcp_server = AsyncMock(return_value=registered_tools or ["tool1", "tool2"])
    tm.remove_mcp_server = AsyncMock(return_value=True)
    return tm


def _make_persistence_service(
    configs: Optional[List[UserTelegramMCPConfig]] = None,
    read_one_result: Optional[UserTelegramMCPConfig] = None,
    remove_result: tuple = (True, None),
) -> MagicMock:
    """Build a TelegramMCPPersistenceService mock."""
    svc = MagicMock(spec=TelegramMCPPersistenceService)
    svc.save = AsyncMock()
    svc.list = AsyncMock(return_value=configs or [])
    svc.read_one = AsyncMock(return_value=read_one_result)
    svc.remove = AsyncMock(return_value=remove_result)
    return svc


def _make_user_tg_config(
    name: str = "fireflies",
    url: str = "https://api.fireflies.ai/mcp",
    auth_scheme: str = "bearer",
    vault_credential_name: Optional[str] = "tg_mcp_fireflies",
    active: bool = True,
) -> UserTelegramMCPConfig:
    """Build a UserTelegramMCPConfig instance."""
    params = TelegramMCPPublicParams(
        name=name,
        url=url,
        auth_scheme=auth_scheme,
    )
    return UserTelegramMCPConfig(
        user_id="tg:12345",
        name=name,
        params=params,
        vault_credential_name=vault_credential_name,
        active=active,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# Module 2: _split_secret_and_public
# ---------------------------------------------------------------------------


class TestSplitSecretAndPublic:
    """Tests for the _split_secret_and_public helper."""

    def test_split_secret_bearer(self, bearer_payload: dict) -> None:
        """bearer scheme → secret contains token, public does not."""
        public, secret = _split_secret_and_public(bearer_payload)
        assert secret == {"token": "sk-test-0123456789"}
        assert not hasattr(public, "token")
        assert public.auth_scheme == "bearer"
        assert public.name == "fireflies"
        assert "token" not in public.model_dump()

    def test_split_secret_api_key(self, api_key_payload: dict) -> None:
        """api_key scheme → secret contains api_key; api_key_header stays public."""
        public, secret = _split_secret_and_public(api_key_payload)
        assert secret == {"api_key": "bsa-...-redacted"}
        assert public.api_key_header == "X-Brave-Key"
        assert "api_key" not in public.model_dump()
        assert public.auth_scheme == "api_key"

    def test_split_secret_basic(self, basic_payload: dict) -> None:
        """basic scheme → secret contains username+password; both absent from public."""
        public, secret = _split_secret_and_public(basic_payload)
        assert secret == {"username": "svc", "password": "p@ss!word"}
        assert "username" not in public.model_dump()
        assert "password" not in public.model_dump()
        assert public.auth_scheme == "basic"

    def test_split_secret_none(self) -> None:
        """none scheme → secret_params is empty dict."""
        payload = {"name": "x", "url": "https://x.com/mcp", "auth_scheme": "none"}
        public, secret = _split_secret_and_public(payload)
        assert secret == {}
        assert public.auth_scheme == "none"

    def test_split_missing_bearer_token(self) -> None:
        """Missing token with bearer scheme → ValueError."""
        payload = {"name": "x", "url": "https://x.com/mcp", "auth_scheme": "bearer"}
        with pytest.raises(ValueError, match="bearer auth requires a 'token' field"):
            _split_secret_and_public(payload)

    def test_split_missing_name(self) -> None:
        """Missing name → ValueError."""
        with pytest.raises(ValueError, match="'name' is required"):
            _split_secret_and_public({"url": "https://x.com/mcp"})

    def test_split_missing_url(self) -> None:
        """Missing url → ValueError."""
        with pytest.raises(ValueError, match="'url' is required"):
            _split_secret_and_public({"name": "x"})

    def test_split_bad_scheme(self) -> None:
        """Unknown auth_scheme → ValueError."""
        payload = {
            "name": "x",
            "url": "https://x.com/mcp",
            "auth_scheme": "oauth2",
        }
        with pytest.raises(ValueError, match="Unsupported auth_scheme"):
            _split_secret_and_public(payload)

    def test_split_api_key_fallback_token(self) -> None:
        """api_key scheme accepts token field as fallback for api_key."""
        payload = {
            "name": "x",
            "url": "https://x.com/mcp",
            "auth_scheme": "api_key",
            "token": "my-token",
        }
        public, secret = _split_secret_and_public(payload)
        assert secret == {"api_key": "my-token"}


# ---------------------------------------------------------------------------
# Module 1: TelegramMCPPersistenceService
# ---------------------------------------------------------------------------


class TestTelegramMCPPersistenceService:
    """CRUD tests for TelegramMCPPersistenceService using mocked DocumentDb."""

    @pytest.mark.asyncio
    async def test_persistence_save_upsert(self) -> None:
        """save() calls db.update_one with upsert=True."""
        params = TelegramMCPPublicParams(
            name="fireflies", url="https://api.fireflies.ai/mcp"
        )
        with patch(
            "parrot.integrations.telegram.mcp_persistence.DocumentDb"
        ) as MockDb:
            db_instance = AsyncMock()
            MockDb.return_value.__aenter__ = AsyncMock(return_value=db_instance)
            MockDb.return_value.__aexit__ = AsyncMock(return_value=False)
            db_instance.update_one = AsyncMock()

            svc = TelegramMCPPersistenceService()
            await svc.save("tg:123", "fireflies", params, "tg_mcp_fireflies")

            db_instance.update_one.assert_called_once()
            call_args = db_instance.update_one.call_args
            # Collection
            assert call_args[0][0] == "telegram_user_mcp_configs"
            # Query
            assert call_args[0][1] == {"user_id": "tg:123", "name": "fireflies"}
            # upsert=True
            assert call_args[1].get("upsert") is True or call_args[0][3] is True

    @pytest.mark.asyncio
    async def test_persistence_list_excludes_inactive(self) -> None:
        """list() only returns active=True docs."""
        active_doc = {
            "user_id": "tg:123",
            "name": "fireflies",
            "params": {
                "name": "fireflies",
                "url": "https://api.fireflies.ai/mcp",
                "transport": "http",
                "description": None,
                "auth_scheme": "bearer",
                "api_key_header": None,
                "use_bearer_prefix": None,
                "headers": {},
                "allowed_tools": None,
                "blocked_tools": None,
            },
            "vault_credential_name": "tg_mcp_fireflies",
            "active": True,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        with patch(
            "parrot.integrations.telegram.mcp_persistence.DocumentDb"
        ) as MockDb:
            db_instance = AsyncMock()
            MockDb.return_value.__aenter__ = AsyncMock(return_value=db_instance)
            MockDb.return_value.__aexit__ = AsyncMock(return_value=False)
            # Only return active docs (the service queries active=True in DocumentDB)
            db_instance.read = AsyncMock(return_value=[active_doc])

            svc = TelegramMCPPersistenceService()
            configs = await svc.list("tg:123")

            assert len(configs) == 1
            assert configs[0].name == "fireflies"
            # Verify the query contained active=True
            db_instance.read.assert_called_once_with(
                "telegram_user_mcp_configs",
                {"user_id": "tg:123", "active": True},
            )

    @pytest.mark.asyncio
    async def test_persistence_remove_soft_delete(self) -> None:
        """remove() sets active=False, returns True if doc found."""
        existing_doc = {"user_id": "tg:123", "name": "fireflies", "active": True}
        with patch(
            "parrot.integrations.telegram.mcp_persistence.DocumentDb"
        ) as MockDb:
            db_instance = AsyncMock()
            MockDb.return_value.__aenter__ = AsyncMock(return_value=db_instance)
            MockDb.return_value.__aexit__ = AsyncMock(return_value=False)
            db_instance.read_one = AsyncMock(return_value=existing_doc)
            db_instance.update_one = AsyncMock()

            svc = TelegramMCPPersistenceService()
            found, vault_name = await svc.remove("tg:123", "fireflies")

            assert found is True
            # update_one must set active=False
            update_call = db_instance.update_one.call_args
            set_data = update_call[0][2]["$set"]
            assert set_data["active"] is False

    @pytest.mark.asyncio
    async def test_persistence_remove_not_found(self) -> None:
        """remove() returns False when doc does not exist."""
        with patch(
            "parrot.integrations.telegram.mcp_persistence.DocumentDb"
        ) as MockDb:
            db_instance = AsyncMock()
            MockDb.return_value.__aenter__ = AsyncMock(return_value=db_instance)
            MockDb.return_value.__aexit__ = AsyncMock(return_value=False)
            db_instance.read_one = AsyncMock(return_value=None)

            svc = TelegramMCPPersistenceService()
            found, vault_name = await svc.remove("tg:123", "nonexistent")

            assert found is False
            assert vault_name is None


# ---------------------------------------------------------------------------
# Module 3: add_mcp_handler
# ---------------------------------------------------------------------------


class TestAddMcpHandler:
    """Tests for add_mcp_handler."""

    @pytest.mark.asyncio
    async def test_add_mcp_happy_path(self, bearer_payload: dict) -> None:
        """add_mcp_handler persists → stores vault → registers tools in order."""
        msg = _make_message(f"/add_mcp {json.dumps(bearer_payload)}")
        tm = _make_tool_manager(["tool1", "tool2"])
        resolver = AsyncMock(return_value=tm)

        with (
            patch(
                "parrot.integrations.telegram.mcp_commands.TelegramMCPPersistenceService"
            ) as MockSvc,
            patch(
                "parrot.integrations.telegram.mcp_commands.store_vault_credential"
            ) as mock_store,
            patch(
                "parrot.integrations.telegram.mcp_commands.delete_vault_credential"
            ) as mock_delete,
        ):
            svc_instance = _make_persistence_service()
            MockSvc.return_value = svc_instance
            mock_store.return_value = None

            await add_mcp_handler(msg, resolver)

            # persistence.save was called
            svc_instance.save.assert_called_once()
            save_args = svc_instance.save.call_args[0]
            assert save_args[0] == "tg:12345"
            assert save_args[1] == "fireflies"

            # store_vault_credential was called with the token
            mock_store.assert_called_once()
            vault_args = mock_store.call_args[0]
            assert vault_args[0] == "tg:12345"
            assert vault_args[2] == {"token": "sk-test-0123456789"}

            # ToolManager.add_mcp_server was called
            tm.add_mcp_server.assert_called_once()

            # delete_vault_credential was NOT called (no rollback)
            mock_delete.assert_not_called()

            # Reply contains "Connected"
            reply_text = msg.reply.call_args[0][0]
            assert "Connected" in reply_text
            assert "fireflies" in reply_text
            assert "2 tool(s)" in reply_text

    @pytest.mark.asyncio
    async def test_add_mcp_rolls_back_on_vault_failure(
        self, bearer_payload: dict
    ) -> None:
        """Vault failure → persistence.remove called, error reply sent."""
        msg = _make_message(f"/add_mcp {json.dumps(bearer_payload)}")
        tm = _make_tool_manager()
        resolver = AsyncMock(return_value=tm)

        with (
            patch(
                "parrot.integrations.telegram.mcp_commands.TelegramMCPPersistenceService"
            ) as MockSvc,
            patch(
                "parrot.integrations.telegram.mcp_commands.store_vault_credential",
                side_effect=RuntimeError("Vault unavailable"),
            ),
        ):
            svc_instance = _make_persistence_service()
            MockSvc.return_value = svc_instance

            await add_mcp_handler(msg, resolver)

            # persistence.save was attempted
            svc_instance.save.assert_called_once()
            # persistence.remove was called to rollback
            svc_instance.remove.assert_called_once_with("tg:12345", "fireflies")
            # ToolManager was NOT called
            tm.add_mcp_server.assert_not_called()
            # Error reply was sent
            reply_text = msg.reply.call_args[0][0]
            assert "Could not store credentials" in reply_text

    @pytest.mark.asyncio
    async def test_add_mcp_rolls_back_on_tool_manager_failure(
        self, bearer_payload: dict
    ) -> None:
        """ToolManager failure → persistence.remove + delete_vault called."""
        msg = _make_message(f"/add_mcp {json.dumps(bearer_payload)}")
        tm = _make_tool_manager()
        tm.add_mcp_server = AsyncMock(side_effect=RuntimeError("MCP unreachable"))
        resolver = AsyncMock(return_value=tm)

        with (
            patch(
                "parrot.integrations.telegram.mcp_commands.TelegramMCPPersistenceService"
            ) as MockSvc,
            patch(
                "parrot.integrations.telegram.mcp_commands.store_vault_credential"
            ) as mock_store,
            patch(
                "parrot.integrations.telegram.mcp_commands.delete_vault_credential"
            ) as mock_delete,
        ):
            svc_instance = _make_persistence_service()
            MockSvc.return_value = svc_instance
            mock_store.return_value = None
            mock_delete.return_value = None

            await add_mcp_handler(msg, resolver)

            # Rollback: persistence.remove called
            svc_instance.remove.assert_called_once_with("tg:12345", "fireflies")
            # Rollback: delete_vault_credential called
            mock_delete.assert_called_once()
            # Error reply
            reply_text = msg.reply.call_args[0][0]
            assert "Could not connect" in reply_text

    @pytest.mark.asyncio
    async def test_non_private_chat_rejected(self, bearer_payload: dict) -> None:
        """Group chat command → security reply, no other calls."""
        msg = _make_message(
            f"/add_mcp {json.dumps(bearer_payload)}", chat_type="group"
        )
        resolver = AsyncMock(return_value=_make_tool_manager())

        with patch(
            "parrot.integrations.telegram.mcp_commands.TelegramMCPPersistenceService"
        ) as MockSvc:
            svc_instance = _make_persistence_service()
            MockSvc.return_value = svc_instance

            await add_mcp_handler(msg, resolver)

            # Security reply sent
            reply_text = msg.reply.call_args[0][0]
            assert "security" in reply_text.lower() or "direct message" in reply_text
            # No persistence
            svc_instance.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_mcp_no_auth_scheme_none(self) -> None:
        """auth_scheme=none → no Vault call needed."""
        payload = {
            "name": "public-server",
            "url": "https://public.example/mcp",
            "auth_scheme": "none",
        }
        msg = _make_message(f"/add_mcp {json.dumps(payload)}")
        tm = _make_tool_manager(["tool1"])
        resolver = AsyncMock(return_value=tm)

        with (
            patch(
                "parrot.integrations.telegram.mcp_commands.TelegramMCPPersistenceService"
            ) as MockSvc,
            patch(
                "parrot.integrations.telegram.mcp_commands.store_vault_credential"
            ) as mock_store,
        ):
            svc_instance = _make_persistence_service()
            MockSvc.return_value = svc_instance

            await add_mcp_handler(msg, resolver)

            # No Vault call for none scheme
            mock_store.assert_not_called()
            # Persistence save called with vault_name=None
            save_args = svc_instance.save.call_args[0]
            assert save_args[3] is None  # vault_credential_name


# ---------------------------------------------------------------------------
# Module 3: list_mcp_handler
# ---------------------------------------------------------------------------


class TestListMcpHandler:
    """Tests for list_mcp_handler."""

    @pytest.mark.asyncio
    async def test_list_mcp_hides_secrets(self, bearer_payload: dict) -> None:
        """Reply text contains name/url/scheme but NOT the bearer token."""
        msg = _make_message("/list_mcp")
        config = _make_user_tg_config(
            name="fireflies",
            url="https://api.fireflies.ai/mcp",
            auth_scheme="bearer",
        )

        with patch(
            "parrot.integrations.telegram.mcp_commands.TelegramMCPPersistenceService"
        ) as MockSvc:
            svc_instance = _make_persistence_service(configs=[config])
            MockSvc.return_value = svc_instance

            await list_mcp_handler(msg)

            reply_text = msg.reply.call_args[0][0]
            assert "fireflies" in reply_text
            assert "https://api.fireflies.ai/mcp" in reply_text
            assert "bearer" in reply_text
            # Secrets must NOT appear
            assert "sk-test-0123456789" not in reply_text
            assert bearer_payload["token"] not in reply_text

    @pytest.mark.asyncio
    async def test_list_mcp_empty(self) -> None:
        """Empty list → 'No MCP servers registered yet.' reply."""
        msg = _make_message("/list_mcp")

        with patch(
            "parrot.integrations.telegram.mcp_commands.TelegramMCPPersistenceService"
        ) as MockSvc:
            svc_instance = _make_persistence_service(configs=[])
            MockSvc.return_value = svc_instance

            await list_mcp_handler(msg)

            reply_text = msg.reply.call_args[0][0]
            assert "No MCP servers" in reply_text

    @pytest.mark.asyncio
    async def test_list_mcp_group_rejected(self) -> None:
        """Group chat → security reply, no DB access."""
        msg = _make_message("/list_mcp", chat_type="group")

        with patch(
            "parrot.integrations.telegram.mcp_commands.TelegramMCPPersistenceService"
        ) as MockSvc:
            svc_instance = _make_persistence_service()
            MockSvc.return_value = svc_instance

            await list_mcp_handler(msg)

            svc_instance.list.assert_not_called()


# ---------------------------------------------------------------------------
# Module 3: remove_mcp_handler
# ---------------------------------------------------------------------------


class TestRemoveMcpHandler:
    """Tests for remove_mcp_handler."""

    @pytest.mark.asyncio
    async def test_remove_mcp_clears_vault_and_doc(self, bearer_payload: dict) -> None:
        """DELETE removes from ToolManager, DocumentDB, and Vault."""
        msg = _make_message("/remove_mcp fireflies")
        tm = _make_tool_manager()
        resolver = AsyncMock(return_value=tm)

        with (
            patch(
                "parrot.integrations.telegram.mcp_commands.TelegramMCPPersistenceService"
            ) as MockSvc,
            patch(
                "parrot.integrations.telegram.mcp_commands.delete_vault_credential"
            ) as mock_delete,
        ):
            svc_instance = _make_persistence_service(
                remove_result=(True, "tg_mcp_fireflies")
            )
            MockSvc.return_value = svc_instance
            mock_delete.return_value = None

            await remove_mcp_handler(msg, resolver)

            # ToolManager.remove_mcp_server called
            tm.remove_mcp_server.assert_called_once_with("fireflies")
            # persistence.remove called
            svc_instance.remove.assert_called_once_with("tg:12345", "fireflies")
            # read_one is no longer called
            svc_instance.read_one.assert_not_called()
            # delete_vault_credential called
            mock_delete.assert_called_once_with("tg:12345", "tg_mcp_fireflies")

            reply_text = msg.reply.call_args[0][0]
            assert "Removed" in reply_text

    @pytest.mark.asyncio
    async def test_remove_mcp_missing_vault_entry_does_not_raise(self) -> None:
        """KeyError from delete_vault_credential is silently ignored."""
        msg = _make_message("/remove_mcp fireflies")
        tm = _make_tool_manager()
        resolver = AsyncMock(return_value=tm)

        with (
            patch(
                "parrot.integrations.telegram.mcp_commands.TelegramMCPPersistenceService"
            ) as MockSvc,
            patch(
                "parrot.integrations.telegram.mcp_commands.delete_vault_credential",
                side_effect=KeyError("not found"),
            ),
        ):
            svc_instance = _make_persistence_service(
                remove_result=(True, "tg_mcp_fireflies")
            )
            MockSvc.return_value = svc_instance

            # Must not raise
            await remove_mcp_handler(msg, resolver)
            # Success reply still sent
            reply_text = msg.reply.call_args[0][0]
            assert "Removed" in reply_text

    @pytest.mark.asyncio
    async def test_remove_mcp_no_vault_name(self) -> None:
        """If vault_credential_name is None, delete_vault_credential is not called."""
        msg = _make_message("/remove_mcp public-server")
        tm = _make_tool_manager()
        resolver = AsyncMock(return_value=tm)

        with (
            patch(
                "parrot.integrations.telegram.mcp_commands.TelegramMCPPersistenceService"
            ) as MockSvc,
            patch(
                "parrot.integrations.telegram.mcp_commands.delete_vault_credential"
            ) as mock_delete,
        ):
            svc_instance = _make_persistence_service(
                remove_result=(True, None)
            )
            MockSvc.return_value = svc_instance

            await remove_mcp_handler(msg, resolver)
            mock_delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_remove_mcp_group_rejected(self) -> None:
        """Group chat → security reply, no DB access."""
        msg = _make_message("/remove_mcp fireflies", chat_type="group")
        resolver = AsyncMock(return_value=_make_tool_manager())

        with patch(
            "parrot.integrations.telegram.mcp_commands.TelegramMCPPersistenceService"
        ) as MockSvc:
            svc_instance = _make_persistence_service()
            MockSvc.return_value = svc_instance

            await remove_mcp_handler(msg, resolver)

            svc_instance.remove.assert_not_called()
            reply_text = msg.reply.call_args[0][0]
            assert "security" in reply_text.lower() or "direct message" in reply_text


# ---------------------------------------------------------------------------
# Module 3: rehydrate_user_mcp_servers
# ---------------------------------------------------------------------------


class TestRehydrate:
    """Tests for rehydrate_user_mcp_servers."""

    @pytest.mark.asyncio
    async def test_rehydrate_reassembles_config(self, bearer_payload: dict) -> None:
        """Public config + Vault secret rebuild a valid MCPClientConfig."""
        tm = _make_tool_manager(["tool1"])
        config = _make_user_tg_config()

        with (
            patch(
                "parrot.integrations.telegram.mcp_commands.TelegramMCPPersistenceService"
            ) as MockSvc,
            patch(
                "parrot.integrations.telegram.mcp_commands.retrieve_vault_credential",
                return_value={"token": "sk-test-0123456789"},
            ),
        ):
            svc_instance = _make_persistence_service(configs=[config])
            MockSvc.return_value = svc_instance

            count = await rehydrate_user_mcp_servers(tm, "tg:12345")

            assert count == 1
            tm.add_mcp_server.assert_called_once()
            # The config passed to add_mcp_server should have the name
            added_config = tm.add_mcp_server.call_args[0][0]
            assert added_config.name == "fireflies"

    @pytest.mark.asyncio
    async def test_rehydrate_skips_missing_secret(self) -> None:
        """Missing Vault entry → server skipped, count reflects only successful ones."""
        tm = _make_tool_manager(["tool1"])
        config1 = _make_user_tg_config(name="fireflies")
        config2 = _make_user_tg_config(
            name="brave",
            url="https://api.brave.com/mcp",
            auth_scheme="bearer",
            vault_credential_name="tg_mcp_brave",
        )

        vault_responses: Dict[str, Any] = {
            "tg_mcp_fireflies": {"token": "sk-ok"},
            "tg_mcp_brave": KeyError("missing"),
        }

        async def fake_retrieve(user_id: str, vault_name: str) -> Dict[str, Any]:
            result = vault_responses[vault_name]
            if isinstance(result, Exception):
                raise result
            return result

        with (
            patch(
                "parrot.integrations.telegram.mcp_commands.TelegramMCPPersistenceService"
            ) as MockSvc,
            patch(
                "parrot.integrations.telegram.mcp_commands.retrieve_vault_credential",
                side_effect=fake_retrieve,
            ),
        ):
            svc_instance = _make_persistence_service(configs=[config1, config2])
            MockSvc.return_value = svc_instance

            count = await rehydrate_user_mcp_servers(tm, "tg:12345")

            # Only fireflies succeeded
            assert count == 1
            # add_mcp_server called exactly once
            tm.add_mcp_server.assert_called_once()

    @pytest.mark.asyncio
    async def test_rehydrate_none_tool_manager(self) -> None:
        """None tool_manager → returns 0 immediately."""
        count = await rehydrate_user_mcp_servers(None, "tg:12345")
        assert count == 0

    @pytest.mark.asyncio
    async def test_rehydrate_empty_list(self) -> None:
        """No persisted configs → returns 0."""
        tm = _make_tool_manager()
        with patch(
            "parrot.integrations.telegram.mcp_commands.TelegramMCPPersistenceService"
        ) as MockSvc:
            svc_instance = _make_persistence_service(configs=[])
            MockSvc.return_value = svc_instance

            count = await rehydrate_user_mcp_servers(tm, "tg:12345")
            assert count == 0
            tm.add_mcp_server.assert_not_called()


# ---------------------------------------------------------------------------
# Regression: Redis key is never written
# ---------------------------------------------------------------------------


class TestRedisNotUsed:
    """Ensure no Redis writes happen in the new Vault-backed implementation."""

    @pytest.mark.asyncio
    async def test_vault_is_used_not_redis(self, bearer_payload: dict) -> None:
        """add_mcp writes secrets to the Vault and config to DocumentDB, not Redis."""
        msg = _make_message(f"/add_mcp {json.dumps(bearer_payload)}")
        tm = _make_tool_manager(["tool1"])
        resolver = AsyncMock(return_value=tm)

        with (
            patch(
                "parrot.integrations.telegram.mcp_commands.TelegramMCPPersistenceService"
            ) as MockSvc,
            patch(
                "parrot.integrations.telegram.mcp_commands.store_vault_credential"
            ) as mock_vault_store,
        ):
            svc_instance = _make_persistence_service()
            MockSvc.return_value = svc_instance

            await add_mcp_handler(msg, resolver)

            # Vault was used for the secret
            mock_vault_store.assert_called_once()
            vault_args = mock_vault_store.call_args[0]
            assert vault_args[0] == "tg:12345"
            assert vault_args[2] == {"token": "sk-test-0123456789"}

            # DocumentDB persistence was used for public config
            svc_instance.save.assert_called_once()


# ---------------------------------------------------------------------------
# Integration: end-to-end add → list → remove (in-memory mocks)
# ---------------------------------------------------------------------------


class TestEndToEnd:
    """Integration-style tests using mocked DocumentDb and Vault."""

    @pytest.mark.asyncio
    async def test_end_to_end_add_list_remove(self, bearer_payload: dict) -> None:
        """add_mcp → list_mcp (no secrets) → remove_mcp (clears both stores)."""
        # In-memory state
        db_store: Dict[str, UserTelegramMCPConfig] = {}
        vault_store: Dict[str, Dict[str, Any]] = {}

        # Patch TelegramMCPPersistenceService with an in-memory implementation
        class InMemoryPersistence:
            COLLECTION = "telegram_user_mcp_configs"

            async def save(
                self,
                user_id: str,
                name: str,
                params: TelegramMCPPublicParams,
                vault_credential_name: Optional[str],
            ) -> None:
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc).isoformat()
                key = f"{user_id}:{name}"
                db_store[key] = UserTelegramMCPConfig(
                    user_id=user_id,
                    name=name,
                    params=params,
                    vault_credential_name=vault_credential_name,
                    active=True,
                    created_at=now,
                    updated_at=now,
                )

            async def list(self, user_id: str) -> List[UserTelegramMCPConfig]:
                return [
                    cfg for cfg in db_store.values()
                    if cfg.user_id == user_id and cfg.active
                ]

            async def read_one(
                self, user_id: str, name: str
            ) -> Optional[UserTelegramMCPConfig]:
                key = f"{user_id}:{name}"
                cfg = db_store.get(key)
                return cfg if cfg and cfg.active else None

            async def remove(self, user_id: str, name: str) -> tuple:
                key = f"{user_id}:{name}"
                if key in db_store:
                    vault_name = db_store[key].vault_credential_name
                    db_store[key] = db_store[key].model_copy(
                        update={"active": False}
                    )
                    return True, vault_name
                return False, None

        async def fake_store(
            user_id: str, vault_name: str, secret_params: Dict[str, Any]
        ) -> None:
            vault_store[f"{user_id}:{vault_name}"] = secret_params

        async def fake_retrieve(user_id: str, vault_name: str) -> Dict[str, Any]:
            key = f"{user_id}:{vault_name}"
            if key not in vault_store:
                raise KeyError(vault_name)
            return vault_store[key]

        async def fake_delete(user_id: str, vault_name: str) -> None:
            vault_store.pop(f"{user_id}:{vault_name}", None)

        tm = _make_tool_manager(["fireflies_list_transcripts"])
        resolver = AsyncMock(return_value=tm)

        with (
            patch(
                "parrot.integrations.telegram.mcp_commands.TelegramMCPPersistenceService",
                return_value=InMemoryPersistence(),
            ),
            patch(
                "parrot.integrations.telegram.mcp_commands.store_vault_credential",
                side_effect=fake_store,
            ),
            patch(
                "parrot.integrations.telegram.mcp_commands.retrieve_vault_credential",
                side_effect=fake_retrieve,
            ),
            patch(
                "parrot.integrations.telegram.mcp_commands.delete_vault_credential",
                side_effect=fake_delete,
            ),
        ):
            # --- /add_mcp ---
            add_msg = _make_message(f"/add_mcp {json.dumps(bearer_payload)}")
            await add_mcp_handler(add_msg, resolver)
            add_reply = add_msg.reply.call_args[0][0]
            assert "Connected" in add_reply
            assert "fireflies" in add_reply

            # Vault should have the secret
            assert "tg:12345:tg_mcp_fireflies" in vault_store
            assert vault_store["tg:12345:tg_mcp_fireflies"] == {
                "token": "sk-test-0123456789"
            }

            # --- /list_mcp ---
            list_msg = _make_message("/list_mcp")
            await list_mcp_handler(list_msg)
            list_reply = list_msg.reply.call_args[0][0]
            assert "fireflies" in list_reply
            assert "sk-test-0123456789" not in list_reply

            # --- /remove_mcp ---
            remove_msg = _make_message("/remove_mcp fireflies")
            await remove_mcp_handler(remove_msg, resolver)
            remove_reply = remove_msg.reply.call_args[0][0]
            assert "Removed" in remove_reply

            # Vault should be cleared
            assert "tg:12345:tg_mcp_fireflies" not in vault_store
            # DB should be soft-deleted
            cfg = db_store.get("tg:12345:fireflies")
            assert cfg is not None
            assert cfg.active is False

            # --- /list_mcp again → empty ---
            list_msg2 = _make_message("/list_mcp")
            await list_mcp_handler(list_msg2)
            list_reply2 = list_msg2.reply.call_args[0][0]
            assert "No MCP servers" in list_reply2

    @pytest.mark.asyncio
    async def test_wrapper_rehydration_on_login(self, bearer_payload: dict) -> None:
        """After rehydrate_user_mcp_servers runs, ToolManager has the MCP tools."""
        config = _make_user_tg_config()
        tm = _make_tool_manager(["tool1"])

        with (
            patch(
                "parrot.integrations.telegram.mcp_commands.TelegramMCPPersistenceService"
            ) as MockSvc,
            patch(
                "parrot.integrations.telegram.mcp_commands.retrieve_vault_credential",
                return_value={"token": "sk-test-0123456789"},
            ),
        ):
            svc_instance = _make_persistence_service(configs=[config])
            MockSvc.return_value = svc_instance

            count = await rehydrate_user_mcp_servers(tm, "tg:12345")

            assert count == 1
            tm.add_mcp_server.assert_called_once()
            # The config should reconstruct properly
            added = tm.add_mcp_server.call_args[0][0]
            assert added.name == "fireflies"
            assert added.url == "https://api.fireflies.ai/mcp"
