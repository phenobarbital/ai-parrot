---
id: F005
query_id: Q008
type: read
intent: Distinguir BotManager (parrot/manager) de IntegrationBotManager (integrations/manager.py)
executed_at: 2026-05-28T13:40:35+02:00
depth: 0
---

# F005 — Dos managers distintos: `BotManager` (core, queda) vs `IntegrationBotManager` (mueve)

## Summary

Hay dos clases "manager" fácilmente confundibles:

1. **`parrot/manager/manager.py::BotManager`** — orquestador global del
   lifecycle de **agentes/chatbots** (no de canales). Es usado por
   ~20+ archivos del codebase: handlers, autonomous, auth, bots, una
   ref en integrations/matrix/crew, etc. **Decisión del usuario (2026-05-28):
   QUEDA EN ai-parrot** porque también lo usan servidores, services,
   autonomous, etc., no solo integrations.

2. **`parrot/integrations/manager.py::IntegrationBotManager`** —
   loader/orquestador específico de bots de canal: lee
   `{ENV_DIR}/integrations_bots.yaml`, instancia Bot/Dispatcher de
   aiogram, registra TelegramHumanChannel en HumanInteractionManager,
   etc. Lo importan solo 2 sitios de producción: `BotManager` y
   `autonomous/orchestrator.py` (ambos vía import lazy dentro de
   funciones). **MUEVE con integrations.**

## Citations

- path: `packages/ai-parrot/src/parrot/manager/__init__.py`
  excerpt: |
    from .manager import BotManager
    __all__ = ["BotManager"]

- path: `packages/ai-parrot/src/parrot/manager/manager.py`
  lines: 1-25
  excerpt: |
    """Chatbot Manager.
    Tool for instanciate, managing and interacting with Chatbot through APIs.
    """
    from aiohttp import web
    from ..rerankers.factory import create_reranker
    from ..stores.parents.factory import create_parent_searcher
    from ..bots.abstract import AbstractBot
    from ..bots.basic import BasicBot
    from ..bots.chatbot import Chatbot

- path: BotManager consumers (~22 archivos)
  excerpt: |
    parrot/auth/pbac.py, jira_oauth.py, agent_guard.py
    parrot/bots/database/agent.py, abstract.py, prompts/presets.py
    parrot/autonomous/orchestrator.py
    parrot/core/hooks/mixins.py
    parrot/handlers/{infographic,chat,web_hitl,datasets,stream,test_handler,
                     agent,bots,agents/users,database/helpers,crew/handler}.py
    parrot/integrations/matrix/crew/crew_wrapper.py    (única ref desde integrations)

- path: `packages/ai-parrot/src/parrot/integrations/manager.py`
  lines: 1-30
  excerpt: |
    """Integration Bot Manager.
    Manages lifecycle of bots (Telegram, MS Teams, WhatsApp) exposing
    AI-Parrot agents. Loads configuration from
    {ENV_DIR}/integrations_bots.yaml.
    """
    from aiogram import Bot, Dispatcher
    from ..conf import AGENTS_DIR, REDIS_URL
    from ..human import (
        HumanInteractionManager,
        TelegramHumanChannel,
    )
    if TYPE_CHECKING:
        from ..bots.abstract import AbstractBot

- path: IntegrationBotManager consumers
  excerpt: |
    parrot/manager/manager.py:        from ..integrations import IntegrationBotManager  (lazy)
    parrot/autonomous/orchestrator.py: from ..integrations import IntegrationBotManager  (lazy)

## Notes

Confirmación explícita del usuario:
> "una aclaratoria, mantengamos a BotManager en ai-parrot, se que se usa
>  en ai-parrot-integrations pero tambien en servidores, servicios,
>  autonomous, etc, BotManager (parrot/manager) stays in ai-parrot."

El acoplamiento `parrot/integrations/matrix/crew/crew_wrapper.py →
BotManager` (única ref de integrations a BotManager) no es problema —
el nuevo paquete `ai-parrot-integrations` declarará dep a `ai-parrot`
y podrá importar BotManager normalmente.

El acoplamiento inverso (`BotManager → IntegrationBotManager`) ya está
**lazy** (import dentro de función), por lo que mover
`IntegrationBotManager` al nuevo paquete no rompe imports en
ai-parrot, solo cambia el sitio del lazy import:
`from ..integrations import IntegrationBotManager`
→ `from parrot_integrations import IntegrationBotManager` (si se usa
nombre nuevo) o sigue funcionando vía PEP 420 (si se mantiene
`parrot.integrations.*`).
