"""Communication channel implementations for HITL interactions."""
# Lazy re-exports (PEP 562). TelegramHumanChannel pulls aiogram (~1.5s),
# so defer it until the symbol is actually accessed.
import importlib
from typing import TYPE_CHECKING

_LAZY_EXPORTS = {
    "HumanChannel": ".base",
    "CLIHumanChannel": ".cli",
    "CLIDaemonHumanChannel": ".cli",
    "TelegramHumanChannel": ".telegram",
}

__all__ = list(_LAZY_EXPORTS.keys())


def __getattr__(name: str):
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_path, package=__name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(list(globals().keys()) + __all__)


if TYPE_CHECKING:
    from .base import HumanChannel
    from .cli import CLIDaemonHumanChannel, CLIHumanChannel
    from .telegram import TelegramHumanChannel
