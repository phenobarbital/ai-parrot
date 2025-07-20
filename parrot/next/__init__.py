"""
Next: is the idea of new generation of Parrot, which is a revolutionary approach to building Apps.
It is designed to be modular, flexible, and easy to use, allowing developers to create applications
with minimal effort and maximum efficiency.
Is a intent of migrating from Langchain to a more streamlined and efficient framework.
"""
from .abstract import AbstractClient
from .claude import ClaudeClient
from .vertex import VertexAIClient
from .google import GenAIClient
from .gpt import OpenAIClient

__all__ = ["AbstractClient", "ClaudeClient", "VertexAIClient", "GenAIClient", "OpenAIClient"]
