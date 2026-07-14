"""
Microsoft 365 Agents SDK integration for AI-Parrot.

Exposes ai-parrot agents to Microsoft Copilot Studio and Teams via the
Microsoft 365 Agents SDK (microsoft-agents-hosting-aiohttp).
"""
# Lazy re-exports (PEP 562). The wrapper/agent modules pull in
# ``microsoft_agents.*`` at runtime, so importing this package eagerly would
# force the optional ``microsoft-agents-*`` dependency even on callers that
# only need the config models (e.g. ``parrot.integrations.models``). Defer
# loading every submodule until the caller actually touches one of the names
# below; importing a specific submodule path (e.g.
# ``parrot.integrations.msagentsdk.models``) no longer triggers the SDK.
import importlib
from typing import TYPE_CHECKING

_LAZY_EXPORTS = {
    "MSAgentSDKConfig": ".models",
    "ParrotM365Agent": ".agent",
    "MSAgentSDKWrapper": ".wrapper",
    "SemanticUIResult": ".semantic",
    "UIAction": ".semantic",
    "render_card": ".cards",
    "render_text": ".cards",
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
    from .models import MSAgentSDKConfig  # noqa: F401
    from .agent import ParrotM365Agent  # noqa: F401
    from .wrapper import MSAgentSDKWrapper  # noqa: F401
    from .semantic import SemanticUIResult, UIAction  # noqa: F401
    from .cards import render_card, render_text  # noqa: F401
