"""Anthropic (Claude) provider wizard for parrot setup."""
import click

from parrot.setup.wizard import BaseClientWizard, ProviderConfig


class AnthropicWizard(BaseClientWizard):
    """Wizard for Anthropic (Claude) credential collection.

    Collects the ``ANTHROPIC_API_KEY`` and model selection via
    interactive click prompts.
    """

    display_name: str = "Anthropic (Claude)"
    provider_key: str = "anthropic"
    default_model: str = "claude-sonnet-4-6"

    def collect(self) -> ProviderConfig:
        """Collect Anthropic credentials interactively.

        Returns:
            ProviderConfig with ``ANTHROPIC_API_KEY`` and selected model.
        """
        click.echo(f"\nConfiguring {self.display_name}")
        model = click.prompt("Model", default=self.default_model)
        api_key = click.prompt("ANTHROPIC_API_KEY", hide_input=True)
        return ProviderConfig(
            provider=self.provider_key,
            model=model,
            env_vars={"ANTHROPIC_API_KEY": api_key},
            llm_string=f"{self.provider_key}:{model}",
        )
