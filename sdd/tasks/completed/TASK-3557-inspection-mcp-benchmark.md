# TASK-3557: Validar MCP real y concurrencia de inspección

**Feature**: FEAT-584 — Optimización medible del flujo SDD y transición compactada a revisión
**Spec**: `sdd/specs/sdd-execution-optimization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3556
**Assigned-to**: unassigned

## Context

Implementa M1 / M7 de la spec aprobada. Baseline de contratos: dev, commit 31f4c47afc72748a387ef8a8e55d0588894668e7.
La optimización conserva aceptación semántica, ownership, cobertura y evidencia explícita; los porcentajes del profiler no son ahorros garantizados.

## Scope

- Cubrir transporte MCP real, schema y latencia de ejecución separada de inferencia.
- No modificar runner o política para hacer pasar benchmarks; reportar regresiones al owner.

**NOT in scope**: cambiar roster/scheduler, relajar sandbox/checks, modificar clients/base.py, introducir dependencias o realizar cambios fuera de los targets. El adaptador específico de host queda diferido por Q1 salvo enmienda aprobada posterior.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/tool_optimizations/integration/test_inspection_mcp.py` | CREATE | Reutilizar tmp_repo_with_yaml/worker_env del conftest local, create_toolkit_mcp_server y JSON-RPC tools/list/call |
| `packages/ai-parrot-tools/tests/tool_optimizations/test_inspection_benchmark.py` | CREATE | Medir warmup y varias repeticiones con reloj monotónico; verificar misma salida, máximo cuatro activas y sum_item_ms separado de wall |
| `packages/ai-parrot-tools/tests/tool_optimizations/integration/test_stdio_protocol.py` | MODIFY | La aserción de inventario exacto ya existe; actualizarla para el nuevo método, sin aflojar igualdad. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Verificación estática de símbolos existentes por AST y lectura de fuentes; no presupone importación del framework. Los imports nuevos se distinguen abajo y requieren completar sus dependencias.

`from parrot_tools.tool_optimizations.reader import BoundedSourceToolkit` — verificado en `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/reader.py:326`.

`from parrot.mcp.toolkit_server import create_toolkit_mcp_server` — verificado en `packages/ai-parrot/src/parrot/mcp/toolkit_server.py:137`.

Imports de blueprint (stdlib / dependencias instaladas / símbolos creados por esta tarea o sus predecesoras; **no** APIs existentes inventadas):

```python
from pathlib import Path
import pytest
```
Pydantic, pytest y Click ya están instalados/declarados; módulos optimization_models/evidence/checkpoint/inspection_models nuevos solo se importan después de sus tareas productoras. Verificar cualquier import adicional antes de introducirlo.

### Existing Signatures to Use

`packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/reader.py:326` · SHA-256 `23792f2110fb1b719bda2d025ced7bcb0f2fa4e3a1797abf9dbd657329399f4a`

```python
class BoundedSourceToolkit(OptimizationToolkitBase):
```

`packages/ai-parrot/src/parrot/mcp/toolkit_server.py:137` · SHA-256 `64145c1f6a38634b3783b1eb154e4e9093e72c00c5b96fd2da8203d39e1ad936`

```python
def create_toolkit_mcp_server(
    name: str,
    root: Path = Path.cwd(),
    **overrides: Any,
) -> StdioMCPServer:
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
      "path": "packages/ai-parrot-tools/tests/tool_optimizations/integration/test_inspection_mcp.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/tool_optimizations/test_inspection_benchmark.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/tool_optimizations/integration/test_stdio_protocol.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/reader.py#BoundedSourceToolkit",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_server.py#create_toolkit_mcp_server"
  ]
}
```

## Implementation Notes

Async-first en MCP; I/O bloqueante fuera del event loop. CLI síncrono permitido. Pydantic v2, Black 120 y Ruff. Core no importa parrot_tools. Los blueprints contienen decisiones acotadas pendientes de implementación: no constituyen un Delegation Contract ni permiten entregar placeholders.

## Implementation Blueprint

### Steps (in order)

1. Extender inventario esperado: mantener compatibilidad comprobable.
2. Ejecutar JSON-RPC mixto y malformed: comprobar validación previa.
3. Medir 8×100ms controlados: demostrar solapamiento sin atribuir ahorro de flujo completo.

### `packages/ai-parrot-tools/tests/tool_optimizations/integration/test_inspection_mcp.py` (CREATE)

```python
"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""
import pytest
from pathlib import Path

def test_discovery_and_mixed_batch(tmp_path: Path) -> None:
    """Actual MCP discovery and calls expose source_inspect_batch without a model."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_raw_argument_rejection(tmp_path: Path) -> None:
    """Malformed raw JSON is rejected before filesystem or process effects."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError
```

**Aplicación y motivo:** Reutilizar tmp_repo_with_yaml/worker_env del conftest local, create_toolkit_mcp_server y JSON-RPC tools/list/call. Comprobar stdout de stdio, serialización y error parcial.

### `packages/ai-parrot-tools/tests/tool_optimizations/test_inspection_benchmark.py` (CREATE)

```python
"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""
import pytest
from pathlib import Path

def test_four_slots_overlap_equivalent_operations(tmp_path: Path) -> None:
    """Eight controlled 100ms I/O operations have p50 parallel/serial ratio at most 0.65."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError
```

