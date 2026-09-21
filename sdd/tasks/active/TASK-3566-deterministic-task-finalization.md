# TASK-3566: Cerrar tareas con evidencia y journal reanudable

**Feature**: FEAT-584 — Optimización medible del flujo SDD y transición compactada a revisión
**Spec**: `sdd/specs/sdd-execution-optimization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3559
**Assigned-to**: unassigned

## Context

Implementa M4 / R4 de la spec aprobada. Baseline de contratos: dev, commit 31f4c47afc72748a387ef8a8e55d0588894668e7.
La optimización conserva aceptación semántica, ownership, cobertura y evidencia explícita; los porcentajes del profiler no son ahorros garantizados.

## Scope

- CLI síncrono con evidencia estructurada y SHA; nunca fabricar review_evidence.
- Prevalidar y journal antes de primitiva close_task, verificar mover/índice/staging al final.

**NOT in scope**: cambiar roster/scheduler, relajar sandbox/checks, modificar clients/base.py, introducir dependencias o realizar cambios fuera de los targets. El adaptador específico de host queda diferido por Q1 salvo enmienda aprobada posterior.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/finalize_task.py` | CREATE | Journal fuera de archivos de código, operación serializada por tarea/índice |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py` | CREATE | Usar repo temporal real con close_task.sh, snapshots de index/staging antes/después; tamper hash refs, notes deterministas y payload distinto requiere operación nueva. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Verificación estática de símbolos existentes por AST y lectura de fuentes; no presupone importación del framework. Los imports nuevos se distinguen abajo y requieren completar sus dependencias.

`from parrot.flows.dev_loop.sdd_coder.fidelity import check_fidelity` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py:56`.

`from parrot.flows.dev_loop.sdd_coder.telemetry import resolve_durable_root` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py:107`.

Imports de blueprint (stdlib / dependencias instaladas / símbolos creados por esta tarea o sus predecesoras; **no** APIs existentes inventadas):

```python
from __future__ import annotations
from parrot.flows.dev_loop.sdd_coder.optimization_models import TaskCompletionEvidence
from pathlib import Path
import pytest
```
Pydantic, pytest y Click ya están instalados/declarados; módulos optimization_models/evidence/checkpoint/inspection_models nuevos solo se importan después de sus tareas productoras. Verificar cualquier import adicional antes de introducirlo.

### Existing Signatures to Use

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py:56` · SHA-256 `5b6af10b0eda7b32ed33fa0f5d6c95e92992dfc55cb12ae24dc30115cc574c4e`

```python
def check_fidelity(expected: List[str], changed: List[str]) -> FidelityReport:
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

Contrato shell verificado: scripts/sdd/close_task.sh TASK-ID feature-slug [verification]. Puede borrar el active cuando existe completed: el wrapper debe impedir esa rama si son divergentes; no modificar el script genérico. Además, el script hace git add -u sdd/tasks/active: invocarlo directamente puede stagear tareas ajenas. Ejecutarlo con GIT_INDEX_FILE temporal inicializado desde el índice real y transferir SOLO entradas de esta tarea/índice al índice real bajo exclusión y comprobación de cambios concurrentes. No copiar el índice temporal entero, no reset global. Probar cambios staged y unstaged ajenos dentro de active/, no solo archivos de código.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "scripts/sdd/finalize_task.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py#check_fidelity",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py#resolve_durable_root"
  ]
}
```

## Implementation Notes

Async-first en MCP; I/O bloqueante fuera del event loop. CLI síncrono permitido. Pydantic v2, Black 120 y Ruff. Core no importa parrot_tools. Los blueprints contienen decisiones acotadas pendientes de implementación: no constituyen un Delegation Contract ni permiten entregar placeholders.

## Implementation Blueprint

### Steps (in order)

1. Validar identidad/evidencia y snapshot Git: impedir cierre stale.
2. Renderizar nota estable y persistir journal: reanudar sin duplicar efectos.
3. Invocar primitiva existente y comprobar postcondiciones: impedir éxito parcial.

