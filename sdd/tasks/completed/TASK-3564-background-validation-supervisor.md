# TASK-3564: Supervisar validaciones con receipts y deadlines

**Feature**: FEAT-584 — Optimización medible del flujo SDD y transición compactada a revisión
**Spec**: `sdd/specs/sdd-execution-optimization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3563
**Assigned-to**: unassigned

## Context

Implementa M8 / R8 de la spec aprobada. Baseline de contratos: dev, commit 31f4c47afc72748a387ef8a8e55d0588894668e7.
La optimización conserva aceptación semántica, ownership, cobertura y evidencia explícita; los porcentajes del profiler no son ahorros garantizados.

## Scope

- Implementar supervisor en background.py tras registro, con idempotencia de admisión y proceso esperado.
- Construir selección desde contrato/índice; feature tier conserva conjunto completo y pending escalations.
- No resucitar procesos sin autoridad tras restart; unknown exige reconciliación.

**NOT in scope**: cambiar roster/scheduler, relajar sandbox/checks, modificar clients/base.py, introducir dependencias o realizar cambios fuera de los targets. El adaptador específico de host queda diferido por Q1 salvo enmienda aprobada posterior.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | Anchor de dependencia, NO observado en source actual: lo crea TASK-3563 |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py` | CREATE | Procesos sintéticos controlados sin proveedor: 0,1,124 voluntario,señal,deadline,hijo propio,log grande |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Verificación estática de símbolos existentes por AST y lectura de fuentes; no presupone importación del framework. Los imports nuevos se distinguen abajo y requieren completar sus dependencias.

`from parrot.flows.dev_loop.worktree_environment import protected_argv` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:142`.

`from parrot.flows.dev_loop.test_scope.select import plan_tests` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py:122`.

`from scripts.sdd.select_tests import main` — verificado en `scripts/sdd/select_tests.py:40`.

Imports de blueprint (stdlib / dependencias instaladas / símbolos creados por esta tarea o sus predecesoras; **no** APIs existentes inventadas):

```python
from pathlib import Path
import pytest
```
Pydantic, pytest y Click ya están instalados/declarados; módulos optimization_models/evidence/checkpoint/inspection_models nuevos solo se importan después de sus tareas productoras. Verificar cualquier import adicional antes de introducirlo.

### Existing Signatures to Use

`packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:142` · SHA-256 `c40042d1af4d8ae1b6e59d2bd0900ded99b02359f7d01458130c1f804023ec30`

```python
def protected_argv(cwd: Path, argv: Sequence[str]) -> list[str]:
```

`packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py:122` · SHA-256 `d32906b3bbd4c27f266f3bf2d9da8c555703125b008bcb43f85cc788fbaad25c`

```python
def plan_tests(
    *,
    worktree: Path,
    changed_files: Sequence[str],
    tier: str,
    declared: Sequence[Sequence[str]] = (),
    policy: ScopePolicy | None = None,
) -> ScopePlan:
```

`scripts/sdd/select_tests.py:40` · SHA-256 `0b34397c539488dd47fef5cdb6eb06ef38c59c2672a82acf2adc8ac6e3603e9f`

```python
def main(argv: list[str] | None = None) -> int:
```

### Does NOT Exist

- Los símbolos nuevos declarados en los blueprints no existen en el baseline; no confundir contrato propuesto con API instalada.
- No existe un bridge genérico que convierta PID/Bash externo en receipt autoritativo ni una llamada MCP verificada para compactar cualquier subagente.
- No existe garantía de éxito por log vacío, instalación Jev o respuesta background inmediata.

### Task-specific integration constraints

