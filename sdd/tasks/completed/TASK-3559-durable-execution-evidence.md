# TASK-3559: Persistir eventos y artefactos idempotentes

**Feature**: FEAT-584 — Optimización medible del flujo SDD y transición compactada a revisión
**Spec**: `sdd/specs/sdd-execution-optimization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3558
**Assigned-to**: unassigned

## Context

Implementa M2 / R3 de la spec aprobada. Baseline de contratos: dev, commit 31f4c47afc72748a387ef8a8e55d0588894668e7.
La optimización conserva aceptación semántica, ownership, cobertura y evidencia explícita; los porcentajes del profiler no son ahorros garantizados.

## Scope

- Añadir executions/<uuid>/events.jsonl, artifacts/<sha>.json y resolución confinada.
- Mantener formato FEAT-*.jsonl existente sin cambios; distinguir fallo observacional de evidencia obligatoria.

**NOT in scope**: cambiar roster/scheduler, relajar sandbox/checks, modificar clients/base.py, introducir dependencias o realizar cambios fuera de los targets. El adaptador específico de host queda diferido por Q1 salvo enmienda aprobada posterior.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/evidence.py` | CREATE | Reutilizar root validada por resolve_durable_root |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_evidence.py` | CREATE | Probar conservación tras borrar worktree temporal, offsets inválidos, concurrencia de executions y symlinks. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Verificación estática de símbolos existentes por AST y lectura de fuentes; no presupone importación del framework. Los imports nuevos se distinguen abajo y requieren completar sus dependencias.

`from parrot.flows.dev_loop.sdd_coder.telemetry import resolve_durable_root` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py:107`.

`from parrot.flows.dev_loop.sdd_coder.telemetry import CoderTelemetrySink` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py:251`.

Imports de blueprint (stdlib / dependencias instaladas / símbolos creados por esta tarea o sus predecesoras; **no** APIs existentes inventadas):

```python
from __future__ import annotations
from parrot.flows.dev_loop.sdd_coder.optimization_models import EvidenceRef, WorkflowEvent
from pathlib import Path
from pydantic import BaseModel
import pytest
```
Pydantic, pytest y Click ya están instalados/declarados; módulos optimization_models/evidence/checkpoint/inspection_models nuevos solo se importan después de sus tareas productoras. Verificar cualquier import adicional antes de introducirlo.

### Existing Signatures to Use

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py:107` · SHA-256 `20575cc03234d60d3e38fb110bd259545a4eb5fcbee6e66910b202279d6da33a`

```python
def resolve_durable_root(configured: Optional[str], *, worktree_base_path: str) -> Path:
```

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py:251` · SHA-256 `20575cc03234d60d3e38fb110bd259545a4eb5fcbee6e66910b202279d6da33a`

```python
class CoderTelemetrySink:
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
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/evidence.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_evidence.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py#CoderTelemetrySink",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py#resolve_durable_root"
  ]
}
```

## Implementation Notes

Async-first en MCP; I/O bloqueante fuera del event loop. CLI síncrono permitido. Pydantic v2, Black 120 y Ruff. Core no importa parrot_tools. Los blueprints contienen decisiones acotadas pendientes de implementación: no constituyen un Delegation Contract ni permiten entregar placeholders.

## Implementation Blueprint

### Steps (in order)

1. Implementar root y publicación atómica: nunca exponer refs antes de persistir.
2. Añadir append con lock interproceso y reparación explícita: asegurar idempotencia tras crash.
3. Probar disco/corrupción y paginación: separar degradación de corrupción silenciada.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/evidence.py` (CREATE)

```python
"""Durable execution evidence with atomic publication and confined reads."""
from __future__ import annotations
from pathlib import Path
from pydantic import BaseModel
from parrot.flows.dev_loop.sdd_coder.optimization_models import EvidenceRef, WorkflowEvent

class ExecutionEvidenceStore:
    """Store immutable evidence outside worktrees, keyed by execution UUID."""
    def __init__(self, root: Path) -> None:
        self.root = root

    async def append_event(self, event: WorkflowEvent) -> EvidenceRef:
        """Append once per event_id; reject conflicting content and corruption."""
        # FILL IN: lock across processes, validate tail, fsync and atomic index.
        raise NotImplementedError

    async def put_artifact(self, execution_id: str, payload: BaseModel) -> EvidenceRef:
        """Publish canonical JSON and its hash only after durable persistence."""
        # FILL IN: reject escapes/symlinks, atomically publish, reuse identical hash.
        raise NotImplementedError

    async def read_artifact(self, execution_id: str, artifact_id: str,
                            offset: int = 0, limit: int = 8192) -> dict[str, object]:
        """Return a bounded UTF-8 page with stable cursor and full snapshot hash."""
        # FILL IN: emitted-ref ownership, limit<=16384, byte-safe continuation.
        raise NotImplementedError
```

**Aplicación y motivo:** Reutilizar root validada por resolve_durable_root. Serializar escritores de la misma ejecución también entre procesos; no solo asyncio.Lock. Recuperación de tail incompleto explícita; corrupción interior bloquea lectura confiable. I/O fuera del loop.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_evidence.py` (CREATE)

```python
"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""
import pytest
from pathlib import Path

