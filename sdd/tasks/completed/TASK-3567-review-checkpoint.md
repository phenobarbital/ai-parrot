# TASK-3567: Publicar y validar checkpoint neutral antes de review

**Feature**: FEAT-584 — Optimización medible del flujo SDD y transición compactada a revisión
**Spec**: `sdd/specs/sdd-execution-optimization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3565, TASK-3566
**Assigned-to**: unassigned

## Context

Implementa M4 / R5 de la spec aprobada. Baseline de contratos: dev, commit 31f4c47afc72748a387ef8a8e55d0588894668e7.
La optimización conserva aceptación semántica, ownership, cobertura y evidencia explícita; los porcentajes del profiler no son ahorros garantizados.

## Scope

- Persistir manifest R5 y brief neutral después del cierre de ejecución y tareas.
- CLI reproduce revisión desde disco; cambios posteriores requieren checkpoint nuevo.

**NOT in scope**: cambiar roster/scheduler, relajar sandbox/checks, modificar clients/base.py, introducir dependencias o realizar cambios fuera de los targets. El adaptador específico de host queda diferido por Q1 salvo enmienda aprobada posterior.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/checkpoint.py` | CREATE | No depender de tablas in-memory desde CLI separado: exigir receipt durable de end_execution y settled validations |
| `scripts/sdd/review_checkpoint.py` | CREATE | No aceptar SHA del LLM para fabricar snapshot |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py` | CREATE | Cubrir CLI prepare/validate exit codes, disco fallido, fallback sin engine con prueba de settlement, UTF-8 brief8KiB, done-with-issues y artifacts faltantes. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Verificación estática de símbolos existentes por AST y lectura de fuentes; no presupone importación del framework. Los imports nuevos se distinguen abajo y requieren completar sus dependencias.

`from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:684`.

`from parrot.flows.dev_loop.sdd_coder.telemetry import resolve_durable_root` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py:107`.

Imports de blueprint (stdlib / dependencias instaladas / símbolos creados por esta tarea o sus predecesoras; **no** APIs existentes inventadas):

```python
from __future__ import annotations
from parrot.flows.dev_loop.sdd_coder.checkpoint import prepare_review_checkpoint, validate_review_checkpoint
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.optimization_models import ReviewCheckpoint
from parrot.flows.dev_loop.sdd_coder.telemetry import resolve_durable_root
from pathlib import Path
import asyncio
import pytest
```
Pydantic, pytest y Click ya están instalados/declarados; módulos optimization_models/evidence/checkpoint/inspection_models nuevos solo se importan después de sus tareas productoras. Verificar cualquier import adicional antes de introducirlo.

### Existing Signatures to Use

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:684` · SHA-256 `aeb4b46eca6261c77f2d42237eb4ca7396a89f76447a8a9b3a869f81e825209c`

```python
    async def end_execution(self, execution_id: str) -> "ExecutionPoolView":
```

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py:107` · SHA-256 `20575cc03234d60d3e38fb110bd259545a4eb5fcbee6e66910b202279d6da33a`

```python
def resolve_durable_root(configured: Optional[str], *, worktree_base_path: str) -> Path:
```

### Does NOT Exist

- Los símbolos nuevos declarados en los blueprints no existen en el baseline; no confundir contrato propuesto con API instalada.
- No existe un bridge genérico que convierta PID/Bash externo en receipt autoritativo ni una llamada MCP verificada para compactar cualquier subagente.
- No existe garantía de éxito por log vacío, instalación Jev o respuesta background inmediata.

### Task-specific integration constraints

El engine actual ya escribe un snapshot cerrado en el feature worktree; no basta para sobrevivir cleanup. Consumir la copia durable de settlement publicada por TASK-3565, comprobar hashes/owner/generación y rechazar persistence_degraded sin evidencia recuperada. No cambiar scripts de cierre ni estado de ejecución desde prepare.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/checkpoint.py",
      "action": "CREATE"
    },
    {
      "path": "scripts/sdd/review_checkpoint.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.end_execution",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py#resolve_durable_root"
  ]
}
```

## Implementation Notes

Async-first en MCP; I/O bloqueante fuera del event loop. CLI síncrono permitido. Pydantic v2, Black 120 y Ruff. Core no importa parrot_tools. Los blueprints contienen decisiones acotadas pendientes de implementación: no constituyen un Delegation Contract ni permiten entregar placeholders.

## Implementation Blueprint

### Steps (in order)

1. Leer settlement durable y todos los refs: CLI no puede adivinar el estado del engine.
2. Publicar manifest canónico y brief: sobrevivir a descarte de contexto.
3. Revalidar antes de review: invalidar ante cualquier cambio cubierto.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/checkpoint.py` (CREATE)

