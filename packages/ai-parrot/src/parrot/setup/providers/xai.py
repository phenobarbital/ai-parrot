"""xAI (Grok) provider wizard for parrot setup."""
import click

from parrot.setup.wizard import BaseClientWizard, ProviderConfig


class XAIWizard(BaseClientWizard):
    """Wizard for xAI (Grok) credential collection.

    Collects the ``XAI_API_KEY`` and model selection via
    interactive click prompts.
    """

    display_name: str = "xAI (Grok)"
    provider_key: str = "xai"
    default_model: str = "grok-3"

    def collect(self) -> ProviderConfig:
        """Collect xAI credentials interactively.

        Returns:
            ProviderConfig with ``XAI_API_KEY`` and selected model.
        """
        click.echo(f"\nConfiguring {self.display_name}")
        model = click.prompt("Model", default=self.default_model)
        api_key = click.prompt("XAI_API_KEY", hide_input=True)
        return ProviderConfig(
            provider=self.provider_key,
            model=model,
            env_vars={"XAI_API_KEY": api_key},
            llm_string=f"{self.provider_key}:{model}",
        )
