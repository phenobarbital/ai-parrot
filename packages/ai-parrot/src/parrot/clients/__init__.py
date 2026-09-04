"""
Client for Interactions with LLMs (Language Models)
This module provides a client interface for interacting with various LLMs.
It includes functionality for sending requests, receiving responses, and handling errors.
"""

# FEAT-523: PEP 420 namespace merging — lets satellite distributions
# (ai-parrot-client-<provider>) contribute their own `parrot/clients/<provider>/`
# folder into this same namespace without core ever importing them directly.
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)

from .base import LLM_PRESETS, AbstractClient, StreamingRetryConfig  # noqa: E402
from .openai_base import OpenAIBaseClient  # noqa: E402

__all__ = (
    "LLM_PRESETS",
    "AbstractClient",
    "OpenAIBaseClient",
    "StreamingRetryConfig",
)
