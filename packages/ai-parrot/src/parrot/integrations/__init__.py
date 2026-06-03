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
import importlib
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

# Public symbols the satellite ai-parrot-integrations publishes at the
# parrot.integrations top level, mapped to the submodule that defines them.
# Resolved lazily here: the satellite ships NO parrot/integrations/__init__.py
# (it would otherwise overwrite this file when both wheels unpack into the same
# site-packages — last writer wins at the file level, not a namespace merge),
# so this core stub is the sole owner of the package's dispatch. The core never
# hard-depends on the satellite, and per-channel SDKs load only when the symbol
# is actually used.
_SATELLITE_EXPORTS: dict[str, str] = {
    "IntegrationBotManager": "manager",
    "IntegrationBotConfig": "models",
    "TelegramAgentConfig": "models",
    "MSTeamsAgentConfig": "models",
    "WhatsAppAgentConfig": "models",
    "SlackAgentConfig": "models",
}


def __getattr__(name: str):
    """Resolve satellite symbols lazily, else raise a helpful error."""
    if name in _MOVED_SYMBOLS:
        new_location = _MOVED_SYMBOLS[name]
        raise ImportError(
            f"'parrot.integrations.{name}' has been relocated to '{new_location}'.\n"
            f"Update your import: from {new_location} import ..."
        )
    extra = _CHANNEL_EXTRAS.get(name, "all")
    submodule = _SATELLITE_EXPORTS.get(name)
    if submodule is not None:
        try:
            module = importlib.import_module(f"{__name__}.{submodule}")
        except ModuleNotFoundError as exc:
            missing = exc.name or ""
            if missing == __name__ or missing.startswith(f"{__name__}."):
                reason = "ai-parrot-integrations is not installed"
            else:
                reason = f"the optional dependency '{missing}' is missing"
            raise ImportError(
                f"'{name}' requires ai-parrot-integrations ({reason}).\n"
                f"Install with: pip install ai-parrot-integrations[{extra}]"
            ) from exc
        return getattr(module, name)
    raise ImportError(
        f"'{name}' requires ai-parrot-integrations.\n"
        f"Install with: pip install ai-parrot-integrations[{extra}]"
    )
