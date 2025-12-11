"""
Client for Interactions with LLMs (Language Models)
This module provides a client interface for interacting with various LLMs.
It includes functionality for sending requests, receiving responses, and handling errors.
"""
from .base import (
    AbstractClient,
    LLM_PRESETS,
    StreamingRetryConfig
)

__all__ = (
    "AbstractClient",
    "LLM_PRESETS",
    "StreamingRetryConfig"
)
