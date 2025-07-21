"""
Next: is the idea of new generation of Parrot, which is a revolutionary approach to building Apps.
It is designed to be modular, flexible, and easy to use, allowing developers to create applications
with minimal effort and maximum efficiency.
Is a intent of migrating from Langchain to a more streamlined and efficient framework.
"""
from .abstract import AbstractClient
from .claude import ClaudeClient, ClaudeModel
from .vertex import VertexAIClient, VertexAIModel
from .google import GoogleGenAIClient, GoogleModel
from .gpt import OpenAIClient, OpenAIModel
from .groq import GroqClient, GroqModel


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
)
