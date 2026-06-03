"""
WhatsApp integration for AI-Parrot.

Exposes agents via WhatsApp Business API (pywa) or WhatsApp Bridge (whatsmeow).
"""
# Lazy re-exports (PEP 562). ``wrapper`` pulls in ``pywa`` at module level, so
# importing this package eagerly would force the optional ``pywa`` dependency
# even on callers that only need the config models (e.g.
# ``parrot.integrations.models`` / ``IntegrationBotManager``). Defer loading
# every submodule until the caller actually touches one of the names below;
# importing a specific submodule path (e.g.
# ``parrot.integrations.whatsapp.models``) no longer triggers the
# pywa-dependent surface.
import importlib
from typing import TYPE_CHECKING

_LAZY_EXPORTS = {
    "WhatsAppAgentConfig": ".models",
    "WhatsAppAgentWrapper": ".wrapper",
    "WhatsAppBridgeConfig": ".bridge_config",
    "WhatsAppBridgeWrapper": ".bridge_wrapper",
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
    from .models import WhatsAppAgentConfig
    from .wrapper import WhatsAppAgentWrapper
    from .bridge_config import WhatsAppBridgeConfig
    from .bridge_wrapper import WhatsAppBridgeWrapper
