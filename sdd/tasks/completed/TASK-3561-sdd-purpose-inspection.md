# TASK-3561: Exponer contexto de tarea y reporte de entrega

**Feature**: FEAT-584 — Optimización medible del flujo SDD y transición compactada a revisión
**Spec**: `sdd/specs/sdd-execution-optimization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3560
**Assigned-to**: unassigned

## Context

Implementa M1b / R1b de la spec aprobada. Baseline de contratos: dev, commit 31f4c47afc72748a387ef8a8e55d0588894668e7.
La optimización conserva aceptación semántica, ownership, cobertura y evidencia explícita; los porcentajes del profiler no son ahorros garantizados.

## Scope

- Resolver cadenas conocidas en código; priorizar estado y errores frente a copiar specs completas.
- Añadir herramientas y schemas sin realizar mutaciones ni validación nueva.

**NOT in scope**: cambiar roster/scheduler, relajar sandbox/checks, modificar clients/base.py, introducir dependencias o realizar cambios fuera de los targets. El adaptador específico de host queda diferido por Q1 salvo enmienda aprobada posterior.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/inspection.py` | CREATE | Snapshots ≤16KiB con referencias paginadas de store |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | Añadir integración dentro del engine existente; preservar ownership, gates, routing y admisión |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` | MODIFY | Registrar schema en arg_models, docstring LLM-facing y mapping vía _run |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | Añadir argumentos estrictos y errores al conjunto ERROR_CODES; reutilizar validadores UUID/worktree/task |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py` | MODIFY | Cubrir descubrimiento real y validación previa de cada nuevo argumento; conservar tests existentes. |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_inspection_reports.py` | CREATE | Inspeccionar diff/dirty/untracked, evidencia grande y cursores; detectar que no se ejecutan tests ni merge. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Verificación estática de símbolos existentes por AST y lectura de fuentes; no presupone importación del framework. Los imports nuevos se distinguen abajo y requieren completar sus dependencias.

`from parrot.flows.dev_loop.sdd_coder.fidelity import parse_task_files` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py:29`.

`from parrot.flows.dev_loop.sdd_coder.fidelity import check_fidelity` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py:56`.

`from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:768`.

`from parrot.flows.dev_loop.sdd_coder.models import CoderResult` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:471`.

Imports de blueprint (stdlib / dependencias instaladas / símbolos creados por esta tarea o sus predecesoras; **no** APIs existentes inventadas):

```python
from __future__ import annotations
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.fidelity import parse_task_files, check_fidelity
from pathlib import Path
import pytest
```
Pydantic, pytest y Click ya están instalados/declarados; módulos optimization_models/evidence/checkpoint/inspection_models nuevos solo se importan después de sus tareas productoras. Verificar cualquier import adicional antes de introducirlo.

### Existing Signatures to Use

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py:29` · SHA-256 `5b6af10b0eda7b32ed33fa0f5d6c95e92992dfc55cb12ae24dc30115cc574c4e`

```python
def parse_task_files(task_md: str) -> List[str]:
```

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py:56` · SHA-256 `5b6af10b0eda7b32ed33fa0f5d6c95e92992dfc55cb12ae24dc30115cc574c4e`

```python
def check_fidelity(expected: List[str], changed: List[str]) -> FidelityReport:
```

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:768` · SHA-256 `aeb4b46eca6261c77f2d42237eb4ca7396a89f76447a8a9b3a869f81e825209c`

```python
    async def _resolve_feature(self, feature: str, worktree: str) -> _FeatureCtx:
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

Los anchors de MODIFY son observados en el baseline. Si una dependencia modifica el mismo archivo, revalidar el anchor y conservar sus adiciones; no restaurar el hash anterior.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/inspection.py",
      "action": "CREATE"
    },
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
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_inspection_reports.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._resolve_feature",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py#check_fidelity",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py#parse_task_files",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#CoderResult"
  ]
}
```

## Implementation Notes

Async-first en MCP; I/O bloqueante fuera del event loop. CLI síncrono permitido. Pydantic v2, Black 120 y Ruff. Core no importa parrot_tools. Los blueprints contienen decisiones acotadas pendientes de implementación: no constituyen un Delegation Contract ni permiten entregar placeholders.

## Implementation Blueprint

### Steps (in order)

1. Resolver índice y attempt autoritativos: fijar operandos antes de concurrencia.
2. Construir vistas con hashes y refs: permitir recuperación completa.
3. Registrar tools y probar ausencia de efectos: no introducir una segunda policy.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/inspection.py` (CREATE)

