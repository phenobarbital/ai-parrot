"""Wizard data models and base abstractions for parrot setup.

This module defines the three core dataclasses used throughout the setup
wizard pipeline, the ``BaseClientWizard`` abstract base class that all
provider wizards inherit from, and the ``WizardRunner`` that orchestrates
the full setup pipeline.
"""
from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Dict, List, Optional

import click

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ProviderConfig:
    """Collected configuration for a single LLM provider.

    Attributes:
        provider: Provider key used by LLMFactory (e.g. ``"anthropic"``).
        model: Model identifier (e.g. ``"claude-sonnet-4-6"``).
        env_vars: Environment variable name → value pairs to write to the
            ``.env`` file.
        llm_string: Combined string for LLMFactory in ``"provider:model"``
            format (e.g. ``"anthropic:claude-sonnet-4-6"``).
    """

    provider: str
    model: str
    env_vars: Dict[str, str]
    llm_string: str


@dataclass
class AgentConfig:
    """Collected configuration for agent scaffolding.

    Attributes:
        name: Human-readable agent name (e.g. ``"My Research Agent"``).
        agent_id: URL-safe hyphenated slug derived from ``name``
            (e.g. ``"my-research-agent"``).
        provider_config: The LLM provider configuration for this agent.
        file_path: Absolute path where the generated agent ``.py`` file
            will be written.
    """

    name: str
    agent_id: str
    provider_config: ProviderConfig
    file_path: str


@dataclass
class WizardResult:
    """Full result of a completed setup wizard run.

    Attributes:
        provider_config: Provider and credentials that were collected
            during the wizard session.
        environment: Target environment string (e.g. ``"dev"``,
            ``"prod"``).
        env_file_path: Path to the ``.env`` file that was written.
        agent_config: Agent scaffolding result. ``None`` if the user
            chose not to create an agent.
        app_bootstrapped: ``True`` if ``app.py`` and ``run.py`` were
            generated successfully.
    """

    provider_config: ProviderConfig
    environment: str
    env_file_path: str
    agent_config: Optional[AgentConfig] = None
    app_bootstrapped: bool = False


# ---------------------------------------------------------------------------
# BaseClientWizard — extensibility mechanism
# ---------------------------------------------------------------------------


class BaseClientWizard(ABC):
    """Abstract base class for provider-specific credential wizards.

    To add support for a new LLM provider:

    1. Subclass ``BaseClientWizard`` in
       ``parrot/setup/providers/<provider>.py``.
    2. Set ``display_name``, ``provider_key``, and ``default_model``
       as class-level string attributes.
    3. Implement ``collect()`` with provider-specific ``click.prompt``
       calls (use ``hide_input=True`` for API keys).

    No changes to the wizard core are required — new subclasses are
    discovered automatically via ``__subclasses__()``.

    Example::

        class MyProviderWizard(BaseClientWizard):
            display_name = "My Provider"
            provider_key = "myprovider"
            default_model = "my-model-v1"

            def collect(self) -> ProviderConfig:
                model = click.prompt("Model", default=self.default_model)
                key = click.prompt("MY_API_KEY", hide_input=True)
                return ProviderConfig(
                    provider=self.provider_key,
                    model=model,
                    env_vars={"MY_API_KEY": key},
                    llm_string=f"{self.provider_key}:{model}",
                )
    """

    display_name: ClassVar[str]
    """Human-readable name shown in the provider selection menu."""

    provider_key: ClassVar[str]
    """Provider key passed to LLMFactory (e.g. ``"anthropic"``)."""

    default_model: ClassVar[str]
    """Default model identifier offered as the prompt default."""

    @abstractmethod
    def collect(self) -> ProviderConfig:
        """Run interactive prompts and return collected provider config.

        Returns:
            ProviderConfig with ``provider``, ``model``, ``env_vars``,
            and ``llm_string`` populated.
        """

    @classmethod
    def all_wizards(cls) -> List[BaseClientWizard]:
        """Return instances of all registered provider wizard subclasses.

        Deduplicates by ``provider_key`` so that re-importing provider
        modules in tests (which creates new class objects) does not
        produce duplicate entries.

        Returns:
            List of instantiated ``BaseClientWizard`` subclasses, one
            per unique ``provider_key``, in registration order.
        """
        seen: set[str] = set()
        result: List[BaseClientWizard] = []
        for sub in cls.__subclasses__():
            instance = sub()
            if instance.provider_key not in seen:
                seen.add(instance.provider_key)
                result.append(instance)
        return result


