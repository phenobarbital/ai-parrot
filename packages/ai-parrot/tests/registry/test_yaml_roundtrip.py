"""Round-trip tests for AgentRegistry.create_agent_definition (FEAT-467 TASK-2509).

Verifies that a fully-populated ``BotConfig`` survives
``create_agent_definition -> load_agent_definitions`` losslessly (all
previously-dropped fields: toolkits, prompt, vector_store, tags, policies,
mcp_servers, priority, at_startup, config — plus singleton/startup_config
for full BotConfig fidelity), and that YAML written by the OLD (lossy)
writer format is still readable.
"""
import pytest

from parrot.registry import registry as registry_module
from parrot.registry.registry import AgentRegistry, BotConfig, PromptConfig
from parrot.models.basic import ModelConfig, ToolConfig
from parrot.models.stores import StoreConfig
from parrot.auth.models import PolicyRuleConfig


@pytest.fixture
def registry(tmp_path):
    """Fresh registry with a temporary agents dir."""
    return AgentRegistry(agents_dir=tmp_path / "agents")


@pytest.fixture(autouse=True)
def patch_agents_dir(monkeypatch, tmp_path):
    """create_agent_definition / load_agent_definitions default paths both
    read the module-level AGENTS_DIR constant — redirect it into tmp_path
    so tests never touch the real repo agents/ directory."""
    monkeypatch.setattr(registry_module, "AGENTS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def full_config() -> BotConfig:
    """BotConfig with every optional field populated."""
    return BotConfig(
        name="full-agent",
        class_name="BasicAgent",
        module="parrot.bots.agent",
        enabled=True,
        origin="repo",
        config={"description": "A fully populated test agent", "custom_key": "value"},
        tools=ToolConfig(
            tools=[{"name": "echo"}],
            mcp_servers=[{"name": "mcp1"}],
            toolkits=["JiraToolkit"],
        ),
        toolkits=["MyToolkit", "OtherToolkit"],
        mcp_servers=[{"name": "test-mcp", "url": "http://localhost:1234"}],
        model=ModelConfig(provider="openai", model="gpt-4o", temperature=0.5, max_tokens=2048),
        system_prompt="You are a helpful assistant.",
        prompt=PromptConfig(
            preset="detailed",
            remove=["safety"],
            add=["custom_layer"],
            customize={"tone": {"style": "formal"}},
        ),
        vector_store=StoreConfig(
            vector_store="postgres",
            table="my_table",
            schema="public",
            embedding_model="text-embedding-3-small",
            dimension=1536,
            dsn=None,
            distance_strategy="COSINE",
            metric_type="COSINE",
            index_type="IVF_FLAT",
            auto_create=True,
            extra={"foo": "bar"},
        ),
        tags={"finance", "marketing"},
        singleton=True,
        at_startup=True,
        startup_config={"key": "value"},
        priority=7,
        policies=[
            PolicyRuleConfig(
                action="agent:chat",
                effect="allow",
                groups=["engineering"],
                priority=15,
                description="test rule",
            )
        ],
    )


class TestRoundtripLossless:
    """Full BotConfig -> YAML -> BotConfig equality matrix."""

    def test_roundtrip_lossless(self, registry, full_config):
        path = registry.create_agent_definition(full_config, category="general")
        assert path.exists()

        count = registry.load_agent_definitions(path.parent)
        assert count == 1

        meta = registry.get_metadata(full_config.name)
        assert meta is not None
        loaded = meta.bot_config
        assert loaded is not None

        # Previously-dropped fields (spec §1 Goals):
        assert loaded.toolkits == full_config.toolkits
        assert loaded.prompt == full_config.prompt
        assert loaded.vector_store == full_config.vector_store
        assert loaded.tags == full_config.tags
        assert loaded.policies == full_config.policies
        assert loaded.mcp_servers == full_config.mcp_servers
        assert loaded.priority == full_config.priority
        assert loaded.at_startup == full_config.at_startup
        assert loaded.config == full_config.config

        # Full BotConfig fidelity (beyond the 9 explicitly dropped fields):
        assert loaded.name == full_config.name
        assert loaded.class_name == full_config.class_name
        assert loaded.module == full_config.module
        assert loaded.enabled == full_config.enabled
        assert loaded.origin == full_config.origin
        assert loaded.singleton == full_config.singleton
        assert loaded.startup_config == full_config.startup_config
        assert loaded.model == full_config.model
        assert loaded.tools == full_config.tools
        assert loaded.system_prompt == full_config.system_prompt

    def test_roundtrip_minimal_config(self, registry):
        """A minimally-populated BotConfig (all optional fields unset)
        round-trips without error and keeps field defaults."""
        minimal = BotConfig(name="minimal-agent", class_name="BasicAgent", module="parrot.bots.agent")
        path = registry.create_agent_definition(minimal, category="general")
        count = registry.load_agent_definitions(path.parent)
        assert count == 1

        loaded = registry.get_metadata("minimal-agent").bot_config
        assert loaded.toolkits == []
        assert loaded.prompt is None
        assert loaded.vector_store is None
        assert loaded.tags == set()
        assert loaded.policies is None
        assert loaded.mcp_servers == []
        assert loaded.priority == 0
        assert loaded.at_startup is False
        assert loaded.singleton is False


class TestOldFormatCompat:
    """YAMLs written by the OLD (lossy) writer must still load."""

    def test_old_format_still_loads(self, registry, tmp_path):
        """YAML lacking the new keys loads with BotConfig defaults."""
        old_yaml = tmp_path / "agents_old" / "general"
        old_yaml.mkdir(parents=True, exist_ok=True)
        (old_yaml / "legacy-agent.yaml").write_text(
            "agent:\n"
            "  name: legacy-agent\n"
            "  class_name: BasicAgent\n"
            "  module: parrot.bots.agent\n"
            "  description: ''\n"
            "  enabled: true\n"
            "  origin: repo\n"
            "  version: 1.0.0\n"
        )

        count = registry.load_agent_definitions(old_yaml)
        assert count == 1

        loaded = registry.get_metadata("legacy-agent").bot_config
        assert loaded.name == "legacy-agent"
        assert loaded.toolkits == []
        assert loaded.vector_store is None
        assert loaded.tags == set()
        assert loaded.policies is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