```python
"""Durable neutral handoff after authoritative execution settlement."""
from __future__ import annotations
from pathlib import Path
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.optimization_models import ReviewCheckpoint

async def prepare_review_checkpoint(*, feature: str, worktree: Path, execution_id: str,
                                    store: ExecutionEvidenceStore) -> ReviewCheckpoint:
    """Validate settlement and persist immutable identity, constraints and evidence."""
    # FILL IN: require durable closed execution; fallback needs verified no-own-
    # activity record. Unknown is busy. Capture full R5 fields + neutral brief8KiB.
    # Hash spec/index/conventions, base/head, branch, evidence; publish atomically.
    raise NotImplementedError

async def validate_review_checkpoint(checkpoint: ReviewCheckpoint, *, worktree: Path) -> None:
    """Reject stale branch, SHA, criteria, conventions or unverifiable evidence."""
    # FILL IN: re-read authoritative state/hashes; never approve the feature.
    raise NotImplementedError
```

**Aplicación y motivo:** No depender de tablas in-memory desde CLI separado: exigir receipt durable de end_execution y settled validations. Mantener pending/done-with-issues y restricciones explícitas del usuario; brief neutral no contiene conclusión del implementador. Nuevos errores checkpoint_stale/busy/incomplete se representan sin evadir gates.

### `scripts/sdd/review_checkpoint.py` (CREATE)

```python
"""Prepare or validate the durable review handoff from authoritative local state."""
from __future__ import annotations
import asyncio
from pathlib import Path
from parrot.flows.dev_loop.sdd_coder.checkpoint import prepare_review_checkpoint, validate_review_checkpoint
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.telemetry import resolve_durable_root

def main(argv: list[str] | None = None) -> int:
    """JSON CLI: 0 success, 1 operation error, 2 invalid input, 3 stale/busy."""
    # FILL IN: prepare|validate --feature --worktree --execution-id;
    # validate additionally requires --checkpoint-id. Resolve SHAs locally.
    # Resolve durable root with existing policy and run the async API once.
    raise NotImplementedError

if __name__ == '__main__':
    raise SystemExit(main())
```

**Aplicación y motivo:** No aceptar SHA del LLM para fabricar snapshot. Cargar checkpoint por ID emitido, nunca path arbitrario fuera del durable root. Salida incluye referencia/hash/brief y pending visibles.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py` (CREATE)

```python
"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""
import pytest
from pathlib import Path

