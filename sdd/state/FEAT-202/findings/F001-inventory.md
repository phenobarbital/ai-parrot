---
id: F001
query_id: Q001,Q002
type: tree
intent: Inventario completo de parrot/integrations/ con tamaños
executed_at: 2026-05-28T13:40:35+02:00
depth: 0
---

# F001 — 6 canales (1.6MB total), piezas comunes (~160K), telegram es el más pesado

## Summary

`parrot/integrations/` contiene 6 subdirectorios de canales y 5
archivos/dir comunes en la raíz. Total ~1.6MB.

## Citations

- path: `packages/ai-parrot/src/parrot/integrations/`
  excerpt: |
    668K  telegram/       (22 archivos + crew/, static/)
    288K  slack/          (10 archivos)
    220K  msteams/        (5 archivos + dialogs/, tools/, voice/)
    180K  matrix/         (9 archivos + crew/)
    116K  whatsapp/       (8 archivos)
    116K  oauth2/         (7 archivos: registry, service, persistence, jira_provider, o365_provider, models)
     20K  parser.py       (shared response parser)
     16K  manager.py      (IntegrationBotManager — config loader)
      8K  zoom/           (client.py, __init__.py)
      8K  core/           (state.py — InMemoryStateStore con TTL)
      4K  models.py       (IntegrationBotConfig — root config dataclass)
      4K  __init__.py     (lazy PEP 562 re-exports)

- path: `packages/ai-parrot/src/parrot/integrations/telegram/`
  excerpt: |
    22 archivos top-level + crew/ (10 archivos) + static/
    Highlights: wrapper.py, auth.py, manager.py, oauth2_callback.py,
    jira_commands.py, mcp_commands.py, mcp_persistence.py,
    office365_commands.py, post_auth.py, post_auth_jira.py,
    human_tool.py, combined_callback.py, filters.py, decorators.py
    crew/: coordinator.py, crew_wrapper.py, transport.py, registry.py,
           mention.py, payload.py, config.py, agent_card.py

- path: `packages/ai-parrot/src/parrot/integrations/msteams/`
  excerpt: |
    Top: adapter.py, handler.py, models.py, wrapper.py
    dialogs/: factory.py, orchestrator.py, models.py + presets/
             (base, wizard, wizard_summary, conversational, simple_form)
    voice/: backend.py, faster_whisper_backend.py, openai_backend.py,
            transcriber.py, models.py  [hereda de parrot.voice]
    tools/: __init__.py (stub)

- path: `packages/ai-parrot/src/parrot/integrations/matrix/`
  excerpt: |
    Top: client.py, appservice.py, registration.py, events.py,
         streaming.py, models.py, a2a_transport.py
    crew/: coordinator.py, crew_wrapper.py, transport.py, registry.py,
           session.py, session_models.py, delegation.py, config.py, mention.py

## Notes

Disparidad de tamaños:
- **telegram (668K)** es el más grande — tiene el mayor número de
  archivos por la familia de comandos OAuth2/Jira/Office365/MCP.
- **slack (288K)** es 2do — incluye assistant.py, dedup.py, files.py,
  interactive.py, security.py, socket_handler.py.
- **msteams (220K)** + sus dialogs/tools/voice subdirs.
- **matrix (180K)** + crew (colaborativo, en desarrollo activo).
- **whatsapp (116K)** mediano.
- **zoom (8K)** es solo un wrapper de cliente HTTP — el más pequeño,
  no expone un bot sino una integración API.
