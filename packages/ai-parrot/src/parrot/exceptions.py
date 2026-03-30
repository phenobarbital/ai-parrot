# -*- coding: utf-8 -*-
"""Parrot exception hierarchy.

Provides the base exception class and all standard Parrot exceptions as pure
Python classes. This module replaces the previous Cython implementation
(``parrot/exceptions.pyx``) with an equivalent pure Python version that
requires no compilation and supports standard Python subclassing.
"""
from typing import Any, Optional


class ParrotError(Exception):
    """Base class for Parrot exceptions.

    Args:
        message: The error message. If the object has a ``.message``
            attribute, that attribute value is used as the message string.
        *args: Ignored positional arguments (for compatibility with
            ``Exception`` call conventions).
        **kwargs: Optional keyword arguments. ``stacktrace`` is extracted and
            stored on ``self.stacktrace``; all kwargs are stored on
            ``self.args`` for backward compatibility with the Cython original.
    """

    def __init__(self, message: Any, *args, **kwargs) -> None:
        super().__init__(message)
        self.message: str = str(getattr(message, 'message', message))
        self.stacktrace: Optional[Any] = kwargs.get('stacktrace')
        self.args = kwargs  # type: ignore[assignment]

    def __repr__(self) -> str:
        return self.message

    __str__ = __repr__

    def get(self) -> str:
        """Return the message of the exception.

        Returns:
            The exception message as a string.
        """
        return self.message


class ConfigError(ParrotError):
    """Raised for configuration-related errors."""


class SpeechGenerationError(ParrotError):
    """Raised for errors related to speech generation."""


class DriverError(ParrotError):
    """Raised for errors related to driver operations."""


class ToolError(ParrotError):
    """Raised for errors related to tool operations."""


class InvokeError(ParrotError):
    """Raised when an ``invoke()`` call fails.

    Wraps provider-level exceptions so callers get a consistent error type
    regardless of which LLM backend was used.

    Args:
        message: Human-readable error description.
        *args: Forwarded to :class:`ParrotError`.
        original: The original provider exception, preserved for debugging.
        **kwargs: Forwarded to :class:`ParrotError`.

    Attributes:
        original: The original exception that caused this error, or ``None``.
    """

    def __init__(
        self,
        message: str,
        *args,
        original: Optional[Exception] = None,
        **kwargs
    ) -> None:
        super().__init__(message, *args, **kwargs)
        self.original: Optional[Exception] = original