**Aplicación y motivo:** Medir warmup y varias repeticiones con reloj monotónico; verificar misma salida, máximo cuatro activas y sum_item_ms separado de wall. Registrar runner y resultados en artifacts/logs; no exigir 4x sobre disco real.

### `packages/ai-parrot-tools/tests/tool_optimizations/integration/test_stdio_protocol.py` (MODIFY)

Anchor verificado: línea 13; ocurrencias exactas = 1; SHA-256 `9cf675349d43aa9312a3e61aaf69c1c4c52c8b09853f73cf0f4488d434fdbe12`.

```text
EXPECTED_TOOLS = {
```

```python
# Within EXPECTED_TOOLS["bounded-source"], add "source_inspect_batch".
# Preserve all existing discovery and stdio-only protocol checks.
```

**Aplicación y motivo:** La aserción de inventario exacto ya existe; actualizarla para el nuevo método, sin aflojar igualdad.

### FILL IN checklist

- [ ] `packages/ai-parrot-tools/tests/tool_optimizations/integration/test_inspection_mcp.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot-tools/tests/tool_optimizations/test_inspection_benchmark.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot-tools/tests/tool_optimizations/integration/test_stdio_protocol.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.

## Acceptance Criteria

- [ ] AC1/AC3/AC15/AC16: MCP descubre y ejecuta lote; ningún LLM se inicializa.
- [ ] Benchmark controlado cumple ratio ≤0,65 y límite4; salida serial/concurrente equivalente.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/tool_optimizations/integration/test_inspection_mcp.py -q`
- `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_inspection_benchmark.py -q`
- `pytest packages/ai-parrot-tools/tests/tool_optimizations/integration/test_stdio_protocol.py -q`

## Test Specification

Los escenarios en los blueprints son el mínimo verificable. Usar repos/procesos sintéticos aislados, fallos de persistencia y assertions sobre resultados observables; no servicios de proveedor en suite offline. Guardar logs en artifacts/logs/. Los tests live se ejecutan aparte y nunca se presentan como pasados por una simulación.

## Agent Instructions

1. Leer `sdd/specs/sdd-execution-optimization.spec.md` y comprobar dependencias en `sdd/tasks/index/sdd-execution-optimization.json`; no usar índice monolítico.
2. Revalidar imports/anchors y convenios antes de editar. Preservar cambios de otras tareas y del usuario.
3. Implementar solo targets, completar blueprints y ejecutar Validation Commands. No rebajar ACs para cerrar la tarea.
4. Registrar evidencia y revisión; usar el flujo SDD para actualizar estado, mover active→completed y commit acotado.
5. Si falta una API o scope, registrar bloqueo/diseño pendiente; no inventar contratos ni declarar done sin evidencia.

## Completion Note

Completed 2026-09-21 by native sonnet coder (attempt `5f6447a05b5441159c2e977788108651`). Read
TASK-3556's delivered `inspection.py`/`inspection_models.py` first. Created only the two
CREATE targets:

- `packages/ai-parrot-tools/tests/tool_optimizations/integration/test_inspection_mcp.py`
  — real stdio JSON-RPC subprocess discovery + a 4-item mixed batch (ok/ok/not_found/git_status)
  asserting stdout purity, `isError` False, per-item identity preservation, `partial`/`consistent`
  flags; plus an in-process raw-argument-rejection test (six malformed shapes) using
  `create_toolkit_mcp_server`.
- `packages/ai-parrot-tools/tests/tool_optimizations/test_inspection_benchmark.py` — times 8
  items at concurrency=4 vs concurrency=1 via a controlled monkeypatched sleep (never real disk
  timing), asserting the 2 to 4 overlap band, identical outputs, and a p50 ratio bound; evidence
  written to `artifacts/logs/` (gitignored).

The MODIFY target (`test_stdio_protocol.py`) was already updated correctly by TASK-3556's own
follow-up fix commit (`86f742a5f`); verified the anchor content and left it untouched per
instructions not to restore a stale hash.

Flagged (not fixed, pre-existing, out of scope): mixing test files across
`tool_optimizations/` root and `tool_optimizations/integration/` in a single `pytest a b c`
invocation can drop the `tmp_repo_with_yaml` fixture for the last integration file in
argument order. Reproduced on baseline files alone (`test_inspection.py` +
`test_raw_mcp_validation.py` + `test_stdio_protocol.py`, none touched by this task) — a
pre-existing conftest/rootdir collection quirk, not introduced here. The task's own
Validation Commands run each file separately, which is what was run.

Validation:
- `pytest packages/ai-parrot-tools/tests/tool_optimizations/integration/test_inspection_mcp.py -q` → 2 passed.
- `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_inspection_benchmark.py -q` → 1 passed.
- `pytest packages/ai-parrot-tools/tests/tool_optimizations/integration/test_stdio_protocol.py -q` → 6 passed.
- `select_tests --tier merge` scoped to completed tasks (TASK-3555, TASK-3556, TASK-3557) → 433 passed, 1 deselected, plus 17 passed.
- `git status --porcelain --untracked-files=all` clean except gitignored `artifacts/logs/`.

Review: `coder-review:35bf067c1681b2cdc7d1251e` (zero fix commits — clean delivery).

Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: 718699ms (~12m) · Tokens: 189535 (subagent total, in/out split not exposed for native).
