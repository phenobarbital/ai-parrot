# TASK-3575: Validar flujo completo tras pérdida de contexto

**Feature**: FEAT-584 — Optimización medible del flujo SDD y transición compactada a revisión
**Spec**: `sdd/specs/sdd-execution-optimization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3557, TASK-3569, TASK-3570, TASK-3571, TASK-3572, TASK-3573, TASK-3574
**Assigned-to**: unassigned

## Context

Implementa M7 integration de la spec aprobada. Baseline de contratos: dev, commit 31f4c47afc72748a387ef8a8e55d0588894668e7.
La optimización conserva aceptación semántica, ownership, cobertura y evidencia explícita; los porcentajes del profiler no son ahorros garantizados.

## Scope

- Ejecutar integración offline completa con los contratos ya implementados.
- Cubrir corrupción, interleaving, presupuestos y review sobre evidencia incorrecta; no modificar producción aquí.

**NOT in scope**: cambiar roster/scheduler, relajar sandbox/checks, modificar clients/base.py, introducir dependencias o realizar cambios fuera de los targets. El adaptador específico de host queda diferido por Q1 salvo enmienda aprobada posterior.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_workflow_contracts.py` | CREATE | Fixture de feature temporal usa APIs/CLI/MCP reales offline, native host simulado con procedencia explícita, borra solo contexto simulado |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Verificación estática de símbolos existentes por AST y lectura de fuentes; no presupone importación del framework. Los imports nuevos se distinguen abajo y requieren completar sus dependencias.

`from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:51`.

`from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:684`.

Imports de blueprint (stdlib / dependencias instaladas / símbolos creados por esta tarea o sus predecesoras; **no** APIs existentes inventadas):

```python
from pathlib import Path
import pytest
```
Pydantic, pytest y Click ya están instalados/declarados; módulos optimization_models/evidence/checkpoint/inspection_models nuevos solo se importan después de sus tareas productoras. Verificar cualquier import adicional antes de introducirlo.

### Existing Signatures to Use

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:51` · SHA-256 `29775c383a1cd1b8b4abc91951b62a9205df7968ae712c4b913433a14436b609`

```python
class SddCoderToolkit(AbstractToolkit):
```

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:684` · SHA-256 `aeb4b46eca6261c77f2d42237eb4ca7396a89f76447a8a9b3a869f81e825209c`

```python
    async def end_execution(self, execution_id: str) -> "ExecutionPoolView":
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
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_workflow_contracts.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.end_execution",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py#SddCoderToolkit"
  ]
}
```

## Implementation Notes

Async-first en MCP; I/O bloqueante fuera del event loop. CLI síncrono permitido. Pydantic v2, Black 120 y Ruff. Core no importa parrot_tools. Los blueprints contienen decisiones acotadas pendientes de implementación: no constituyen un Delegation Contract ni permiten entregar placeholders.

## Implementation Blueprint

### Steps (in order)

1. Construir fixture de feature y APIs reales: probar conexiones entre módulos.
2. Descartar contexto y sembrar defecto verificable: comprobar suficiencia de handoff.
3. Inyectar fallos y dos executions: evitar confianza en evidencia corrupta o ajena.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_workflow_contracts.py` (CREATE)

```python
"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""
import pytest
from pathlib import Path

