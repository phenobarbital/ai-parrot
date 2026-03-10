"""Google (Gemini) provider wizard for parrot setup."""
import click

from parrot.setup.wizard import BaseClientWizard, ProviderConfig


class GoogleWizard(BaseClientWizard):
    """Wizard for Google (Gemini) credential collection.

    Collects the ``GOOGLE_API_KEY`` and model selection via
    interactive click prompts.
    """

    display_name: str = "Google (Gemini)"
    provider_key: str = "google"
    default_model: str = "gemini-2.5-flash"

    def collect(self) -> ProviderConfig:
        """Collect Google credentials interactively.

        Returns:
            ProviderConfig with ``GOOGLE_API_KEY`` and selected model.
        """
        click.echo(f"\nConfiguring {self.display_name}")
        model = click.prompt("Model", default=self.default_model)
        api_key = click.prompt("GOOGLE_API_KEY", hide_input=True)
        return ProviderConfig(
            provider=self.provider_key,
            model=model,
            env_vars={"GOOGLE_API_KEY": api_key},
            llm_string=f"{self.provider_key}:{model}",
        )
