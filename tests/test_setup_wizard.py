"""Unit and integration tests for the parrot setup wizard (FEAT-041).

Covers:
- Data models (ProviderConfig, AgentConfig, WizardResult)
- BaseClientWizard auto-discovery
- All five provider wizard collect() methods
- Scaffolding utilities (slugify, class_name_from_slug, write_env_vars,
  scaffold_agent, bootstrap_app)
- CLI integration via click.testing.CliRunner
"""
from __future__ import annotations

import ast
import sys
import unittest.mock as mock
from pathlib import Path
from typing import Generator

import pytest
from click.testing import CliRunner

from parrot.cli import cli
from parrot.setup.scaffolding import (
    bootstrap_app,
    class_name_from_slug,
    scaffold_agent,
    slugify,
    write_env_vars,
)
from parrot.setup.wizard import AgentConfig, BaseClientWizard, ProviderConfig, WizardResult


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    """Provide a Click test runner."""
    return CliRunner()


@pytest.fixture
def anthropic_pc() -> ProviderConfig:
    """Minimal Anthropic ProviderConfig for reuse across tests."""
    return ProviderConfig(
        provider="anthropic",
        model="claude-sonnet-4-6",
        env_vars={"ANTHROPIC_API_KEY": "sk-ant-test"},
        llm_string="anthropic:claude-sonnet-4-6",
    )


@pytest.fixture
def test_agent_config(anthropic_pc: ProviderConfig) -> AgentConfig:
    """Minimal AgentConfig for reuse across tests."""
    return AgentConfig(
        name="Test Agent",
        agent_id="test-agent",
        provider_config=anthropic_pc,
        file_path="",
    )


@pytest.fixture(autouse=True)
def _reset_subclasses() -> Generator[None, None, None]:
    """Ensure BaseClientWizard subclass list is clean for each test.

    Re-imports the providers package so tests that need all wizards get them,
    and tests that check empty state can clear modules from sys.modules.
    """
    yield
    # Remove cached provider modules so subclass registry stays predictable
    for mod in list(sys.modules.keys()):
        if mod.startswith("parrot.setup.providers"):
            del sys.modules[mod]


# ---------------------------------------------------------------------------
# 1. Data models
# ---------------------------------------------------------------------------


class TestProviderConfig:
    """Tests for the ProviderConfig dataclass."""

    def test_fields(self) -> None:
        pc = ProviderConfig(
            provider="anthropic",
            model="claude-sonnet-4-6",
            env_vars={"ANTHROPIC_API_KEY": "sk-test"},
            llm_string="anthropic:claude-sonnet-4-6",
        )
        assert pc.provider == "anthropic"
        assert pc.model == "claude-sonnet-4-6"
        assert pc.env_vars == {"ANTHROPIC_API_KEY": "sk-test"}
        assert pc.llm_string == "anthropic:claude-sonnet-4-6"


class TestAgentConfig:
    """Tests for the AgentConfig dataclass."""

    def test_fields(self, anthropic_pc: ProviderConfig) -> None:
        ac = AgentConfig(
            name="My Research Agent",
            agent_id="my-research-agent",
            provider_config=anthropic_pc,
            file_path="/tmp/agents/my_research_agent.py",
        )
        assert ac.name == "My Research Agent"
        assert ac.agent_id == "my-research-agent"
        assert ac.provider_config is anthropic_pc
        assert ac.file_path == "/tmp/agents/my_research_agent.py"


class TestWizardResult:
    """Tests for the WizardResult dataclass."""

    def test_defaults(self, anthropic_pc: ProviderConfig) -> None:
        wr = WizardResult(
            provider_config=anthropic_pc,
            environment="dev",
            env_file_path="/tmp/.env",
        )
        assert wr.agent_config is None
        assert wr.app_bootstrapped is False

    def test_with_agent(
        self,
        anthropic_pc: ProviderConfig,
        test_agent_config: AgentConfig,
    ) -> None:
        wr = WizardResult(
            provider_config=anthropic_pc,
            environment="prod",
            env_file_path="/tmp/env/.env",
            agent_config=test_agent_config,
            app_bootstrapped=True,
        )
        assert wr.agent_config is test_agent_config
        assert wr.app_bootstrapped is True


# ---------------------------------------------------------------------------
# 2. BaseClientWizard discovery
# ---------------------------------------------------------------------------