# ---------------------------------------------------------------------------
# WizardRunner — pipeline orchestrator
# ---------------------------------------------------------------------------


class WizardRunner:
    """Orchestrates the full ``parrot setup`` wizard pipeline.

    Pipeline steps:

    1. Import provider package to trigger subclass registration.
    2. Present a numbered provider selection menu.
    3. Run the chosen provider wizard to collect credentials.
    4. Ask for the target environment name (default: ``"dev"``).
    5. Check the target ``.env`` for existing keys; offer per-key overwrite.
    6. Write credentials to the env file via ``scaffolding.write_env_vars``.
    7. Optionally prompt for agent creation and scaffold it.
    8. Optionally prompt for app bootstrap (``app.py`` / ``run.py``).
    9. Return a ``WizardResult`` summarising everything that was created.

    Args:
        force: When ``True``, overwrite existing ``app.py`` / ``run.py``
            without prompting.
        cwd: Project root directory. Defaults to the current working
            directory.
    """

    def __init__(self, force: bool = False, cwd: Optional[Path] = None) -> None:
        self.force = force
        self.cwd = cwd or Path.cwd()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> WizardResult:
        """Execute the full setup wizard and return results.

        Handles ``KeyboardInterrupt`` by printing a cancellation message
        and re-raising so the CLI layer can exit cleanly.

        Returns:
            WizardResult describing everything that was created.

        Raises:
            KeyboardInterrupt: Propagated after printing a cancellation
                message, so the caller can exit with code 0.
        """
        # Lazy import to trigger BaseClientWizard subclass registration
        import parrot.setup.providers  # noqa: F401

        try:
            return self._run_pipeline()
        except KeyboardInterrupt:
            click.echo("\nSetup cancelled.")
            raise

    # ------------------------------------------------------------------
    # Internal pipeline steps
    # ------------------------------------------------------------------

    def _run_pipeline(self) -> WizardResult:
        """Run all pipeline steps sequentially.

        Returns:
            WizardResult with everything the user configured.
        """
        # Step 1 — provider selection
        provider_config = self._collect_provider()

        # Step 2 — environment selection
        environment = self._collect_environment()

        # Step 3 — resolve env file path
        env_path = self._resolve_env_path(environment)

        # Step 4 — filter env_vars against existing keys
        env_vars = self._filter_existing_keys(provider_config.env_vars, env_path)

        # Step 5 — write credentials
        from parrot.setup.scaffolding import write_env_vars

        write_env_vars(env_vars, env_path, environment=environment)
        click.secho(f"\n  Credentials written to {env_path}", fg="green")

        # Step 6 — optional agent scaffolding
        agent_config: Optional[AgentConfig] = None
        if click.confirm("\nCreate an Agent?", default=True):
            agent_config = self._collect_and_scaffold_agent(provider_config)

        # Step 7 — optional app bootstrap
        app_bootstrapped = False
        if click.confirm("\nGenerate app.py and run.py?", default=True):
            from parrot.setup.scaffolding import bootstrap_app

            if agent_config is None:
                # Bootstrap without agent context — use a placeholder
                _placeholder = self._make_placeholder_agent_config(provider_config)
                app_bootstrapped = bootstrap_app(_placeholder, self.cwd, force=self.force)
            else:
                app_bootstrapped = bootstrap_app(agent_config, self.cwd, force=self.force)

        return WizardResult(
            provider_config=provider_config,
            environment=environment,
            env_file_path=str(env_path),
            agent_config=agent_config,
            app_bootstrapped=app_bootstrapped,
        )

    def _collect_provider(self) -> ProviderConfig:
        """Present the provider menu and run the selected wizard.

        Returns:
            ProviderConfig returned by the chosen provider wizard.
        """
        wizards = BaseClientWizard.all_wizards()
        if not wizards:
            click.secho("No provider wizards registered.", fg="red")
            sys.exit(1)

        click.echo("\nSelect an LLM provider:")
        for i, w in enumerate(wizards, 1):
            click.echo(f"  {i}. {w.display_name}")

        choice = click.prompt(
            "Enter number",
            type=click.IntRange(1, len(wizards)),
        )
        selected = wizards[choice - 1]
        return selected.collect()

    def _collect_environment(self) -> str:
        """Prompt for the target environment name.

        Returns:
            Environment string (e.g. ``"default"``, ``"dev"``, ``"prod"``).
        """
        return click.prompt(
            "\nTarget environment (default, dev, staging, prod)",
            default="default",
        )

    @staticmethod
    def _resolve_env_path(environment: str) -> Path:
        """Resolve the target .env file path for the given environment.

        - ``"default"`` writes to ``env/.env`` (shared/base credentials).
        - All other environments write to ``env/<environment>/.env``.

        Args:
            environment: Environment name string.

        Returns:
            Path to the target ``.env`` file.
        """
        if environment == "default":
            return Path("env") / ".env"
        return Path("env") / environment / ".env"

    @staticmethod
    def _filter_existing_keys(
        env_vars: Dict[str, str],
        env_path: Path,
    ) -> Dict[str, str]:
        """Check for existing keys and offer per-key overwrite.

        Reads the target ``.env`` file (if it exists) and identifies
        any keys that would be overwritten. For each conflict, the user
        is prompted whether to overwrite.

        Args:
            env_vars: Candidate key → value pairs from the provider wizard.
            env_path: Path to the target ``.env`` file.

        Returns:
            Filtered dict containing only the keys the user approved.
        """
        if not env_path.exists():
            return dict(env_vars)

        existing_keys: set[str] = set()
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                existing_keys.add(line.split("=", 1)[0].strip())

        conflicting = existing_keys & set(env_vars.keys())
        if not conflicting:
            return dict(env_vars)

        click.echo(
            f"\n  Found {len(conflicting)} existing key(s) in {env_path}:"
        )
        filtered: Dict[str, str] = dict(env_vars)
        for key in sorted(conflicting):
            if not click.confirm(f"    {key} already exists. Overwrite?", default=False):
                del filtered[key]
        return filtered

    def _collect_and_scaffold_agent(
        self,
        provider_config: ProviderConfig,
    ) -> AgentConfig:
        """Prompt for agent details and scaffold the agent file.

        Args:
            provider_config: The provider config to embed in the agent.

        Returns:
            AgentConfig describing the scaffolded agent file.
        """
        from parrot.setup.scaffolding import scaffold_agent, slugify

        name = click.prompt("\nAgent name", default="My Agent")
        agent_id = slugify(name)
        click.echo(f"  Agent ID (slug): {agent_id}")

        # Allow overriding the LLM for the agent
        llm_string = click.prompt(
            "LLM for this agent",
            default=provider_config.llm_string,
        )
        agent_provider = ProviderConfig(
            provider=provider_config.provider,
            model=provider_config.model,
            env_vars={},
            llm_string=llm_string,
        )

        agent_config = AgentConfig(
            name=name,
            agent_id=agent_id,
            provider_config=agent_provider,
            file_path="",  # filled in by scaffold_agent
        )
        out_path = scaffold_agent(agent_config, self.cwd)
        agent_config.file_path = str(out_path)
        click.secho(f"  Agent created: {out_path}", fg="green")
        return agent_config

    @staticmethod
    def _make_placeholder_agent_config(provider_config: ProviderConfig) -> AgentConfig:
        """Create a minimal AgentConfig when no agent was scaffolded.

        Used to provide template context for app.py / run.py generation
        when the user skipped agent creation.

        Args:
            provider_config: The provider config selected during setup.

        Returns:
            AgentConfig with placeholder name and id.
        """
        return AgentConfig(
            name="My Agent",
            agent_id="my-agent",
            provider_config=provider_config,
            file_path="",
        )
