---
kind: inline
jira_key: null
fetched_at: 2026-10-28T00:00:00Z
summary_oneline: Configurable post-closeout event hooks for /sdd-done (E2E subagents, Jira, Telegram/push) defined per repo
---
sdd-done-more-tests -- ¿puede el sdd-done invocar más tests luego de finalizar las consideraciones finales y antes de construir el PR? (E2E con parrot-browsing + plan pre-construido, screenshots/screencasts; repos como navigator-frontend-next). sdd-done es genérico (lo instala el flujo sdd): definir vía CLAUDE.md o config en .parrot/ qué pruebas/operaciones adicionales ejecutar — sub-agentes e2e-*, cerrar ticket Jira, notificar Telegram/Push — un "evento" al que se suscriben "métodos".
