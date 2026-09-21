# TASK-3562: Proyectar vistas compactas y lectura de artefactos

**Feature**: FEAT-584 — Optimización medible del flujo SDD y transición compactada a revisión
**Spec**: `sdd/specs/sdd-execution-optimization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3561
**Assigned-to**: unassigned

## Context

Implementa M3 / R2 de la spec aprobada. Baseline de contratos: dev, commit 31f4c47afc72748a387ef8a8e55d0588894668e7.
La optimización conserva aceptación semántica, ownership, cobertura y evidencia explícita; los porcentajes del profiler no son ahorros garantizados.

## Scope

- Añadir response_mode compatible y MCP para refs durables.
- Separar schemas heredados donde el nuevo argumento no pertenece al método existente.

**NOT in scope**: cambiar roster/scheduler, relajar sandbox/checks, modificar clients/base.py, introducir dependencias o realizar cambios fuera de los targets. El adaptador específico de host queda diferido por Q1 salvo enmienda aprobada posterior.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/views.py` | CREATE | Medir bytes serializados full/compact; artefactos inmutables antes de exponer refs |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` | MODIFY | Registrar schema en arg_models, docstring LLM-facing y mapping vía _run |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | Añadir argumentos estrictos y errores al conjunto ERROR_CODES; reutilizar validadores UUID/worktree/task |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py` | MODIFY | Cubrir descubrimiento real y validación previa de cada nuevo argumento; conservar tests existentes. |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_compact_views.py` | CREATE | Cubrir schema inválido, límites Unicode, begin/feedback inheritance y espera unchanged; comparar payload contra fixture anterior. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Verificación estática de símbolos existentes por AST y lectura de fuentes; no presupone importación del framework. Los imports nuevos se distinguen abajo y requieren completar sus dependencias.

`from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:192`.

`from parrot.flows.dev_loop.sdd_coder.models import CoderPlanArgs` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:506`.

`from parrot.flows.dev_loop.sdd_coder.models import CoderResult` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:471`.

Imports de blueprint (stdlib / dependencias instaladas / símbolos creados por esta tarea o sus predecesoras; **no** APIs existentes inventadas):

```python
from __future__ import annotations
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from pathlib import Path
from pydantic import BaseModel
from typing import Literal
import pytest
```
Pydantic, pytest y Click ya están instalados/declarados; módulos optimization_models/evidence/checkpoint/inspection_models nuevos solo se importan después de sus tareas productoras. Verificar cualquier import adicional antes de introducirlo.

### Existing Signatures to Use

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:192` · SHA-256 `29775c383a1cd1b8b4abc91951b62a9205df7968ae712c4b913433a14436b609`

```python
    async def coder_plan(self, feature: str, worktree: str, execution_id: str) -> CoderResult:
```

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:301` · SHA-256 `29775c383a1cd1b8b4abc91951b62a9205df7968ae712c4b913433a14436b609`

```python
    async def coder_wait(self, job_id: str, timeout_seconds: int = 120) -> CoderResult:
```

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:309` · SHA-256 `29775c383a1cd1b8b4abc91951b62a9205df7968ae712c4b913433a14436b609`

```python
    async def coder_status(self, job_id: str) -> CoderResult:
```

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:506` · SHA-256 `b459601f842150f19ddb8cd7d37c12ac81cf0a59cc77ccab612a1a532cc1a342`

```python
class CoderPlanArgs(_Args):
```

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:471` · SHA-256 `b459601f842150f19ddb8cd7d37c12ac81cf0a59cc77ccab612a1a532cc1a342`

```python
class CoderResult(BaseModel):
```

### Does NOT Exist

- Los símbolos nuevos declarados en los blueprints no existen en el baseline; no confundir contrato propuesto con API instalada.
- No existe un bridge genérico que convierta PID/Bash externo en receipt autoritativo ni una llamada MCP verificada para compactar cualquier subagente.
- No existe garantía de éxito por log vacío, instalación Jev o respuesta background inmediata.

### Task-specific integration constraints

Añadir from typing import Literal en toolkit/models cuando falte. CoderResult ya existe; project_response y ExecutionEvidenceStore proceden de dependencias. La clase CoderPlanArgs también es base de argumentos de feedback/review: aislar response_mode para no admitirlo en APIs ajenas.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/views.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_compact_views.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#CoderPlanArgs",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#CoderResult",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py#SddCoderToolkit.coder_plan",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py#SddCoderToolkit.coder_status",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py#SddCoderToolkit.coder_wait"
  ]
}
```

## Implementation Notes

Async-first en MCP; I/O bloqueante fuera del event loop. CLI síncrono permitido. Pydantic v2, Black 120 y Ruff. Core no importa parrot_tools. Los blueprints contienen decisiones acotadas pendientes de implementación: no constituyen un Delegation Contract ni permiten entregar placeholders.

## Implementation Blueprint

### Steps (in order)

1. Implementar proyección y persistencia previa: referencias nunca huérfanas.
2. Actualizar schemas/firmas y separar begin: impedir kwargs no soportados.
3. Probar compatibilidad, paginación y reducción: evitar optimización a costa de información.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/views.py` (CREATE)

