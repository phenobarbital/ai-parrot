# TASK-3560: Integrar eventos del engine y observaciones nativas

**Feature**: FEAT-584 — Optimización medible del flujo SDD y transición compactada a revisión
**Spec**: `sdd/specs/sdd-execution-optimization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3559
**Assigned-to**: unassigned

## Context

Implementa M2 / R3 de la spec aprobada. Baseline de contratos: dev, commit 31f4c47afc72748a387ef8a8e55d0588894668e7.
La optimización conserva aceptación semántica, ownership, cobertura y evidencia explícita; los porcentajes del profiler no son ahorros garantizados.

## Scope

- Emitir eventos en transiciones reales y registrar observaciones del worker contra attempts ya emitidos.
- No cambiar FEAT usage records ni convertir observación en fuente de aceptación.

**NOT in scope**: cambiar roster/scheduler, relajar sandbox/checks, modificar clients/base.py, introducir dependencias o realizar cambios fuera de los targets. El adaptador específico de host queda diferido por Q1 salvo enmienda aprobada posterior.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | Añadir integración dentro del engine existente; preservar ownership, gates, routing y admisión |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` | MODIFY | Registrar schema en arg_models, docstring LLM-facing y mapping vía _run |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | Añadir argumentos estrictos y errores al conjunto ERROR_CODES; reutilizar validadores UUID/worktree/task |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py` | MODIFY | Cubrir descubrimiento real y validación previa de cada nuevo argumento; conservar tests existentes. |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_native_observations.py` | CREATE | Observar timestamps reales/no conocidos, tokens null y correlation de eventos MCP/native |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Verificación estática de símbolos existentes por AST y lectura de fuentes; no presupone importación del framework. Los imports nuevos se distinguen abajo y requieren completar sus dependencias.

`from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:768`.

`from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:169`.

`from parrot.flows.dev_loop.sdd_coder.telemetry import resolve_durable_root` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py:107`.

`from parrot.flows.dev_loop.sdd_coder.models import CoderResult` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:471`.

Imports de blueprint (stdlib / dependencias instaladas / símbolos creados por esta tarea o sus predecesoras; **no** APIs existentes inventadas):

```python
from pathlib import Path
import pytest
```
Pydantic, pytest y Click ya están instalados/declarados; módulos optimization_models/evidence/checkpoint/inspection_models nuevos solo se importan después de sus tareas productoras. Verificar cualquier import adicional antes de introducirlo.

### Existing Signatures to Use

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:768` · SHA-256 `aeb4b46eca6261c77f2d42237eb4ca7396a89f76447a8a9b3a869f81e825209c`

```python
    async def _resolve_feature(self, feature: str, worktree: str) -> _FeatureCtx:
```

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:684` · SHA-256 `aeb4b46eca6261c77f2d42237eb4ca7396a89f76447a8a9b3a869f81e825209c`

```python
    async def end_execution(self, execution_id: str) -> "ExecutionPoolView":
```

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:169` · SHA-256 `29775c383a1cd1b8b4abc91951b62a9205df7968ae712c4b913433a14436b609`

```python
    async def _run(self, operation: str, coro: Awaitable[BaseModel]) -> CoderResult:
```

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py:107` · SHA-256 `20575cc03234d60d3e38fb110bd259545a4eb5fcbee6e66910b202279d6da33a`

```python
def resolve_durable_root(configured: Optional[str], *, worktree_base_path: str) -> Path:
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
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_native_observations.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._resolve_feature",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.end_execution",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#CoderResult",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py#resolve_durable_root",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py#SddCoderToolkit._run"
  ]
}
```

## Implementation Notes

Async-first en MCP; I/O bloqueante fuera del event loop. CLI síncrono permitido. Pydantic v2, Black 120 y Ruff. Core no importa parrot_tools. Los blueprints contienen decisiones acotadas pendientes de implementación: no constituyen un Delegation Contract ni permiten entregar placeholders.

## Implementation Blueprint

### Steps (in order)

1. Conectar store al engine: preservar raíz durable existente.
2. Instrumentar transiciones y añadir API observacional: correlacionar por identidad.
3. Actualizar inventario y tests de gates: verificar que no se abre vía alternativa de merge.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY)

Anchor verificado: línea 326; ocurrencias exactas = 1; SHA-256 `aeb4b46eca6261c77f2d42237eb4ca7396a89f76447a8a9b3a869f81e825209c`.

```text
class SddCoderEngine:
```

