"""Tests for agent definition loading and BotConfig registration."""
import pytest
import asyncio
from pathlib import Path
from parrot.registry.registry import AgentRegistry, BotConfig, BotMetadata
from parrot.models.basic import ModelConfig, ToolConfig
from parrot.bots.agent import BasicAgent
from parrot.bots.abstract import AbstractBot


@pytest.fixture
def registry(tmp_path):
    """Fresh registry with a temporary agents dir."""
    return AgentRegistry(agents_dir=tmp_path / "agents")


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent / "fixtures" / "agents"


@pytest.fixture
def project_agents_dir():
    return Path(__file__).resolve().parents[1] / "agents" / "agents"


# -- YAML agent definition loading -------------------------------------------

class TestLoadAgentDefinitions:
    """Test loading agent definitions from YAML files."""

    @pytest.mark.asyncio
    async def test_load_definitions_from_fixtures(self, registry, fixtures_dir):
        """YAML definitions load and register agents with bot_config."""
        count = registry.load_agent_definitions(fixtures_dir)
        assert count > 0, "Should load at least one agent"
        assert registry.has("MarketingAgent")

    @pytest.mark.asyncio
    async def test_bot_config_populated_on_metadata(self, registry, fixtures_dir):
        """BotMetadata.bot_config is populated from YAML definitions."""
        registry.load_agent_definitions(fixtures_dir)
        meta = registry.get_metadata("MarketingAgent")
        assert meta is not None
        assert meta.bot_config is not None
        assert isinstance(meta.bot_config, BotConfig)

    @pytest.mark.asyncio
    async def test_bot_config_fields(self, registry, fixtures_dir):
        """BotConfig carries class_name, model, tools, system_prompt."""
        registry.load_agent_definitions(fixtures_dir)
        config = registry.get_metadata("MarketingAgent").bot_config

        assert config.name == "MarketingAgent"
        assert config.class_name == "BasicAgent"
        assert config.module == "parrot.bots.agent"

        # Model
        assert config.model is not None
        assert config.model.provider == "google"
        assert config.model.model == "gemini-2.5-flash"
        assert config.model.temperature == 0.7

        # Tools
        assert config.tools is not None
        assert len(config.tools.tools) > 0
        assert len(config.tools.toolkits) > 0
        assert "JiraToolkit" in config.tools.toolkits

        # System prompt
        assert config.system_prompt is not None
        assert "marketing expert" in config.system_prompt

    @pytest.mark.asyncio
    async def test_bot_config_model_dump(self, registry, fixtures_dir):
        """BotConfig.model_dump() produces JSON-safe dict with all fields."""
        registry.load_agent_definitions(fixtures_dir)
        config = registry.get_metadata("MarketingAgent").bot_config
        data = config.model_dump(mode="json")

        assert data["name"] == "MarketingAgent"
        assert data["class_name"] == "BasicAgent"
        assert data["model"]["provider"] == "google"
        assert data["model"]["model"] == "gemini-2.5-flash"
        assert data["tools"]["toolkits"] == ["JiraToolkit"]
        assert "system_prompt" in data
        assert data["enabled"] is True

    @pytest.mark.asyncio
    async def test_load_definitions_from_project_dir(self, registry, project_agents_dir):
        """Load YAML definitions from agents/agents/ project directory."""
        if not project_agents_dir.exists():
            pytest.skip("Project agents/agents/ directory not found")

        count = registry.load_agent_definitions(project_agents_dir)
        assert count >= 2, f"Expected at least 2 definitions, got {count}"

        # marketing_agent.yaml
        assert registry.has("MarketingAgent")
        marketing = registry.get_metadata("MarketingAgent").bot_config
        assert marketing.class_name == "BasicAgent"
        assert marketing.model.provider == "google"

        # data_analyst.yaml
        assert registry.has("DataAnalyst")
        analyst = registry.get_metadata("DataAnalyst").bot_config
        assert analyst.class_name == "BasicAgent"
        assert analyst.model.model == "gemini-2.5-pro"
        assert analyst.model.temperature == 0.2


# -- Decorator-based registration --------------------------------------------

class TestDecoratorRegistration:
    """Test that @register_agent constructs a BotConfig from class introspection."""

    @pytest.mark.asyncio
    async def test_decorator_creates_bot_config(self, registry):
        """@register_agent populates bot_config with class_name and module."""
        @registry.register_bot_decorator(name="test_bot", singleton=True)
        class TestBot(AbstractBot):
            """A test bot for unit tests."""
            pass

        meta = registry.get_metadata("test_bot")
        assert meta is not None
        assert meta.bot_config is not None
        assert meta.bot_config.class_name == "TestBot"
        assert meta.bot_config.name == "test_bot"
        assert meta.bot_config.singleton is True

    @pytest.mark.asyncio
    async def test_decorator_captures_model(self, registry):
        """@register_agent extracts model attribute from class."""
        @registry.register_bot_decorator(name="model_bot")
        class ModelBot(AbstractBot):
            """Bot with a model attribute."""
            model = "gemini-2.5-pro"
            max_tokens = 4096

        config = registry.get_metadata("model_bot").bot_config
        assert config.model is not None
        assert config.model.model == "gemini-2.5-pro"
        assert config.model.max_tokens == 4096

    @pytest.mark.asyncio
    async def test_decorator_captures_system_prompt(self, registry):
        """@register_agent extracts system_prompt from class."""
        @registry.register_bot_decorator(name="prompt_bot")
        class PromptBot(AbstractBot):
            """Bot with system prompt."""
            system_prompt = "You are a helpful assistant."

        config = registry.get_metadata("prompt_bot").bot_config
        assert config.system_prompt == "You are a helpful assistant."

    @pytest.mark.asyncio
    async def test_decorator_bot_config_model_dump(self, registry):
        """Decorator-registered bot_config serializes properly."""
        @registry.register_bot_decorator(name="dump_bot", priority=5, tags=["test"])
        class DumpBot(AbstractBot):
            """Dump test bot."""
            model = "gpt-4o"
            max_tokens = 2048

        config = registry.get_metadata("dump_bot").bot_config
        data = config.model_dump(mode="json")

        assert data["name"] == "dump_bot"
        assert data["class_name"] == "DumpBot"
        assert data["priority"] == 5
        assert data["model"]["model"] == "gpt-4o"
        assert data["model"]["max_tokens"] == 2048
        assert data["enabled"] is True

    @pytest.mark.asyncio
    async def test_decorator_without_model(self, registry):
        """@register_agent handles classes without model attribute gracefully."""
        @registry.register_bot_decorator(name="simple_bot")
        class SimpleBot(AbstractBot):
            """Simple bot."""
            pass

        config = registry.get_metadata("simple_bot").bot_config
        assert config.model is None
        assert config.tools is None
        assert config.system_prompt is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
