"""Unit tests for the _warm_up coroutine (TASK-1036).

Loads ephemeral.py directly via importlib so we avoid the full BotManager
import chain.  All external dependencies (FAISSStore, validate_mcp_http,
pageindex builder) are mocked.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Load ephemeral.py directly (bypass heavy package chain)
# ---------------------------------------------------------------------------

_WT_ROOT = Path(__file__).resolve().parents[2]
_EPHEMERAL_SRC = (
    _WT_ROOT / "packages" / "ai-parrot" / "src" / "parrot" / "manager" / "ephemeral.py"
)

if "parrot.manager.ephemeral" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "parrot.manager.ephemeral", str(_EPHEMERAL_SRC)
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["parrot.manager.ephemeral"] = _mod
    _spec.loader.exec_module(_mod)

from parrot.manager.ephemeral import (  # noqa: E402
    EphemeralAgentStatus,
    _warm_up,
    _extract_mcp_servers,
)

_EPHEMERAL_MOD = sys.modules["parrot.manager.ephemeral"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_status(
    chatbot_id: str = "bot-abc",
    user_id: int = 42,
    phase: str = "creating",
    rag_mode=None,
) -> EphemeralAgentStatus:
    now = datetime.utcnow()
    return EphemeralAgentStatus(
        chatbot_id=chatbot_id,
        user_id=user_id,
        phase=phase,
        created_at=now,
        expires_at=now + timedelta(hours=24),
        rag_mode=rag_mode,
    )


def _make_bot(mcp_config=None, documents=None) -> MagicMock:
    bot = MagicMock()
    bot.configure = AsyncMock()
    bot.chatbot_id = "bot-abc"
    bot.mcp_config = mcp_config or []
    bot.documents = documents or []
    return bot


# ---------------------------------------------------------------------------
# Tests — phase transitions
# ---------------------------------------------------------------------------


class TestWarmUpPhaseTransitions:
    """Verify phase transitions through the warm-up lifecycle."""

    @pytest.mark.asyncio
    async def test_success_reaches_ready(self) -> None:
        """_warm_up transitions creating → warming → ready on success."""
        bot = _make_bot()
        status = _make_status()
        assert status.phase == "creating"

        await _warm_up(bot, status, MagicMock())

        assert status.phase == "ready"

    @pytest.mark.asyncio
    async def test_warming_phase_set_before_configure(self) -> None:
        """Phase is set to 'warming' before configure() is awaited."""
        phases_seen: list[str] = []

        async def _track_phase(*a, **kw):
            phases_seen.append(status.phase)

        bot = _make_bot()
        bot.configure = AsyncMock(side_effect=_track_phase)
        status = _make_status()

        await _warm_up(bot, status, MagicMock())

        assert "warming" in phases_seen

    @pytest.mark.asyncio
    async def test_configure_failure_sets_error_phase(self) -> None:
        """configure() raising sets phase='error' and records error message."""
        bot = _make_bot()
        bot.configure = AsyncMock(side_effect=RuntimeError("LLM init failed"))
        status = _make_status()

        await _warm_up(bot, status, MagicMock())

        assert status.phase == "error"
        assert "LLM init failed" in status.error

    @pytest.mark.asyncio
    async def test_error_does_not_reraise(self) -> None:
        """Exceptions in _warm_up must NOT propagate — fire-and-forget safe."""
        bot = _make_bot()
        bot.configure = AsyncMock(side_effect=Exception("boom"))
        status = _make_status()

        # Must not raise:
        await _warm_up(bot, status, MagicMock())
        assert status.phase == "error"


# ---------------------------------------------------------------------------
# Tests — progress dict
# ---------------------------------------------------------------------------


class TestWarmUpProgress:
    """Verify progress dict updates for each subsystem."""

    @pytest.mark.asyncio
    async def test_tools_progress_reaches_ready(self) -> None:
        """progress['tools'] must be 'ready' after a successful warm-up."""
        bot = _make_bot()
        status = _make_status()
        await _warm_up(bot, status, MagicMock())
        assert status.progress.get("tools") == "ready"

    @pytest.mark.asyncio
    async def test_mcp_skipped_when_no_servers(self) -> None:
        """progress['mcp'] is 'skipped' when bot has no MCP servers."""
        bot = _make_bot(mcp_config=[])
        status = _make_status()
        await _warm_up(bot, status, MagicMock())
        assert status.progress.get("mcp") == "skipped"

    @pytest.mark.asyncio
    async def test_rag_skipped_when_no_documents(self) -> None:
        """progress['rag'] is 'skipped' when bot has no documents."""
        bot = _make_bot(documents=[])
        status = _make_status(rag_mode="vector")
        await _warm_up(bot, status, MagicMock())
        assert status.progress.get("rag") == "skipped"

    @pytest.mark.asyncio
    async def test_rag_skipped_when_no_rag_mode(self) -> None:
        """progress['rag'] is 'skipped' when rag_mode is None."""
        bot = _make_bot(documents=[{"name": "doc.pdf"}])
        status = _make_status(rag_mode=None)
        await _warm_up(bot, status, MagicMock())
        assert status.progress.get("rag") == "skipped"


# ---------------------------------------------------------------------------
# Tests — MCP validation
# ---------------------------------------------------------------------------


class TestWarmUpMCPValidation:
    """Tests for MCP handshake validation during warm-up."""

    @pytest.mark.asyncio
    async def test_mcp_validation_called_per_server(self) -> None:
        """validate_mcp_http is awaited once per MCP server in the config."""
        server1 = MagicMock()
        server2 = MagicMock()

        bot = _make_bot(mcp_config=[server1, server2])
        status = _make_status()

        mock_validate = AsyncMock()
        with patch.object(_EPHEMERAL_MOD, "__builtins__", __builtins__):
            # Patch the lazy import inside _warm_up via the sys.modules path.
            import types as _types
            _fake_mcp_mod = _types.ModuleType("parrot.mcp.integration")
            _fake_mcp_mod.validate_mcp_http = mock_validate
            old = sys.modules.get("parrot.mcp.integration")
            sys.modules["parrot.mcp.integration"] = _fake_mcp_mod
            try:
                await _warm_up(bot, status, MagicMock())
            finally:
                if old is None:
                    sys.modules.pop("parrot.mcp.integration", None)
                else:
                    sys.modules["parrot.mcp.integration"] = old

        assert status.phase == "ready"
        assert mock_validate.call_count == 2
        assert status.progress.get("mcp") == "ready"

    @pytest.mark.asyncio
    async def test_mcp_failure_sets_error_phase(self) -> None:
        """validate_mcp_http raising causes phase='error'."""
        server = MagicMock()
        bot = _make_bot(mcp_config=[server])
        status = _make_status()

        mock_validate = AsyncMock(side_effect=Exception("handshake failed"))
        import types as _types
        _fake_mcp_mod = _types.ModuleType("parrot.mcp.integration")
        _fake_mcp_mod.validate_mcp_http = mock_validate
        old = sys.modules.get("parrot.mcp.integration")
        sys.modules["parrot.mcp.integration"] = _fake_mcp_mod
        try:
            await _warm_up(bot, status, MagicMock())
        finally:
            if old is None:
                sys.modules.pop("parrot.mcp.integration", None)
            else:
                sys.modules["parrot.mcp.integration"] = old

        assert status.phase == "error"
        assert status.error is not None


# ---------------------------------------------------------------------------
# Tests — FAISS RAG build
# ---------------------------------------------------------------------------


class TestWarmUpFAISSBuild:
    """Tests for FAISS index building during warm-up."""

    @pytest.mark.asyncio
    async def test_faiss_add_documents_called_on_vector_mode(self) -> None:
        """_build_faiss_index is triggered when rag_mode='vector' and docs present."""
        docs = [{"name": "doc1.pdf"}, {"name": "doc2.pdf"}]
        bot = _make_bot(documents=docs)
        status = _make_status(rag_mode="vector")

        mock_store = MagicMock()
        mock_store.add_documents = AsyncMock()

        import types as _types
        _fake_faiss_mod = _types.ModuleType("parrot.stores.faiss_store")
        _fake_faiss_mod.FAISSStore = MagicMock(return_value=mock_store)

        old = sys.modules.get("parrot.stores.faiss_store")
        sys.modules["parrot.stores.faiss_store"] = _fake_faiss_mod
        try:
            await _warm_up(bot, status, MagicMock())
        finally:
            if old is None:
                sys.modules.pop("parrot.stores.faiss_store", None)
            else:
                sys.modules["parrot.stores.faiss_store"] = old

        mock_store.add_documents.assert_called_once()
        assert status.phase == "ready"
        assert status.progress.get("rag") == "ready"


# ---------------------------------------------------------------------------
# Tests — _extract_mcp_servers helper
# ---------------------------------------------------------------------------


class TestExtractMCPServers:
    """Tests for the _extract_mcp_servers helper."""

    def test_returns_empty_when_bot_has_no_mcp_config(self) -> None:
        """Returns [] when bot.mcp_config is absent or empty."""
        bot = MagicMock()
        bot.mcp_config = []
        assert _extract_mcp_servers(bot) == []

    def test_returns_empty_when_mcp_config_is_none(self) -> None:
        """Returns [] when bot.mcp_config is None."""
        bot = MagicMock()
        bot.mcp_config = None
        assert _extract_mcp_servers(bot) == []

    def test_returns_objects_unchanged(self) -> None:
        """Non-dict entries in mcp_config are passed through unchanged."""
        bot = MagicMock()
        server = MagicMock()  # already a config object
        bot.mcp_config = [server]
        result = _extract_mcp_servers(bot)
        assert result == [server]