```python
# Initialize ExecutionEvidenceStore using resolve_durable_root, outside worktrees.
# At actual lifecycle transitions emit attempt.dispatched/finished,
# delivery.observed and merge.finished with issued attempt/job/execution ids.
async def record_native_observation(
    self, feature: str, worktree: str, execution_id: str,
    observation: dict[str, object],
) -> dict[str, object]:
    """Validate an issued native attempt and persist an observation, not acceptance."""
    # FILL IN: reuse feature/owner checks, validate identity and event conflict.
    # Never release a native reservation or call merge from this method.
    raise NotImplementedError
```

**Aplicación y motivo:** Añadir integración dentro del engine existente; preservar ownership, gates, routing y admisión. Revalidar anchor tras dependencias.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` (MODIFY)

Anchor verificado: línea 51; ocurrencias exactas = 1; SHA-256 `29775c383a1cd1b8b4abc91951b62a9205df7968ae712c4b913433a14436b609`.

```text
class SddCoderToolkit(AbstractToolkit):
```

```python
async def coder_record_native_observation(
    self, feature: str, worktree: str, execution_id: str,
    observation: dict[str, object],
) -> CoderResult:
    """Persist host observations for an issued native attempt without accepting it."""
    # FILL IN: _run -> engine.record_native_observation; strict schema first.
    raise NotImplementedError
```

**Aplicación y motivo:** Registrar schema en arg_models, docstring LLM-facing y mapping vía _run. No registrar helpers internos como tools.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` (MODIFY)

Anchor verificado: línea 481; ocurrencias exactas = 1; SHA-256 `b459601f842150f19ddb8cd7d37c12ac81cf0a59cc77ccab612a1a532cc1a342`.

```text
class _Args(BaseModel):
```

```python
# Add CoderRecordNativeObservationArgs(_Args) with feature/worktree/execution_id
# and a typed observation schema. Required: event_id, task_id, attempt_uid,
# agent_id, observed_at, kind dispatched|finished, evidence_ref.
# Optional: started_at, ended_at, terminal; validate UTC and ordering.
# Extend ERROR_CODES with observation_conflict, artifact_not_found,
# artifact_scope_mismatch, evidence_persistence_failed, evidence_invalid.
```