Imports del nuevo supervisor: from pathlib import Path; from typing import Literal; from parrot.flows.dev_loop.worktree_environment import protected_argv; from parrot.flows.dev_loop.test_scope.select import plan_tests. Verificados abajo. BackgroundRegistry/EvidenceStore/BackgroundRegistration proceden de sus dependencias, no existen como API original.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py#plan_tests",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#protected_argv",
    "sym:scripts/sdd/select_tests.py#main"
  ]
}
```

## Implementation Notes

Async-first en MCP; I/O bloqueante fuera del event loop. CLI síncrono permitido. Pydantic v2, Black 120 y Ruff. Core no importa parrot_tools. Los blueprints contienen decisiones acotadas pendientes de implementación: no constituyen un Delegation Contract ni permiten entregar placeholders.

## Implementation Blueprint

### Steps (in order)

1. Validar ownership/selección antes de registrar: rechazar ampliación de superficie.
2. Persistir admisión y crear proceso protegido: acotar ventana de crash sin duplicación.
3. Drenar, aplicar deadline y esperar reap: producir receipt verificable de todo el trabajo admitido.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` (MODIFY)

Anchor **propuesto por TASK-3563**, no existente en baseline: `class BackgroundRegistry:`. La dependencia lo declara una vez; verificar ocurrencias=1 al ejecutar antes de editar. No se afirma hash fuente inexistente.

```python
# Add imports: pathlib.Path, typing.Literal, protected_argv and test_scope selector.
# Append to the module after BackgroundRegistry, keeping status read-only.
class ValidationSupervisor:
    """Own admitted processes, bounded log drains, deadlines and terminal receipts."""
    def __init__(self, *, registry: BackgroundRegistry, store: ExecutionEvidenceStore) -> None:
        self.registry = registry
        self.store = store

    async def start(self, *, feature: str, worktree: Path, execution_id: str,
                    task_ids: list[str], tier: Literal['merge', 'feature'],
                    timeout_seconds: int, request_id: str) -> BackgroundRegistration:
        """Launch only declared protected selection; return without awaiting the suite."""
        # FILL IN: admission/request journal before spawn, selector coverage,
        # protected_argv mandatory; process-group ownership, concurrent drains.
        # Terminal truth is process.wait receipt, including negative signals.
        # Known deadline terminates owned tree and reaps before timed_out.
        raise NotImplementedError
```

**Aplicación y motivo:** Anchor de dependencia, NO observado en source actual: lo crea TASK-3563. Verificar ocurrencia única tras completar esa tarea; si cambia, actualizar este blueprint antes de implementar. Usar selector y ledger existentes; no introducir suite/argv libre.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py` (CREATE)

```python
"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""
import pytest
from pathlib import Path

