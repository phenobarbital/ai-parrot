"""
Matrix Swarm Sample Test Suite (FEAT-464).

Validates the YAML files, demo script, environment template, and
agent instantiation with mocked LLM clients.
"""

import ast
import re
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch, MagicMock

SAMPLE_DIR = Path(__file__).parent.parent


# --- Unit Tests: agents.yaml ---


class TestAgentsYaml:
    """Tests for agents.yaml structure and content."""

    def test_agents_yaml_loads(self) -> None:
        """agents.yaml parses with yaml.safe_load and has 4 agents."""
        data = yaml.safe_load((SAMPLE_DIR / "agents.yaml").read_text())
        assert "agents" in data
        assert len(data["agents"]) == 4

    def test_agents_have_required_fields(self) -> None:
        """Each agent has required fields: name, llm, system_prompt."""
        data = yaml.safe_load((SAMPLE_DIR / "agents.yaml").read_text())
        for agent_id, agent in data["agents"].items():
            assert "name" in agent, f"{agent_id} missing name"
            assert "llm" in agent, f"{agent_id} missing llm"
            assert "system_prompt" in agent, f"{agent_id} missing system_prompt"
            # Verify system_prompt is substantive (>=3 sentences)
            sentences = len([s for s in agent["system_prompt"].split(".") if s.strip()])
            assert sentences >= 3, f"{agent_id} system_prompt has {sentences} sentences, need >=3"

    def test_agents_use_different_providers(self) -> None:
        """Each agent uses a different LLM provider."""
        data = yaml.safe_load((SAMPLE_DIR / "agents.yaml").read_text())
        providers = [a["llm"].split(":")[0] for a in data["agents"].values()]
        assert set(providers) == {"openai", "anthropic", "google", "nvidia"}

    def test_agents_chatbot_ids_exact(self) -> None:
        """Verify exact chatbot_ids match specification."""
        data = yaml.safe_load((SAMPLE_DIR / "agents.yaml").read_text())
        expected_ids = {"web-researcher", "financial-analyst", "report-writer", "synthesis-agent"}
        assert set(data["agents"].keys()) == expected_ids


# --- Unit Tests: swarm_config.yaml ---


class TestSwarmConfig:
    """Tests for swarm_config.yaml structure and agent matching."""

    def test_swarm_config_loads(self) -> None:
        """swarm_config.yaml parses with yaml.safe_load."""
        data = yaml.safe_load((SAMPLE_DIR / "swarm_config.yaml").read_text())
        assert "homeserver_url" in data
        assert "agents" in data
        assert "channels" in data

    def test_chatbot_ids_match(self) -> None:
        """chatbot_ids in agents.yaml match swarm_config.yaml exactly."""
        agents = yaml.safe_load((SAMPLE_DIR / "agents.yaml").read_text())
        config = yaml.safe_load((SAMPLE_DIR / "swarm_config.yaml").read_text())
        agent_ids = set(agents["agents"].keys())
        config_ids = set(config["agents"].keys())
        assert agent_ids == config_ids, f"Mismatch: agents={agent_ids}, config={config_ids}"

    def test_swarm_config_has_channels(self) -> None:
        """Config has at least 2 channels."""
        data = yaml.safe_load((SAMPLE_DIR / "swarm_config.yaml").read_text())
        channels = data["channels"]
        assert len(channels) >= 2

    def test_channel_answer_policies(self) -> None:
        """Channels have correct answer policies."""
        data = yaml.safe_load((SAMPLE_DIR / "swarm_config.yaml").read_text())
        channels = {ch["name"]: ch for ch in data["channels"]}
        assert "general" in channels
        assert channels["general"]["answer_policy"] == "swarm"
        assert "finance" in channels
        assert channels["finance"]["answer_policy"] == "mention"

    def test_tunnels_enabled(self) -> None:
        """Tunnels are enabled."""
        data = yaml.safe_load((SAMPLE_DIR / "swarm_config.yaml").read_text())
        assert data["tunnels"]["enabled"] is True

    def test_collaborative_mode(self) -> None:
        """Collaborative mode is configured with synthesizer."""
        data = yaml.safe_load((SAMPLE_DIR / "swarm_config.yaml").read_text())
        collab = data.get("collaborative")
        assert collab is not None
        assert collab["summarizer_agent"] == "synthesis-agent"


# --- Unit Tests: Demo Script ---


class TestDemoScript:
    """Tests for swarm_demo.py structure and syntax."""

    def test_demo_script_syntax(self) -> None:
        """swarm_demo.py compiles without syntax errors."""
        source = (SAMPLE_DIR / "swarm_demo.py").read_text()
        ast.parse(source)  # Raises SyntaxError if invalid

    def test_demo_script_has_functions(self) -> None:
        """swarm_demo.py has required functions."""
        source = (SAMPLE_DIR / "swarm_demo.py").read_text()
        tree = ast.parse(source)
        func_names = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        required = {"_load_agents_from_yaml", "_setup_agents", "_run_swarm", "main"}
        assert required.issubset(func_names)

    def test_demo_script_has_docstrings(self) -> None:
        """swarm_demo.py has docstrings."""
        source = (SAMPLE_DIR / "swarm_demo.py").read_text()
        # Count docstrings ("""...""" patterns)
        docstring_count = source.count('"""')
        assert docstring_count >= 4  # Module + functions