class TestBaseClientWizardDiscovery:
    """Tests for BaseClientWizard auto-discovery via __subclasses__()."""

    def test_all_wizards_discovered(self) -> None:
        import parrot.setup.providers  # noqa: F401

        wizards = BaseClientWizard.all_wizards()
        assert len(wizards) == 5

    def test_display_names_present(self) -> None:
        import parrot.setup.providers  # noqa: F401

        wizards = BaseClientWizard.all_wizards()
        names = {w.display_name for w in wizards}
        assert "Anthropic (Claude)" in names
        assert "OpenAI" in names
        assert "Google (Gemini)" in names
        assert "xAI (Grok)" in names
        assert "OpenRouter" in names

    def test_provider_keys_unique(self) -> None:
        import parrot.setup.providers  # noqa: F401

        wizards = BaseClientWizard.all_wizards()
        keys = [w.provider_key for w in wizards]
        assert len(keys) == len(set(keys)), "provider_key must be unique across wizards"


# ---------------------------------------------------------------------------
# 3. Provider wizard collect() methods
# ---------------------------------------------------------------------------


class TestAnthropicWizard:
    """Tests for AnthropicWizard.collect()."""

    def test_collects_correct_config(self) -> None:
        from parrot.setup.providers.anthropic import AnthropicWizard

        with mock.patch("click.prompt", side_effect=["claude-sonnet-4-6", "sk-ant-test"]):
            with mock.patch("click.echo"):
                config = AnthropicWizard().collect()

        assert config.provider == "anthropic"
        assert config.model == "claude-sonnet-4-6"
        assert config.env_vars == {"ANTHROPIC_API_KEY": "sk-ant-test"}
        assert config.llm_string == "anthropic:claude-sonnet-4-6"

    def test_default_model(self) -> None:
        from parrot.setup.providers.anthropic import AnthropicWizard

        assert AnthropicWizard.default_model == "claude-sonnet-4-6"


class TestGoogleWizard:
    """Tests for GoogleWizard.collect()."""

    def test_collects_correct_config(self) -> None:
        from parrot.setup.providers.google import GoogleWizard

        with mock.patch("click.prompt", side_effect=["gemini-2.5-flash", "AIza-test"]):
            with mock.patch("click.echo"):
                config = GoogleWizard().collect()

        assert config.provider == "google"
        assert "GOOGLE_API_KEY" in config.env_vars
        assert config.env_vars["GOOGLE_API_KEY"] == "AIza-test"
        assert config.llm_string == "google:gemini-2.5-flash"


class TestOpenAIWizard:
    """Tests for OpenAIWizard.collect()."""

    def test_default_base_url(self) -> None:
        from parrot.setup.providers.openai import OPENAI_DEFAULT_BASE_URL, OpenAIWizard

        with mock.patch(
            "click.prompt",
            side_effect=["gpt-4o", OPENAI_DEFAULT_BASE_URL, "sk-openai-test"],
        ):
            with mock.patch("click.echo"):
                config = OpenAIWizard().collect()

        assert config.env_vars["OPENAI_BASE_URL"] == "https://api.openai.com/v1"
        assert "OPENAI_API_KEY" in config.env_vars

    def test_custom_base_url(self) -> None:
        from parrot.setup.providers.openai import OpenAIWizard

        custom_url = "http://localhost:8080/v1"
        with mock.patch("click.prompt", side_effect=["gpt-4o", custom_url, "sk-openai-test"]):
            with mock.patch("click.echo"):
                config = OpenAIWizard().collect()

        assert config.env_vars["OPENAI_BASE_URL"] == custom_url

    def test_both_env_vars_present(self) -> None:
        from parrot.setup.providers.openai import OPENAI_DEFAULT_BASE_URL, OpenAIWizard

        with mock.patch(
            "click.prompt",
            side_effect=["gpt-4o", OPENAI_DEFAULT_BASE_URL, "sk-openai-test"],
        ):
            with mock.patch("click.echo"):
                config = OpenAIWizard().collect()

        assert "OPENAI_API_KEY" in config.env_vars
        assert "OPENAI_BASE_URL" in config.env_vars


