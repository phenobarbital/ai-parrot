"""
Client for Interactions with LLMs (Language Models)
This module provides a client interface for interacting with various LLMs.
It includes functionality for sending requests, receiving responses, and handling errors.
"""
from .base import LLM_PRESETS, AbstractClient, StreamingRetryConfig
from .openai_base import OpenAIBaseClient

__all__ = (
    "LLM_PRESETS",
    "AbstractClient",
    "OpenAIBaseClient",
    "StreamingRetryConfig",
    "ZaiClient",
)

from .zai import ZaiClient
