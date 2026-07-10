"""
A2A (Agent-to-Agent) integration for AI-Parrot.

Exposes ai-parrot agents as A2A protocol services declaratively via
``kind: a2a`` entries in ``integrations_bots.yaml``.
"""
# Lazy re-exports (PEP 562). Submodules added in later tasks (e.g. the
# startup wiring) pull in the optional ``ai-parrot-server`` package, so
# importing this package eagerly would force that dependency even on
# callers that only need the config model (e.g. ``parrot.integrations.models``).
# Defer loading every submodule until the caller actually touches one of the
# names below; importing a specific submodule path (e.g.
# ``parrot.integrations.a2a.models``) does not trigger any optional SDK.
import importlib
from typing import TYPE_CHECKING

_LAZY_EXPORTS = {
    "A2AAgentConfig": ".models",
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
    from .models import A2AAgentConfig  # noqa: F401
