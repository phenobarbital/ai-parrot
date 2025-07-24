"""
Client for Interactions with LLMs (Language Models)
This module provides a client interface for interacting with various LLMs.
It includes functionality for sending requests, receiving responses, and handling errors.
"""
from .abstract import AbstractClient
from .claude import ClaudeClient, ClaudeModel
from .vertex import VertexAIClient, VertexAIModel
from .google import GoogleGenAIClient, GoogleModel
from .gpt import OpenAIClient, OpenAIModel
from .groq import GroqClient, GroqModel


LLM_PRESETS = {
    "analytical": {"temperature": 0.1, "max_tokens": 4000},
    "creative": {"temperature": 0.7, "max_tokens": 6000},
    "balanced": {"temperature": 0.4, "max_tokens": 4000},
    "concise": {"temperature": 0.2, "max_tokens": 2000},
    "detailed": {"temperature": 0.3, "max_tokens": 8000},
    "comprehensive": {"temperature": 0.5, "max_tokens": 10000},
    "verbose": {"temperature": 0.6, "max_tokens": 12000},
    "summarization": {"temperature": 0.2, "max_tokens": 3000},
    "translation": {"temperature": 0.1, "max_tokens": 5000},
    "inspiration": {"temperature": 0.8, "max_tokens": 7000},
    "default": {"temperature": 0.4, "max_tokens": 4000}
}

SUPPORTED_CLIENTS = {
    "claude": ClaudeClient,
    "vertexai": VertexAIClient,
    "google": GoogleGenAIClient,
    "openai": OpenAIClient,
    "groq": GroqClient
}


__all__ = (
    "AbstractClient",
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
