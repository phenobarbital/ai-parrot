# TASK-3563: Registrar handles y estado background determinista

**Feature**: FEAT-584 — Optimización medible del flujo SDD y transición compactada a revisión
**Spec**: `sdd/specs/sdd-execution-optimization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3559
**Assigned-to**: unassigned

## Context

Implementa M8 / R8 de la spec aprobada. Baseline de contratos: dev, commit 31f4c47afc72748a387ef8a8e55d0588894668e7.
La optimización conserva aceptación semántica, ownership, cobertura y evidencia explícita; los porcentajes del profiler no son ahorros garantizados.

## Scope

- Implementar registro durable y snapshot determinista para autoridades engine/supervisor/host_observation.
- Exponer solo métodos internos; no register_pid, adopt_process ni espera de suite.

**NOT in scope**: cambiar roster/scheduler, relajar sandbox/checks, modificar clients/base.py, introducir dependencias o realizar cambios fuera de los targets. El adaptador específico de host queda diferido por Q1 salvo enmienda aprobada posterior.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | CREATE | ≤8KiB resultado, tail 0..4096, presupuesto I/O1s y p95 local<100ms |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_status.py` | CREATE | Probar receipt terminal durable tras restart, native observational, MCP logical exit_code null, UTF-8 truncado, reloj falso/backoff y lecturas grandes sin cargar archivo entero. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Verificación estática de símbolos existentes por AST y lectura de fuentes; no presupone importación del framework. Los imports nuevos se distinguen abajo y requieren completar sus dependencias.

`from parrot.flows.dev_loop.sdd_coder.jobs import JobTable` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py:93`.

Imports de blueprint (stdlib / dependencias instaladas / símbolos creados por esta tarea o sus predecesoras; **no** APIs existentes inventadas):

```python
from __future__ import annotations
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.optimization_models import BackgroundRegistration, BackgroundStatus
from pathlib import Path
import pytest
```
Pydantic, pytest y Click ya están instalados/declarados; módulos optimization_models/evidence/checkpoint/inspection_models nuevos solo se importan después de sus tareas productoras. Verificar cualquier import adicional antes de introducirlo.

### Existing Signatures to Use

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py:93` · SHA-256 `8e9a2198e2cce6a02017af7d3f8b57b0ab64dad5ba005604d092a478f40b519f`

```python
    def snapshot(self, job_id: str) -> CoderJob:
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
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_status.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py#JobTable.snapshot",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py#JobTable.wait"
  ]
}
```

## Implementation Notes

Async-first en MCP; I/O bloqueante fuera del event loop. CLI síncrono permitido. Pydantic v2, Black 120 y Ruff. Core no importa parrot_tools. Los blueprints contienen decisiones acotadas pendientes de implementación: no constituyen un Delegation Contract ni permiten entregar placeholders.

## Implementation Blueprint

### Steps (in order)

1. Persistir identidad de launch/owner: evitar adopción por PID reutilizado.
2. Resolver estado desde autoridad y receipts: unknown preserva incertidumbre.
3. Añadir lectura incremental y benchmark local: no bloquear el MCP esperando tests.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` (CREATE)

```python
"""Authoritative background registrations; never adopt arbitrary process ids."""
from __future__ import annotations
from parrot.flows.dev_loop.sdd_coder.optimization_models import BackgroundRegistration, BackgroundStatus
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore

class BackgroundRegistry:
    """Bind opaque handles to execution, worktree, owner instance and authority."""
    def __init__(self, *, store: ExecutionEvidenceStore, owner_instance_id: str) -> None:
        self.store = store
        self.owner_instance_id = owner_instance_id

    async def register(self, registration: BackgroundRegistration) -> str:
        """Persist a launch-bound registration and emit its idempotent handle."""
        # FILL IN: internal launch provenance, opaque handle and payload conflict.
        raise NotImplementedError

    async def status(self, execution_id: str, handle: str,
                     since_revision: int | None = None, tail_bytes: int = 2048) -> BackgroundStatus:
        """Read known state and a bounded registered log without waiting for completion."""
        # FILL IN: ownership + authoritative receipt/state; never ps or kill-0.
        # Owner loss without terminal receipt => unknown, stale, exit_code=None.
        # Revision changes on state/log bytes, never just elapsed wall time.
        # Same revision => changed=false and omit tail/payload repetition.
        raise NotImplementedError
```

**Aplicación y motivo:** ≤8KiB resultado, tail 0..4096, presupuesto I/O1s y p95 local<100ms. Registro contiene authority/owner_instance, log_ref confinado; no aceptar log_path del caller. Redactar credenciales o denegar tail con motivo. Guardar terminal estable y minimizar lectura de logs mediante offsets.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_status.py` (CREATE)

