"""
Interfaces package - Mixins for bot functionality.

This package contains interface classes that provide specific functionality
to bot implementations through multiple inheritance.
"""
from .tools import ToolInterface
from .vector import VectorInterface

from .rss import RSSInterface

__all__ = ['ToolInterface', 'VectorInterface', 'RSSInterface']
