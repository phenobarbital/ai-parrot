"""Tests for CollaborativeConfig and MatrixCrewConfig extension (TASK-1296 — FEAT-195)."""
import pytest

from parrot.integrations.matrix.crew.config import (
    CollaborativeConfig,
    MatrixCrewConfig,
)


class TestCollaborativeConfig:
    """Tests for CollaborativeConfig model."""

    def test_defaults(self):
        """CollaborativeConfig has correct default values."""
        config = CollaborativeConfig()
        assert config.command_prefix == "!investigate"
        assert config.max_rounds == 1
        assert config.agent_timeout == 120.0
        assert config.session_timeout == 600.0
        assert config.summarizer_agent is None
        assert config.session_verbosity == "full"
        assert config.include_chat_context is True

    def test_custom_values(self):
        """CollaborativeConfig accepts custom field values."""
        config = CollaborativeConfig(
            command_prefix="!collab",
            max_rounds=3,
            agent_timeout=60.0,
            session_timeout=300.0,
            summarizer_agent="summarizer",
            session_verbosity="minimal",
            include_chat_context=False,
        )
        assert config.command_prefix == "!collab"
        assert config.max_rounds == 3
        assert config.agent_timeout == 60.0
        assert config.summarizer_agent == "summarizer"
        assert config.session_verbosity == "minimal"
        assert config.include_chat_context is False

    def test_max_rounds_validation_too_low(self):
        """max_rounds below 1 raises validation error."""
        with pytest.raises(Exception):
            CollaborativeConfig(max_rounds=0)

    def test_max_rounds_validation_too_high(self):
        """max_rounds above 10 raises validation error."""
        with pytest.raises(Exception):
            CollaborativeConfig(max_rounds=11)

    def test_max_rounds_boundary_values(self):
        """max_rounds accepts boundary values 1 and 10."""
        config_min = CollaborativeConfig(max_rounds=1)
        config_max = CollaborativeConfig(max_rounds=10)
        assert config_min.max_rounds == 1
        assert config_max.max_rounds == 10

    def test_serialization(self):
        """CollaborativeConfig serializes to dict correctly."""
        config = CollaborativeConfig(max_rounds=2, summarizer_agent="synth")
        data = config.model_dump()
        assert data["max_rounds"] == 2
        assert data["summarizer_agent"] == "synth"
        assert data["command_prefix"] == "!investigate"


class TestMatrixCrewConfigBackwardCompat:
    """Tests for backward compatibility of MatrixCrewConfig."""

    def _base_config_kwargs(self):
        """Return minimal valid MatrixCrewConfig keyword arguments."""
        return {
            "homeserver_url": "http://localhost:8008",
            "server_name": "test.local",
            "as_token": "test_as",
            "hs_token": "test_hs",
            "bot_mxid": "@bot:test.local",
            "general_room_id": "!room:test.local",
        }

    def test_loads_without_collaborative(self):
        """Existing config without collaborative: section loads fine."""
        config = MatrixCrewConfig(**self._base_config_kwargs())
        assert config.collaborative is None

    def test_loads_with_collaborative_dict(self):
        """Config with collaborative dict loads and validates."""
        kwargs = self._base_config_kwargs()
        kwargs["collaborative"] = {
            "max_rounds": 3,
            "summarizer_agent": "summarizer",
        }
        config = MatrixCrewConfig(**kwargs)
        assert config.collaborative is not None
        assert config.collaborative.max_rounds == 3
        assert config.collaborative.summarizer_agent == "summarizer"

    def test_loads_with_collaborative_model(self):
        """Config with CollaborativeConfig instance loads correctly."""
        kwargs = self._base_config_kwargs()
        kwargs["collaborative"] = CollaborativeConfig(max_rounds=2)
        config = MatrixCrewConfig(**kwargs)
        assert config.collaborative.max_rounds == 2

    def test_collaborative_defaults_when_provided(self):
        """When collaborative: section provided, unset fields use defaults."""
        kwargs = self._base_config_kwargs()
        kwargs["collaborative"] = {"summarizer_agent": "synth"}
        config = MatrixCrewConfig(**kwargs)
        # Explicit field
        assert config.collaborative.summarizer_agent == "synth"
        # Default fields remain at defaults
        assert config.collaborative.command_prefix == "!investigate"
        assert config.collaborative.max_rounds == 1

    def test_existing_fields_unaffected(self):
        """Adding collaborative field does not affect existing MatrixCrewConfig fields."""
        config = MatrixCrewConfig(**self._base_config_kwargs())
        assert config.homeserver_url == "http://localhost:8008"
        assert config.server_name == "test.local"
        assert config.appservice_port == 8449
        assert config.unaddressed_agent is None
        assert config.max_message_length == 4096

    def test_from_yaml_without_collaborative(self, tmp_path):
        """from_yaml loads YAML without collaborative section (backward compat)."""
        yaml_content = """
homeserver_url: "http://localhost:8008"
server_name: "test.local"
as_token: "as_token"
hs_token: "hs_token"
bot_mxid: "@bot:test.local"
general_room_id: "!room:test.local"
"""
        yaml_file = tmp_path / "crew_config.yaml"
        yaml_file.write_text(yaml_content)

        config = MatrixCrewConfig.from_yaml(str(yaml_file))
        assert config.collaborative is None
        assert config.server_name == "test.local"

    def test_from_yaml_with_collaborative(self, tmp_path):
        """from_yaml loads YAML with collaborative section correctly."""
        yaml_content = """
homeserver_url: "http://localhost:8008"
server_name: "test.local"
as_token: "as_token"
hs_token: "hs_token"
bot_mxid: "@bot:test.local"
general_room_id: "!room:test.local"
collaborative:
  command_prefix: "!investigate"
  max_rounds: 2
  agent_timeout: 60.0
  session_timeout: 300.0
  summarizer_agent: "synth"
  session_verbosity: "full"
  include_chat_context: true
"""
        yaml_file = tmp_path / "collab_config.yaml"
        yaml_file.write_text(yaml_content)

        config = MatrixCrewConfig.from_yaml(str(yaml_file))
        assert config.collaborative is not None
        assert config.collaborative.max_rounds == 2
        assert config.collaborative.summarizer_agent == "synth"
        assert config.collaborative.agent_timeout == 60.0