class TestXAIWizard:
    """Tests for XAIWizard.collect()."""

    def test_collects_correct_config(self) -> None:
        from parrot.setup.providers.xai import XAIWizard

        with mock.patch("click.prompt", side_effect=["grok-3", "xai-test-key"]):
            with mock.patch("click.echo"):
                config = XAIWizard().collect()

        assert config.provider == "xai"
        assert "XAI_API_KEY" in config.env_vars
        assert config.env_vars["XAI_API_KEY"] == "xai-test-key"


class TestOpenRouterWizard:
    """Tests for OpenRouterWizard.collect()."""

    def test_collects_correct_config(self) -> None:
        from parrot.setup.providers.openrouter import OpenRouterWizard

        with mock.patch(
            "click.prompt",
            side_effect=["anthropic/claude-sonnet-4-6", "sk-or-test"],
        ):
            with mock.patch("click.echo"):
                config = OpenRouterWizard().collect()

        assert config.provider == "openrouter"
        assert "OPENROUTER_API_KEY" in config.env_vars
        assert config.env_vars["OPENROUTER_API_KEY"] == "sk-or-test"


# ---------------------------------------------------------------------------
# 4. Scaffolding utilities
# ---------------------------------------------------------------------------


class TestSlugify:
    """Tests for the slugify() function."""

    def test_simple(self) -> None:
        assert slugify("My Agent") == "my-agent"

    def test_special_chars(self) -> None:
        assert slugify("Agent #1 (Test)") == "agent-1-test"

    def test_multiple_spaces(self) -> None:
        assert slugify("  hello   world  ") == "hello-world"

    def test_already_lower(self) -> None:
        assert slugify("my-agent") == "my-agent"

    def test_numbers(self) -> None:
        assert slugify("Agent 42") == "agent-42"

    def test_underscores_become_hyphens(self) -> None:
        assert slugify("my_agent_name") == "my-agent-name"


class TestClassNameFromSlug:
    """Tests for class_name_from_slug()."""

    def test_multi_word(self) -> None:
        assert class_name_from_slug("my-research-agent") == "MyResearchAgent"

    def test_single_word(self) -> None:
        assert class_name_from_slug("bot") == "Bot"

    def test_two_words(self) -> None:
        assert class_name_from_slug("my-agent") == "MyAgent"


class TestWriteEnvVars:
    """Tests for write_env_vars()."""

    def test_creates_file_with_content(self, tmp_path: Path) -> None:
        env_path = tmp_path / "env" / ".env"
        write_env_vars({"FOO": "bar", "BAZ": "qux"}, env_path)
        assert env_path.exists()
        content = env_path.read_text()
        assert "FOO=bar\n" in content
        assert "BAZ=qux\n" in content

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        env_path = tmp_path / "a" / "b" / "c" / ".env"
        write_env_vars({"KEY": "val"}, env_path)
        assert env_path.exists()

    def test_appends_to_existing_file(self, tmp_path: Path) -> None:
        env_path = tmp_path / ".env"
        env_path.write_text("EXISTING=yes\n")
        write_env_vars({"NEW_VAR": "hello"}, env_path)
        content = env_path.read_text()
        assert "EXISTING=yes\n" in content
        assert "NEW_VAR=hello\n" in content

    def test_dev_env_path(self, tmp_path: Path) -> None:
        env_path = tmp_path / "env" / "dev" / ".env"
        write_env_vars({"DEV_KEY": "devval"}, env_path)
        assert (tmp_path / "env" / "dev" / ".env").exists()


class TestScaffoldAgent:
    """Tests for scaffold_agent()."""

    def test_creates_file(
        self,
        tmp_path: Path,
        test_agent_config: AgentConfig,
    ) -> None:
        import parrot.conf as conf_mod

        original = conf_mod.AGENTS_DIR
        conf_mod.AGENTS_DIR = tmp_path
        try:
            out = scaffold_agent(test_agent_config, tmp_path)
            assert out.exists()
        finally:
            conf_mod.AGENTS_DIR = original

    def test_correct_class_name_in_file(
        self,
        tmp_path: Path,
        test_agent_config: AgentConfig,
    ) -> None:
        import parrot.conf as conf_mod

        original = conf_mod.AGENTS_DIR
        conf_mod.AGENTS_DIR = tmp_path
        try:
            out = scaffold_agent(test_agent_config, tmp_path)
            content = out.read_text()
            assert "class TestAgent" in content
            assert "test-agent" in content
            assert "anthropic:claude-sonnet-4-6" in content
        finally:
            conf_mod.AGENTS_DIR = original

    def test_generated_agent_is_valid_python(
        self,
        tmp_path: Path,
        test_agent_config: AgentConfig,
    ) -> None:
        import parrot.conf as conf_mod

        original = conf_mod.AGENTS_DIR
        conf_mod.AGENTS_DIR = tmp_path
        try:
            out = scaffold_agent(test_agent_config, tmp_path)
            ast.parse(out.read_text())  # raises SyntaxError if invalid
        finally:
            conf_mod.AGENTS_DIR = original


