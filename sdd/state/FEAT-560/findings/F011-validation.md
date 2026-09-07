---
id: F011
query_id: Q005
type: read
intent: Comprobar la línea base de tests existentes
executed_at: 2026-09-07T05:39:14.792114+00:00
parent_id: F007
depth: 2
---

# F011 — Línea base: 19 tests pasan

## Summary

`uv run pytest packages/ai-parrot/tests/clients/test_live_tool_routing.py packages/ai-parrot/tests/clients/test_nova_tool_result.py -q`: 19 passed, 8 warnings in 1.45s. La primera ejecución no pudo escribir la caché uv en sandbox; la repetición autorizada fuera del sandbox terminó correctamente. Estas pruebas no acreditan paridad dual Nova ni disponibilidad de AWS/LiveAvatar.

## Citations

- path: `packages/ai-parrot/tests/clients/test_live_tool_routing.py`
- path: `packages/ai-parrot/tests/clients/test_nova_tool_result.py`
- log: `artifacts/logs/voicebot_liveavatar_proposal_pytest.log` (local, excluido del commit documental).