```python
"""Compatible full responses and bounded, recoverable compact projections."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore

async def project_response(payload: BaseModel, *, mode: Literal['full', 'compact'],
                           execution_id: str, store: ExecutionEvidenceStore) -> dict[str, object]:
    """Preserve full data or publish detail before returning a compact snapshot."""
    # FILL IN: mode=full matches existing model_dump; compact<=16384 bytes.
    # Keep identity/generation/chunk/assessments/blockers/errors/suspensions/
    # orphans/outcomes, with required_pages_remaining for mandatory pages.
    raise NotImplementedError
```

**Aplicación y motivo:** Medir bytes serializados full/compact; artefactos inmutables antes de exponer refs. No truncar coder_feedback de prepare_native. Páginas obligatorias conservan todos los IDs.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` (MODIFY)

Anchor verificado: línea 51; ocurrencias exactas = 1; SHA-256 `29775c383a1cd1b8b4abc91951b62a9205df7968ae712c4b913433a14436b609`.

```text
class SddCoderToolkit(AbstractToolkit):
```

```python
# Add response_mode: Literal['full','compact']='full' to coder_plan,
# coder_wait and coder_status. Project only after existing call completes.
# Resolve job->execution server-side; preserve timeout and shield behavior.
async def coder_read_artifact(self, execution_id: str, artifact_id: str,
                             offset: int = 0, limit: int = 8192) -> CoderResult:
    """Read a bounded page from evidence emitted for this execution only."""
    # FILL IN: schema -> ownership check -> store.read_artifact -> CoderResult.
    raise NotImplementedError
```

**Aplicación y motivo:** Registrar schema en arg_models, docstring LLM-facing y mapping vía _run. No registrar helpers internos como tools.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` (MODIFY)

Anchor verificado: línea 481; ocurrencias exactas = 1; SHA-256 `b459601f842150f19ddb8cd7d37c12ac81cf0a59cc77ccab612a1a532cc1a342`.

```text
class _Args(BaseModel):
```

```python
# Extend plan/status/wait argument schemas with the Literal default full.
# coder_begin_execution currently reuses CoderPlanArgs: split its schema
# so it does not silently accept response_mode or receive an extra kwarg.
# Preserve feedback/report/review schemas that inherit plan's old shape.
# Add CoderReadArtifactArgs: execution UUID, opaque artifact_id,
# offset>=0, limit=8192 and 1..16384. No raw paths.
```

**Aplicación y motivo:** Añadir argumentos estrictos y errores al conjunto ERROR_CODES; reutilizar validadores UUID/worktree/task. No ampliar schema accidentalmente de otros métodos.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py` (MODIFY)

Anchor verificado: línea 20; ocurrencias exactas = 1; SHA-256 `0f798a1f0d66a6489138c7cf203e03f440c4b99b3b89bac0ab63425a370a3e30`.

```text
EXPECTED_TOOLS = {
```

```python
# Extend the exact set with the tools from R2.
# Keep every existing tool and the strict equality assertion.
```

**Aplicación y motivo:** Cubrir descubrimiento real y validación previa de cada nuevo argumento; conservar tests existentes.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_compact_views.py` (CREATE)

```python
"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""
import pytest
from pathlib import Path

def test_full_default_wire_compatibility(tmp_path: Path) -> None:
    """Omitting response_mode preserves old plan/status/wait payloads and native feedback."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_mandatory_pages_and_roundtrip(tmp_path: Path) -> None:
    """Huge blocker sets stay fully recoverable and prevent dispatch before pages are read."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_byte_reduction_and_foreign_artifact(tmp_path: Path) -> None:
    """Representative plan shrinks at least 50 percent; cross-execution artifact access fails."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError
```

**Aplicación y motivo:** Cubrir schema inválido, límites Unicode, begin/feedback inheritance y espera unchanged; comparar payload contra fixture anterior.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/views.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_compact_views.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.

## Acceptance Criteria

- [ ] AC4/AC5: full sigue default y mantiene contrato, compact≤16KiB con páginas obligatorias.
- [ ] Fixture grande reduce bytes ≥50%; no se oculta decisión ni feedback vinculante.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_compact_views.py -q`

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
