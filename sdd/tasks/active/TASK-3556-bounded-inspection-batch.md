# TASK-3556: Implementar lote de inspección read-only concurrente

**Feature**: FEAT-584 — Optimización medible del flujo SDD y transición compactada a revisión
**Spec**: `sdd/specs/sdd-execution-optimization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implementa M1 / R1 de la spec aprobada. Baseline de contratos: dev, commit 31f4c47afc72748a387ef8a8e55d0588894668e7.
La optimización conserva aceptación semántica, ownership, cobertura y evidencia explícita; los porcentajes del profiler no son ahorros garantizados.

## Scope

- Implementar los seis kinds de R1 con error por ítem, orden estable y cursores verificables.
- Preservar registros de error y metadata incluso con truncación; no concatenar shell ni invocar LLM.
- Probar límites globales compartidos entre llamadas y cancelación de procesos propios.

**NOT in scope**: cambiar roster/scheduler, relajar sandbox/checks, modificar clients/base.py, introducir dependencias o realizar cambios fuera de los targets. El adaptador específico de host queda diferido por Q1 salvo enmienda aprobada posterior.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/inspection_models.py` | CREATE | Completar tipos antes del runner |
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/inspection.py` | CREATE | Reader/runner forman una unidad según §7 |
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/reader.py` | MODIFY | Añadir método a clase, schema estricto y registro sin modificar semántica de source_info/read |
| `packages/ai-parrot-tools/tests/tool_optimizations/test_inspection.py` | CREATE | Añadir casos secretos, traversal, symlinks, SHA/range obsoletos, regex tratado literalmente, args extra, duplicados, cancelación y reap. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Verificación estática de símbolos existentes por AST y lectura de fuentes; no presupone importación del framework. Los imports nuevos se distinguen abajo y requieren completar sus dependencias.

`from parrot_tools.tool_optimizations.reader import BoundedSourceToolkit` — verificado en `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/reader.py:443`.

`from parrot_tools.tool_optimizations.base import OptimizationToolkitBase` — verificado en `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/base.py:83`.

`from parrot_tools.tool_optimizations.policy import fit_to_budget` — verificado en `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/policy.py:162`.

`from parrot.tools.decorators import tool_schema` — verificado en `packages/ai-parrot/src/parrot/tools/decorators.py:39`.

`from parrot_tools.tool_optimizations.models import OperationResult` — verificado en `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/models.py:123`.

Imports de blueprint (stdlib / dependencias instaladas / símbolos creados por esta tarea o sus predecesoras; **no** APIs existentes inventadas):

```python
from __future__ import annotations
from parrot_tools.tool_optimizations.inspection_models import InspectionBatchArgs
from parrot_tools.tool_optimizations.models import OperationResult
from parrot_tools.tool_optimizations.reader import BoundedSourceToolkit
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Annotated, Literal
from typing import TYPE_CHECKING
import asyncio
import pytest
```
Pydantic, pytest y Click ya están instalados/declarados; módulos optimization_models/evidence/checkpoint/inspection_models nuevos solo se importan después de sus tareas productoras. Verificar cualquier import adicional antes de introducirlo.

### Existing Signatures to Use

`packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/reader.py:443` · SHA-256 `23792f2110fb1b719bda2d025ced7bcb0f2fa4e3a1797abf9dbd657329399f4a`

```python
    async def source_read(
        self,
        path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        expected_sha256: Optional[str] = None,
    ) -> SourceResult | OperationResult:
```

`packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/reader.py:341` · SHA-256 `23792f2110fb1b719bda2d025ced7bcb0f2fa4e3a1797abf9dbd657329399f4a`

```python
    def _resolve(self, path: str) -> tuple[Path, str]:
```

`packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/base.py:83` · SHA-256 `ae713d9540fb701fe98138226bb4f97429b7dd89af7f77c381ac8b289fb94db9`

```python
    async def _pre_execute(self, tool_name: str, /, **kwargs: Any) -> None:
```

`packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/policy.py:162` · SHA-256 `6375a613cacbd4c81aa6b0ca1c75d1e0f126c38c934464cbad3103947c9fbd82`

```python
def fit_to_budget(result: OperationResult, budget: int) -> OperationResult:
```

`packages/ai-parrot/src/parrot/tools/decorators.py:39` · SHA-256 `86e1d2aa178d37b651dc09f197aac693c297f51b06aabaded6662f146af1649e`

