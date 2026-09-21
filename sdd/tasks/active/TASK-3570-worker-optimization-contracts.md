# TASK-3570: Actualizar worker y twins con herramientas deterministas

**Feature**: FEAT-584 — Optimización medible del flujo SDD y transición compactada a revisión
**Spec**: `sdd/specs/sdd-execution-optimization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3556, TASK-3561, TASK-3562, TASK-3565, TASK-3566, TASK-3568
**Assigned-to**: unassigned

## Context

Implementa M6 worker / R1–R8 de la spec aprobada. Baseline de contratos: dev, commit 31f4c47afc72748a387ef8a8e55d0588894668e7.
La optimización conserva aceptación semántica, ownership, cobertura y evidencia explícita; los porcentajes del profiler no son ahorros garantizados.

## Scope

- Actualizar worker instalado/empaquetado a herramientas nuevas y cierre determinista.
- Conservar routing, sandbox, wiki-first, feedback completo, revisión adversarial y retries existentes.

**NOT in scope**: cambiar roster/scheduler, relajar sandbox/checks, modificar clients/base.py, introducir dependencias o realizar cambios fuera de los targets. El adaptador específico de host queda diferido por Q1 salvo enmienda aprobada posterior.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/agents/sdd-worker.md` | MODIFY | Integrar secuencia en loop y Completion, reemplazar instrucciones mecánicas contradictorias |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` | MODIFY | Mismo contrato semántico empaquetado; conservar modos task-scoped/fallback y DevelopmentOutput. |
| `packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py` | MODIFY | No solo buscar nombres: probar orden checkpoint→compaction outcome→revalidate→reviewer y que fallback no asume engine. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Verificación estática de símbolos existentes por AST y lectura de fuentes; no presupone importación del framework. Los imports nuevos se distinguen abajo y requieren completar sus dependencias.

`from parrot.flows.dev_loop._subagent_defs import load_subagent_definition` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py:95`.

### Existing Signatures to Use

`packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py:95` · SHA-256 `eb696f8f273b24de83d5499df75df24e34d666d50c5b7f1a815d1a8ff7598f06`

```python
def load_subagent_definition(name: str) -> str:
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
      "path": ".claude/agents/sdd-worker.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py#load_subagent_definition"
  ]
}
```

## Implementation Notes

Async-first en MCP; I/O bloqueante fuera del event loop. CLI síncrono permitido. Pydantic v2, Black 120 y Ruff. Core no importa parrot_tools. Los blueprints contienen decisiones acotadas pendientes de implementación: no constituyen un Delegation Contract ni permiten entregar placeholders.

## Implementation Blueprint

### Steps (in order)

1. Actualizar allowlist y loop: hacer tools invocables.
2. Reemplazar cierre mecánico y handoff inline: evitar instrucciones contradictorias.
3. Probar twins y fallback: mantener capacidades por host.

### `.claude/agents/sdd-worker.md` (MODIFY)

Anchor verificado: línea 269; ocurrencias exactas = 1; SHA-256 `1ca987c1a59429075a446596bd4b30baaa1a245ea98e3fc5ad76ad815fe95718`.

```text
## Orchestrator Loop (FEAT-549)
```

```text
## Execution optimization (FEAT-584)
Use coder_task_context and coder_delivery_report for known inspection chains;
use source_inspect_batch for independent reads after wiki-first discovery.
Request compact plan/status/wait; consume every required decision page before dispatch.
Retain issued background handles. Query coder_bg_status on notification, before consuming
results or after next_poll_after_ms when needed; never ps/grep/sleep loops.
Validation launch uses declared selector, explicit timeout and stable request_id.
Unknown background work blocks end/cleanup/checkpoint; status is never test acceptance.
After semantic delivery review and required green checks, call finalize_task with exact
evidence and HEAD, inspect staged paths, then make the existing explicit task commit.
At the feature development-to-review boundary: settle children, close execution,
persist checkpoint, request one supported between-turn compaction, record actual outcome,
reload/validate checkpoint, and start a fresh independent reviewer from neutral evidence.
Unsupported hosts/contexts use an explicit outcome and checkpoint; never invoke /compact
through Bash or claim parent compaction also compacts a native child. Real adapter wiring
requires M0 and the approved M5 amendment. Keep current 90s coder_wait policy and no busy-wait.
```

**Aplicación y motivo:** Integrar secuencia en loop y Completion, reemplazar instrucciones mecánicas contradictorias. Actualizar allowlist tools del frontmatter con nombres MCP reales; no añadir dependencia de todos los tools en fallback.

### `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` (MODIFY)

Anchor verificado: línea 269; ocurrencias exactas = 1; SHA-256 `1ca987c1a59429075a446596bd4b30baaa1a245ea98e3fc5ad76ad815fe95718`.

```text
## Orchestrator Loop (FEAT-549)
```

```text
## Execution optimization (FEAT-584)
Use coder_task_context and coder_delivery_report for known inspection chains;
use source_inspect_batch for independent reads after wiki-first discovery.
Request compact plan/status/wait; consume every required decision page before dispatch.
Retain issued background handles. Query coder_bg_status on notification, before consuming
results or after next_poll_after_ms when needed; never ps/grep/sleep loops.
Validation launch uses declared selector, explicit timeout and stable request_id.
Unknown background work blocks end/cleanup/checkpoint; status is never test acceptance.
After semantic delivery review and required green checks, call finalize_task with exact
evidence and HEAD, inspect staged paths, then make the existing explicit task commit.
At the feature development-to-review boundary: settle children, close execution,
persist checkpoint, request one supported between-turn compaction, record actual outcome,
reload/validate checkpoint, and start a fresh independent reviewer from neutral evidence.
Unsupported hosts/contexts use an explicit outcome and checkpoint; never invoke /compact
through Bash or claim parent compaction also compacts a native child. Real adapter wiring
requires M0 and the approved M5 amendment. Keep current 90s coder_wait policy and no busy-wait.
```

**Aplicación y motivo:** Mismo contrato semántico empaquetado; conservar modos task-scoped/fallback y DevelopmentOutput.

### `packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py` (MODIFY)

Anchor verificado: línea 9; ocurrencias exactas = 1; SHA-256 `306ed43901eaad74ea8fd1ac30059a8ab87c003621d7f756e6b5c9a1919008a4`.

```text
TOOLS = [
```

```python
# Extend tool inventory expectations for FEAT-584 and preserve legacy tools.
# Add assertions of ordering/mandatory decision pagination and unknown gates,
# checking both installed and packaged definitions with existing loader.
```

**Aplicación y motivo:** No solo buscar nombres: probar orden checkpoint→compaction outcome→revalidate→reviewer y que fallback no asume engine.

### FILL IN checklist

- [ ] `.claude/agents/sdd-worker.md` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.

## Acceptance Criteria

- [ ] AC17: twins comparten contrato y no eliminan checks.
- [ ] AC4/AC19: no dispatch con páginas obligatorias pendientes ni busy-wait/PID probing.
- [ ] No afirmar AC11 sin driver homologado; capability gate permanece explícita.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py -q`

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
