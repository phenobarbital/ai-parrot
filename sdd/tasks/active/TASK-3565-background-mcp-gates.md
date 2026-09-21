# TASK-3565: Exponer coder_bg_status y bloquear cierres no asentados

**Feature**: FEAT-584 — Optimización medible del flujo SDD y transición compactada a revisión
**Spec**: `sdd/specs/sdd-execution-optimization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3562, TASK-3564
**Assigned-to**: unassigned

## Context

Implementa M8 / R8 de la spec aprobada. Baseline de contratos: dev, commit 31f4c47afc72748a387ef8a8e55d0588894668e7.
La optimización conserva aceptación semántica, ownership, cobertura y evidencia explícita; los porcentajes del profiler no son ahorros garantizados.

## Scope

- Registrar launch handles en MCP/native/validación y añadir schemas cerrados de status y launch.
- Bloquear checkpoint indirectamente mediante settlement durable de ejecución; preservar execution_busy/recovery_required.

**NOT in scope**: cambiar roster/scheduler, relajar sandbox/checks, modificar clients/base.py, introducir dependencias o realizar cambios fuera de los targets. El adaptador específico de host queda diferido por Q1 salvo enmienda aprobada posterior.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | Añadir integración dentro del engine existente; preservar ownership, gates, routing y admisión |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` | MODIFY | Registrar schema en arg_models, docstring LLM-facing y mapping vía _run |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | Añadir argumentos estrictos y errores al conjunto ERROR_CODES; reutilizar validadores UUID/worktree/task |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py` | MODIFY | Cubrir descubrimiento real y validación previa de cada nuevo argumento; conservar tests existentes. |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_mcp.py` | CREATE | Probar dos executions/worktrees, no race launch-vs-close, end después de reap, external unsupported y budgets por wire |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Verificación estática de símbolos existentes por AST y lectura de fuentes; no presupone importación del framework. Los imports nuevos se distinguen abajo y requieren completar sus dependencias.

`from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:684`.

`from parrot.flows.dev_loop.sdd_coder.jobs import JobTable` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py:18`.

`from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:169`.

`from parrot.flows.dev_loop.sdd_coder.models import CoderResult` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:471`.

Imports de blueprint (stdlib / dependencias instaladas / símbolos creados por esta tarea o sus predecesoras; **no** APIs existentes inventadas):

```python
from pathlib import Path
import pytest
```
Pydantic, pytest y Click ya están instalados/declarados; módulos optimization_models/evidence/checkpoint/inspection_models nuevos solo se importan después de sus tareas productoras. Verificar cualquier import adicional antes de introducirlo.

### Existing Signatures to Use

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:684` · SHA-256 `aeb4b46eca6261c77f2d42237eb4ca7396a89f76447a8a9b3a869f81e825209c`

```python
    async def end_execution(self, execution_id: str) -> "ExecutionPoolView":
```

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:1715` · SHA-256 `aeb4b46eca6261c77f2d42237eb4ca7396a89f76447a8a9b3a869f81e825209c`

```python
    async def cleanup(
        self, feature: str, worktree: str, keep_conflicted: bool = True, execution_id: Optional[str] = None
    ) -> CleanupReport:
```

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py:18` · SHA-256 `8e9a2198e2cce6a02017af7d3f8b57b0ab64dad5ba005604d092a478f40b519f`

```python
class JobTable:
```

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:169` · SHA-256 `29775c383a1cd1b8b4abc91951b62a9205df7968ae712c4b913433a14436b609`

```python
    async def _run(self, operation: str, coro: Awaitable[BaseModel]) -> CoderResult:
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

Añadir from typing import Literal en toolkit si falta. Persiste, al cerrar correctamente, una copia verificable del snapshot de ejecución y receipts del supervisor en la raíz durable exterior. El end_execution actual escribe snapshot en el worktree y puede devolver persistence_degraded: eso NO autoriza checkpoint. La persistencia de este handoff es obligatoria y su ausencia bloquea prepare, aunque falle solo la telemetría observacional por otra vía.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py",
      "action": "MODIFY"
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
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_mcp.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.cleanup",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.end_execution",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py#JobTable",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#CoderResult",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py#SddCoderToolkit._run"
  ]
}
```

## Implementation Notes

Async-first en MCP; I/O bloqueante fuera del event loop. CLI síncrono permitido. Pydantic v2, Black 120 y Ruff. Core no importa parrot_tools. Los blueprints contienen decisiones acotadas pendientes de implementación: no constituyen un Delegation Contract ni permiten entregar placeholders.

## Implementation Blueprint

### Steps (in order)

