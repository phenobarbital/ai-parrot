---
id: F006
query_id: Q009
type: grep
intent: parrot.voice y parrot.human coupling con integrations
executed_at: 2026-05-28T13:40:35+02:00
depth: 0
---

# F006 — voice y human son usados SOLO por msteams + telegram; ambos son candidatos a moverse parcialmente

## Summary

**parrot.voice**: tiene 5 archivos (handler.py, models.py, server.py,
session.py + transcriber/ + ui/) y solo es consumido por
`integrations/msteams/voice/*` (6 archivos) e
`integrations/telegram/{models,wrapper}.py`. **Cero consumidores fuera
de integrations.** Por lo tanto `parrot.voice` puede moverse al nuevo
paquete (o al menos el subsistema transcriber).

**parrot.human**: tiene channel-specific class
`parrot/human/channels/telegram.py::TelegramHumanChannel` que es
inherentemente acoplada a un canal específico (telegram). El resto de
`parrot.human` (manager, models, events, actions, escalation, node,
cli_companion) es genérico/core. Decisión: mover
`parrot/human/channels/` con integrations; mantener el core de
`parrot.human` en ai-parrot.

## Citations

- path: parrot.voice consumers (fuera de parrot/voice/)
  excerpt: |
    integrations/msteams/voice/__init__.py
    integrations/msteams/voice/backend.py
    integrations/msteams/voice/transcriber.py
    integrations/msteams/voice/faster_whisper_backend.py
    integrations/msteams/voice/openai_backend.py
    integrations/msteams/voice/models.py
    integrations/telegram/models.py
    integrations/telegram/wrapper.py
    tests/integrations/msteams/test_msteams_voice_backward_compat.py
    tests/integrations/telegram/test_telegram_voice_integration.py

- path: `packages/ai-parrot/src/parrot/voice/`
  excerpt: |
    handler.py     (~6K)
    server.py      (~25K — aiohttp server)
    session.py
    models.py
    transcriber/   (backend, faster_whisper_backend, openai_backend,
                    transcriber, models — ~30K)
    ui/            (chat.html, voice_chat.html, basic.js)

- path: `packages/ai-parrot/src/parrot/human/`
  excerpt: |
    Top: __init__.py, manager.py, models.py, events.py,
         escalation_intent.py, node.py, tool.py, cli_companion.py
    channels/: __init__.py, telegram.py (TelegramHumanChannel)
    actions/   (HITL actions)

- path: `packages/ai-parrot/src/parrot/integrations/manager.py`
  lines: 18-21
  excerpt: |
    from ..human import (
        HumanInteractionManager,
        TelegramHumanChannel,    # ← canal-específico
    )

## Notes

Opciones para voice (necesita decisión):

| Opción | Pros | Contras |
|---|---|---|
| **A. Mover todo parrot.voice al nuevo paquete** | parrot.voice solo lo usa integrations; cero consumidores fuera | parrot.voice deja de existir en ai-parrot (breaking si algún consumidor externo al repo lo usa) |
| **B. Mover solo `voice/transcriber/`** y dejar handler/server/session en core | core mantiene capacidad voice (servidor genérico) | El transcriber es la parte pesada (whisper); split parcial |
| **C. Dejar parrot.voice en core, no mover** | Cero migración | Las deps de whisper viven en core aunque solo se usen vía integrations |

Recomendación tentativa: **A** (mover todo) — los datos lo respaldan:
parrot.voice nunca se usa fuera de integrations.

Para human:
- Mover `parrot/human/channels/telegram.py` al nuevo paquete
  (probablemente a `parrot_integrations.telegram.human` o similar).
- Dejar el resto de `parrot.human` en ai-parrot (HITL es concepto core).
- Crear hook/registry para que canales registren sus
  HumanChannel implementations (similar al patrón de outputs en FEAT-200).
