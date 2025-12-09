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
from .claude import AnthropicClient, ClaudeClient, ClaudeModel
from .google import GoogleGenAIClient, GoogleModel
from .gpt import OpenAIClient, OpenAIModel
from .groq import GroqClient, GroqModel
from .factory import LLMFactory, SUPPORTED_CLIENTS




__all__ = (
    "AbstractClient",
    "StreamingRetryConfig",
    "SUPPORTED_CLIENTS",
    "AnthropicClient",
    "ClaudeClient",  # Backward compatibility alias
    "ClaudeModel",
    "GoogleGenAIClient",
    "GoogleModel",
    "OpenAIClient",
    "OpenAIModel",
    "GroqClient",
    "GroqModel",
    "LLM_PRESETS",
)
