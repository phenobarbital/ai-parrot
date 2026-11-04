"""Public fixture API."""

from typing import overload

from pydantic import BaseModel


__all__ = ["PublicModel", "format_value"]


class PublicModel(BaseModel):
    """A public model used to exercise class rendering."""

    name: str
    count: int = 1

    @property
    def label(self) -> str:
        """Return a readable label."""
        return f"{self.name}:{self.count}"

    class Nested:
        """A nested public class."""

        pass


@overload
def format_value(value: int) -> str: ...


@overload
def format_value(value: str) -> str: ...


def format_value(value: int | str) -> str:
    """Format a value."""
    return str(value)


def _private() -> None:
    """Private fixture member that must not render."""
