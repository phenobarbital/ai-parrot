"""Unit tests for MSTeamsAgentConfig voice extension.

Tests the voice_config field and voice_enabled property on MSTeamsAgentConfig.
"""
from parrot.integrations.msteams.models import MSTeamsAgentConfig
from parrot.integrations.msteams.voice.models import (
    TranscriberBackend,
    VoiceTranscriberConfig,
)


class TestMSTeamsAgentConfigVoice:
    """Tests for MSTeamsAgentConfig voice configuration."""

    def test_voice_config_optional(self):
        """voice_config is optional and defaults to None."""
        config = MSTeamsAgentConfig(
            name="TestBot",
            chatbot_id="test-bot",
            client_id="app-123",
            client_secret="secret",
        )
        assert config.voice_config is None
        assert config.voice_enabled is False

    def test_voice_enabled_property(self):
        """voice_enabled returns True when voice is configured and enabled."""
        config = MSTeamsAgentConfig(
            name="TestBot",
            chatbot_id="test-bot",
            client_id="app-123",
            client_secret="secret",
            voice_config=VoiceTranscriberConfig(enabled=True),
        )
        assert config.voice_enabled is True

    def test_voice_disabled_explicitly(self):
        """voice_enabled returns False when enabled=False."""
        config = MSTeamsAgentConfig(
            name="TestBot",
            chatbot_id="test-bot",
            client_id="app-123",
            client_secret="secret",
            voice_config=VoiceTranscriberConfig(enabled=False),
        )
        assert config.voice_enabled is False

    def test_voice_config_full_settings(self):
        """Full voice config with all settings."""
        config = MSTeamsAgentConfig(
            name="TestBot",
            chatbot_id="test-bot",
            client_id="app-123",
            client_secret="secret",
            voice_config=VoiceTranscriberConfig(
                enabled=True,
                backend=TranscriberBackend.OPENAI_WHISPER,
                openai_api_key="sk-test",
                model_size="medium",
                language="es",
                show_transcription=True,
                max_audio_duration_seconds=120,
            ),
        )
        assert config.voice_config is not None
        assert config.voice_config.backend == TranscriberBackend.OPENAI_WHISPER
        assert config.voice_config.language == "es"
        assert config.voice_config.openai_api_key == "sk-test"
        assert config.voice_enabled is True

    def test_backward_compatibility(self):
        """Existing code without voice_config still works."""
        # Simulate loading old config
        config_dict = {
            "name": "OldBot",
            "chatbot_id": "old-bot",
            "client_id": "app-old",
            "client_secret": "secret",
            # No voice_config
        }
        config = MSTeamsAgentConfig(**config_dict)
        assert config.voice_config is None
        assert config.voice_enabled is False

    def test_from_dict_without_voice(self):
        """from_dict works without voice_config (backward compatible)."""
        config_dict = {
            "chatbot_id": "test-bot",
            "client_id": "app-123",
            "client_secret": "secret",
        }
        config = MSTeamsAgentConfig.from_dict("TestBot", config_dict)
        assert config.name == "TestBot"
        assert config.voice_config is None
        assert config.voice_enabled is False

    def test_from_dict_with_voice_dict(self):
        """from_dict parses voice_config from dict."""
        config_dict = {
            "chatbot_id": "test-bot",
            "client_id": "app-123",
            "client_secret": "secret",
            "voice_config": {
                "enabled": True,
                "backend": "faster_whisper",
                "model_size": "small",
                "language": "en",
            },
        }
        config = MSTeamsAgentConfig.from_dict("TestBot", config_dict)
        assert config.voice_config is not None
        assert config.voice_config.enabled is True
        assert config.voice_config.backend == TranscriberBackend.FASTER_WHISPER
        assert config.voice_config.language == "en"
        assert config.voice_enabled is True

    def test_from_dict_with_voice_object(self):
        """from_dict accepts VoiceTranscriberConfig object directly."""
        voice_cfg = VoiceTranscriberConfig(
            enabled=True,
            backend=TranscriberBackend.OPENAI_WHISPER,
            openai_api_key="sk-test",
        )
        config_dict = {
            "chatbot_id": "test-bot",
            "client_id": "app-123",
            "client_secret": "secret",
            "voice_config": voice_cfg,
        }
        config = MSTeamsAgentConfig.from_dict("TestBot", config_dict)
        assert config.voice_config is voice_cfg
        assert config.voice_enabled is True

    def test_voice_config_default_values(self):
        """VoiceTranscriberConfig uses sensible defaults."""
        config = MSTeamsAgentConfig(
            name="TestBot",
            chatbot_id="test-bot",
            client_id="app-123",
            client_secret="secret",
            voice_config=VoiceTranscriberConfig(),  # All defaults
        )
        assert config.voice_config.enabled is True  # Default is enabled
        assert config.voice_config.backend == TranscriberBackend.FASTER_WHISPER
        assert config.voice_config.model_size == "small"
        assert config.voice_config.show_transcription is True
        assert config.voice_config.max_audio_duration_seconds == 60
        assert config.voice_enabled is True

    def test_existing_fields_unchanged(self):
        """Verify existing fields still work correctly."""
        config = MSTeamsAgentConfig(
            name="TestBot",
            chatbot_id="test-bot",
            client_id="app-123",
            client_secret="secret",
            welcome_message="Hello!",
            commands={"help": "Show help"},
            enable_group_mentions=False,
            enable_group_commands=True,
        )
        assert config.name == "TestBot"
        assert config.chatbot_id == "test-bot"
        assert config.APP_ID == "app-123"
        assert config.APP_PASSWORD == "secret"
        assert config.welcome_message == "Hello!"
        assert config.commands == {"help": "Show help"}
        assert config.enable_group_mentions is False
        assert config.enable_group_commands is True
        assert config.voice_config is None
