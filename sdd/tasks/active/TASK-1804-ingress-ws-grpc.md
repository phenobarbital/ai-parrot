# TASK-1804: Mudar ingress WebSocket y gRPC (+ proto package fix)

**Feature**: FEAT-312 — EventBus Core Extraction → `navigator-eventbus`
**Spec**: `sdd/specs/eventbus-core-extraction.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1800, TASK-1803
**Assigned-to**: unassigned

---

## Context

Module 7 del spec. Los dos ingress externos del bus (WS y gRPC) implementan
el contrato `BaseHook` (por eso dependen de TASK-1803). El paquete `proto/`
de origen NO tiene `__init__.py` (resuelve por namespace implícito) — la
mudanza debe añadirlo y ajustar/regenerar los stubs al nuevo package root.

## Scope

- Copiar `bus/ingress/{websocket,grpc}.py` → `src/navigator_eventbus/ingress/`
  con imports intra-paquete (`EventBus` de `navigator_eventbus.evb`,
  `IngressEnvelope` de `ingress_models`, `BaseHook` de `hooks.base`).
- Copiar `bus/ingress/proto/{events.proto,events_pb2.py,events_pb2_grpc.py,README.md}`
  → `src/navigator_eventbus/ingress/proto/` y **añadir `__init__.py`**.
- Ajustar el package/import path de los stubs: `events_pb2_grpc.py` importa
  `events_pb2` por nombre — verificar que resuelve bajo el nuevo root; si el
  `.proto` declara `package parrot.events.v1`, conservarlo (contrato de wire,
  no de import) pero regenerar los stubs con `grpcio-tools` si el import
  relativo se rompe. Documentar el comando de regeneración en el README del proto.
- Auth por token (`BUS_INGRESS_TOKEN`) se conserva tal cual.
- Mudar tests de ingress (WS con aiohttp test utils; gRPC marcado si
  requiere `grpcio` — extra `[grpc]`).

**NOT in scope**: cambios al contrato proto (pregunta resuelta en
brainstorm-v2: reutilizar las ideas del envelope A2UI — ya aplicado en
FEAT-310); nuevos métodos RPC.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/navigator_eventbus/ingress/websocket.py` | CREATE | copia + imports intra-paquete |
| `src/navigator_eventbus/ingress/grpc.py` | CREATE | copia + imports intra-paquete |
| `src/navigator_eventbus/ingress/proto/__init__.py` | CREATE | **nuevo** (falta en origen) |
| `src/navigator_eventbus/ingress/proto/{events.proto,events_pb2.py,events_pb2_grpc.py,README.md}` | CREATE | copia (+ regen si hace falta) |
| `src/navigator_eventbus/ingress/__init__.py` | MODIFY | exports |
| `tests/test_ingress_*.py` | CREATE | suite mudada |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navigator_eventbus.evb import EventBus                # TASK-1800
from navigator_eventbus.ingress_models import IngressEnvelope  # TASK-1800
from navigator_eventbus.hooks.base import BaseHook         # TASK-1803
```

### Existing Signatures to Use
```python
# ORIGEN: packages/ai-parrot/src/parrot/core/events/bus/ingress/websocket.py
#   línea 23: from parrot.core.events import EventBus            ← intra-paquete
#   línea 24: from ...ingress_models import IngressEnvelope       ← intra-paquete
#   línea 25: from parrot.core.hooks.base import BaseHook         ← intra-paquete
#   BUS_INGRESS_TOKEN leído vía navconfig (~línea 60)

# ORIGEN: packages/ai-parrot/src/parrot/core/events/bus/ingress/grpc.py
#   líneas 26-28: mismos tres imports                             ← intra-paquete
#   línea 42: lazy import de ...ingress.proto (events_pb2, events_pb2_grpc)
#   BUS_INGRESS_TOKEN (~línea 202)

# ORIGEN proto/ (verificado 2026-07-17): events.proto, events_pb2.py,
#   events_pb2_grpc.py, README.md — SIN __init__.py
```

### Does NOT Exist
- ~~`__init__.py` en el proto de origen~~ — hay que CREARLO en destino
  (criterio de aceptación del spec).
- ~~Dependencia dura de grpcio~~ — es extra `[grpc]`; los imports gRPC son
  lazy (patrón del origen, línea 42); el módulo debe importar sin grpcio
  instalado y fallar con mensaje claro solo al usarlo.
- ~~Ingress HTTP genérico en bus/ingress~~ — el ingress HTTP son los hooks
  webhook (no se muda nada más aquí).

---

## Implementation Notes

### Key Constraints
- `WebSocketIngress`/`GrpcIngress` implementan start/stop de `BaseHook` —
  no cambiar el contrato.
- aiohttp es dep directa (WS server side); grpcio extra.
- Si se regeneran stubs: `python -m grpc_tools.protoc -I src/navigator_eventbus/ingress/proto --python_out=... --grpc_python_out=... events.proto`
  y revisar el import de `events_pb2` en `events_pb2_grpc.py` (suele requerir
  ajuste a import relativo/absoluto del nuevo package).

### References in Codebase
- Origen: `packages/ai-parrot/src/parrot/core/events/bus/ingress/`
- Tests origen: grep "Ingress" en `packages/ai-parrot/tests/`

---

## Acceptance Criteria

- [ ] `from navigator_eventbus.ingress.websocket import <clase WS>` funciona sin grpcio
- [ ] Con extra `[grpc]`: import del módulo gRPC y de `proto/` funciona
- [ ] `proto/__init__.py` presente
- [ ] Auth por `BUS_INGRESS_TOKEN` conservada (tests mudados verdes)
- [ ] `ruff` + `mypy` limpios (stubs generados pueden excluirse del lint,
      como haga ai-parrot); cero `parrot.` en `src/`

---

## Test Specification

```python
# tests/test_ingress_websocket.py (extracto — mudar los de origen)
# Verificar: envelope válido publicado al bus; token inválido → rechazo;
# payload malformado → error sin tumbar el hook.
```

---

## Agent Instructions

1. Read the spec; verifica TASK-1800 y TASK-1803 en `completed/`.
2. Repo navigator-eventbus, rama `feat-FEAT-312-eventbus-core-extraction`.
3. Verify the Codebase Contract; lee ambos ingress de origen enteros.
4. Update index en ai-parrot `dev`; commit
   `feat: WS/gRPC ingress (FEAT-312 TASK-1804)`; move a `completed/`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
