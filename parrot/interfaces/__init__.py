"""
Interfaces package - Mixins for bot functionality.

This package contains interface classes that provide specific functionality
to bot implementations through multiple inheritance.
"""
from .tools import ToolInterface
from .vector import VectorInterface

from .rss import RSSInterface
from .odoointerface import OdooInterface
from .flowtask import FlowtaskInterface

__all__ = [
    'ToolInterface',
    'VectorInterface',
    'RSSInterface',
    'OdooInterface',
    'FlowtaskInterface',
]
