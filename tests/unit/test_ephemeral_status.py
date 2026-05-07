"""Unit tests for EphemeralAgentStatus and EphemeralRegistry (TASK-1034)."""
from __future__ import annotations

import importlib.util
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Direct module load — bypasses parrot.manager.__init__ (which pulls in the
# entire BotManager dependency chain including Cython extensions not available
# in worktrees).  This pattern mirrors conftest_db.py used by other unit tests.
# ---------------------------------------------------------------------------
_WORKTREE_ROOT = Path(__file__).resolve().parents[2]
_EPHEMERAL_SRC = _WORKTREE_ROOT / "packages" / "ai-parrot" / "src" / "parrot" / "manager" / "ephemeral.py"

if "parrot.manager.ephemeral" not in sys.modules:
    _spec = importlib.util.spec_from_file_location("parrot.manager.ephemeral", str(_EPHEMERAL_SRC))
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["parrot.manager.ephemeral"] = _mod
    _spec.loader.exec_module(_mod)

from parrot.manager.ephemeral import EphemeralAgentStatus, EphemeralRegistry  # noqa: E402


class TestEphemeralAgentStatus:
    """Tests for the EphemeralAgentStatus Pydantic model."""

    def test_create_with_valid_fields(self):
        """Model accepts all fields from spec §2 Data Models."""
        now = datetime.utcnow()
        status = EphemeralAgentStatus(
            chatbot_id="abc-123",
            user_id=42,
            phase="creating",
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )
        assert status.phase == "creating"
        assert status.error is None
        assert status.progress == {}
        assert status.rag_mode is None

    def test_create_with_all_optional_fields(self):
        """Optional fields default correctly."""
        now = datetime.utcnow()
        status = EphemeralAgentStatus(
            chatbot_id="abc-123",
            user_id=42,
            phase="warming",
            created_at=now,
            expires_at=now + timedelta(hours=24),
            progress={"tools": "syncing"},
            error=None,
            rag_mode="vector",
        )
        assert status.rag_mode == "vector"
        assert status.progress["tools"] == "syncing"

    def test_phase_transition(self):
        """Phase can be updated in place (validate_assignment=True)."""
        now = datetime.utcnow()
        status = EphemeralAgentStatus(
            chatbot_id="abc-123",
            user_id=42,
            phase="creating",
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )
        status.phase = "warming"
        assert status.phase == "warming"
        status.phase = "ready"
        assert status.phase == "ready"
        status.phase = "error"
        assert status.phase == "error"

    def test_invalid_phase_rejected(self):
        """Invalid phase string raises ValidationError."""
        now = datetime.utcnow()
        with pytest.raises(ValidationError):
            EphemeralAgentStatus(
                chatbot_id="abc-123",
                user_id=42,
                phase="bogus",  # type: ignore[arg-type]
                created_at=now,
                expires_at=now + timedelta(hours=24),
            )

    def test_invalid_phase_update_rejected(self):
        """Assigning an invalid phase string raises ValidationError."""
        now = datetime.utcnow()
        status = EphemeralAgentStatus(
            chatbot_id="abc-123",
            user_id=42,
            phase="creating",
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )
        with pytest.raises(ValidationError):
            status.phase = "invalid"  # type: ignore[assignment]

    def test_progress_dict_is_mutable(self):
        """progress dict can be updated in place."""
        now = datetime.utcnow()
        status = EphemeralAgentStatus(
            chatbot_id="abc-123",
            user_id=42,
            phase="warming",
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )
        status.progress["tools"] = "ready"
        status.progress["mcp"] = "validating"
        assert status.progress == {"tools": "ready", "mcp": "validating"}


class TestEphemeralRegistry:
    """Tests for EphemeralRegistry ownership checks and expiration logic."""

    def _make_status(
        self,
        chatbot_id: str = "abc-123",
        user_id: int = 42,
        phase="creating",
        expires_in_hours: float = 24.0,
    ) -> EphemeralAgentStatus:
        now = datetime.utcnow()
        return EphemeralAgentStatus(
            chatbot_id=chatbot_id,
            user_id=user_id,
            phase=phase,
            created_at=now,
            expires_at=now + timedelta(hours=expires_in_hours),
        )

    @pytest.mark.asyncio
    async def test_register_and_get(self):
        """register() stores entry; get() returns it for the owning user."""
        reg = EphemeralRegistry()
        status = self._make_status()
        await reg.register(status)
        result = reg.get("abc-123", user_id=42)
        assert result is status

    @pytest.mark.asyncio
    async def test_get_wrong_user_returns_none(self):
        """get() with a different user_id returns None (ownership check)."""
        reg = EphemeralRegistry()
        status = self._make_status()
        await reg.register(status)
        assert reg.get("abc-123", user_id=999) is None

    def test_get_unknown_chatbot_returns_none(self):
        """get() for an unknown chatbot_id returns None."""
        reg = EphemeralRegistry()
        assert reg.get("nonexistent", user_id=42) is None

    @pytest.mark.asyncio
    async def test_remove_existing(self):
        """remove() deletes the entry and subsequent get() returns None."""
        reg = EphemeralRegistry()
        status = self._make_status()
        await reg.register(status)
        result = await reg.remove("abc-123")
        assert result is True
        assert reg.get("abc-123", user_id=42) is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent_returns_false(self):
        """remove() on a missing chatbot_id returns False."""
        reg = EphemeralRegistry()
        assert await reg.remove("does-not-exist") is False

    @pytest.mark.asyncio
    async def test_get_expired_returns_expired_ids(self):
        """get_expired() returns chatbot_ids past their expires_at."""
        reg = EphemeralRegistry()
        past_status = self._make_status(
            chatbot_id="expired-1", expires_in_hours=-25.0
        )
        future_status = self._make_status(
            chatbot_id="not-expired", expires_in_hours=24.0
        )
        await reg.register(past_status)
        await reg.register(future_status)

        expired = reg.get_expired()
        assert "expired-1" in expired
        assert "not-expired" not in expired

    @pytest.mark.asyncio
    async def test_get_expired_empty_when_all_fresh(self):
        """get_expired() returns empty list when all entries are fresh."""
        reg = EphemeralRegistry()
        await reg.register(self._make_status(expires_in_hours=24.0))
        assert reg.get_expired() == []

    @pytest.mark.asyncio
    async def test_register_overwrites_existing(self):
        """Registering a new status for the same chatbot_id overwrites."""
        reg = EphemeralRegistry()
        s1 = self._make_status(phase="creating")
        s2 = self._make_status(phase="ready")
        await reg.register(s1)
        await reg.register(s2)
        result = reg.get("abc-123", user_id=42)
        assert result is s2
        assert result.phase == "ready"

    @pytest.mark.asyncio
    async def test_get_all_for_user(self):
        """get_all_for_user() returns only entries for the specified user."""
        reg = EphemeralRegistry()
        await reg.register(self._make_status(chatbot_id="bot-1", user_id=42))
        await reg.register(self._make_status(chatbot_id="bot-2", user_id=42))
        await reg.register(self._make_status(chatbot_id="bot-3", user_id=99))

        user42_entries = reg.get_all_for_user(42)
        assert len(user42_entries) == 2
        assert all(s.user_id == 42 for s in user42_entries)

    @pytest.mark.asyncio
    async def test_snapshot_is_shallow_copy(self):
        """snapshot() returns a copy — mutations don't affect the registry."""
        reg = EphemeralRegistry()
        await reg.register(self._make_status())
        snap = reg.snapshot()
        snap.pop("abc-123")
        assert reg.get("abc-123", user_id=42) is not None