### `scripts/sdd/finalize_task.py` (CREATE)

```python
"""Finalize a verified task deterministically without committing or pushing."""
from __future__ import annotations
from pathlib import Path
from parrot.flows.dev_loop.sdd_coder.optimization_models import TaskCompletionEvidence

def finalize_task(*, evidence: TaskCompletionEvidence, worktree: Path,
                  expected_head: str) -> dict[str, object]:
    """Validate evidence, journal intent, close one task and return staged paths."""
    # FILL IN: validate feature/task/HEAD/scope/checks/semantic review refs.
    # Reject divergent active/completed twins before close_task.sh is invoked.
    # Journal task_id+implementation_sha+evidence_hash and resume each phase.
    # Use a temporary Git index for close_task.sh; transfer only owned entries
    # to the real index with concurrency checks, never its broad active/ stage.
    # Preserve unrelated files/staging; deterministic note and metrics only.
    raise NotImplementedError

def main(argv: list[str] | None = None) -> int:
    """Exit 0 success/replay, 1 operation error, 2 invalid input, 3 stale/busy."""
    # FILL IN: --evidence --worktree --expected-head; JSON result/error.
    raise NotImplementedError

if __name__ == '__main__':
    raise SystemExit(main())
```

**Aplicación y motivo:** Journal fuera de archivos de código, operación serializada por tarea/índice. Wrapper usa close_task.sh existente sin modificarlo y verifica postcondiciones. Detectar índice/tracked task con cambios ajenos antes de stage; no reset/git add ./commit/push. Emitir task.accepted solo con evidencia completa.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py` (CREATE)

```python
"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""
import pytest
from pathlib import Path

def test_semantic_evidence_and_head_required(tmp_path: Path) -> None:
    """Missing review, red tests or stale implementation SHA prevent mutation."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_crash_resume_and_twin_conflict(tmp_path: Path) -> None:
    """Each journal phase resumes once and divergent twins remain intact."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_preserve_foreign_staging(tmp_path: Path) -> None:
    """Only the task and its index are staged; unrelated staged/unstaged content stays unchanged."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError
```

**Aplicación y motivo:** Usar repo temporal real con close_task.sh, snapshots de index/staging antes/después; tamper hash refs, notes deterministas y payload distinto requiere operación nueva.

### FILL IN checklist

- [ ] `scripts/sdd/finalize_task.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.

## Acceptance Criteria

- [ ] AC8: repetición idéntica idempotente y reanudación tras crash; twin divergente nunca borrado.
- [ ] Solo tarea/índice, sin stage ajeno, commit/push/reset; checks obligatorios y revisión real ligados al SHA.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py -q`

## Test Specification

Los escenarios en los blueprints son el mínimo verificable. Usar repos/procesos sintéticos aislados, fallos de persistencia y assertions sobre resultados observables; no servicios de proveedor en suite offline. Guardar logs en artifacts/logs/. Los tests live se ejecutan aparte y nunca se presentan como pasados por una simulación.

## Agent Instructions

1. Leer `sdd/specs/sdd-execution-optimization.spec.md` y comprobar dependencias en `sdd/tasks/index/sdd-execution-optimization.json`; no usar índice monolítico.
2. Revalidar imports/anchors y convenios antes de editar. Preservar cambios de otras tareas y del usuario.
3. Implementar solo targets, completar blueprints y ejecutar Validation Commands. No rebajar ACs para cerrar la tarea.
4. Registrar evidencia y revisión; usar el flujo SDD para actualizar estado, mover active→completed y commit acotado.
5. Si falta una API o scope, registrar bloqueo/diseño pendiente; no inventar contratos ni declarar done sin evidencia.

## Completion Note

Pendiente de ejecución. Registrar autor, fecha, evidencia, validaciones y desviaciones; no rellenar con éxito anticipado.
