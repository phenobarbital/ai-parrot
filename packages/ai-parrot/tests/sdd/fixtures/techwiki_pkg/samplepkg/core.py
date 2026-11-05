"""Public fixture API."""

from typing import overload

from pydantic import BaseModel, Field

__all__ = ["PublicModel", "Widget", "format_value", "make"]


class PublicModel(BaseModel):
    """A public model used to exercise class rendering."""

    name: str
    count: int = Field(default=1, description="How many times to repeat the name.")

    @property
    def label(self) -> str:
        """Return a readable label."""
        return f"{self.name}:{self.count}"

    class Nested:
        """A nested public class."""


@overload
def format_value(value: int) -> str: ...


@overload
def format_value(value: str) -> str: ...


def format_value(value: int | str) -> str:
    """Format a value.

    Args:
        value: The value to format.

    Returns:
        The formatted string.
    """
    return str(value)


class Widget:
    """A sized widget.

    Args:
        size: Edge length in pixels.
        name: Optional display name.
    """

    def __init__(self, size: int, *, name: str | None = None) -> None:
        self.size = size
        self.name = name

    def resize(self, size: int) -> None:
        """Change the widget size.

        Args:
            size: New edge length in pixels.

        Raises:
            ValueError: If ``size`` is not positive.
        """
        if size <= 0:
            raise ValueError("size must be positive")
        self.size = size

    def describe(self) -> str:
        """Return a one-line description."""
        return f"{self.name or 'widget'}:{self.size}"

    def _helper(self) -> None:
        """Internal helper that must not render."""


def make(size: int, *, name: str | None = None) -> Widget:
    """Build a widget.

    Args:
        size: Edge length in pixels.
        name: Optional display name.

    Returns:
        The new widget.
    """
    return Widget(size, name=name)


def _private() -> None:
    """Private fixture member that must not render."""
