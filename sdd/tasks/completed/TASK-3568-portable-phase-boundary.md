# TASK-3568: Coordinar frontera de review sin asumir API de host

**Feature**: FEAT-584 — Optimización medible del flujo SDD y transición compactada a revisión
**Spec**: `sdd/specs/sdd-execution-optimization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3555, TASK-3567
**Assigned-to**: unassigned

## Context

Implementa M5 portable / R6 de la spec aprobada. Baseline de contratos: dev, commit 31f4c47afc72748a387ef8a8e55d0588894668e7.
La optimización conserva aceptación semántica, ownership, cobertura y evidencia explícita; los porcentajes del profiler no son ahorros garantizados.

## Scope

- Implementar protocolo propuesto y política auto|off durable, con idempotencia y outcomes observables.
- No implementar adaptador Claude ni instalar plugin; M0 debe fijar contrato primero.

**NOT in scope**: cambiar roster/scheduler, relajar sandbox/checks, modificar clients/base.py, introducir dependencias o realizar cambios fuera de los targets. El adaptador específico de host queda diferido por Q1 salvo enmienda aprobada posterior.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/phase_boundary.py` | CREATE | Solo política Python portable |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_phase_boundary.py` | CREATE | Drivers fake solo verifican política offline |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Verificación estática de símbolos existentes por AST y lectura de fuentes; no presupone importación del framework. Los imports nuevos se distinguen abajo y requieren completar sus dependencias.

`from parrot.knowledge.wiki.claude_code.compaction import compaction_status` — verificado en `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/compaction.py:317`.

Imports de blueprint (stdlib / dependencias instaladas / símbolos creados por esta tarea o sus predecesoras; **no** APIs existentes inventadas):

```python
from __future__ import annotations
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.optimization_models import ReviewCheckpoint, CompactionReceipt
from pathlib import Path
from typing import Literal, Protocol
import pytest
```
Pydantic, pytest y Click ya están instalados/declarados; módulos optimization_models/evidence/checkpoint/inspection_models nuevos solo se importan después de sus tareas productoras. Verificar cualquier import adicional antes de introducirlo.

### Existing Signatures to Use

`packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/compaction.py:317` · SHA-256 `907a498a68686d77e6337cf95a1abb4518a3201333874b2ae0bca8150ef98e94`

```python
def compaction_status(root: Path) -> dict[str, bool]:
```

### Does NOT Exist

- Los símbolos nuevos declarados en los blueprints no existen en el baseline; no confundir contrato propuesto con API instalada.
- No existe un bridge genérico que convierta PID/Bash externo en receipt autoritativo ni una llamada MCP verificada para compactar cualquier subagente.
- No existe garantía de éxito por log vacío, instalación Jev o respuesta background inmediata.

### Task-specific integration constraints

Los anchors de MODIFY son observados en el baseline. Si una dependencia modifica el mismo archivo, revalidar el anchor y conservar sus adiciones; no restaurar el hash anterior.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/phase_boundary.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_phase_boundary.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/compaction.py#compaction_status"
  ]
}
```

## Implementation Notes

Async-first en MCP; I/O bloqueante fuera del event loop. CLI síncrono permitido. Pydantic v2, Black 120 y Ruff. Core no importa parrot_tools. Los blueprints contienen decisiones acotadas pendientes de implementación: no constituyen un Delegation Contract ni permiten entregar placeholders.

## Implementation Blueprint

### Steps (in order)

1. Consumir hallazgos M0: comprobar que el protocolo portable sigue válido.
2. Persistir intención y serializar key antes de llamar driver: prevenir doble compaction.
3. Reconciliar receipt y revalidar handoff: evitar review sobre contexto/evidencia incorrectos.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/phase_boundary.py` (CREATE)

```python
"""Portable compaction policy; actual host adapters require M0 evidence."""
from __future__ import annotations
from typing import Literal, Protocol
from parrot.flows.dev_loop.sdd_coder.optimization_models import ReviewCheckpoint, CompactionReceipt
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore

