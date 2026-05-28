"""Integrations stub — actual implementations are in ai-parrot-integrations.

This stub provides helpful error messages when the satellite package is not
installed.  If ``ai-parrot-integrations`` is installed, its own
``__init__.py`` (at the same namespace path) wins via PEP 420 namespace
extension, and this stub is never reached.

Migration notes
---------------
- OAuth2 moved: ``parrot.integrations.oauth2.*`` → ``parrot.auth.oauth2.*``
- Zoom moved:   ``parrot.integrations.zoom.*``   → ``parrot_tools.zoom.*``
"""

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