```python
def tool_schema(schema: Type[BaseModel], description: Optional[str] = None):
```

`packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/models.py:123` · SHA-256 `7f8f5b06b2f9551d8d98066500300af21b8a5c7a1624d48bb9d52efc1b4bdd61`

```python
class OperationResult(_StrictModel):
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
      "path": "packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/inspection_models.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/inspection.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/reader.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/tool_optimizations/test_inspection.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/base.py#OptimizationToolkitBase._pre_execute",
    "sym:packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/models.py#OperationResult",
    "sym:packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/policy.py#fit_to_budget",
    "sym:packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/reader.py#BoundedSourceToolkit._resolve",
    "sym:packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/reader.py#BoundedSourceToolkit.source_read",
    "sym:packages/ai-parrot/src/parrot/tools/decorators.py#tool_schema"
  ]
}
```

## Implementation Notes

Async-first en MCP; I/O bloqueante fuera del event loop. CLI síncrono permitido. Pydantic v2, Black 120 y Ruff. Core no importa parrot_tools. Los blueprints contienen decisiones acotadas pendientes de implementación: no constituyen un Delegation Contract ni permiten entregar placeholders.

## Implementation Blueprint

### Steps (in order)

1. Definir modelos discriminados: rechazar inputs antes de I/O.
2. Implementar runner y registrar una instancia persistente: limitar concurrencia entre lotes.
3. Ejercitar equivalencia, fallos y presupuesto serializado: comprobar el resultado observable.

### `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/inspection_models.py` (CREATE)

```python
"""Strict discriminated contracts for bounded independent inspections."""
from __future__ import annotations
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class InspectionModel(BaseModel):
    """Reject undeclared arguments before effects."""
    model_config = ConfigDict(extra="forbid")

class ReadRequest(InspectionModel):
    """Read a bounded revision-checked line range."""
    id: str = Field(min_length=1)
    kind: Literal['read']
    path: str
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    expected_sha256: str | None = None

class InfoRequest(InspectionModel):
    """Inspect metadata without returning unbounded source."""
    id: str = Field(min_length=1)
    kind: Literal['info']
    path: str

class SearchRequest(InspectionModel):
    """Search literal text in confined paths."""
    id: str = Field(min_length=1)
    kind: Literal['search']
    paths: list[str] = Field(min_length=1, max_length=8)
    text: str = Field(min_length=1, max_length=1024)
    max_matches: int = Field(default=20, ge=1, le=100)
    continuation: str | None = None

class FilesRequest(InspectionModel):
    """List bounded repository-relative paths under validated roots."""
    id: str = Field(min_length=1)
    kind: Literal['files']
    paths: list[str] = Field(default_factory=lambda: ['.'], min_length=1, max_length=8)
    continuation: str | None = None

class GitStatusRequest(InspectionModel):
    """Read status without index refresh or writes."""
    id: str = Field(min_length=1)
    kind: Literal['git_status']

class GitDiffNamesRequest(InspectionModel):
    """Compare immutable full Git commit ids."""
    id: str = Field(min_length=1)
    kind: Literal['git_diff_names']
    base_sha: str
    head_sha: str

InspectionRequest = Annotated[
    ReadRequest | InfoRequest | SearchRequest | FilesRequest | GitStatusRequest | GitDiffNamesRequest,
    Field(discriminator='kind'),
]

class InspectionBatchArgs(InspectionModel):
    """Bound batch cardinality, admission and response size."""
    requests: list[InspectionRequest] = Field(min_length=1, max_length=8)
    concurrency: int = Field(default=4, ge=1, le=4)
    max_output_bytes: int = Field(default=24576, ge=4096, le=24576)
    # FILL IN: duplicate-id and request cross-field validators before any I/O.

class InspectionItem(InspectionModel):
    """One stable item result even when peers fail."""
    id: str
    kind: str
    status: Literal['ok', 'error', 'cancelled']
    data: dict[str, object] = Field(default_factory=dict)
    error_code: str | None = None
    elapsed_ms: int = Field(ge=0)
    truncated: bool = False
    continuation: str | None = None
```

Continuación del mismo archivo:

```python

class InspectionBatch(InspectionModel):
    """Ordered response with snapshot consistency and measured byte cost."""
    schema_version: Literal[1] = 1
    items: list[InspectionItem]
    partial: bool
    consistent: bool
    head_before: str | None
    head_after: str | None
    elapsed_ms: int = Field(ge=0)
    sum_item_ms: int = Field(ge=0)
    returned_bytes: int = Field(ge=0)
# FILL IN: full-SHA/range/path/cursor constraints from R1 and existing reader.
```

**Aplicación y motivo:** Completar tipos antes del runner. Reutilizar límites de rangos de SourceReadArgs; limitar texto, paths, matches y cursores. Validar todas las variantes sin ejecutar I/O.

### `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/inspection.py` (CREATE)

```python
"""Bounded read-only inspection with an instance-wide admission limit."""
from __future__ import annotations
import asyncio
from typing import TYPE_CHECKING
from parrot_tools.tool_optimizations.inspection_models import InspectionBatchArgs
from parrot_tools.tool_optimizations.models import OperationResult
if TYPE_CHECKING:
    from parrot_tools.tool_optimizations.reader import BoundedSourceToolkit

class InspectionRunner:
    """Execute independent operations without a shell or model call."""
    def __init__(self, reader: BoundedSourceToolkit) -> None:
        self.reader = reader
        self._slots = asyncio.Semaphore(4)

    async def run(self, args: InspectionBatchArgs) -> OperationResult:
        """Return ordered items, individual failures and bounded continuations."""
        # FILL IN: use global slots plus per-batch concurrency; 10s per item,
        # 20s per batch, cancellation and reap for fixed-argv subprocesses.
        # Reuse reader policy for all paths, including discovered matches.
        # Return head/hash revisions; mixed observations set consistent=false.
        # Budget serialized UTF-8: 2KiB/item and 24KiB whole envelope.
        raise NotImplementedError
```

**Aplicación y motivo:** Reader/runner forman una unidad según §7. Implementar read/info mediante reader; search/files con paths confinados y resultados deterministas; Git con argv fijo, SHA completo, sin shell ni external diff. Mantener un runner por instancia, no un semáforo por llamada.

### `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/reader.py` (MODIFY)

Anchor verificado: línea 326; ocurrencias exactas = 1; SHA-256 `23792f2110fb1b719bda2d025ced7bcb0f2fa4e3a1797abf9dbd657329399f4a`.

```text
class BoundedSourceToolkit(OptimizationToolkitBase):
```

```python
# Import InspectionBatchArgs; register source_inspect_batch in arg_models.
# Instantiate/cache one InspectionRunner for this toolkit instance.
@tool_schema(InspectionBatchArgs)
async def source_inspect_batch(
    self, requests: list[dict[str, object]], concurrency: int = 4,
    max_output_bytes: int = 24576,
) -> OperationResult:
    """Inspect independent read-only operations with bounded concurrency."""
    # FILL IN: validate model, call the persistent runner; preserve source_read.
    raise NotImplementedError
```

**Aplicación y motivo:** Añadir método a clase, schema estricto y registro sin modificar semántica de source_info/read. Evitar import cycle: runner importa reader solo TYPE_CHECKING.

### `packages/ai-parrot-tools/tests/tool_optimizations/test_inspection.py` (CREATE)

```python
"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""
import pytest
from pathlib import Path

def test_path_policy_and_equivalence(tmp_path: Path) -> None:
    """All six operations obey policy and match individual read-only results."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_global_concurrency_and_partial_deadlines(tmp_path: Path) -> None:
    """Two batches share four slots and retain every item identity on failure."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_utf8_budget_and_stale_snapshot(tmp_path: Path) -> None:
    """Large Unicode output is bounded and changed files invalidate consistency."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError
```

**Aplicación y motivo:** Añadir casos secretos, traversal, symlinks, SHA/range obsoletos, regex tratado literalmente, args extra, duplicados, cancelación y reap.

### FILL IN checklist

- [ ] `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/inspection_models.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/inspection.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/reader.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot-tools/tests/tool_optimizations/test_inspection.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.

## Acceptance Criteria

- [ ] AC1–AC4: 1–8 operaciones, concurrency 1–4, 10s/ítem, 20s/lote; sin procesos huérfanos.
- [ ] AC2: secretos/symlinks/rutas y snapshots aplican también a search/files; consistent no afirma transacción.
- [ ] OperationResult completo respeta 24576 bytes; error/truncation/continuation nunca desaparecen.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_inspection.py -q`
- `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_reader.py -q`

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