def test_idempotent_launch_and_scope(tmp_path: Path) -> None:
    """Same request and payload launch once; conflict and foreign task ids fail."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_exit_signal_and_deadline_receipts(tmp_path: Path) -> None:
    """Real process exits, signals and imposed deadline remain distinct after reap."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_lost_owner_blocks_settlement(tmp_path: Path) -> None:
    """Spawn/persistence failure and unknown ownership never report settled validation."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError
```

**Aplicación y motivo:** Procesos sintéticos controlados sin proveedor: 0,1,124 voluntario,señal,deadline,hijo propio,log grande. Verificar selector merge/feature, entorno protegido y ledger de escalación; fallo de bwrap no hace fallback unsandboxed.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.

## Acceptance Criteria

- [ ] AC21: request_id repetido no duplica proceso; timeout obligatorio1..7200 y tier merge|feature.
- [ ] AC20/AC21: terminal solo tras wait/reap y receipt durable;124 no implica timed_out.
- [ ] stdout/stderr acotados, hijos propios terminados; no test retry automático sin justificación nueva.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py -q`

## Test Specification

Los escenarios en los blueprints son el mínimo verificable. Usar repos/procesos sintéticos aislados, fallos de persistencia y assertions sobre resultados observables; no servicios de proveedor en suite offline. Guardar logs en artifacts/logs/. Los tests live se ejecutan aparte y nunca se presentan como pasados por una simulación.

## Agent Instructions

1. Leer `sdd/specs/sdd-execution-optimization.spec.md` y comprobar dependencias en `sdd/tasks/index/sdd-execution-optimization.json`; no usar índice monolítico.
2. Revalidar imports/anchors y convenios antes de editar. Preservar cambios de otras tareas y del usuario.
3. Implementar solo targets, completar blueprints y ejecutar Validation Commands. No rebajar ACs para cerrar la tarea.
4. Registrar evidencia y revisión; usar el flujo SDD para actualizar estado, mover active→completed y commit acotado.
5. Si falta una API o scope, registrar bloqueo/diseño pendiente; no inventar contratos ni declarar done sin evidencia.

## Completion Note

Completed 2026-09-21 by native sonnet coder (attempt `d3a550e8ee714e47a8abf45ce370c9a1`). Touched
only the two listed targets:

- `background.py` MODIFY — added `ValidationSupervisor` after `BackgroundRegistry`.
  `start(*, feature, worktree, execution_id, task_ids, tier, timeout_seconds, request_id) ->
  BackgroundRegistration` validates shape before anything is persisted; idempotency via
  `handle = request_id`, `launch_id = sha256(canonical payload)`, reusing
  `BackgroundRegistry.register`'s existing conflict check (same payload replays the same
  handle, a different payload under the same request_id raises `BackgroundConflictError`).
  Spawns the first invocation synchronously via `protected_argv` (own process-group,
  `start_new_session=True`) and calls the reserved `registry._record_transition(state=
  "running", ...)` before returning — `start()` never awaits the suite's completion. Draining,
  the deadline, and the terminal `_record_transition(state="finished", ...)` run in a
  background `asyncio.Task`, reusing TASK-3563's reserved internal method rather than adding a
  parallel state path. Deadline handling: `os.killpg` (SIGTERM then SIGKILL after a grace
  period), always reaps via `process.wait()`; a signal returncode or an isolated 124 is
  preserved verbatim as `failed`, never reinterpreted as `timed_out`/success. A spawn/admission
  failure propagates and releases the in-process claim so a retry under the same request_id
  is not locked out.
- `test_background_validation.py` CREATE — 3 tests.

Design decisions flagged and accepted:
1. Imported `changed_files` from the same already-verified `test_scope.select` module (the
   Codebase Contract named only `plan_tests`, but `plan_tests` requires `changed_files` to be
   called meaningfully at all) — verified by reading the source before use, not a fabricated
   symbol.
2. No `base_ref` parameter exists on the blueprint's fixed `start()` signature, so the coder
   hardcoded `_DEFAULT_BASE_REF = "origin/dev"` (mirroring `select_tests.py`'s own CLI
   default). A hotfix worktree (based on `origin/main`) would diff against the wrong base;
   flagged as needing a signature-changing amendment in a future task, not silently patched.
3. `task_ids` is validated for shape and folded into the idempotency hash, but the selection
   relies purely on the selector's mirror/impact/core coverage over `changed_files`, not each
   task's own declared Validation Commands (no `parse_validation_commands`/`TaskScheduler`
   import was in this file's allowed list). Flagged as requiring a Codebase Contract amendment
   if per-task declared-command coverage is actually required here.

No MCP tool was registered (file table has no toolkit.py/models.py/engine.py) so the
TASK-3560/3561/3562 allowlist collateral pattern does not apply.

Validation:
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py -q` → 3 passed.
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_status.py -q` → 5 passed (regression check, TASK-3563's suite).
- Full scoped `packages/ai-parrot/tests/flows/dev_loop/sdd_coder` suite → 433 passed (up from 430 at TASK-3563).
- `git status --porcelain --untracked-files=all` clean except gitignored build artifacts.
- `ruff check` clean; verified no orphaned processes remained after the deadline/own-child test.

Review: `coder-review:4a7c9ba0f21c5f069b3ff341` (zero fix commits — clean delivery).

Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: 1066180ms (~17m46s) · Tokens: 234053 (subagent total, in/out split not exposed for native).
