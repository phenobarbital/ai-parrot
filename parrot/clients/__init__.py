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
from .claude import ClaudeClient, ClaudeModel
from .vertex import VertexAIClient, VertexAIModel
from .google import GoogleGenAIClient, GoogleModel
from .gpt import OpenAIClient, OpenAIModel
from .groq import GroqClient, GroqModel


SUPPORTED_CLIENTS = {
    "claude": ClaudeClient,
    "vertexai": VertexAIClient,
    "google": GoogleGenAIClient,
    "openai": OpenAIClient,
    "groq": GroqClient
}


__all__ = (
    "AbstractClient",
    "StreamingRetryConfig",
    "SUPPORTED_CLIENTS",
    "ClaudeClient",
    "ClaudeModel",
    "VertexAIClient",
    "VertexAIModel",
    "GoogleGenAIClient",
    "GoogleModel",
    "OpenAIClient",
    "OpenAIModel",
    "GroqClient",
    "GroqModel",
    "LLM_PRESETS",
)
