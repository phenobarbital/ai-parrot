"""Flow execution records: what ran, for whom, and how it ended."""
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from .models import Run, RunStatus
    from .repository import RunRepository

__all__ = ("Run", "RunRepository", "RunStatus")

_LAZY_EXPORTS = {
    "Run": ("parrot_saas.runs.models", "Run"),
    "RunStatus": ("parrot_saas.runs.models", "RunStatus"),
    "RunRepository": ("parrot_saas.runs.repository", "RunRepository"),
}


def __getattr__(name: str) -> Any:
    """Resolve lazily-exported names on first access (PEP 562)."""
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(target[0]), target[1])
