# TASK-3576: Documentar aceptación, piloto y decisión de activación

**Feature**: FEAT-584 — Optimización medible del flujo SDD y transición compactada a revisión
**Spec**: `sdd/specs/sdd-execution-optimization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h de análisis; piloto y host requieren ventana externa)
**Depends-on**: TASK-3575
**Assigned-to**: unassigned

## Context

Implementa M7 acceptance / Q1 / Q2 de la spec aprobada. Baseline de contratos: dev, commit 31f4c47afc72748a387ef8a8e55d0588894668e7.
La optimización conserva aceptación semántica, ownership, cobertura y evidencia explícita; los porcentajes del profiler no son ahorros garantizados.

## Scope

- Consolidar docs operativas y evidencia de aceptación; correr benchmarks existentes y piloto controlado con logs redactados.
- Bloquear cierre de esta tarea hasta que M0 produzca enmienda, se añadan/completen las tareas del driver específico y AC11 tenga smoke real.
- Aplicar al menos10 pares comparables o replay aislado para decisión default; si no hay datos suficientes, documentar opt-in y Q2 pendiente sin afirmar ahorro.

**NOT in scope**: cambiar roster/scheduler, relajar sandbox/checks, modificar clients/base.py, introducir dependencias o realizar cambios fuera de los targets. El adaptador específico de host queda diferido por Q1 salvo enmienda aprobada posterior.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/dev_loop/sdd-execution-optimization.md` | CREATE | Completar ejemplos contra schemas reales |
| `docs/dev_loop/sdd-coder-orchestrator.md` | MODIFY | Actualizar secciones loop/telemetry/troubleshooting manteniendo defaults de API y límites de host |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Verificación estática de símbolos existentes por AST y lectura de fuentes; no presupone importación del framework. Los imports nuevos se distinguen abajo y requieren completar sus dependencias.

`from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:51`.

### Existing Signatures to Use

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:51` · SHA-256 `29775c383a1cd1b8b4abc91951b62a9205df7968ae712c4b913433a14436b609`

```python
class SddCoderToolkit(AbstractToolkit):
```

### Does NOT Exist

- Los símbolos nuevos declarados en los blueprints no existen en el baseline; no confundir contrato propuesto con API instalada.
- No existe un bridge genérico que convierta PID/Bash externo en receipt autoritativo ni una llamada MCP verificada para compactar cualquier subagente.
- No existe garantía de éxito por log vacío, instalación Jev o respuesta background inmediata.

### Task-specific integration constraints

DEFERRED IMPLEMENTATION GATE: Q1 bloquea descomposición del driver de host, no los módulos comunes. Antes de iniciar esta tarea de aceptación, actualizar spec aprobada e índice con IDs nuevos reservados y depends_on explícitos a las tareas del driver. No inventar IDs ni un placeholder de implementación. Esta tarea final pendiente evita declarar FEAT-584 terminada con solo tests offline. En la ejecución de esta tarea, correr además los archivos de benchmark e integración creados por sus dependencias; sus rutas se resuelven desde el índice ya implementado. La sección Validation Commands solo lista archivos existentes al planificar para evitar declarar archivos ajenos como targets.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/dev_loop/sdd-execution-optimization.md",
      "action": "CREATE"
    },
    {
      "path": "docs/dev_loop/sdd-coder-orchestrator.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py#SddCoderToolkit"
  ]
}
```

## Implementation Notes

Async-first en MCP; I/O bloqueante fuera del event loop. CLI síncrono permitido. Pydantic v2, Black 120 y Ruff. Core no importa parrot_tools. Los blueprints contienen decisiones acotadas pendientes de implementación: no constituyen un Delegation Contract ni permiten entregar placeholders.

## Implementation Blueprint

### Steps (in order)

1. Comprobar el gate externo M5 antes de ejecutar aceptación: no esconder scope incompleto.
2. Recoger benchmarks/piloto y revisión fresca real: medir tiempo hasta aceptación y calidad.
3. Publicar configuración, límites y rollback: habilitar defaults solo con evidencia suficiente.

### `docs/dev_loop/sdd-execution-optimization.md` (CREATE)

```text
# SDD execution optimization — operation and rollout
## Capability and configuration matrix
## Inspection and compact-view examples
## Background authority, receipts and recovery
## Deterministic finalization and checkpoint lifecycle
## Compaction outcomes and verified host integration
## Reproducible benchmark environment and results
## Matched pilot protocol and observations
## Acceptance matrix AC1–AC23
## Rollout decision and rollback
```

**Aplicación y motivo:** Completar ejemplos contra schemas reales. Matriz AC1–AC23 enlaza evidencia, no checks autoafirmados. Incluir perfiles corregidos del §1, baseline post-fixes, muestra/p50/p95, calidad, failures y coste de compaction. Cualquier ausencia de piloto mantiene opt-in; ninguna garantía de ahorro de campo.

### `docs/dev_loop/sdd-coder-orchestrator.md` (MODIFY)

Anchor verificado: línea 150; ocurrencias exactas = 1; SHA-256 `0653f07c1bb452029795ec24129446d0775c75e843975150593fda81fdfced3d`.

```text
## The loop
```

```text
# Update the loop to purpose inspections and optional compact projections.
# Document launch handles/status authority, safe validation, finalization and
# settled checkpoint -> capability-aware boundary -> fresh reviewer.
# Preserve API full defaults, wait=90, routing/coverage and fallback policy.
# Link the FEAT-584 operational guide and actual capability evidence.
```

**Aplicación y motivo:** Actualizar secciones loop/telemetry/troubleshooting manteniendo defaults de API y límites de host. No anunciar activación general si piloto no cumple objetivos.

### FILL IN checklist

- [ ] `docs/dev_loop/sdd-execution-optimization.md` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `docs/dev_loop/sdd-coder-orchestrator.md` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.

## Acceptance Criteria

- [ ] AC11/AC15: al menos un host/contexto homologado compacta una vez y reanuda review; unsupported/mocks no bastan.
- [ ] AC16/AC23: resultados controlados y limitaciones publicados; default solo con reducción≥20% requests y≥15% tiempo mediano sin deterioro de calidad.
- [ ] Todas ACs con evidencia o excepción aprobada explícitamente; AC11 no puede quedar exceptuada por decisión unilateral del implementador.
- [ ] El índice se amplía tras M0: esta tarea NO se marca done mientras falte integración host.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py -q`
- `pytest tests/knowledge/wiki/test_claude_code_compaction.py -q`

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
