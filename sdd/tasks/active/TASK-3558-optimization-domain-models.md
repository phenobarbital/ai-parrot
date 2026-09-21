# TASK-3558: Definir modelos estrictos de evidencia y background

**Feature**: FEAT-584 — Optimización medible del flujo SDD y transición compactada a revisión
**Spec**: `sdd/specs/sdd-execution-optimization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implementa M2 / M4 / M5 / M8 de la spec aprobada. Baseline de contratos: dev, commit 31f4c47afc72748a387ef8a8e55d0588894668e7.
La optimización conserva aceptación semántica, ownership, cobertura y evidencia explícita; los porcentajes del profiler no son ahorros garantizados.

## Scope

- Crear contratos Pydantic v2 extra=forbid indicados en spec, sin I/O ni import desde parrot_tools.
- Documentar representación canónica y validadores reutilizables de identity/state; no cambiar modelos existentes.

**NOT in scope**: cambiar roster/scheduler, relajar sandbox/checks, modificar clients/base.py, introducir dependencias o realizar cambios fuera de los targets. El adaptador específico de host queda diferido por Q1 salvo enmienda aprobada posterior.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py` | CREATE | Definir todos los modelos compartidos una vez |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_models.py` | CREATE | Cubrir todos los modelos y estados R8; códigos negativos preservados y 124 no implica timed_out. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Verificación estática de símbolos existentes por AST y lectura de fuentes; no presupone importación del framework. Los imports nuevos se distinguen abajo y requieren completar sus dependencias.

`from parrot.flows.dev_loop.sdd_coder.models import CoderResult` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:471`.

`from parrot.flows.dev_loop.sdd_coder.models import ExecutionSnapshot` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:426`.

Imports de blueprint (stdlib / dependencias instaladas / símbolos creados por esta tarea o sus predecesoras; **no** APIs existentes inventadas):

```python
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal
import pytest
```
Pydantic, pytest y Click ya están instalados/declarados; módulos optimization_models/evidence/checkpoint/inspection_models nuevos solo se importan después de sus tareas productoras. Verificar cualquier import adicional antes de introducirlo.

### Existing Signatures to Use

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:471` · SHA-256 `b459601f842150f19ddb8cd7d37c12ac81cf0a59cc77ccab612a1a532cc1a342`

```python
class CoderResult(BaseModel):
```

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:426` · SHA-256 `b459601f842150f19ddb8cd7d37c12ac81cf0a59cc77ccab612a1a532cc1a342`

```python
class ExecutionSnapshot(BaseModel):
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
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_models.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#CoderResult",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#ExecutionSnapshot"
  ]
}
```

## Implementation Notes

Async-first en MCP; I/O bloqueante fuera del event loop. CLI síncrono permitido. Pydantic v2, Black 120 y Ruff. Core no importa parrot_tools. Los blueprints contienen decisiones acotadas pendientes de implementación: no constituyen un Delegation Contract ni permiten entregar placeholders.

## Implementation Blueprint

### Steps (in order)

1. Definir identidades y refs: evitar strings libres interpretados como paths.
2. Completar modelos de cada dominio: compartir un contrato entre persistencia y tools.
3. Probar serialización/validación de fronteras: impedir evidencia falsa.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py` (CREATE)