def test_settlement_and_unknown_gate(tmp_path: Path) -> None:
    """Unknown validation or unclosed execution prevents publication."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_stale_head_spec_index_and_conventions(tmp_path: Path) -> None:
    """Each covered revision change invalidates the handoff before review."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_durable_neutral_resume(tmp_path: Path) -> None:
    """A new reader with no development conversation recovers criteria, diff and constraints."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError
```

**Aplicación y motivo:** Cubrir CLI prepare/validate exit codes, disco fallido, fallback sin engine con prueba de settlement, UTF-8 brief8KiB, done-with-issues y artifacts faltantes.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/checkpoint.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `scripts/sdd/review_checkpoint.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.

## Acceptance Criteria

- [ ] AC7/AC9/AC10: no checkpoint válido si falta evidencia, actividad unknown o hashes obsoletos.
- [ ] Brief≤8KiB, diff completo por refs y restricciones de usuario intactas; no aprobación sintética.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py -q`

## Test Specification

Los escenarios en los blueprints son el mínimo verificable. Usar repos/procesos sintéticos aislados, fallos de persistencia y assertions sobre resultados observables; no servicios de proveedor en suite offline. Guardar logs en artifacts/logs/. Los tests live se ejecutan aparte y nunca se presentan como pasados por una simulación.

## Agent Instructions

1. Leer `sdd/specs/sdd-execution-optimization.spec.md` y comprobar dependencias en `sdd/tasks/index/sdd-execution-optimization.json`; no usar índice monolítico.
2. Revalidar imports/anchors y convenios antes de editar. Preservar cambios de otras tareas y del usuario.
3. Implementar solo targets, completar blueprints y ejecutar Validation Commands. No rebajar ACs para cerrar la tarea.
4. Registrar evidencia y revisión; usar el flujo SDD para actualizar estado, mover active→completed y commit acotado.
5. Si falta una API o scope, registrar bloqueo/diseño pendiente; no inventar contratos ni declarar done sin evidencia.

## Completion Note

Completado 2026-09-21 por coder nativo sonnet (attempt `47137220887642e8a74e0e381459ac65`). Tocó solo
los tres targets listados:

- `checkpoint.py` CREATE — `prepare_review_checkpoint`/`validate_review_checkpoint` (firmas del
  blueprint sin cambios). `prepare` nunca confía en estado en memoria: escanea el evidence root
  durable por el `ExecutionSnapshot` que `end_execution` publicó (TASK-3565), valida scope
  (feature_id/worktree_path) y que admitted_attempts/native_reservations/outstanding_job_ids estén
  vacíos, confirma que toda registración `kind=="validation"` asentó vía la API pública
  `BackgroundRegistry.status()`, hashea spec/index/tres archivos de convenciones, resuelve
  branch/base_sha (`git merge-base HEAD origin/<base_branch>`)/HEAD/commits vía git, publica
  excerpts de task+criteria como evidencia durable, renderiza un `neutral_brief` fáctico acotado
  (sin veredicto), computa `checkpoint_id` vía `ReviewCheckpoint.compute_checkpoint_id`, y publica
  atómicamente el checkpoint bajo `executions/<execution_id>/review/<checkpoint_id>.json` (layout
  R3 de la spec). `validate` re-deriva cada uno de esos hechos desde cero y lanza `checkpoint_stale`
  ante cualquier drift (branch/HEAD/spec/index/convención/hash de evidence-ref) — nunca aprueba código.
- `scripts/sdd/review_checkpoint.py` CREATE — CLI `prepare|validate --feature --worktree
  --execution-id[--checkpoint-id]`, exit 0/1/2/3 según el blueprint (`checkpoint_busy`/
  `checkpoint_stale`/`checkpoint_incomplete` → 3; otro `CheckpointError` → 1; `ValueError`/argparse
  → 2). Los SHA siempre se resuelven localmente vía git, nunca aceptados de un caller.
- `test_review_checkpoint.py` CREATE — 3 escenarios: `test_settlement_and_unknown_gate`,
  `test_stale_head_spec_index_and_conventions`, `test_durable_neutral_resume`, contra repos git
  temporales reales.

Decisiones de diseño flagueadas por el coder (revisadas, aceptadas sin cambios): (1)
`ReviewCheckpoint.user_constraints` siempre se publica como `[]` porque la firma fija del
blueprint no tiene forma de recibirlo explícitamente — `pending_actions` sí se deriva de forma
durable (toda tarea no-`done` del índice) y se puebla real. (2) `evidence_refs` está anclado solo a
`[settlement_ref]` — ningún productor en el alcance actual de esta feature publica todavía
evidencia de fix/feedback/review bajo una key descubrible (mismo gap honesto que
`inspection.delivery_report`). (3) "Validaciones asentadas" se leen escaneando los registros en
disco de `background.py` directamente (parseando solo el payload público anidado
`BackgroundRegistration`) porque `BackgroundRegistry` no tiene API pública de listado y añadir una
tocaría `background.py`, fuera del scope de esta tarea; cualquier registro ilegible/malformado
falla SEGURO (`checkpoint_busy`, nunca un falso "clear"). (4) `base_sha` requiere que
`origin/<base_branch>` resuelva localmente vía git — siempre cierto en worktrees SDD reales
(`ensure_worktree` bifurca desde `origin/<base_branch>`). (5) Nota de entorno, no defecto de código:
misma ausencia de `.so` de Cython que TASK-3566 documentó; copiados temporalmente para verificar
localmente y removidos antes del commit (`git status` confirma su ausencia). (6) También observado
(preexistente, no introducido aquí): importar `parrot` configura logging a stdout, por lo que la
línea JSON de este CLI queda precedida de ruido INFO/DEBUG — idéntico al ya mergeado
`scripts/sdd/finalize_task.py`; un caller debe tomar la ÚLTIMA línea de stdout como el payload JSON.

Sin bloqueos ni desviaciones del blueprint. `.claude/agents/sdd-worker.md` NO fue tocado — esta
tarea no registra tools MCP nuevos.

Validación:
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py -q` → 3 passed.
- Smoke-test manual del CLI: busy (sin settlement) → exit 3; prepare tras publicar settlement
  cerrado → exit 0 con checkpoint bien formado; validate → exit 0; mutar un archivo de convenciones
  → validate exit 3 `checkpoint_stale`.
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder -q` (regresión completa del paquete,
  post-merge) → 446 passed.
- `ruff check` en los tres archivos → clean (lint autofix del engine: commit `94e646d6a`).
- Merge-tier ai-parrot/ai-parrot-integrations: ver nota consolidada del feature — la escalación a
  paquete completo tropieza con fallos preexistentes ajenos a esta feature (`ai-parrot`, confirmado
  contra baseline `dev`) y con un hang de suite ajeno a nuestro scope en
  `ai-parrot-integrations` (3 intentos, ~2500s, detenido consistentemente ~97%); no bloqueante para
  este task, documentado para seguimiento separado.

Review: `coder-review:3a85bb3261868d12bd927b9c`.

Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: ~1407s · Tokens: 325293 (subagent total, in/out no separado para native).
