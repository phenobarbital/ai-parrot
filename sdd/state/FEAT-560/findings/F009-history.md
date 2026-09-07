---
id: F009
query_id: Q006
type: git_log
intent: Identificar cambios recientes de rutas de proveedores
executed_at: 2026-09-07T05:36:39.417510+00:00
parent_id: null
depth: 0
---

# F009 — Extracción reciente de clientes

## Summary

HEAD investigado: `3d03bb2cdb4ef4a864fc51ec89c8dfb14781599e`, rama dev. La wiki de FEAT-418 usa rutas anteriores; las localizaciones de esta propuesta usan los paquetes satélite leídos.

## Citations

- `14b548483` — 2026-09-05 — Jesus — style: apply black formatting (post sdd-worker).
- `c00b575cd` — 2026-09-04 — Jesus — feat(pep-420-llm-clients): TASK-2850 — satellites ai-parrot-client-anthropic, ai-parrot-client-amazon.
- `6a4e7dbcf` — 2026-09-04 — Jesus — feat(pep-420-llm-clients): TASK-2845 — convert bedrock+nova→amazon/, gemma4/, hf/ folders with their enums.
- path: `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py`
- path: `packages/ai-parrot/src/parrot/clients/nova/audio.py` (ruta histórica consultada con git log; no destino de implementación).

## Notes

Log limitado a cinco commits sobre ambas rutas; no se atribuye causalidad del defecto a la extracción.
