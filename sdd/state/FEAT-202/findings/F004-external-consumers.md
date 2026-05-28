---
id: F004
query_id: Q005,Q006
type: grep
intent: Consumidores externos a parrot.integrations + coupling con bots/tools/human/voice/forms
executed_at: 2026-05-28T13:40:35+02:00
depth: 0
---

# F004 — 10 archivos de producción consumen parrot.integrations (mayoría tocan oauth2)

## Summary

`grep -rln "from parrot\\.integrations|from \\.\\.integrations"` retorna
10 archivos de producción en `ai-parrot` + 1 en `ai-parrot-tools` +
~25 tests. La mayoría consumen el subsistema **oauth2** (auth/routes,
auth/oauth2_routes, handlers/integrations, handlers/user_objects,
manager/manager). Solo `parrot/core/hooks/matrix.py` y
`parrot/bots/jira_specialist.py` consumen canales concretos.
Acoplamientos invertidos: integrations → bots/tools usa
`TYPE_CHECKING` (no runtime), integrations → human es runtime, voice
sí es runtime (msteams/voice y telegram/models).

## Citations

- path: imports de producción en ai-parrot
  excerpt: |
    parrot/manager/manager.py:
        from ..integrations import IntegrationBotManager   (lazy en función)
    parrot/handlers/integrations.py:
        from parrot.integrations.oauth2.service import IntegrationsService
    parrot/auth/oauth2_routes.py:
        from parrot.integrations.oauth2.jira_provider import JiraOAuth2Provider
        from parrot.integrations.oauth2.registry import register_oauth2_provider
    parrot/auth/routes.py:
        from ..integrations.oauth2.persistence import list_user_agent_toolkits
        from ..integrations.oauth2.registry import OAuth2ProviderRegistry
        from ..integrations.oauth2.models import AuthRequiredEnvelope
    parrot/autonomous/orchestrator.py:
        from ..integrations import IntegrationBotManager   (lazy)
    parrot/bots/jira_specialist.py:
        from parrot.integrations.telegram.jira_commands import TelegramOAuthNotifier
    parrot/core/hooks/matrix.py:
        from parrot.integrations.matrix.client import MatrixClientWrapper
    parrot/handlers/agent.py:
        from ..integrations.telegram.combined_callback import (...)
    parrot/handlers/user_objects.py:
        from parrot.integrations.oauth2.models import EnableResponse
    parrot/handlers/integrations.py:
        (heavy oauth2 use)

- path: cross-package (ai-parrot-tools)
  excerpt: |
    packages/ai-parrot-tools/src/parrot_tools/zoomtoolkit.py:
        from parrot.integrations.zoom.client import ZoomUsInterface

- path: integrations → bots/* (todos en TYPE_CHECKING — no runtime)
  excerpt: |
    integrations/manager.py:36:    from ..bots.abstract import AbstractBot   (TYPE_CHECKING)
    integrations/msteams/dialogs/orchestrator.py:32  (TYPE_CHECKING)
    integrations/slack/wrapper.py:64  (TYPE_CHECKING)
    integrations/telegram/wrapper.py:56  (TYPE_CHECKING)
    integrations/whatsapp/wrapper.py:31  (TYPE_CHECKING)
    integrations/matrix/crew/crew_wrapper.py:28  (TYPE_CHECKING)
    integrations/telegram/manager.py:32  (TYPE_CHECKING)

- path: integrations → human (RUNTIME)
  lines: integrations/manager.py:18-21
  excerpt: |
    from ..human import (
        HumanInteractionManager,
        TelegramHumanChannel,
    )

- path: integrations → voice (RUNTIME)
  excerpt: |
    integrations/msteams/voice/{backend,transcriber,faster_whisper_backend,
                                 openai_backend,models,__init__}.py
        from parrot.voice.transcriber import (...)
    integrations/telegram/models.py
        (referencia a parrot.voice)

- path: integrations → forms (RUNTIME — FEAT-199)
  excerpt: |
    integrations/msteams/dialogs/{*.py}, presets/*.py, wrapper.py
        from parrot.forms[.*] import ...   (8 archivos — ver FEAT-199)

## Notes

**Tres ejes de coupling:**

1. **oauth2 es el más usado externamente** (5 archivos de producción
   en core lo consumen) — sugiere que oauth2/ podría:
   a) quedarse en core (y este paquete depende de core para usarlo), o
   b) moverse junto con integrations, y core declara la dep al nuevo
      paquete en su extra `integrations`.
   Decisión arquitectónica.

2. **Canales concretos solo se consumen en:**
   - `core/hooks/matrix.py` → MatrixClientWrapper (parrot.core necesita
     conocer el wrapper de matrix → unfortunate coupling)
   - `bots/jira_specialist.py` → TelegramOAuthNotifier (telegram-specific)
   - `handlers/agent.py` → telegram.combined_callback
   - `manager/manager.py` + `autonomous/orchestrator.py` →
     IntegrationBotManager (lazy import en función)
   Esos 4 sitios necesitan adaptarse — opciones: imports lazy,
   indirección vía interface en core, o asumir dep al nuevo paquete.

3. **integrations → bots es solo type hints** — relación limpia.

4. **integrations → human, voice, forms son runtime.** Decisiones:
   - **human**: ¿se mueve con integrations? Probablemente no — HITL es
     un concepto core que channels implementan. `TelegramHumanChannel`
     vive en `parrot.human` hoy (no en integrations/telegram). Cuando
     integrations se mueva, `TelegramHumanChannel` también debe moverse
     (acoplamiento canal-específico). `parrot.human` core (interface +
     manager) se queda.
   - **voice**: ver F007.
   - **forms**: resuelto en FEAT-199 — la dep formdesigner sale en el
     extra `[msteams]` de este nuevo paquete.