def test_multiprocess_append_idempotency(tmp_path: Path) -> None:
    """Identical event ids deduplicate and conflicting payloads fail across writers."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_crash_tail_and_disk_failure(tmp_path: Path) -> None:
    """Interrupted appends and failed persistence never publish valid missing evidence."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_artifact_scope_and_unicode_pages(tmp_path: Path) -> None:
    """Cross-execution and traversal reads fail while Unicode pages reconstruct the exact snapshot."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError
```

**Aplicación y motivo:** Probar conservación tras borrar worktree temporal, offsets inválidos, concurrencia de executions y symlinks.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/evidence.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_evidence.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.

## Acceptance Criteria

- [ ] AC7: evidencia sobrevive cleanup; publicación atómica y conflictos no sobrescriben.
- [ ] AC4: paginación íntegra, bytes≤16KiB y hash verificable; referencias no son paths caller-controlled.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_evidence.py -q`

## Test Specification

Los escenarios en los blueprints son el mínimo verificable. Usar repos/procesos sintéticos aislados, fallos de persistencia y assertions sobre resultados observables; no servicios de proveedor en suite offline. Guardar logs en artifacts/logs/. Los tests live se ejecutan aparte y nunca se presentan como pasados por una simulación.

## Agent Instructions

1. Leer `sdd/specs/sdd-execution-optimization.spec.md` y comprobar dependencias en `sdd/tasks/index/sdd-execution-optimization.json`; no usar índice monolítico.
2. Revalidar imports/anchors y convenios antes de editar. Preservar cambios de otras tareas y del usuario.
3. Implementar solo targets, completar blueprints y ejecutar Validation Commands. No rebajar ACs para cerrar la tarea.
4. Registrar evidencia y revisión; usar el flujo SDD para actualizar estado, mover active→completed y commit acotado.
5. Si falta una API o scope, registrar bloqueo/diseño pendiente; no inventar contratos ni declarar done sin evidencia.

## Completion Note

Completed 2026-09-21 by native sonnet coder (attempt `e1cb2506a3654a8aa1fd270250329ba1`). Created
only the two CREATE targets:

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/evidence.py` — `ExecutionEvidenceStore`
  with `append_event`, `put_artifact`, `read_artifact` matching the blueprint's constructor and
  method signatures. `append_event` writes canonical JSON lines to
  `executions/<uuid>/events.jsonl`, deduplicated by `event_id`, serialized both in process
  (asyncio lock per execution) and cross process (flock, no-op fallback on non-POSIX). Repairs
  a crash-truncated trailing line transparently; any other corruption raises a new
  `EvidenceCorruptionError`; a conflicting re-append with different content raises a new
  `EvidenceConflictError`; identical content is an idempotent no-op. `put_artifact` publishes
  canonical-JSON content-addressed (sha256) artifacts via temp-file, fsync, atomic replace, so
  a reader never observes a partial file. `read_artifact` uses confined path resolution (UUID
  shape check, hex artifact id check, symlink rejection), a max page limit of 16384 bytes,
  byte-safe UTF-8 pagination, plus a full-snapshot sha256 and size in every page.
- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_evidence.py` — the three
  blueprint-named tests (`test_multiprocess_append_idempotency` with real multiprocessing
  children, `test_crash_tail_and_disk_failure`, `test_artifact_scope_and_unicode_pages`) plus
  one added test, `test_evidence_survives_temp_worktree_deletion`, exercising
  `resolve_durable_root` directly to prove evidence outlives a deleted worktree directory (AC7).

Design decision flagged for the downstream chain (TASK-3560 through TASK-3576 depend on this
module transitively): two new exception classes, `EvidenceConflictError(ValueError)` and
`EvidenceCorruptionError(RuntimeError)`, were introduced as the concrete mechanism for
rejecting conflicting content and corruption since the blueprint did not pin an exact shape.
Reviewed and accepted as the durable public contract: both are new symbols owned by this
module, not calls into a fabricated pre-existing API, and both subclass a standard exception
base so a generic catch still works.

Environment note: this worktree's compiled Cython extensions
(`parrot/utils/types*.so`, `parrot/utils/parsers/toml*.so`) were missing (gitignored build
artifacts only present in the main checkout); copied from the main checkout into this
worktree rather than rebuilt or synced, to unblock `import parrot` for validation. No shared
environment was mutated.

Validation:
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_evidence.py -q` → 4 passed (stable across 5 repeated runs per the coder, re-verified once here).
- `select_tests --tier merge` scoped to completed tasks (TASK-3555, TASK-3556, TASK-3557, TASK-3558) plus this one → dev_loop/sdd_coder core-escalation suite 405 passed; tool_optimizations suite 433 passed/1 deselected; wiki compaction suite 17 passed.
- `git status --porcelain --untracked-files=all` clean except gitignored build artifacts.
- `ruff check` on both new files → clean.

Review: `coder-review:5c77598a728b4b673f67a397` (zero fix commits — clean delivery).

Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: 604552ms (~10m5s) · Tokens: 150691 (subagent total, in/out split not exposed for native).
