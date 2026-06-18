"""Unit tests for parrot.integrations.liveavatar models (TASK-001, TASK-1591)."""
import pytest
from pydantic import ValidationError

from parrot.integrations.liveavatar import (
    AvatarSessionHandle,
    FullModeConfig,
    FullModeSessionHandle,
    LiveAvatarConfig,
    LiveKitRoomTokens,
    TenantAvatarConfig,
)
from parrot.integrations.liveavatar.models import (
    FullModeConfig,
    FullModeSessionHandle,
    TenantAvatarConfig,
)


def test_config_defaults():
    """LiveAvatarConfig defaults: is_sandbox=True, correct base_url, no duration."""
    cfg = LiveAvatarConfig(api_key="k", avatar_id="a")
    assert cfg.is_sandbox is True
    assert cfg.base_url == "https://api.liveavatar.com"
    assert cfg.max_session_duration is None
    assert cfg.quality is None
    assert cfg.encoding is None


def test_config_requires_keys():
    """api_key and avatar_id are required; missing either raises ValidationError."""
    with pytest.raises(ValidationError):
        LiveAvatarConfig()  # type: ignore[call-arg]


def test_config_requires_avatar_id():
    """avatar_id alone missing also raises ValidationError."""
    with pytest.raises(ValidationError):
        LiveAvatarConfig(api_key="k")  # type: ignore[call-arg]


def test_config_optional_fields():
    """Optional fields accept values when provided."""
    cfg = LiveAvatarConfig(
        api_key="k",
        avatar_id="a",
        max_session_duration=600,
        quality="medium",
        encoding="h264",
        is_sandbox=False,
    )
    assert cfg.max_session_duration == 600
    assert cfg.quality == "medium"
    assert cfg.encoding == "h264"
    assert cfg.is_sandbox is False


def test_room_tokens_roundtrip():
    """LiveKitRoomTokens stores all fields correctly."""
    t = LiveKitRoomTokens(
        livekit_url="wss://x.livekit.cloud",
        room="r",
        client_token="c",
        agent_token="a",
    )
    assert t.room == "r"
    assert t.livekit_url == "wss://x.livekit.cloud"
    assert t.client_token == "c"
    assert t.agent_token == "a"


def test_room_tokens_requires_all_fields():
    """All LiveKitRoomTokens fields are required."""
    with pytest.raises(ValidationError):
        LiveKitRoomTokens(livekit_url="wss://x.livekit.cloud", room="r")  # type: ignore[call-arg]


def test_session_handle():
    """AvatarSessionHandle constructs correctly; tenant_id defaults to None."""
    h = AvatarSessionHandle(
        session_id="s",
        liveavatar_session_id="ls",
        session_token="st",
        ws_url="wss://ws",
        agent_name="bot",
    )
    assert h.tenant_id is None
    assert h.session_id == "s"
    assert h.agent_name == "bot"


def test_session_handle_with_tenant():
    """AvatarSessionHandle accepts an explicit tenant_id."""
    h = AvatarSessionHandle(
        session_id="s",
        liveavatar_session_id="ls",
        session_token="st",
        ws_url="wss://ws",
        agent_name="bot",
        tenant_id="acme",
    )
    assert h.tenant_id == "acme"


# ---------------------------------------------------------------------------
# FEAT-248: FullModeConfig tests (TASK-1591)
# ---------------------------------------------------------------------------