class TestBootstrapApp:
    """Tests for bootstrap_app()."""

    def test_creates_both_files(
        self,
        tmp_path: Path,
        test_agent_config: AgentConfig,
    ) -> None:
        result = bootstrap_app(test_agent_config, tmp_path, force=True)
        assert result is True
        assert (tmp_path / "app.py").exists()
        assert (tmp_path / "run.py").exists()

    def test_class_name_in_app_py(
        self,
        tmp_path: Path,
        test_agent_config: AgentConfig,
    ) -> None:
        bootstrap_app(test_agent_config, tmp_path, force=True)
        content = (tmp_path / "app.py").read_text()
        assert "TestAgent" in content
        assert "test_agent" in content  # module name

    def test_skips_existing_files_without_force(
        self,
        tmp_path: Path,
        test_agent_config: AgentConfig,
    ) -> None:
        (tmp_path / "app.py").write_text("# existing")
        with mock.patch("click.secho"):
            result = bootstrap_app(test_agent_config, tmp_path, force=False)
        assert result is False
        assert (tmp_path / "app.py").read_text() == "# existing"

    def test_force_overwrites_existing(
        self,
        tmp_path: Path,
        test_agent_config: AgentConfig,
    ) -> None:
        (tmp_path / "app.py").write_text("# old")
        result = bootstrap_app(test_agent_config, tmp_path, force=True)
        assert result is True
        assert "# old" not in (tmp_path / "app.py").read_text()

    def test_skips_when_only_run_py_exists(
        self,
        tmp_path: Path,
        test_agent_config: AgentConfig,
    ) -> None:
        (tmp_path / "run.py").write_text("# existing run")
        with mock.patch("click.secho"):
            result = bootstrap_app(test_agent_config, tmp_path, force=False)
        assert result is False


# ---------------------------------------------------------------------------
# 5. CLI integration
# ---------------------------------------------------------------------------


class TestSetupCLIRegistration:
    """Tests for parrot setup CLI registration."""

    def test_setup_in_parrot_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "setup" in result.output

    def test_setup_help_shows_force_flag(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["setup", "--help"])
        assert result.exit_code == 0
        assert "--force" in result.output

    def test_setup_help_describes_wizard(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["setup", "--help"])
        assert result.exit_code == 0
        assert "LLM provider" in result.output

    def test_keyboard_interrupt_exits_cleanly(self, runner: CliRunner) -> None:
        from parrot.setup.wizard import WizardRunner

        with mock.patch.object(WizardRunner, "run", side_effect=KeyboardInterrupt):
            result = runner.invoke(cli, ["setup"])
        assert "Setup cancelled" in result.output
        assert result.exit_code == 0

    def test_existing_commands_unaffected(self, runner: CliRunner) -> None:
        for cmd in ("mcp", "autonomous", "install", "conf"):
            result = runner.invoke(cli, [cmd, "--help"])
            assert result.exit_code == 0, f"{cmd} --help broken after setup registration"


class TestGeneratedAgentIsImportable:
    """Integration test: scaffolded agent file is syntactically valid Python."""

    def test_agent_file_valid_syntax(self, tmp_path: Path, anthropic_pc: ProviderConfig) -> None:
        import parrot.conf as conf_mod

        ac = AgentConfig(
            name="Syntax Test Agent",
            agent_id="syntax-test-agent",
            provider_config=anthropic_pc,
            file_path="",
        )
        original = conf_mod.AGENTS_DIR
        conf_mod.AGENTS_DIR = tmp_path
        try:
            out = scaffold_agent(ac, tmp_path)
            ast.parse(out.read_text())
        finally:
            conf_mod.AGENTS_DIR = original