1. Conectar registro a launch real: el handle no se inventa al consultar.
2. Registrar tools y resultado compatible: conservar job_id y defaults.
3. Incluir supervisor en admisión/cierre atómico: evitar que launch y end se crucen.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY)

Anchor verificado: línea 326; ocurrencias exactas = 1; SHA-256 `aeb4b46eca6261c77f2d42237eb4ca7396a89f76447a8a9b3a869f81e825209c`.

```text
class SddCoderEngine:
```

```python
# Initialize registry/supervisor using durable store and unique owner instance.
# run_chunk returns bg_handle alongside unchanged job_id; prepare_native
# registers pending handle, observations link only issued attempts.
# Map logical job completion from JobTable, never a fabricated POSIX code.
# Add bg_status/run_validation entry points with owner/execution validation.
# end_execution and cleanup reject admitted pending/running/unknown validations.
# Persist actual validation.finished receipts; never inject TaskResult fakes.
# Publish a durable settlement artifact outside the worktree only after gates pass.
# Preserve the existing close result; persistence_degraded is not checkpoint authority.
```

**Aplicación y motivo:** Añadir integración dentro del engine existente; preservar ownership, gates, routing y admisión. Revalidar anchor tras dependencias.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` (MODIFY)

Anchor verificado: línea 51; ocurrencias exactas = 1; SHA-256 `29775c383a1cd1b8b4abc91951b62a9205df7968ae712c4b913433a14436b609`.

```text
class SddCoderToolkit(AbstractToolkit):
```

```python
async def coder_bg_status(self, execution_id: str, handle: str,
                         since_revision: int | None = None, tail_bytes: int = 2048) -> CoderResult:
    """Read authoritative known background state without waiting for termination."""
    # FILL IN: strict schema -> owner validation -> registry snapshot -> _run.
    raise NotImplementedError

async def coder_run_validation(self, feature: str, worktree: str, execution_id: str,
                               task_ids: list[str], tier: Literal['merge', 'feature'],
                               timeout_seconds: int, request_id: str) -> CoderResult:
    """Admit only declared protected validation and return an opaque handle."""
    # FILL IN: strict schema -> execution admission -> supervisor.start -> _run.
    raise NotImplementedError
```

**Aplicación y motivo:** Registrar schema en arg_models, docstring LLM-facing y mapping vía _run. No registrar helpers internos como tools.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` (MODIFY)

Anchor verificado: línea 481; ocurrencias exactas = 1; SHA-256 `b459601f842150f19ddb8cd7d37c12ac81cf0a59cc77ccab612a1a532cc1a342`.

```text
class _Args(BaseModel):
```

```python
# Add CoderBgStatusArgs: execution UUID, opaque handle, since_revision>=0|null,
# tail_bytes0..4096=2048. Add CoderRunValidationArgs with required timeout1..7200,
# nonempty request_id, valid task_ids and Literal tier merge|feature.
# Add bg_handle to launch/preparation result models compatibly (optional default).
# Errors: background_not_found/background_scope_mismatch/background_source_unsupported/
# background_status_unavailable/validation_request_conflict/validation_scope_invalid.
```

**Aplicación y motivo:** Añadir argumentos estrictos y errores al conjunto ERROR_CODES; reutilizar validadores UUID/worktree/task. No ampliar schema accidentalmente de otros métodos.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py` (MODIFY)

Anchor verificado: línea 20; ocurrencias exactas = 1; SHA-256 `0f798a1f0d66a6489138c7cf203e03f440c4b99b3b89bac0ab63425a370a3e30`.

```text
EXPECTED_TOOLS = {
```

```python
# Extend the exact set with the tools from R8.
# Keep every existing tool and the strict equality assertion.
```

**Aplicación y motivo:** Cubrir descubrimiento real y validación previa de cada nuevo argumento; conservar tests existentes.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_mcp.py` (CREATE)

```python
"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""
import pytest
from pathlib import Path

def test_mcp_schema_and_issued_handles(tmp_path: Path) -> None:
    """Both tools are discoverable and handles come only from admitted launches."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_cleanup_and_end_execution_block_unknown(tmp_path: Path) -> None:
    """Pending, running and unknown validations block closure and cleanup."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_native_and_logical_authorities(tmp_path: Path) -> None:
    """Native handback remains observation; logical MCP jobs never invent an exit code."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError
```

**Aplicación y motivo:** Probar dos executions/worktrees, no race launch-vs-close, end después de reap, external unsupported y budgets por wire. Conservar reservas/gates existentes.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_mcp.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.

## Acceptance Criteria

- [ ] AC19–AC21: tool determinista, handle ownership, no shell/LLM/PID probing y sin duplicar tests.
- [ ] AC5/AC10: end/cleanup no pasan con unknown; native observations no liberan reservas.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_mcp.py -q`

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