# --- Unit Tests: Environment ---


class TestEnvironment:
    """Tests for .env.example configuration."""

    def test_env_example_exists(self) -> None:
        """.env.example file exists."""
        assert (SAMPLE_DIR / ".env.example").exists()

    def test_env_example_has_all_keys(self) -> None:
        """.env.example contains all 7 required environment variables."""
        content = (SAMPLE_DIR / ".env.example").read_text()
        required_keys = [
            "MATRIX_AS_TOKEN",
            "MATRIX_HS_TOKEN",
            "MATRIX_GENERAL_ROOM_ID",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "NVIDIA_API_KEY",
        ]
        for key in required_keys:
            assert key in content, f"Missing {key} in .env.example"


# --- Unit Tests: Documentation ---


class TestDocumentation:
    """Tests for README.md and Makefile."""

    def test_readme_exists(self) -> None:
        """README.md file exists."""
        assert (SAMPLE_DIR / "README.md").exists()

    def test_readme_has_sections(self) -> None:
        """README.md has expected sections."""
        readme = (SAMPLE_DIR / "README.md").read_text()
        sections = ["Prerequisites", "Quick Start", "Troubleshooting"]
        for section in sections:
            assert section.lower() in readme.lower(), f"README missing section: {section}"

    def test_makefile_exists(self) -> None:
        """Makefile exists."""
        assert (SAMPLE_DIR / "Makefile").exists()

    def test_makefile_has_targets(self) -> None:
        """Makefile has all required targets."""
        makefile = (SAMPLE_DIR / "Makefile").read_text()
        targets = ["setup", "start", "stop", "logs", "demo", "clean"]
        for target in targets:
            pattern = rf"^{target}\s*:"
            assert re.search(pattern, makefile, re.MULTILINE), f"Makefile missing target: {target}"


# --- Integration Tests ---


class TestAgentIntegration:
    """Integration tests with mocked LLM clients."""

    @pytest.fixture
    def agent_defs(self) -> dict:
        """Fixture: load agent definitions from agents.yaml."""
        data = yaml.safe_load((SAMPLE_DIR / "agents.yaml").read_text())
        return data["agents"]

    @patch("parrot.clients.factory.LLMFactory.create")
    def test_agent_instantiation(self, mock_create: MagicMock, agent_defs: dict) -> None:
        """Create all 4 agents with mocked LLM clients.

        This test verifies that BasicAgent can be instantiated with the
        configurations from agents.yaml without calling real LLM APIs.
        """
        # Mock LLMFactory.create to return a mock client
        mock_create.return_value = MagicMock()

        from parrot.bots.agent import BasicAgent

        agents = []
        for agent_id, defn in agent_defs.items():
            agent = BasicAgent(
                name=defn["name"],
                agent_id=agent_id,
                use_llm=defn["llm"],
                system_prompt=defn["system_prompt"],
                use_tools=bool(defn.get("tools")),
                chatbot_id=agent_id,
            )
            agents.append(agent)

        assert len(agents) == 4

    @patch("parrot.clients.factory.LLMFactory.create")
    def test_botmanager_registration(self, mock_create: MagicMock, agent_defs: dict) -> None:
        """Register agents and retrieve by chatbot_id.

        This test verifies that agents can be registered in BotManager
        and retrieved correctly.
        """
        mock_create.return_value = MagicMock()

        from parrot.bots.agent import BasicAgent
        from parrot.manager import BotManager

        manager = BotManager()
        for agent_id, defn in agent_defs.items():
            agent = BasicAgent(
                name=defn["name"],
                agent_id=agent_id,
                use_llm=defn["llm"],
                system_prompt=defn["system_prompt"],
                chatbot_id=agent_id,
            )
            manager.add_agent(agent)

        bots = manager.get_bots()
        # Verify all agent_ids are in the bots dict (keyed by chatbot_id)
        for agent_id in agent_defs.keys():
            assert agent_id in bots, f"Agent {agent_id} not in BotManager"


# --- LLM String Validation Tests ---


class TestLLMStrings:
    """Tests for LLM provider string validation."""

    def test_llm_strings_valid(self) -> None:
        """All llm strings parse via LLMFactory.parse_llm_string()."""
        data = yaml.safe_load((SAMPLE_DIR / "agents.yaml").read_text())

        from parrot.clients.factory import LLMFactory

        for agent_id, agent in data["agents"].items():
            llm_str = agent["llm"]
            provider, model = LLMFactory.parse_llm_string(llm_str)
            assert provider in {
                "openai",
                "anthropic",
                "google",
                "nvidia",
            }, f"{agent_id}: invalid provider {provider}"
            assert model is not None, f"{agent_id}: model is None"