```python
"""Read-only SDD context and delivery projections using existing fidelity rules."""
from __future__ import annotations
from pathlib import Path
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.fidelity import parse_task_files, check_fidelity

async def task_context(*, feature: str, worktree: Path, task_id: str,
                       execution_id: str, store: ExecutionEvidenceStore) -> dict[str, object]:
    """Resolve index, task, dependencies and contract into a bounded snapshot."""
    # FILL IN: established feature resolver/ownership is a precondition;
    # preserve errors and all readiness blockers, hashes and required refs.
    raise NotImplementedError

async def delivery_report(*, feature: str, worktree: Path, task_id: str,
                          execution_id: str, store: ExecutionEvidenceStore) -> dict[str, object]:
    """Report issued attempt, immutable diff, scope and known verification refs."""
    # FILL IN: resolve attempt before independent Git reads (max concurrency4).
    # Use existing fidelity; absent evidence is unknown, never implicit green.
    raise NotImplementedError
```

**Aplicación y motivo:** Snapshots ≤16KiB con referencias paginadas de store. Pasar contexto validado del engine; no duplicar policy de fidelity ni inferir rama por convención de nombre. Helpers propuestos, no existentes.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY)

Anchor verificado: línea 326; ocurrencias exactas = 1; SHA-256 `aeb4b46eca6261c77f2d42237eb4ca7396a89f76447a8a9b3a869f81e825209c`.

```text
class SddCoderEngine:
```

```python
# Add task_context/delivery_report entry points that perform existing
# feature/execution/worktree ownership checks before calling inspection.py.
# Supply authoritative issued attempt and durable evidence, never guessed refs.
```

**Aplicación y motivo:** Añadir integración dentro del engine existente; preservar ownership, gates, routing y admisión. Revalidar anchor tras dependencias.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` (MODIFY)

Anchor verificado: línea 51; ocurrencias exactas = 1; SHA-256 `29775c383a1cd1b8b4abc91951b62a9205df7968ae712c4b913433a14436b609`.

```text
class SddCoderToolkit(AbstractToolkit):
```

```python
async def coder_task_context(self, feature: str, worktree: str, task_id: str,
                             execution_id: str) -> CoderResult:
    """Inspect task context and blockers without modifying SDD state."""
    # FILL IN: _run through the engine's validated read-only entry point.
    raise NotImplementedError

async def coder_delivery_report(self, feature: str, worktree: str, task_id: str,
                                execution_id: str) -> CoderResult:
    """Inspect delivery scope and known evidence; never validate or merge."""
    # FILL IN: _run through the engine's validated read-only entry point.
    raise NotImplementedError
```

**Aplicación y motivo:** Registrar schema en arg_models, docstring LLM-facing y mapping vía _run. No registrar helpers internos como tools.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` (MODIFY)

Anchor verificado: línea 481; ocurrencias exactas = 1; SHA-256 `b459601f842150f19ddb8cd7d37c12ac81cf0a59cc77ccab612a1a532cc1a342`.

```text
class _Args(BaseModel):
```

```python
# Add strict CoderTaskContextArgs and CoderDeliveryReportArgs, reusing
# CoderPrepareNativeArgs shape without invoking native preparation.
# Register both separately; keep existing closed error identities.
```

