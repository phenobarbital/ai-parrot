"""Unit tests for AgentCard and AgentSkill models."""
import pytest
from datetime import datetime, timezone

from parrot.integrations.telegram.crew.agent_card import AgentCard, AgentSkill


@pytest.fixture
def sample_skill():
    return AgentSkill(name="echo", description="Echoes input")


@pytest.fixture
def sample_card(sample_skill):
    return AgentCard(
        agent_id="test_agent",
        agent_name="TestAgent",
        telegram_username="test_agent_bot",
        telegram_user_id=999999,
        model="test:model",
        skills=[sample_skill],
        tags=["test"],
        joined_at=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
    )


class TestAgentSkill:
    def test_creation(self, sample_skill):
        assert sample_skill.name == "echo"
        assert sample_skill.description == "Echoes input"
        assert sample_skill.input_types == []
        assert sample_skill.output_types == []
        assert sample_skill.example is None

    def test_with_all_fields(self):
        skill = AgentSkill(
            name="analyze",
            description="Analyzes data",
            input_types=["csv", "json"],
            output_types=["text", "chart"],
            example="Analyze sales Q2",
        )
        assert len(skill.input_types) == 2
        assert len(skill.output_types) == 2
        assert skill.example == "Analyze sales Q2"


class TestAgentCard:
    def test_creation(self, sample_card):
        assert sample_card.agent_id == "test_agent"
        assert sample_card.agent_name == "TestAgent"
        assert sample_card.telegram_username == "test_agent_bot"
        assert sample_card.telegram_user_id == 999999
        assert sample_card.model == "test:model"
        assert sample_card.status == "ready"
        assert sample_card.current_task is None

    def test_default_empty_lists(self):
        card = AgentCard(
            agent_id="a1",
            agent_name="A",
            telegram_username="a_bot",
            telegram_user_id=1,
            model="m",
            joined_at=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        )
        assert card.skills == []
        assert card.tags == []
        assert card.accepts_files == []
        assert card.emits_files == []

    def test_to_telegram_text(self, sample_card):
        text = sample_card.to_telegram_text()
        assert "TestAgent" in text
        assert "@test_agent_bot" in text
        assert "test:model" in text
        assert "echo" in text
        assert "Echoes input" in text
        assert "test" in text  # tag

    def test_to_telegram_text_with_files(self, sample_card):
        sample_card.accepts_files = ["csv", "json"]
        sample_card.emits_files = ["pdf"]
        text = sample_card.to_telegram_text()
        assert "csv" in text
        assert "json" in text
        assert "pdf" in text

    def test_to_telegram_text_minimal(self):
        card = AgentCard(
            agent_id="a1",
            agent_name="Minimal",
            telegram_username="min_bot",
            telegram_user_id=1,
            model="gpt-4",
            joined_at=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        )
        text = card.to_telegram_text()
        assert "Minimal" in text
        assert "@min_bot" in text
        assert "Skills:" not in text  # no skills

    def test_to_registry_line_ready(self, sample_card):
        line = sample_card.to_registry_line()
        assert "@test_agent_bot" in line
        assert "TestAgent" in line
        assert "\u2705" in line  # checkmark

    def test_to_registry_line_busy(self, sample_card):
        sample_card.status = "busy"
        sample_card.current_task = "processing Q2"
        line = sample_card.to_registry_line()
        assert "processing Q2" in line
        assert "\u23f3" in line  # hourglass
        assert "@test_agent_bot" in line

    def test_to_registry_line_offline(self, sample_card):
        sample_card.status = "offline"
        line = sample_card.to_registry_line()
        assert "@test_agent_bot" in line
        assert "\U0001f534" in line  # red circle

    def test_to_registry_line_no_task(self, sample_card):
        line = sample_card.to_registry_line()
        assert "\u00b7" not in line  # no middle dot when no task

    def test_to_registry_line_with_task(self, sample_card):
        sample_card.current_task = "analyzing data"
        line = sample_card.to_registry_line()
        assert "\u00b7 analyzing data" in line