class PhaseBoundaryDriver(Protocol):
    """Verified target context, safe between-turn boundary and observable receipt."""
    async def supports(self, context_id: str) -> bool:
        """Return false when context, host or version is not homologated."""
        ...

    async def compact(self, checkpoint: ReviewCheckpoint) -> CompactionReceipt:
        """Request one compaction in the checkpoint's actual context."""
        ...

async def prepare_review_boundary(checkpoint: ReviewCheckpoint, *, driver: PhaseBoundaryDriver,
                                  policy: Literal['auto', 'off'], store: ExecutionEvidenceStore) -> CompactionReceipt:
    """Persist intent, enforce one request and return an honest continuation receipt."""
    # FILL IN: durable idempotency key checkpoint_id+context_id; policy off skips.
    # supports=false is explicit unsupported, never completed.
    # Crash/timeout leaves in_progress until reconciled, never blind retry.
    # Persist compaction events and revalidate checkpoint before continuation.
    raise NotImplementedError
```

**Aplicación y motivo:** Solo política Python portable. Driver concreto y transporte no incluidos hasta enmienda de M0. Coordinar frontera mediante contrato; Python no puede garantizar por sí solo que el host esté entre turnos. Outcome de backend requiere evidencia, no settings.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_phase_boundary.py` (CREATE)

```python
"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""
import pytest
from pathlib import Path

def test_once_per_checkpoint_and_context(tmp_path: Path) -> None:
    """Concurrent/replayed requests invoke a supported driver at most once."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_unsupported_off_and_fallback(tmp_path: Path) -> None:
    """Unsupported/off/skipped/failed/backend-unknown are explicit and never fake Jev success."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_crash_timeout_and_stale_resume(tmp_path: Path) -> None:
    """Unknown in-progress state is reconciled without retry and stale handoff blocks continuation."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError
```

**Aplicación y motivo:** Drivers fake solo verifican política offline. No contabilizar estos tests como cumplimiento de AC11; exige live driver posterior.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/phase_boundary.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_phase_boundary.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.

## Acceptance Criteria

