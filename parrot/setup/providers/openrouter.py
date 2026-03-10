"""OpenRouter provider wizard for parrot setup."""
import click

from parrot.setup.wizard import BaseClientWizard, ProviderConfig


class OpenRouterWizard(BaseClientWizard):
    """Wizard for OpenRouter credential collection.

    Collects the ``OPENROUTER_API_KEY`` and model selection via
    interactive click prompts. OpenRouter uses a ``provider/model``
    format for model identifiers.
    """

    display_name: str = "OpenRouter"
    provider_key: str = "openrouter"
    default_model: str = "anthropic/claude-sonnet-4-6"

    def collect(self) -> ProviderConfig:
        """Collect OpenRouter credentials interactively.

        Returns:
            ProviderConfig with ``OPENROUTER_API_KEY`` and selected model.
        """
        click.echo(f"\nConfiguring {self.display_name}")
        model = click.prompt("Model", default=self.default_model)
        api_key = click.prompt("OPENROUTER_API_KEY", hide_input=True)
        return ProviderConfig(
            provider=self.provider_key,
            model=model,
            env_vars={"OPENROUTER_API_KEY": api_key},
            llm_string=f"{self.provider_key}:{model}",
        )
