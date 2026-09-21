# TASK-3574: Reconstruir requests y spans por identidad

**Feature**: FEAT-584 — Optimización medible del flujo SDD y transición compactada a revisión
**Spec**: `sdd/specs/sdd-execution-optimization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3559, TASK-3565
**Assigned-to**: unassigned

## Context

Implementa M7 / R7 de la spec aprobada. Baseline de contratos: dev, commit 31f4c47afc72748a387ef8a8e55d0588894668e7.
La optimización conserva aceptación semántica, ownership, cobertura y evidencia explícita; los porcentajes del profiler no son ahorros garantizados.

## Scope

- Implementar profiler reproducible sobre fuentes explícitas, sin ejecutar scripts personales de profiling.
- Generar métricas de requests, bytes, spans y calidad de atribución sin causalidad asumida.

**NOT in scope**: cambiar roster/scheduler, relajar sandbox/checks, modificar clients/base.py, introducir dependencias o realizar cambios fuera de los targets. El adaptador específico de host queda diferido por Q1 salvo enmienda aprobada posterior.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/profile_execution.py` | CREATE | Eventos background usan launch/receipt reales; tool_result inmediato no termina span |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_profile.py` | CREATE | Construir fixtures sintéticos inline con eventos fuera de orden, poll solapado, receipts ausentes, signals/timeouts y fallback; nunca copiar transcripts privados. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Verificación estática de símbolos existentes por AST y lectura de fuentes; no presupone importación del framework. Los imports nuevos se distinguen abajo y requieren completar sus dependencias.

`from parrot.flows.dev_loop.sdd_coder.telemetry import CoderTelemetrySink` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py:251`.

`from parrot.flows.dev_loop.sdd_coder.jobs import JobTable` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py:96`.

Imports de blueprint (stdlib / dependencias instaladas / símbolos creados por esta tarea o sus predecesoras; **no** APIs existentes inventadas):

```python
from __future__ import annotations
from pathlib import Path
import pytest
```
Pydantic, pytest y Click ya están instalados/declarados; módulos optimization_models/evidence/checkpoint/inspection_models nuevos solo se importan después de sus tareas productoras. Verificar cualquier import adicional antes de introducirlo.

### Existing Signatures to Use

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py:251` · SHA-256 `20575cc03234d60d3e38fb110bd259545a4eb5fcbee6e66910b202279d6da33a`

```python
class CoderTelemetrySink:
```

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py:96` · SHA-256 `8e9a2198e2cce6a02017af7d3f8b57b0ab64dad5ba005604d092a478f40b519f`

```python
    async def wait(self, job_id: str, timeout_s: float) -> CoderJob:
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
      "path": "scripts/sdd/profile_execution.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_profile.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py#JobTable.wait",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py#CoderTelemetrySink"
  ]
}
```

## Implementation Notes

Async-first en MCP; I/O bloqueante fuera del event loop. CLI síncrono permitido. Pydantic v2, Black 120 y Ruff. Core no importa parrot_tools. Los blueprints contienen decisiones acotadas pendientes de implementación: no constituyen un Delegation Contract ni permiten entregar placeholders.

## Implementation Blueprint

### Steps (in order)

1. Normalizar identidad/reloj: no sumar duraciones monotónicas de procesos distintos.
2. Calcular union global y buckets independientes: mantener sumas explicables.
3. Ejercitar fixtures con resultados conocidos: detectar sesgos originales.

### `scripts/sdd/profile_execution.py` (CREATE)

```python
"""Offline versioned execution profiling with identity-aware interval unions."""
from __future__ import annotations
from pathlib import Path

def main(argv: list[str] | None = None) -> int:
    """Read explicit event/transcript paths and emit versioned aggregate JSON."""
    # FILL IN: parse --events/--transcript/--output explicit paths, no discovery
    # of private home sessions. Normalize sources/clocks, union globally,
    # deduplicate requestId and join attempts/merges by execution+attempt/task.
    # Preserve unknown/proxy/observed separately and long request spans.
    raise NotImplementedError

if __name__ == '__main__':
    raise SystemExit(main())
```

**Aplicación y motivo:** Eventos background usan launch/receipt reales; tool_result inmediato no termina span. Sumar input+cache_read+cache_creation coherentemente, tokens unknown=null. Separar idle heurístico de ausencia humana demostrada, fallback/autodesarrollo y defectos previos.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_profile.py` (CREATE)

```python
"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""
import pytest
from pathlib import Path

def test_global_union_and_request_dedup(tmp_path: Path) -> None:
    """Overlapping categories are unioned once globally and streamed messages share one request."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_background_and_merge_identity(tmp_path: Path) -> None:
    """Immediate tool results and unrelated later merges cannot shorten or misattribute attempts."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_unknown_tokens_long_requests_and_clock(tmp_path: Path) -> None:
    """Unknown values, long requests and cross-process clocks remain explicit."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError
```

**Aplicación y motivo:** Construir fixtures sintéticos inline con eventos fuera de orden, poll solapado, receipts ausentes, signals/timeouts y fallback; nunca copiar transcripts privados.

### FILL IN checklist

- [ ] `scripts/sdd/profile_execution.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_profile.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.

## Acceptance Criteria

- [ ] AC14/AC22: union global sin doble resta; correlación por identidad, requests no filas assistant.
- [ ] No excluir spans≥120s; latencia proxy se etiqueta y Bash desconocido no se clasifica como inspección.
- [ ] Informe distingue baseline posterior a fixes y tiempo de fallback/autodesarrollo.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_profile.py -q`

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