```python
"""Versioned evidence, checkpoint, compaction and background contracts."""
from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class OptimizationModel(BaseModel):
    """Reject extra keys; never manufacture unknown measurements."""
    model_config = ConfigDict(extra='forbid')

class EvidenceRef(OptimizationModel):
    """Resolve content-addressed references only under durable storage."""
    artifact_id: str
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    relative_path: str
    size_bytes: int = Field(ge=0)
    media_type: str

class WorkflowEvent(OptimizationModel):
    """One bounded event with explicit source and clock provenance."""
    schema_version: Literal[1] = 1
    event_id: str
    kind: str
    execution_id: str
    task_id: str | None = None
    attempt_uid: str | None = None
    job_id: str | None = None
    timestamp: datetime
    source: Literal['engine', 'worker_observation', 'transcript_import']
    payload: dict[str, object] = Field(default_factory=dict)
    # FILL IN: bound payload and validate per-kind identity; no prompts/secrets.

class TaskCompletionEvidence(OptimizationModel):
    """Green checks and semantic review tied to one implementation revision."""
    feature_slug: str
    task_id: str
    implementation_sha: str
    validation_refs: list[EvidenceRef]
    review_evidence: EvidenceRef
    fix_commits: list[str] = Field(default_factory=list)
    completion_facts: dict[str, object]

class ReviewCheckpoint(OptimizationModel):
    """Neutral continuation identity, criteria, constraints and evidence."""
    schema_version: Literal[1] = 1
    checkpoint_id: str
    feature: str
    execution_id: str
    worktree: str
    branch: str
    base_sha: str
    implementation_head: str
    spec_hash: str
    index_hash: str
    convention_hashes: dict[str, str]
    task_refs: list[EvidenceRef]
    criteria_refs: list[EvidenceRef]
    commits: list[str]
    validation_refs: list[EvidenceRef]
    evidence_refs: list[EvidenceRef]
    user_constraints: list[str]
    user_constraint_refs: list[EvidenceRef] = Field(default_factory=list)
    pending_actions: list[str]
    settlement_ref: EvidenceRef
    neutral_brief: str
    context_id: str | None = None
    # FILL IN: canonical hash excludes checkpoint_id; brief UTF-8 <=8192 bytes.
```

Continuación del mismo archivo:

```python

class CompactionReceipt(OptimizationModel):
    """Actual outcome, including unsupported or still-unsettled requests."""
    checkpoint_id: str
    context_id: str
    status: Literal['completed', 'skipped', 'unsupported', 'failed', 'in_progress']
    reason: str
    backend: Literal['jev', 'builtin', 'unknown']
    before_bytes: int | None = None
    after_bytes: int | None = None
    before_tokens: int | None = None
    after_tokens: int | None = None
    elapsed_ms: int = Field(ge=0)

class BackgroundRegistration(OptimizationModel):
    """Opaque launch identity bound to its true owner and worktree."""
    handle: str
    execution_id: str
    task_id: str | None = None
    attempt_uid: str | None = None
    launch_id: str
    owner_instance_id: str
    kind: Literal['mcp_job', 'validation', 'native_agent', 'host_bridge']
    authority: Literal['supervisor', 'engine', 'host_observation']
    worktree: str
    backend: str
    started_at: datetime | None = None
    registered_log_ref: EvidenceRef | None = None

class BackgroundStatus(OptimizationModel):
    """Known status is distinct from successful validation or task acceptance."""
    state: Literal['pending', 'running', 'finished', 'unknown']
    outcome: Literal['completed', 'failed', 'timed_out', 'cancelled'] | None = None
    exit_code: int | None = None
    source: str
    authority: Literal['supervisor', 'engine', 'host_observation']
    verified_at: datetime | None
    stale: bool
    revision: int = Field(ge=0)
    changed: bool
    log_tail: str | None = None
    log_ref: EvidenceRef | None = None
    log_truncated: bool = False
    elapsed_ms: int = Field(ge=0)
    next_poll_after_ms: int = Field(ge=0)
    # FILL IN: native/logical exit_code null, unknown/stale combos, 124 not
    # an automatic timeout; status envelope <=8192 bytes including log data.
# FILL IN: UUID/full SHA/UTC/order/finite-size validators for all models.
```

**Aplicación y motivo:** Definir todos los modelos compartidos una vez. Separar en bloques de clases durante implementación; eventos/snapshots JSON canónico, bytes y tokens distintos, null explícito. No añadir símbolos a models.py aún.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_models.py` (CREATE)

```python
"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""
import pytest
from pathlib import Path

def test_reject_invalid_identity_and_time(tmp_path: Path) -> None:
    """Cross-field identity, reversed timestamps and extra fields are rejected."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_nullable_authority_and_outcome(tmp_path: Path) -> None:
    """Unknown/native/logical jobs do not invent POSIX exit codes or tokens."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_canonical_json_roundtrip(tmp_path: Path) -> None:
    """Versioned contracts serialize deterministically and preserve pending actions."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError
```

**Aplicación y motivo:** Cubrir todos los modelos y estados R8; códigos negativos preservados y 124 no implica timed_out.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_models.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.

## Acceptance Criteria

- [ ] AC6/AC7/AC10/AC12/AC20: snapshots preservan identidad/procedencia/unknown y no confunden finished con verde.
- [ ] Hash del checkpoint excluye su propio checkpoint_id; todos los campos R5 se representan sin texto inferido.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_models.py -q`

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
