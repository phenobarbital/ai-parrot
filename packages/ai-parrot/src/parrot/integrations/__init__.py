"""Integrations stub — actual implementations are in ai-parrot-integrations.

This stub provides helpful error messages when the satellite package is not
installed.  When ``ai-parrot-integrations`` is installed, Python's implicit
namespace package mechanism (``pkgutil.extend_path`` / PEP 328 implicit
namespaces) merges both distributions' ``parrot/integrations/`` directories
into a single logical package; the satellite's concrete modules are imported
directly and this stub's ``__getattr__`` is bypassed for those names.

Migration notes
---------------
- OAuth2 moved: ``parrot.integrations.oauth2.*`` → ``parrot.auth.oauth2.*``
- Zoom moved:   ``parrot.integrations.zoom.*``   → ``parrot_tools.zoom.*``
"""
from pkgutil import extend_path

# Merge this stub with the satellite ``ai-parrot-integrations`` distribution's
# ``parrot/integrations/`` directory (PEP 420 / pkgutil namespace). Without
# this, the stub stays a single-directory regular package and the satellite's
# concrete modules (telegram/, slack/, msteams/, ...) are never found, so the
# ``__getattr__`` fallback below fires even when the satellite IS installed.
__path__ = extend_path(__path__, __name__)

_CHANNEL_EXTRAS: dict[str, str] = {
    "slack": "slack",
    "telegram": "telegram",
    "msteams": "msteams",
    "whatsapp": "whatsapp",
    "matrix": "matrix",
    "voice": "voice",
    "IntegrationBotManager": "all",
    "IntegrationBotConfig": "all",
    "TelegramAgentConfig": "telegram",
    "MSTeamsAgentConfig": "msteams",
    "WhatsAppAgentConfig": "whatsapp",
    "SlackAgentConfig": "slack",
}

_MOVED_SYMBOLS: dict[str, str] = {
    "oauth2": "parrot.auth.oauth2",
    "zoom": "parrot_tools.zoom",
}


def __getattr__(name: str):
    """Provide helpful error messages for missing symbols."""
    if name in _MOVED_SYMBOLS:
        new_location = _MOVED_SYMBOLS[name]
        raise ImportError(
            f"'parrot.integrations.{name}' has been relocated to '{new_location}'.\n"
            f"Update your import: from {new_location} import ..."
        )
    extra = _CHANNEL_EXTRAS.get(name, "all")
    raise ImportError(
        f"'{name}' requires ai-parrot-integrations.\n"
        f"Install with: pip install ai-parrot-integrations[{extra}]"
    )
