"""Unit tests for parrot.integrations.liveavatar models (TASK-001)."""
import pytest
from pydantic import ValidationError

from parrot.integrations.liveavatar import (
    AvatarSessionHandle,
    LiveAvatarConfig,
    LiveKitRoomTokens,
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
