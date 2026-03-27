"""Unit tests for TelegramCrewConfig and CrewAgentEntry."""
import os

import pytest
from pydantic import ValidationError

from parrot.integrations.telegram.crew.config import (
    CrewAgentEntry,
    TelegramCrewConfig,
)


class TestCrewAgentEntry:
    def test_creation(self):
        entry = CrewAgentEntry(
            chatbot_id="agent1",
            bot_token="fake:token",
            username="agent1_bot",
        )
        assert entry.chatbot_id == "agent1"
        assert entry.bot_token == "fake:token"
        assert entry.username == "agent1_bot"
        assert entry.skills == []
        assert entry.tags == []
        assert entry.accepts_files == []
        assert entry.emits_files == []
        assert entry.system_prompt_override is None

    def test_with_all_fields(self):
        entry = CrewAgentEntry(
            chatbot_id="agent1",
            bot_token="fake:token",
            username="agent1_bot",
            skills=[{"name": "echo", "description": "Echoes input"}],
            tags=["test"],
            accepts_files=["csv"],
            emits_files=["json"],
            system_prompt_override="Custom prompt",
        )
        assert len(entry.skills) == 1
        assert entry.skills[0]["name"] == "echo"
        assert entry.tags == ["test"]
        assert entry.system_prompt_override == "Custom prompt"

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            CrewAgentEntry(chatbot_id="agent1")  # missing bot_token and username


class TestTelegramCrewConfig:
    def test_from_dict(self):
        config = TelegramCrewConfig(
            group_id=-1001234567890,
            coordinator_token="fake:coordinator",
            coordinator_username="coord_bot",
        )
        assert config.group_id == -1001234567890
        assert config.coordinator_token == "fake:coordinator"
        assert config.coordinator_username == "coord_bot"
        assert config.max_message_length == 4000
        assert config.announce_on_join is True
        assert config.silent_tool_calls is True
        assert config.typing_indicator is True
        assert config.temp_dir == "/tmp/parrot_crew"
        assert config.max_file_size_mb == 50
        assert len(config.allowed_mime_types) == 7

    def test_with_agents(self):
        config = TelegramCrewConfig(
            group_id=-100123,
            coordinator_token="fake:token",
            coordinator_username="coord_bot",
            agents={
                "TestAgent": CrewAgentEntry(
                    chatbot_id="test",
                    bot_token="fake:agent",
                    username="test_bot",
                )
            },
        )
        assert "TestAgent" in config.agents
        assert config.agents["TestAgent"].chatbot_id == "test"

    def test_max_message_length_capped(self):
        config = TelegramCrewConfig(
            group_id=-100123,
            coordinator_token="fake:token",
            coordinator_username="coord_bot",
            max_message_length=5000,
        )
        assert config.max_message_length == 4096

    def test_max_message_length_negative(self):
        with pytest.raises(ValidationError, match="must be positive"):
            TelegramCrewConfig(
                group_id=-100123,
                coordinator_token="fake:token",
                coordinator_username="coord_bot",
                max_message_length=0,
            )

    def test_defaults(self):
        config = TelegramCrewConfig(
            group_id=-100123,
            coordinator_token="fake:token",
            coordinator_username="coord_bot",
        )
        assert config.hitl_user_ids == []
        assert config.agents == {}
        assert config.reply_to_sender is True
        assert config.update_pinned_registry is True

    def test_from_yaml(self, tmp_path):
        yaml_content = """\
group_id: -1001234567890
coordinator_token: "fake:coordinator"
coordinator_username: "coord_bot"
agents:
  TestAgent:
    chatbot_id: "test"
    bot_token: "fake:agent"
    username: "test_bot"
"""
        yaml_file = tmp_path / "crew.yaml"
        yaml_file.write_text(yaml_content)
        config = TelegramCrewConfig.from_yaml(str(yaml_file))
        assert config.group_id == -1001234567890
        assert "TestAgent" in config.agents
        assert config.agents["TestAgent"].username == "test_bot"

    def test_from_yaml_with_env_substitution(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEST_COORD_TOKEN", "env_coordinator_token")
        monkeypatch.setenv("TEST_AGENT_TOKEN", "env_agent_token")
        yaml_content = """\
group_id: -1001234567890
coordinator_token: "${TEST_COORD_TOKEN}"
coordinator_username: "coord_bot"
agents:
  EnvAgent:
    chatbot_id: "env_agent"
    bot_token: "${TEST_AGENT_TOKEN}"
    username: "env_bot"
"""
        yaml_file = tmp_path / "crew_env.yaml"
        yaml_file.write_text(yaml_content)
        config = TelegramCrewConfig.from_yaml(str(yaml_file))
        assert config.coordinator_token == "env_coordinator_token"
        assert config.agents["EnvAgent"].bot_token == "env_agent_token"

    def test_from_yaml_empty_file(self, tmp_path):
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("")
        with pytest.raises(ValueError, match="Empty YAML"):
            TelegramCrewConfig.from_yaml(str(yaml_file))

    def test_from_yaml_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            TelegramCrewConfig.from_yaml("/nonexistent/path.yaml")

    def test_with_hitl_users(self):
        config = TelegramCrewConfig(
            group_id=-100123,
            coordinator_token="fake:token",
            coordinator_username="coord_bot",
            hitl_user_ids=[123456789, 987654321],
        )
        assert len(config.hitl_user_ids) == 2
        assert 123456789 in config.hitl_user_ids

    def test_custom_mime_types(self):
        config = TelegramCrewConfig(
            group_id=-100123,
            coordinator_token="fake:token",
            coordinator_username="coord_bot",
            allowed_mime_types=["text/csv", "application/json"],
        )
        assert len(config.allowed_mime_types) == 2