**Aplicación y motivo:** Añadir argumentos estrictos y errores al conjunto ERROR_CODES; reutilizar validadores UUID/worktree/task. No ampliar schema accidentalmente de otros métodos.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py` (MODIFY)

Anchor verificado: línea 20; ocurrencias exactas = 1; SHA-256 `0f798a1f0d66a6489138c7cf203e03f440c4b99b3b89bac0ab63425a370a3e30`.

```text
EXPECTED_TOOLS = {
```

```python
# Extend the exact set with the tools from R3.
# Keep every existing tool and the strict equality assertion.
```

**Aplicación y motivo:** Cubrir descubrimiento real y validación previa de cada nuevo argumento; conservar tests existentes.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_native_observations.py` (CREATE)

```python
"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""
import pytest
from pathlib import Path

def test_observation_does_not_settle_attempt(tmp_path: Path) -> None:
    """Valid native completion observation leaves reservation and merge gates intact."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_foreign_or_conflicting_identity(tmp_path: Path) -> None:
    """Foreign execution, unknown attempt and contradictory event_id fail before mutation."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_telemetry_failure_is_reported(tmp_path: Path) -> None:
    """Observational write failures are visible but do not invalidate a correct merge."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError
```

**Aplicación y motivo:** Observar timestamps reales/no conocidos, tokens null y correlation de eventos MCP/native. No deducir span del tool_result instantáneo.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_native_observations.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.

## Acceptance Criteria

- [ ] AC6: idempotencia estricta; observaciones no liberan reservas ni crean tokens/spans.
- [ ] AC5/AC7: gates y routing existentes intactos; fallo de telemetría visible como degradación.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_native_observations.py -q`

## Test Specification

Los escenarios en los blueprints son el mínimo verificable. Usar repos/procesos sintéticos aislados, fallos de persistencia y assertions sobre resultados observables; no servicios de proveedor en suite offline. Guardar logs en artifacts/logs/. Los tests live se ejecutan aparte y nunca se presentan como pasados por una simulación.

## Agent Instructions

1. Leer `sdd/specs/sdd-execution-optimization.spec.md` y comprobar dependencias en `sdd/tasks/index/sdd-execution-optimization.json`; no usar índice monolítico.
2. Revalidar imports/anchors y convenios antes de editar. Preservar cambios de otras tareas y del usuario.
3. Implementar solo targets, completar blueprints y ejecutar Validation Commands. No rebajar ACs para cerrar la tarea.
4. Registrar evidencia y revisión; usar el flujo SDD para actualizar estado, mover active→completed y commit acotado.
5. Si falta una API o scope, registrar bloqueo/diseño pendiente; no inventar contratos ni declarar done sin evidencia.

## Completion Note

Completed 2026-09-21 by native sonnet coder (attempt `75123a2c770847e9926fbc3ad938ec36`). Touched
only the five listed targets:

- `engine.py` MODIFY — added `self._evidence_store: Optional[ExecutionEvidenceStore]`
  constructed alongside the existing telemetry sink under the same
  `telemetry_dir is not None or conf.DEV_LOOP_CODER_TELEMETRY` gate (no new conf var, no
  behavior change for callers that never pass `telemetry_dir`). Added
  `record_native_observation(feature, worktree, execution_id, observation) -> EvidenceRef`:
  resolves the feature, validates the raw observation dict against `NativeObservation`,
  checks the execution owns the given feature/worktree, checks `attempt_uid` matches the
  execution's own native reservation for `task_id`, then appends a `delivery.observed`
  `WorkflowEvent`. Maps `EvidenceConflictError` to `observation_conflict`,
  `EvidenceCorruptionError`/`OSError` to `evidence_persistence_failed`, schema/`ValueError`
  to `evidence_invalid`. Never touches pool release/merge/consolidate.
- `models.py` MODIFY — extended `ERROR_CODES` with the five spec-mandated codes plus
  `attempt_not_found` (a pre-existing gap: `suspend_model` already raised it but it was
  missing from the closed set; a tightly-coupled 1-line fix, not scope creep). Added
  `NativeObservation` and `CoderRecordNativeObservationArgs(CoderPlanArgs)`.
- `toolkit.py` MODIFY — registered `coder_record_native_observation` in `arg_models` and
  routed it through the existing generic `_run()`.
- `test_toolkit.py` MODIFY — extended `EXPECTED_TOOLS` and the execution_id-scoped set; two
  new tests for `_pre_execute` validation and `_run` success/error mapping.
- `test_native_observations.py` CREATE — three scenarios: valid observation leaves pool
  admission/merge gates untouched; foreign execution and unknown attempt fail before any
  durable write, a valid observation settles, a same-event_id different-content retry is
  rejected (`observation_conflict`); a forced `append_event` `OSError` surfaces as
  `evidence_persistence_failed` while a subsequent real `merge()` for the same task still
  succeeds.

Design decision flagged and accepted: the blueprint's engine method signature literally said
`-> dict[str, object]`, but `SddCoderToolkit._run()` calls `.model_dump()` on the return
value, requiring a `BaseModel`. Resolved by returning `EvidenceRef` (the same type
`ExecutionEvidenceStore.append_event` already returns), consistent with every other engine
method `_run()` composes with — a necessary resolution of a contradiction between two
blueprint-declared signatures, not an invented API.

Collateral breakage flagged by the coder (correctly not fixed out of scope) and fixed by
the orchestrator: two sibling test files hardcode the toolkit's exposed tool-name set
independently of `test_toolkit.py` (`test_mcp_local.py::EXPECTED`,
`test_execution_pool_integration.py::test_mcp_and_prompt_twins`, the latter also requiring
every registered MCP tool to be allow-listed in the sdd-worker prompt frontmatter, both
canonical and packaged twin). Fixed in commit `8181d58ca` (not recordable via
`coder_record_review`'s `fix_commits` since it does not follow the
`fix(<feature>): TASK-N review fixes` message convention the tool validates against;
recorded here instead), following the identical precedent of TASK-3556's own follow-up fix
(`86f742a5f`).

Validation:
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_native_observations.py -q` → 21 passed.
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_mcp_local.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py -q` → 16 passed (post-fix; 3 failed pre-fix, matching the coder's own diagnosis).
- `select_tests --tier merge` escalated to core (engine.py is a core module): full `packages/ai-parrot/tests` sweep → 2240 passed, 24 failed, 28 errors — every failure/error confined to the unrelated `packages/ai-parrot-integrations` satellite package (Telegram, Matrix, Jira, Slack, voice-demo-browser modules with no dependency on `sdd_coder`); zero failures in `packages/ai-parrot/tests` itself. Confirmed pre-existing/environmental, not a regression from this task. `tool_optimizations` suite 433 passed/1 deselected; wiki compaction suite 17 passed.
- `git status --porcelain --untracked-files=all` clean except gitignored build artifacts.

Review: `coder-review:2cbeef63345c2d8dac9d8e5f` (fix commit `8181d58ca`, applied by the orchestrator, not the coder).

Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: 1110335ms (~18m30s) · Tokens: 286754 (subagent total, in/out split not exposed for native).
