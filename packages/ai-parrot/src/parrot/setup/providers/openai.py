"""OpenAI provider wizard for parrot setup."""
import click

from parrot.setup.wizard import BaseClientWizard, ProviderConfig

OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIWizard(BaseClientWizard):
    """Wizard for OpenAI credential collection.

    Collects ``OPENAI_API_KEY``, ``OPENAI_BASE_URL``, and model selection
    via interactive click prompts. The base URL defaults to the official
    OpenAI endpoint but can be overridden for compatible providers.
    """

    display_name: str = "OpenAI"
    provider_key: str = "openai"
    default_model: str = "gpt-4o"

    def collect(self) -> ProviderConfig:
        """Collect OpenAI credentials interactively.

        Returns:
            ProviderConfig with ``OPENAI_API_KEY``, ``OPENAI_BASE_URL``,
            and selected model.
        """
        click.echo(f"\nConfiguring {self.display_name}")
        model = click.prompt("Model", default=self.default_model)
        base_url = click.prompt("Base URL", default=OPENAI_DEFAULT_BASE_URL)
        api_key = click.prompt("OPENAI_API_KEY", hide_input=True)
        return ProviderConfig(
            provider=self.provider_key,
            model=model,
            env_vars={
                "OPENAI_API_KEY": api_key,
                "OPENAI_BASE_URL": base_url,
            },
            llm_string=f"{self.provider_key}:{model}",
        )