class TestFullModeConfig:
    """Tests for FullModeConfig (FULL mode session configuration)."""

    def test_defaults(self) -> None:
        """FullModeConfig defaults: language=en, interactivity_type=CONVERSATIONAL, voice_id=None."""
        cfg = FullModeConfig(api_key="key", avatar_id="avatar")
        assert cfg.language == "en"
        assert cfg.interactivity_type == "CONVERSATIONAL"
        assert cfg.voice_id is None

    def test_inherits_lite_fields(self) -> None:
        """FullModeConfig inherits all LiveAvatarConfig fields."""
        cfg = FullModeConfig(api_key="key", avatar_id="avatar")
        assert cfg.base_url == "https://api.liveavatar.com"
        assert cfg.is_sandbox is True
        assert cfg.max_session_duration is None
        assert cfg.quality is None
        assert cfg.encoding is None

    def test_custom_values(self) -> None:
        """FullModeConfig accepts custom voice_id, language, interactivity_type."""
        cfg = FullModeConfig(
            api_key="key",
            avatar_id="avatar",
            voice_id="v1",
            language="es",
            interactivity_type="PUSH_TO_TALK",
        )
        assert cfg.voice_id == "v1"
        assert cfg.language == "es"
        assert cfg.interactivity_type == "PUSH_TO_TALK"

    def test_requires_api_key_and_avatar_id(self) -> None:
        """FullModeConfig still requires api_key and avatar_id (inherited)."""
        with pytest.raises(ValidationError):
            FullModeConfig()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# FEAT-248: FullModeSessionHandle tests (TASK-1591)
# ---------------------------------------------------------------------------


class TestFullModeSessionHandle:
    """Tests for FullModeSessionHandle (FULL mode runtime session handle)."""

    def test_livekit_fields(self) -> None:
        """FullModeSessionHandle carries livekit_url and livekit_client_token."""
        handle = FullModeSessionHandle(
            session_id="s1",
            liveavatar_session_id="la1",
            session_token="tok",
            ws_url="",
            agent_name="agent",
            livekit_url="wss://test.livekit.cloud",
            livekit_client_token="eyJ...",
        )
        assert handle.livekit_url == "wss://test.livekit.cloud"
        assert handle.livekit_client_token == "eyJ..."

    def test_livekit_fields_default_empty(self) -> None:
        """livekit_url and livekit_client_token default to empty strings."""
        handle = FullModeSessionHandle(
            session_id="s1",
            liveavatar_session_id="la1",
            session_token="tok",
            ws_url="",
            agent_name="agent",
        )
        assert handle.livekit_url == ""
        assert handle.livekit_client_token == ""

    def test_inherits_session_handle_fields(self) -> None:
        """FullModeSessionHandle inherits all AvatarSessionHandle fields."""
        handle = FullModeSessionHandle(
            session_id="s1",
            liveavatar_session_id="la1",
            session_token="tok",
            ws_url="",
            agent_name="agent",
            tenant_id="acme",
        )
        assert handle.session_id == "s1"
        assert handle.liveavatar_session_id == "la1"
        assert handle.session_token == "tok"
        assert handle.ws_url == ""
        assert handle.agent_name == "agent"
        assert handle.tenant_id == "acme"


# ---------------------------------------------------------------------------
# FEAT-248: TenantAvatarConfig tests (TASK-1591)
# ---------------------------------------------------------------------------


class TestTenantAvatarConfig:
    """Tests for TenantAvatarConfig (per-tenant DB override model)."""

    def test_required_tenant_id(self) -> None:
        """TenantAvatarConfig requires tenant_id; other fields default to None/False."""
        cfg = TenantAvatarConfig(tenant_id="acme")
        assert cfg.tenant_id == "acme"
        assert cfg.fullmode_enabled is False
        assert cfg.avatar_id is None
        assert cfg.voice_id is None
        assert cfg.language is None
        assert cfg.interactivity_type is None
        assert cfg.api_key is None

    def test_all_optional_fields(self) -> None:
        """TenantAvatarConfig accepts all optional fields."""
        cfg = TenantAvatarConfig(
            tenant_id="acme",
            avatar_id="av1",
            voice_id="v1",
            language="fr",
            interactivity_type="PUSH_TO_TALK",
            fullmode_enabled=True,
        )
        assert cfg.avatar_id == "av1"
        assert cfg.voice_id == "v1"
        assert cfg.language == "fr"
        assert cfg.interactivity_type == "PUSH_TO_TALK"
        assert cfg.fullmode_enabled is True

    def test_requires_tenant_id(self) -> None:
        """TenantAvatarConfig raises ValidationError when tenant_id is missing."""
        with pytest.raises(ValidationError):
            TenantAvatarConfig()  # type: ignore[call-arg]
