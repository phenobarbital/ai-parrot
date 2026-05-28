---
id: F007
query_id: Q010
type: git_log
intent: Actividad reciente por canal
executed_at: 2026-05-28T13:40:35+02:00
depth: 0
---

# F007 — matrix está en desarrollo MUY activo; resto está estable

## Summary

`git log --oneline -- integrations/{ch}/` por canal: **matrix** tiene
la actividad más reciente y abundante (matrix-collaborative-crew, 6+
commits recientes con TASKs 1295-1300). **telegram** tuvo fixes
recientes (validation, webhooks, OAuth2 generic). **msteams** tuvo
form-abstraction-layer rewrite (TASK-532). **slack**, **whatsapp**, y
**zoom** están dormantes desde la monorepo-migration (TASK-398, hace
meses).

## Citations

- excerpt: |
    === matrix ===
    2736e1af fix(matrix-collaborative-crew): address all code review issues
    c33a0cc4 fix(matrix-collaborative-crew): use getattr for _active_sessions
    5af2c6ab feat(matrix-collaborative-crew): TASK-1300 — Hybrid Tool Delegation
    6692e0ca feat(matrix-collaborative-crew): TASK-1299 — Transport Integration
    a481b377 feat(matrix-collaborative-crew): TASK-1298 — Collaborative Session
    d60f7c83 feat(matrix-collaborative-crew): TASK-1297 — Session State Models

    === telegram ===
    aee9b33f fix telegram command integration
    2481d0bd fix telegram validation
    7fd7f0de removing stalled telegram webhooks

    === msteams ===
    e0a92991 fix
    be10181a various fixes over dataset manager and integrations
    b2668adc feat(form-abstraction-layer): TASK-532 — MS Teams Integration Rewrite

    === slack ===
    49536110 feat(monorepo-migration): TASK-398 — Workspace Scaffolding

    === whatsapp ===
    49536110 feat(monorepo-migration): TASK-398 — Workspace Scaffolding

    === zoom ===
    49536110 feat(monorepo-migration): TASK-398 — Workspace Scaffolding

## Notes

Implicación de faseo:
- **matrix** debe extraerse al final o no extraerse en este FEAT.
  Está en pleno desarrollo activo (matrix-collaborative-crew sigue
  abriendo tasks). Mover en frío rompería el feature en curso.
- **slack, whatsapp, zoom**: candidatos ideales para primera fase
  (dormantes desde migración a monorepo, deps claras).
- **telegram**: estable a pesar de fixes recientes; segunda fase.
- **msteams**: depende de FEAT-199 (formdesigner) — si FEAT-199 se
  hace primero (escenario U3.a de FEAT-199), msteams puede moverse
  con sus imports ya migrados a `parrot_formdesigner`.
