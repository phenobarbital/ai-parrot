"""Communication channel implementations for HITL interactions."""
# Lazy re-exports (PEP 562). TelegramHumanChannel pulls aiogram (~1.5s),
# so defer it until the symbol is actually accessed.
import importlib
import logging
from typing import TYPE_CHECKING

_registry_logger = logging.getLogger("parrot.human.channels.registry")


class ChannelRegistry:
    """Registry for HumanChannel implementations.

    Satellite packages (e.g. ai-parrot-integrations) register channel
    implementations at module import time so that the core can discover
    them without a static dependency::

        # packages/ai-parrot-integrations/src/parrot/human/channels/telegram.py
        from parrot.human.channels import ChannelRegistry
        ChannelRegistry.register("telegram", TelegramHumanChannel)

    The registry works gracefully when *no* channels are registered
    (e.g. when only the core package is installed).
    """

    _channels: dict[str, type] = {}

    @classmethod
    def register(cls, name: str, channel_cls: type) -> None:
        """Register a channel implementation under ``name``.

        Args:
            name: Channel identifier, e.g. ``"telegram"``, ``"slack"``.
            channel_cls: Concrete class implementing :class:`HumanChannel`.
        """
        if name in cls._channels:
            _registry_logger.warning(
                "ChannelRegistry: '%s' already registered — replacing with %s",
                name,
                channel_cls.__name__,
            )
        cls._channels[name] = channel_cls
        _registry_logger.debug(
            "ChannelRegistry: registered '%s' -> %s", name, channel_cls.__name__
        )

    @classmethod
    def get(cls, name: str) -> type | None:
        """Return the registered channel class for ``name``, or ``None``.

        Args:
            name: Channel identifier.

        Returns:
            The channel class, or ``None`` if not registered.
        """
        return cls._channels.get(name)

    @classmethod
    def available(cls) -> list[str]:
        """Return a list of registered channel names.

        Returns:
            Sorted list of channel identifiers.
        """
        return sorted(cls._channels.keys())


_LAZY_EXPORTS = {
    "HumanChannel": ".base",
    "CLIHumanChannel": ".cli",
    "CLIDaemonHumanChannel": ".cli",
    # TelegramHumanChannel is now in satellite — resolved via PEP 420
    "TelegramHumanChannel": ".telegram",
}

__all__ = ["ChannelRegistry"] + list(_LAZY_EXPORTS.keys())


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