```python
"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""
import pytest
from pathlib import Path

def test_restart_without_receipt_is_unknown(tmp_path: Path) -> None:
    """Losing owner authority never becomes finished by PID absence or empty logs."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_revision_and_incremental_tail(tmp_path: Path) -> None:
    """Only new state/log bytes advance revision; unchanged reads omit repeated tail."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_scope_budget_and_deadline(tmp_path: Path) -> None:
    """Foreign handles, unsafe logs and I/O budget overruns are explicit bounded errors."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError
```

**Aplicación y motivo:** Probar receipt terminal durable tras restart, native observational, MCP logical exit_code null, UTF-8 truncado, reloj falso/backoff y lecturas grandes sin cargar archivo entero.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_status.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.

## Acceptance Criteria

- [ ] AC19/AC20: no ps/shell/LLM; ownership y authority obligatorios; finished nunca acepta tarea.
- [ ] R8: p95local<100ms, máximo1s operativo, 8KiB, revisiones estables y tails seguros.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_status.py -q`

## Test Specification

Los escenarios en los blueprints son el mínimo verificable. Usar repos/procesos sintéticos aislados, fallos de persistencia y assertions sobre resultados observables; no servicios de proveedor en suite offline. Guardar logs en artifacts/logs/. Los tests live se ejecutan aparte y nunca se presentan como pasados por una simulación.

## Agent Instructions

1. Leer `sdd/specs/sdd-execution-optimization.spec.md` y comprobar dependencias en `sdd/tasks/index/sdd-execution-optimization.json`; no usar índice monolítico.
2. Revalidar imports/anchors y convenios antes de editar. Preservar cambios de otras tareas y del usuario.
3. Implementar solo targets, completar blueprints y ejecutar Validation Commands. No rebajar ACs para cerrar la tarea.
4. Registrar evidencia y revisión; usar el flujo SDD para actualizar estado, mover active→completed y commit acotado.
5. Si falta una API o scope, registrar bloqueo/diseño pendiente; no inventar contratos ni declarar done sin evidencia.

## Completion Note

Completed 2026-09-21 by native sonnet coder (attempt `3023c07826484209ad448d91822776b3`). Created
only the two listed targets:

- `background.py` CREATE — `BackgroundRegistry` with exactly the two public methods the
  blueprint fixes: `register(registration) -> str` and `status(execution_id, handle,
  since_revision=None, tail_bytes=2048) -> BackgroundStatus`. Registrations persist durably
  under `store.root/executions/<execution_id>/background/<sha256(handle)>.json` (atomic
  temp-file + `os.replace`), keyed so a handle from a different execution_id is
  indistinguishable from never-registered. `status()` degrades to `unknown`/`exit_code=None`/
  `stale=True` whenever `owner_instance_id` no longer matches the querying instance and no
  terminal receipt exists — never resurrects state from an absent/reused PID. Tail reads use
  bounded `seek()+read()` (never a whole-file read), UTF-8 codepoint-boundary safe; a 1s I/O
  budget overrun raises `BackgroundBudgetExceededError` rather than a false terminal state.
- `test_background_status.py` CREATE — 5 tests.

Design decision flagged and accepted: the spec's M8 module-level skeleton also shows a
`ValidationSupervisor` class and toolkit/engine wiring, but those live in files not in this
task's table (later M8 tasks own them). Since `register`/`status` alone cannot progress state
past pending without some transition write-path, the coder added one internal,
underscore-prefixed method `_record_transition(execution_id, handle, *, state, outcome,
exit_code, log_path)` — documented as callable only by the owning engine/supervisor/
host-observation authority in this same process, never the LLM. A later M8 task is expected
to call this hook or introduce its own. Accepted: this is a private helper within the single
CREATE file this task owns, not a change to any other file, and does not invent a public
contract beyond the two blueprint-fixed methods.

No MCP tool was registered (confirmed by the coder via grep) so the TASK-3560/3561/3562
allowlist collateral pattern does not apply here.

Validation:
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_status.py -q` → 5 passed.
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_models.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_evidence.py -q` → 12 passed (combined regression check).
- Full scoped `packages/ai-parrot/tests/flows/dev_loop/sdd_coder` suite → 430 passed (up from 425 at TASK-3562).
- `git status --porcelain --untracked-files=all` clean except gitignored build artifacts.
- `ruff check` clean (one ASYNC240 blocking-call-in-async finding self-corrected by the coder before commit); `black --line-length 120` applied.

Review: `coder-review:5cb7ae49302086b68318ef58` (zero fix commits — clean delivery).

Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: 921801ms (~15m22s) · Tokens: 205247 (subagent total, in/out split not exposed for native).
