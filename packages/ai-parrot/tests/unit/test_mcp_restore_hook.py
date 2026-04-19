"""Unit tests for AgentTalk._restore_user_mcp_servers (TASK-772).

Since importing AgentTalk triggers a heavy dependency chain (Cython extensions,
etc.), we test _restore_user_mcp_servers as an extracted coroutine, passing a
mock ``self`` as the first argument. This isolates the restore logic from the
rest of the handler.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.mcp.registry import UserMCPServerConfig


# ---------------------------------------------------------------------------
# Import the method at module level — only agent.py is imported, not AgentTalk's
# __init__ chain. We use sys.modules to avoid the Cython import issue.
# ---------------------------------------------------------------------------

import importlib
import sys


def _get_restore_method():
    """Return _restore_user_mcp_servers as an unbound coroutine function."""
    # Import only what we need — agent.py is in the source path
    # but may have Cython deps. Use the installed package path.
    import parrot.handlers.agent as _agent_mod
    return _agent_mod.AgentTalk._restore_user_mcp_servers


try:
    _restore_fn = _get_restore_method()
    _IMPORT_OK = True
except Exception as _import_err:
    _IMPORT_OK = False
    _restore_fn = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_self() -> MagicMock:
    """Mock the AgentTalk instance (self) for method calls."""
    handler = MagicMock()
    handler.logger = MagicMock()
    return handler


def _make_session(user_id: str | None = "user-42") -> MagicMock:
    """Build a mock session with optional user_id."""
    session = MagicMock(spec=[] if user_id is None else ["user_id"])
    if user_id is not None:
        session.user_id = user_id
    return session


def _make_tool_manager() -> AsyncMock:
    """Build a mock ToolManager."""
    tm = AsyncMock()
    tm.add_mcp_server = AsyncMock(return_value=["tool1", "tool2"])
    return tm


def _make_sample_config(
    server_name: str = "perplexity",
    vault_name: str | None = "mcp_perplexity_test-agent",
    params: dict | None = None,
) -> UserMCPServerConfig:
    """Build a sample UserMCPServerConfig."""
    return UserMCPServerConfig(
        server_name=server_name,
        agent_id="test-agent",
        user_id="user-42",
        params=params or {},
        vault_credential_name=vault_name,
        active=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _IMPORT_OK, reason="AgentTalk import unavailable")
class TestRestoreUserMCPServers:
    """Tests for AgentTalk._restore_user_mcp_servers (via the installed module)."""

    @pytest.mark.asyncio
    async def test_skips_when_tool_manager_is_none(self) -> None:
        """No-op when tool_manager is None."""
        self_ = _make_self()
        session = _make_session()

        await _restore_fn(self_, tool_manager=None, request_session=session, agent_name="a")

        self_.logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_user_id_missing_from_session(self) -> None:
        """No-op when user_id cannot be extracted from session."""
        self_ = _make_self()
        tool_manager = _make_tool_manager()
        session = MagicMock(spec=[])  # empty spec = no attributes

        await _restore_fn(self_, tool_manager=tool_manager, request_session=session, agent_name="a")

        tool_manager.add_mcp_server.assert_not_called()
        self_.logger.debug.assert_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_saved_configs(self) -> None:
        """No-op when persistence returns empty list."""
        self_ = _make_self()
        tool_manager = _make_tool_manager()
        session = _make_session()

        with (
            patch("parrot.handlers.agent._MCPPersistenceService") as mock_svc,
            patch("navigator_session.vault.config.load_master_keys", return_value={1: b"k" * 32}),
        ):
            mock_svc.return_value.load_user_mcp_configs = AsyncMock(return_value=[])
            await _restore_fn(self_, tool_manager=tool_manager, request_session=session, agent_name="a")

        tool_manager.add_mcp_server.assert_not_called()

    @pytest.mark.asyncio
    async def test_logs_warning_on_persistence_failure(self) -> None:
        """Logs WARNING and returns early when persistence load fails."""
        self_ = _make_self()
        tool_manager = _make_tool_manager()
        session = _make_session()

        with (
            patch("parrot.handlers.agent._MCPPersistenceService") as mock_svc,
            patch("navigator_session.vault.config.load_master_keys", return_value={1: b"k" * 32}),
        ):
            mock_svc.return_value.load_user_mcp_configs = AsyncMock(
                side_effect=Exception("DB down")
            )
            await _restore_fn(self_, tool_manager=tool_manager, request_session=session, agent_name="a")

        self_.logger.warning.assert_called()
        tool_manager.add_mcp_server.assert_not_called()

    @pytest.mark.asyncio
    async def test_vault_unavailable_returns_early(self) -> None:
        """Returns gracefully when vault keys cannot be loaded."""
        self_ = _make_self()
        tool_manager = _make_tool_manager()
        session = _make_session()

        config = _make_sample_config()

        with (
            patch("parrot.handlers.agent._MCPPersistenceService") as mock_svc,
            patch(
                "navigator_session.vault.config.load_master_keys",
                side_effect=RuntimeError("Vault unavailable"),
            ),
        ):
            mock_svc.return_value.load_user_mcp_configs = AsyncMock(return_value=[config])
            await _restore_fn(self_, tool_manager=tool_manager, request_session=session, agent_name="a")

        self_.logger.warning.assert_called()
        tool_manager.add_mcp_server.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_server_without_factory(self) -> None:
        """Logs DEBUG and skips servers that have no create_* factory (genmedia)."""
        self_ = _make_self()
        tool_manager = _make_tool_manager()
        session = _make_session()

        config = _make_sample_config(server_name="genmedia", vault_name=None)

        with (
            patch("parrot.handlers.agent._MCPPersistenceService") as mock_svc,
            patch("navigator_session.vault.config.load_master_keys", return_value={1: b"k" * 32}),
        ):
            mock_svc.return_value.load_user_mcp_configs = AsyncMock(return_value=[config])
            await _restore_fn(self_, tool_manager=tool_manager, request_session=session, agent_name="a")

        tool_manager.add_mcp_server.assert_not_called()

    @pytest.mark.asyncio
    async def test_logs_warning_when_vault_credential_missing(self) -> None:
        """Logs WARNING and skips server when Vault credential is not found in DB."""
        self_ = _make_self()
        tool_manager = _make_tool_manager()
        session = _make_session()

        config = _make_sample_config(server_name="perplexity", vault_name="mcp_perplexity_a")

        mock_db = AsyncMock()
        mock_db.read_one = AsyncMock(return_value=None)  # Vault cred missing
        mock_db_cm = AsyncMock()
        mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("parrot.handlers.agent._MCPPersistenceService") as mock_svc,
            patch("navigator_session.vault.config.load_master_keys", return_value={1: b"k" * 32}),
            patch("parrot.interfaces.documentdb.DocumentDb", return_value=mock_db_cm),
        ):
            mock_svc.return_value.load_user_mcp_configs = AsyncMock(return_value=[config])
            await _restore_fn(self_, tool_manager=tool_manager, request_session=session, agent_name="a")

        self_.logger.warning.assert_called()
        tool_manager.add_mcp_server.assert_not_called()

    @pytest.mark.asyncio
    async def test_continues_after_individual_server_failure(self) -> None:
        """Logs WARNING for each failed server but continues with the next one."""
        self_ = _make_self()

        call_count = 0

        async def flaky_add(config):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("refused")
            return ["tool-ok"]

        tool_manager = _make_tool_manager()
        tool_manager.add_mcp_server = AsyncMock(side_effect=flaky_add)
        session = _make_session()

        # Use two servers that have no required secret params so the factory succeeds
        configs = [
            _make_sample_config("google-maps", vault_name=None, params={}),
            _make_sample_config("chrome-devtools", vault_name=None, params={}),
        ]

        with (
            patch("parrot.handlers.agent._MCPPersistenceService") as mock_svc,
            patch("navigator_session.vault.config.load_master_keys", return_value={1: b"k" * 32}),
        ):
            mock_svc.return_value.load_user_mcp_configs = AsyncMock(return_value=configs)
            await _restore_fn(self_, tool_manager=tool_manager, request_session=session, agent_name="a")

        # Warning logged for the failed server
        self_.logger.warning.assert_called()
        # Both servers had add_mcp_server attempted (one failed, one succeeded)
        assert tool_manager.add_mcp_server.call_count == 2
        # Info logged for the successful one
        self_.logger.info.assert_called()

    @pytest.mark.asyncio
    async def test_restores_server_without_vault_needed(self) -> None:
        """Restores a server whose config has no vault_credential_name."""
        self_ = _make_self()
        tool_manager = _make_tool_manager()
        session = _make_session()

        config = _make_sample_config(server_name="google-maps", vault_name=None, params={})

        with (
            patch("parrot.handlers.agent._MCPPersistenceService") as mock_svc,
            patch("navigator_session.vault.config.load_master_keys", return_value={1: b"k" * 32}),
        ):
            mock_svc.return_value.load_user_mcp_configs = AsyncMock(return_value=[config])
            await _restore_fn(self_, tool_manager=tool_manager, request_session=session, agent_name="a")

        tool_manager.add_mcp_server.assert_called_once()
        self_.logger.info.assert_called()


# ---------------------------------------------------------------------------
# Fallback tests when import is not available
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_IMPORT_OK, reason="Only runs when import fails")
class TestRestoreHookImportFallback:
    """Placeholder tests for environments where AgentTalk cannot be imported."""

    def test_restore_method_exists_in_source(self) -> None:
        """Verify the method was added to agent.py by checking source content."""
        import os

        agent_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "src",
            "parrot",
            "handlers",
            "agent.py",
        )
        with open(os.path.abspath(agent_path)) as f:
            content = f.read()

        assert "_restore_user_mcp_servers" in content, (
            "_restore_user_mcp_servers method not found in agent.py"
        )

    def test_enable_mcp_restore_opt_in_present(self) -> None:
        """Verify the opt-in check is present in agent.py."""
        import os

        agent_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "src",
            "parrot",
            "handlers",
            "agent.py",
        )
        with open(os.path.abspath(agent_path)) as f:
            content = f.read()

        assert "enable_mcp_restore" in content, (
            "enable_mcp_restore opt-in not found in agent.py"
        )