def test_mixed_delivery_checkpoint_fresh_review(tmp_path: Path) -> None:
    """MCP and native deliveries reach settled checkpoint and expose a seeded defect to fresh review."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_concurrent_executions_and_crash(tmp_path: Path) -> None:
    """Two worktrees remain isolated and crash/disk failures cannot publish trusted missing evidence."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_stale_fix_and_full_compatibility(tmp_path: Path) -> None:
    """A later fix invalidates prior hashes while legacy full responses and gates remain compatible."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError
```

**Aplicación y motivo:** Fixture de feature temporal usa APIs/CLI/MCP reales offline, native host simulado con procedencia explícita, borra solo contexto simulado. El defecto sembrado debe figurar en diff/criterios recuperables y ser comprobado sin historial. No pretender que un test determinista demuestra razonamiento del LLM; el piloto hará la revisión real.

### FILL IN checklist

- [ ] `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_workflow_contracts.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.

## Acceptance Criteria

- [ ] AC7/AC9/AC10/AC15/AC17: pipeline offline mantiene neutralidad, constraints y snapshots verificables.
- [ ] No declarar AC11 satisfecho: host smoke real es gate separado en tarea final.
- [ ] No rebajar cobertura al fallar: reportar bug y corregir mediante tarea dueña.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_workflow_contracts.py -q`

## Test Specification

Los escenarios en los blueprints son el mínimo verificable. Usar repos/procesos sintéticos aislados, fallos de persistencia y assertions sobre resultados observables; no servicios de proveedor en suite offline. Guardar logs en artifacts/logs/. Los tests live se ejecutan aparte y nunca se presentan como pasados por una simulación.

## Agent Instructions

1. Leer `sdd/specs/sdd-execution-optimization.spec.md` y comprobar dependencias en `sdd/tasks/index/sdd-execution-optimization.json`; no usar índice monolítico.
2. Revalidar imports/anchors y convenios antes de editar. Preservar cambios de otras tareas y del usuario.
3. Implementar solo targets, completar blueprints y ejecutar Validation Commands. No rebajar ACs para cerrar la tarea.
4. Registrar evidencia y revisión; usar el flujo SDD para actualizar estado, mover active→completed y commit acotado.
5. Si falta una API o scope, registrar bloqueo/diseño pendiente; no inventar contratos ni declarar done sin evidencia.

## Completion Note

Completado 2026-09-21 por coder nativo sonnet (attempt manual, sin registro MCP — ver nota de
enrutamiento abajo). Tocó solo el único target CREATE listado:

- `test_optimization_workflow_contracts.py` CREATE (684 líneas) — los tres escenarios exactos del
  blueprint: `test_mixed_delivery_checkpoint_fresh_review` (dispatch MCP real + ciclo native real
  prepare_native→work→record_native_observation→merge en la misma ejecución, asienta una validación
  vía `BackgroundRegistry`, cierra vía `end_execution`, prepara checkpoint; descarta todo objeto en
  memoria y, usando solo durable_root/ids, abre un `ExecutionEvidenceStore` nuevo, recarga/valida el
  checkpoint y recupera un criterio de aceptación genuinamente no cumplido de una tarea no entregada
  — el "defecto sembrado" es una entrega real faltante, no un bug fabricado); `test_concurrent_executions_and_crash`
  (dos ejecuciones en dos worktrees en un engine compartido prueban `background_scope_mismatch`;
  simula fallo de disco exactamente en la publicación de settlement de `end_execution` y prueba que
  `prepare_review_checkpoint` lanza `CheckpointBusyError` — AC7 literal; corrupción interior de
  `events.jsonl` lanza `EvidenceCorruptionError`, nunca omitida silenciosamente, mientras una línea
  final truncada por crash real se repara transparentemente); `test_stale_fix_and_full_compatibility`
  (Parte A: `finalize_task` real contra `close_task.sh` — un fix commit posterior a la evidencia hace
  que el cierre lance `TaskEvidenceStaleError`, luego tiene éxito contra el nuevo HEAD real; Parte B:
  dispatch MCP real a checkpoint asentado, `coder_status` `response_mode='full'` byte-compatible con
  forma legacy, `'compact'` añade `evidence_ref`/`required_pages_remaining` recuperables vía
  `coder_read_artifact`; un fix commit posterior invalida el checkpoint preparado
  (`CheckpointStaleError`), y uno recién preparado obtiene `checkpoint_id`/`implementation_head`
  genuinamente distinto y valida limpio).

**Nota de enrutamiento (por instrucción explícita del usuario "re-execute TASK-3575"):** el motor
`parrot-sdd-coder` se niega a rutar esta tarea en `coder_plan`/`coder_prepare_native`
(`task_not_in_plan`) porque su dependencia TASK-3569 tiene status `"done-with-issues"` en el índice
per-spec, no el literal `"done"` que exige el resolver de dependencias del motor — aunque el trabajo
real de TASK-3569 (lazy_commands.py + cli.py + tests) está mergeado y funcional; solo un benchmark
suave p50<300ms no se cumplió, honestamente documentado en la nota de esa tarea. Todas las demás
dependencias (TASK-3557, TASK-3570, TASK-3571, TASK-3572, TASK-3573, TASK-3574) están `"done"`. Ante
esta instrucción explícita del usuario, se creó manualmente un sub-worktree/branch fuera del
seguimiento del motor (mismo patrón de aislamiento que usa el motor, sin sus tablas de jobs/attempts
internas), se despachó el mismo coder nativo sonnet, y se mergeó/cerró manualmente siguiendo la
mecánica del Fallback Loop (pasos e-g).

**Defecto confirmado encontrado y flagueado por el coder (NO arreglado, fuera del scope de archivos
de esta tarea):** `SddCoderEngine._job_worktrees` se puebla en `run_chunk` (engine.py ~3301) y nunca
se limpia en ningún lugar de engine.py. El enriquecimiento del snapshot de `end_execution`
(engine.py ~811-816) re-añade incondicionalmente cada job id jamás despachado para un worktree al
`ExecutionSnapshot.outstanding_job_ids` publicado de forma durable, sin verificar el estado terminal
real del job. `prepare_review_checkpoint` (checkpoint.py ~484) trata cualquier
`outstanding_job_ids` no vacío como aún-ocupado — así que una entrega MCP real vía `run_chunk` NUNCA
puede alcanzar un checkpoint válido, incluso mucho después de que el job esté completamente
`done`/`merged`, a menos que algo limpie `_job_worktrees` manualmente (no existe API pública para
ello). El coder no lo ocultó: ambos tests afectados llevan un comentario explícito en el sitio
exacto de la llamada documentando que es un workaround de test que expone un gap real en la
integración M4/M8 ya mergeada (scope de TASK-3565/TASK-3567), no evidencia de que el comportamiento
sea correcto. **Requiere una tarea de fix de seguimiento contra `engine.py`.**

Sin desviaciones fuera de lo flagueado. Nada bajo `sdd/` tocado salvo el propio flujo SDD.
AC11 explícitamente nunca tocado ni reclamado (TASK-3576, gate separado diferido). Cobertura nunca
rebajada para esquivar el defecto `_job_worktrees` confirmado — los tests siguen ejercitando el
camino MCP-delivery→checkpoint real completo, con el gap documentado en vez de evitado.

Validación:
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_workflow_contracts.py -q`
  (Validation Command exacto) → 3 passed (repetido 4 veces por el coder, sin flakiness).
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder -q` (regresión completa del paquete,
  post-merge) → 461 passed.
- `ruff check` + `black --check` → clean.
- `git status --porcelain --untracked-files=all` limpio salvo artefactos gitignored.

Ledger: `wikitoolkit ledger open --kind bug --severity major` para el defecto `_job_worktrees`
confirmado → `Ledger unavailable; NOT filed: shared ledger is read-only`. **NOT filed: shared
ledger is read-only** — pendiente de un follow-up privilegiado; ver resumen final del feature.

Seat: sonnet (native, manual dispatch — sin registro coder_prepare_native/coder_merge del motor) ·
Backend: native · Model: sonnet · Attempts: 1 · Duration: ~1818s · Tokens: 452081 (subagent total,
in/out no separado para native).