- [ ] AC12/AC13: unsupported/fallback/timeout explícitos y una solicitud por frontera/contexto.
- [ ] No compactar dentro de tool/turno activo ni sobre contexto padre por inferencia.
- [ ] AC11 sigue pendiente del driver real; mocks no lo satisfacen.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_phase_boundary.py -q`

## Test Specification

Los escenarios en los blueprints son el mínimo verificable. Usar repos/procesos sintéticos aislados, fallos de persistencia y assertions sobre resultados observables; no servicios de proveedor en suite offline. Guardar logs en artifacts/logs/. Los tests live se ejecutan aparte y nunca se presentan como pasados por una simulación.

## Agent Instructions

1. Leer `sdd/specs/sdd-execution-optimization.spec.md` y comprobar dependencias en `sdd/tasks/index/sdd-execution-optimization.json`; no usar índice monolítico.
2. Revalidar imports/anchors y convenios antes de editar. Preservar cambios de otras tareas y del usuario.
3. Implementar solo targets, completar blueprints y ejecutar Validation Commands. No rebajar ACs para cerrar la tarea.
4. Registrar evidencia y revisión; usar el flujo SDD para actualizar estado, mover active→completed y commit acotado.
5. Si falta una API o scope, registrar bloqueo/diseño pendiente; no inventar contratos ni declarar done sin evidencia.

## Completion Note

Completado 2026-09-21 por coder nativo sonnet (attempt `1f84ea4979ba43e8a42b139e849edf74`). Tocó
solo los dos targets listados:

- `phase_boundary.py` CREATE — `PhaseBoundaryDriver` Protocol (`async supports(context_id)` /
  `compact(checkpoint)`) y `prepare_review_boundary(checkpoint, *, driver, policy, store) ->
  CompactionReceipt` (firma fija del blueprint). Solo la política Python portable; sin adaptador
  Claude, sin instalación de plugin, sin inventar API de host — `compaction_status`
  (`knowledge/wiki/claude_code/compaction.py:317`, el único Verified Import) se referencia solo en
  el docstring del módulo, nunca invocado para decidir `driver.supports()` (R6: es diagnóstico de
  instalación, no un handshake de capacidad — mismo patrón que TASK-3567 con su propio
  contract_symbol no literalmente importado). Idempotency key = `sha256(checkpoint_id+context_id)`;
  antes de invocar el driver escribe un `CompactionReceipt` placeholder `in_progress` bajo
  `store.root/executions/<execution_id>/compaction/<key>.json`, con flock interprocess por key
  (mismo convenio de manifest-por-key que `checkpoint.py`, no `put_artifact` direccionado por
  contenido). Llamadas subsecuentes con la misma key (replay, concurrencia real vía
  `asyncio.gather`, o sesión reanudada tras crash) ven el registro existente bajo el lock y lo
  devuelven sin re-invocar el driver. `policy='off'` y `driver.supports()==False` cortocircuitan a
  receipts terminales `skipped`/`unsupported` explícitos sin llamar `compact()`. Una excepción del
  driver durante `compact()` no se atrapa y propaga al caller — el registro durable queda
  `in_progress` para que la siguiente llamada lo observe y rechace el retry. Un receipt del driver
  cuyo checkpoint_id/context_id no coincide con la solicitud se persiste como `failed` terminal y
  lanza `PhaseBoundaryStaleHandoffError`, bloqueando continuación en vez de confiar en evidencia
  desalineada.
- `test_phase_boundary.py` CREATE — 3 escenarios: `test_once_per_checkpoint_and_context` (replay
  secuencial + concurrencia real vía `asyncio.gather`, `call_count` del driver permanece en 1 en
  ambos casos), `test_unsupported_off_and_fallback` (`policy=off` nunca llama al driver;
  `supports()=False` → `unsupported` sin completar; `failed` reportado por el driver se ecoa
  verbatim; un resultado `unsupported` durable nunca se re-pregunta a un driver que ahora diría sí),
  `test_crash_timeout_and_stale_resume` (excepción no atrapada deja el registro `in_progress` y una
  llamada de seguimiento reconcilia sin reintentar; receipt de identidad desalineada del driver
  lanza `PhaseBoundaryStaleHandoffError` y su estado `failed` persistido bloquea cualquier retry en
  replay).

Decisión de diseño flagueada por el coder (requiere atención del orquestador, aceptada sin
cambios): `ReviewCheckpoint.context_id` es `Optional` y ningún productor actual (`prepare_review_checkpoint`
de TASK-3567) lo asigna — campo reservado para un futuro productor homologado con M0.
`prepare_review_boundary` lanza `ValueError` si `checkpoint.context_id` es `None`/vacío en vez de
fabricar un valor, ya que `CompactionReceipt.context_id` es un campo requerido no-vacío y no hay
default independiente del productor en el contrato. Esto significa que la función NO es aún
invocable end-to-end con el productor de checkpoint real de hoy hasta que una tarea posterior
asigne `context_id` — consistente con la nota de scope de la propia tarea de que el adaptador de
host/direccionamiento de contexto queda diferido a una M0 enmendada.

Sin desviaciones del blueprint fuera de lo flagueado arriba. `.claude/agents/sdd-worker.md` NO fue
tocado — esta tarea no registra tools MCP nuevos.

Validación:
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_phase_boundary.py -q` → 3 passed.
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder -q` (regresión completa, post-merge) →
  449 passed.
- `ruff check` en ambos archivos → clean (lint autofix del engine: commit `fa2f04b5a`).
- `git status --porcelain --untracked-files=all` limpio salvo artefactos de build gitignored.

Review: `coder-review:18b89ff7fb38bd262cc9c461`.

Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: ~860s · Tokens: 199369 (subagent total, in/out no separado para native).