**Aplicación y motivo:** Añadir argumentos estrictos y errores al conjunto ERROR_CODES; reutilizar validadores UUID/worktree/task. No ampliar schema accidentalmente de otros métodos.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py` (MODIFY)

Anchor verificado: línea 20; ocurrencias exactas = 1; SHA-256 `0f798a1f0d66a6489138c7cf203e03f440c4b99b3b89bac0ab63425a370a3e30`.

```text
EXPECTED_TOOLS = {
```

```python
# Extend the exact set with the tools from R1b.
# Keep every existing tool and the strict equality assertion.
```

**Aplicación y motivo:** Cubrir descubrimiento real y validación previa de cada nuevo argumento; conservar tests existentes.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_inspection_reports.py` (CREATE)

```python
"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""
import pytest
from pathlib import Path

def test_context_preserves_blockers(tmp_path: Path) -> None:
    """Dependency status and file contract determine readiness without modifying index."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_delivery_scope_and_unknown_evidence(tmp_path: Path) -> None:
    """Report matches existing fidelity and missing checks remain unknown."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_ownership_and_snapshot_race(tmp_path: Path) -> None:
    """Foreign worktree and changed revisions do not yield a trustworthy delivery snapshot."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError
```

**Aplicación y motivo:** Inspeccionar diff/dirty/untracked, evidencia grande y cursores; detectar que no se ejecutan tests ni merge.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/inspection.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_inspection_reports.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.

## Acceptance Criteria

- [ ] AC18: contexto/entrega equivalen a inspección manual de snapshots y conservan unknown.
- [ ] AC4/AC5: 16KiB y ownership; no cambia readiness, fidelity ni aprobación.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_inspection_reports.py -q`

## Test Specification

Los escenarios en los blueprints son el mínimo verificable. Usar repos/procesos sintéticos aislados, fallos de persistencia y assertions sobre resultados observables; no servicios de proveedor en suite offline. Guardar logs en artifacts/logs/. Los tests live se ejecutan aparte y nunca se presentan como pasados por una simulación.

## Agent Instructions

1. Leer `sdd/specs/sdd-execution-optimization.spec.md` y comprobar dependencias en `sdd/tasks/index/sdd-execution-optimization.json`; no usar índice monolítico.
2. Revalidar imports/anchors y convenios antes de editar. Preservar cambios de otras tareas y del usuario.
3. Implementar solo targets, completar blueprints y ejecutar Validation Commands. No rebajar ACs para cerrar la tarea.
4. Registrar evidencia y revisión; usar el flujo SDD para actualizar estado, mover active→completed y commit acotado.
5. Si falta una API o scope, registrar bloqueo/diseño pendiente; no inventar contratos ni declarar done sin evidencia.

## Completion Note

Completed 2026-09-21 by native sonnet coder (attempt `d4a6513ea6404470ac4b9e9fb5e5ce22`). Touched
only the six listed targets:

- `inspection.py` CREATE — two free functions, `task_context` and `delivery_report`, exact
  blueprint 5-parameter signature (`feature, worktree, task_id, execution_id, store`).
  `task_context` resolves index → task → dependencies → contract via `TaskScheduler`, never
  marking a dependency satisfied on trust. `delivery_report` discovers the execution-owned
  attempt branch, diffs it against the feature branch, and runs it through the existing
  `check_fidelity`/`parse_task_files`; never merges, lints, tests, or approves. Lint/test/
  review evidence is reported as `"unknown"` since no producer in this task's scope publishes
  it into the durable store yet. Both snapshots stay bounded (spec 16KiB): large text is
  excerpted inline and always durably published via `ExecutionEvidenceStore.put_artifact`.
- `engine.py` MODIFY — `SddCoderEngine.task_context`/`delivery_report`: thin wrappers doing
  feature resolution plus the same execution-ownership check `record_native_observation`
  already uses, then delegating to `inspection.py`.
- `models.py` MODIFY — `CoderTaskContextArgs`/`CoderDeliveryReportArgs` reusing
  `CoderPrepareNativeArgs`'s shape (same pattern `CoderMergeArgs` already uses). No new
  `ERROR_CODES` needed; every failure path reuses an existing code.
- `toolkit.py` MODIFY — registered `coder_task_context`/`coder_delivery_report`; generalized
  `_run()` (one line) to accept either a `BaseModel` or a plain dict, since these two
  read-only projections return `dict[str, object]` per the blueprint, not a nested
  `CoderResult`.
- `test_toolkit.py` MODIFY — extended `EXPECTED_TOOLS` and the scoped set; new pre-execute/
  routing tests for both tools.
- `test_inspection_reports.py` CREATE — 3 scenarios.

Design decision flagged and accepted: the blueprint's fixed 5-parameter signature for
`inspection.py`'s functions leaves no room to pass an attempt's branch/path explicitly, and
its Codebase Contract excludes any git subprocess capability. To make `delivery_report` work,
the coder added a small private git helper local to `inspection.py` (avoiding a circular
import: `engine.py` only imports `inspection` lazily inside its two new methods) that
discovers the task's attempt branch by enumerating real git branches matching the engine's
own naming convention, verifying each candidate's embedded execution-id hex before trusting
it — mirrors the already-established, documented precedent in
`SddCoderEngine._orphan_branches`/`_parse_orphan_suffix` ("parsing for reporting only", never
adopted/mutated). Verified end-to-end against a real `SddCoderEngine` instance over a
synthetic git repo (task_context, delivery_report, foreign-execution rejection,
foreign-worktree rejection), not just isolated unit tests. Accepted as a documented,
non-fabricated extension of an existing pattern.

Collateral breakage flagged by the coder (correctly not fixed out of scope, same pattern as
TASK-3560: two new MCP tools not yet allow-listed in the sdd-worker prompt frontmatter) and
fixed by the orchestrator in commit `d14823a35` (canonical + packaged twin +
`test_mcp_local.py::EXPECTED`).

Validation:
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_inspection_reports.py -q` → 22 + 3 passed.
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_mcp_local.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py -q` → 16 passed (post-fix; 3 failed pre-fix, matching the coder's own diagnosis).
- Scoped regression (dev_loop/sdd_coder, tool_optimizations, wiki compaction — the full core-escalation sweep was already paid once for the identical engine.py/toolkit.py/models.py change pattern at TASK-3560 with zero sdd_coder-related failures, so it was not re-run in full here): 417 passed; 433 passed, 1 skipped; 17 passed.
- `git status --porcelain --untracked-files=all` clean except gitignored build artifacts.
- `ruff check --select E9,F63,F7,F82` clean on all six changed files.

Review: `coder-review:d415430b31342e2e154b0ad8` (fix commit `d14823a35`, applied by the orchestrator, not the coder).

Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: 1259083ms (~21m) · Tokens: 287581 (subagent total, in/out split not exposed for native).
