"""Provider wizard implementations — imported to register BaseClientWizard subclasses."""
from parrot.setup.providers.anthropic import AnthropicWizard  # noqa: F401
from parrot.setup.providers.google import GoogleWizard  # noqa: F401
from parrot.setup.providers.openai import OpenAIWizard  # noqa: F401
from parrot.setup.providers.xai import XAIWizard  # noqa: F401
from parrot.setup.providers.openrouter import OpenRouterWizard  # noqa: F401

__all__ = [
    "AnthropicWizard",
    "GoogleWizard",
    "OpenAIWizard",
    "XAIWizard",
    "OpenRouterWizard",
]
