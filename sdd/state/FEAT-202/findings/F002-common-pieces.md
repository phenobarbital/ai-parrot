---
id: F002
query_id: Q003
type: read
intent: Inspeccionar piezas comunes en integrations/ (core, oauth2, manager, parser, models, __init__)
executed_at: 2026-05-28T13:40:35+02:00
depth: 0
---

# F002 — Piezas comunes: lazy PEP 562 __init__ + 5 archivos compartidos

## Summary

`integrations/__init__.py` ya implementa **lazy re-exports vía PEP 562**
(`__getattr__`) para diferir `aiogram` (~1.5s import). `models.py` es
el `IntegrationBotConfig` dataclass raíz que carga
`{ENV_DIR}/integrations_bots.yaml`. `manager.py` es el
`IntegrationBotManager` que orquesta el lifecycle de bots (depende de
`parrot.human` para HITL y de `aiogram` directamente). `parser.py`
(20K) es el parser unificado de respuestas AIMessage para canales.
`core/state.py` es un `InMemoryStateStore` genérico con TTL.
`oauth2/` (116K) tiene infra OAuth2 reutilizable (registry + service
+ persistence + jira_provider + o365_provider).

## Citations

- path: `packages/ai-parrot/src/parrot/integrations/__init__.py`
  lines: 14-50
  excerpt: |
    _LAZY_EXPORTS = {
        "IntegrationBotConfig": ".models",
        "TelegramAgentConfig": ".models",
        "MSTeamsAgentConfig": ".models",
        "WhatsAppAgentConfig": ".models",
        "SlackAgentConfig": ".models",
        "IntegrationBotManager": ".manager",
    }
    def __getattr__(name: str):
        module_path = _LAZY_EXPORTS.get(name)
        if module_path is None:
            raise AttributeError(...)
        module = importlib.import_module(module_path, package=__name__)
        value = getattr(module, name)
        globals()[name] = value
        return value

- path: `packages/ai-parrot/src/parrot/integrations/manager.py`
  lines: 1-25
  excerpt: |
    """Integration Bot Manager.
    Manages lifecycle of bots (Telegram, MS Teams, WhatsApp) exposing
    AI-Parrot agents. Loads from {ENV_DIR}/integrations_bots.yaml
    (or telegram_bots.yaml fallback).
    """
    from aiogram import Bot, Dispatcher
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from navconfig import BASE_DIR
    from ..conf import AGENTS_DIR, REDIS_URL
    from ..human import (
        HumanInteractionManager,
        TelegramHumanChannel,
    )
    if TYPE_CHECKING:
        from ..bots.abstract import AbstractBot

- path: `packages/ai-parrot/src/parrot/integrations/models.py`
  lines: 1-15
  excerpt: |
    from .telegram.models import TelegramAgentConfig
    from .msteams.models import MSTeamsAgentConfig
    from .whatsapp.models import WhatsAppAgentConfig
    from .slack.models import SlackAgentConfig

    @dataclass
    class IntegrationBotConfig:
        agents: Dict[str, Union[TelegramAgentConfig, MSTeamsAgentConfig,
                                 WhatsAppAgentConfig, SlackAgentConfig]] = field(default_factory=dict)

- path: `packages/ai-parrot/src/parrot/integrations/parser.py`
  lines: 1-15
  excerpt: |
    """Shared Response Parser for Integration Wrappers.
    Provides a unified way to parse AIMessage responses into structured
    content for rendering in different platforms (Telegram, MS Teams, etc.).
    """
    try:
        import pandas as pd
        HAS_PANDAS = True
    except ImportError:
        HAS_PANDAS = False

- path: `packages/ai-parrot/src/parrot/integrations/core/state.py`
  lines: 12-30
  excerpt: |
    class InMemoryStateStore:
        """Simple in-memory key-value store with TTL support.
        Used as a fallback when no persistent store (e.g., Redis) is available.
        """
        def __init__(self):
            self._data: Dict[str, Any] = {}
            self._expiry: Dict[str, float] = {}
        async def set(self, key: str, value: str, expire: int = 0) -> None: ...
        async def get(self, key: str) -> Optional[str]: ...

- path: `packages/ai-parrot/src/parrot/integrations/oauth2/`
  excerpt: |
    Files: registry.py, service.py, persistence.py, jira_provider.py,
           o365_provider.py, models.py, __init__.py
    Symbols: OAuth2ProviderRegistry, IntegrationsService,
             register_oauth2_provider, JiraOAuth2Provider,
             O365OAuth2Provider, AuthRequiredEnvelope, EnableResponse,
             list_user_agent_toolkits

## Notes

Clasificación tentativa de las piezas comunes para el split:

| Archivo/dir | Decisión sugerida |
|---|---|
| `__init__.py` (lazy) | **MUEVE** — re-exporta canales |
| `manager.py` (IntegrationBotManager) | **MUEVE** — orquestador de canales, depende de aiogram |
| `models.py` (IntegrationBotConfig) | **MUEVE** — agrega los configs de canales |
| `parser.py` (Response Parser) | **MUEVE** — usado solo por wrappers de canales |
| `core/state.py` (InMemoryStateStore genérico) | **QUEDA en core** o se vuelve interno de integrations — utility 100% genérica, decisión depende de si lo usa algo más |
| `oauth2/` | **Discusión necesaria**: lo usan `parrot.auth.{oauth2_routes,routes}`, `parrot.handlers.{integrations,user_objects}`, `parrot.manager` — más amplio que solo canales. Puede ser **paquete propio** (`ai-parrot-oauth2`) o **quedarse en core**. |
