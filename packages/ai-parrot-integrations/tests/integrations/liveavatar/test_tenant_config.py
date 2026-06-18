"""Unit tests for the per-tenant config resolver (TASK-1593).

Verifies ``resolve_fullmode_config`` under various env configurations:
- Env defaults resolve to a valid FullModeConfig.
- Missing required env vars raise RuntimeError.
- Optional vars fall back to defaults.
- LIVEAVATAR_SANDBOX flag is parsed correctly.
"""
from __future__ import annotations

import pytest

from parrot.integrations.liveavatar.tenant_config import resolve_fullmode_config


class TestResolveFullmodeConfig:
    """Tests for resolve_fullmode_config() (env-only phase)."""

    def test_env_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Env defaults resolve to a valid FullModeConfig with expected values."""
        monkeypatch.setenv("LIVEAVATAR_API_KEY", "key")
        monkeypatch.setenv("LIVEAVATAR_AVATAR_ID", "avatar")
        # Clear optional vars to test defaults
        monkeypatch.delenv("LIVEAVATAR_VOICE_ID", raising=False)
        monkeypatch.delenv("LIVEAVATAR_LANGUAGE", raising=False)
        monkeypatch.delenv("LIVEAVATAR_INTERACTIVITY_TYPE", raising=False)
        monkeypatch.delenv("LIVEAVATAR_SANDBOX", raising=False)
        monkeypatch.delenv("LIVEAVATAR_MAX_SESSION_DURATION", raising=False)

        cfg = resolve_fullmode_config()

        assert cfg.api_key == "key"
        assert cfg.avatar_id == "avatar"
        assert cfg.language == "en"
        assert cfg.interactivity_type == "CONVERSATIONAL"
        assert cfg.voice_id is None
        assert cfg.is_sandbox is True
        assert cfg.max_session_duration is None

    def test_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Raises RuntimeError when LIVEAVATAR_API_KEY is missing."""
        monkeypatch.delenv("LIVEAVATAR_API_KEY", raising=False)
        monkeypatch.setenv("LIVEAVATAR_AVATAR_ID", "avatar")

        with pytest.raises(RuntimeError, match="LIVEAVATAR_API_KEY"):
            resolve_fullmode_config()

    def test_missing_avatar_id_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Raises RuntimeError when LIVEAVATAR_AVATAR_ID is missing."""
        monkeypatch.setenv("LIVEAVATAR_API_KEY", "key")
        monkeypatch.delenv("LIVEAVATAR_AVATAR_ID", raising=False)

        with pytest.raises(RuntimeError, match="LIVEAVATAR_AVATAR_ID"):
            resolve_fullmode_config()

    def test_missing_both_required_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Raises RuntimeError when both required vars are missing."""
        monkeypatch.delenv("LIVEAVATAR_API_KEY", raising=False)
        monkeypatch.delenv("LIVEAVATAR_AVATAR_ID", raising=False)

        with pytest.raises(RuntimeError):
            resolve_fullmode_config()

    def test_custom_env_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Custom env vars override the defaults."""
        monkeypatch.setenv("LIVEAVATAR_API_KEY", "key")
        monkeypatch.setenv("LIVEAVATAR_AVATAR_ID", "avatar")
        monkeypatch.setenv("LIVEAVATAR_VOICE_ID", "voice-1")
        monkeypatch.setenv("LIVEAVATAR_LANGUAGE", "es")
        monkeypatch.setenv("LIVEAVATAR_INTERACTIVITY_TYPE", "PUSH_TO_TALK")

        cfg = resolve_fullmode_config()

        assert cfg.voice_id == "voice-1"
        assert cfg.language == "es"
        assert cfg.interactivity_type == "PUSH_TO_TALK"

    def test_sandbox_parsing_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LIVEAVATAR_SANDBOX=false sets is_sandbox to False."""
        monkeypatch.setenv("LIVEAVATAR_API_KEY", "key")
        monkeypatch.setenv("LIVEAVATAR_AVATAR_ID", "avatar")
        monkeypatch.setenv("LIVEAVATAR_SANDBOX", "false")

        cfg = resolve_fullmode_config()

        assert cfg.is_sandbox is False

    def test_sandbox_parsing_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LIVEAVATAR_SANDBOX=true (default) sets is_sandbox to True."""
        monkeypatch.setenv("LIVEAVATAR_API_KEY", "key")
        monkeypatch.setenv("LIVEAVATAR_AVATAR_ID", "avatar")
        monkeypatch.setenv("LIVEAVATAR_SANDBOX", "true")

        cfg = resolve_fullmode_config()

        assert cfg.is_sandbox is True

    def test_sandbox_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """is_sandbox defaults to True when LIVEAVATAR_SANDBOX is unset."""
        monkeypatch.setenv("LIVEAVATAR_API_KEY", "key")
        monkeypatch.setenv("LIVEAVATAR_AVATAR_ID", "avatar")
        monkeypatch.delenv("LIVEAVATAR_SANDBOX", raising=False)

        cfg = resolve_fullmode_config()

        assert cfg.is_sandbox is True

    def test_max_session_duration_parsed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LIVEAVATAR_MAX_SESSION_DURATION is parsed as integer."""
        monkeypatch.setenv("LIVEAVATAR_API_KEY", "key")
        monkeypatch.setenv("LIVEAVATAR_AVATAR_ID", "avatar")
        monkeypatch.setenv("LIVEAVATAR_MAX_SESSION_DURATION", "600")

        cfg = resolve_fullmode_config()

        assert cfg.max_session_duration == 600

    def test_max_session_duration_invalid_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Invalid LIVEAVATAR_MAX_SESSION_DURATION is silently ignored (returns None)."""
        monkeypatch.setenv("LIVEAVATAR_API_KEY", "key")
        monkeypatch.setenv("LIVEAVATAR_AVATAR_ID", "avatar")
        monkeypatch.setenv("LIVEAVATAR_MAX_SESSION_DURATION", "not-a-number")

        cfg = resolve_fullmode_config()

        assert cfg.max_session_duration is None

    def test_voice_id_empty_string_treated_as_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty LIVEAVATAR_VOICE_ID is treated as None (uses avatar default)."""
        monkeypatch.setenv("LIVEAVATAR_API_KEY", "key")
        monkeypatch.setenv("LIVEAVATAR_AVATAR_ID", "avatar")
        monkeypatch.setenv("LIVEAVATAR_VOICE_ID", "")

        cfg = resolve_fullmode_config()

        assert cfg.voice_id is None

    def test_tenant_id_accepted_but_ignored_in_env_phase(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """tenant_id argument is accepted without error (future DB layer)."""
        monkeypatch.setenv("LIVEAVATAR_API_KEY", "key")
        monkeypatch.setenv("LIVEAVATAR_AVATAR_ID", "avatar")

        cfg = resolve_fullmode_config(tenant_id="acme")

        assert cfg.api_key == "key"
        assert cfg.avatar_id == "avatar"

    def test_base_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LIVEAVATAR_BASE_URL is read from environment."""
        monkeypatch.setenv("LIVEAVATAR_API_KEY", "key")
        monkeypatch.setenv("LIVEAVATAR_AVATAR_ID", "avatar")
        monkeypatch.setenv("LIVEAVATAR_BASE_URL", "https://sandbox.liveavatar.com")

        cfg = resolve_fullmode_config()

        assert cfg.base_url == "https://sandbox.liveavatar.com"

    def test_base_url_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LIVEAVATAR_BASE_URL defaults to the production URL."""
        monkeypatch.setenv("LIVEAVATAR_API_KEY", "key")
        monkeypatch.setenv("LIVEAVATAR_AVATAR_ID", "avatar")
        monkeypatch.delenv("LIVEAVATAR_BASE_URL", raising=False)

        cfg = resolve_fullmode_config()

        assert cfg.base_url == "https://api.liveavatar.com"
