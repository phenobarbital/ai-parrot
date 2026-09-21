# TASK-3571: Alinear coder y reviewer con checkpoint neutral

**Feature**: FEAT-584 — Optimización medible del flujo SDD y transición compactada a revisión
**Spec**: `sdd/specs/sdd-execution-optimization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3567, TASK-3568
**Assigned-to**: unassigned

## Context

Implementa M6 coder/reviewer de la spec aprobada. Baseline de contratos: dev, commit 31f4c47afc72748a387ef8a8e55d0588894668e7.
La optimización conserva aceptación semántica, ownership, cobertura y evidencia explícita; los porcentajes del profiler no son ahorros garantizados.

## Scope

- Actualizar cuatro definiciones con responsabilidad separada y evidencia durable.
- No reducir checklist, severidades o cross-check adversarial existente.

**NOT in scope**: cambiar roster/scheduler, relajar sandbox/checks, modificar clients/base.py, introducir dependencias o realizar cambios fuera de los targets. El adaptador específico de host queda diferido por Q1 salvo enmienda aprobada posterior.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/agents/sdd-coder.md` | MODIFY | Integrar en lectura/validación/output sin transferir al coder cierre o compaction de feature. |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md` | MODIFY | Twin empaquetado: conservar firmas/output y restricciones propias. |
| `.claude/agents/code-reviewer.md` | MODIFY | Añadir bootstrap desde checkpoint, no fork del historial; conservar revisión independiente. |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-codereview.md` | MODIFY | Este reviewer empaquetado es un gate cualitativo con fixes y JSON, no un twin literal del code-reviewer |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_handoff_contract.py` | CREATE | Comprobar relaciones/orden de contrato y retención de reglas, no igualdad literal entre perfiles distintos. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Verificación estática de símbolos existentes por AST y lectura de fuentes; no presupone importación del framework. Los imports nuevos se distinguen abajo y requieren completar sus dependencias.

`from parrot.flows.dev_loop._subagent_defs import load_subagent_definition` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py:95`.

Imports de blueprint (stdlib / dependencias instaladas / símbolos creados por esta tarea o sus predecesoras; **no** APIs existentes inventadas):

```python
from pathlib import Path
import pytest
```
Pydantic, pytest y Click ya están instalados/declarados; módulos optimization_models/evidence/checkpoint/inspection_models nuevos solo se importan después de sus tareas productoras. Verificar cualquier import adicional antes de introducirlo.

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
      "path": ".claude/agents/sdd-coder.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/agents/code-reviewer.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-codereview.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_handoff_contract.py",
      "action": "CREATE"
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

1. Integrar lectura y validación de evidencia en bootstrap: evitar sesgo de implementación.
2. Mantener contratos de entrega: no mezclar aceptación con desarrollo.
3. Comparar twins con tests de semántica: impedir divergencia instalada/empaquetada.

### `.claude/agents/sdd-coder.md` (MODIFY)

Anchor verificado: línea 107; ocurrencias exactas = 1; SHA-256 `8d0cba252d68ce19a3c94b389231863a83326c3f0c6d81b342efd3a1b375d2e4`.

```text
### a) Read and Understand Task
```

```text
## Bounded inspection and delivery (FEAT-584)
Preserve wiki-first discovery and the complete task acceptance/file contract.
Batch only independent read-only inspections; inspect every partial error and snapshot hash.
Do not interpret compact payloads, background finished or a log as task acceptance.
Keep validation selectors and full native coder_feedback; do not repeat unchanged checks
without a reason. Commit code only under the existing delivery contract; task closure
and feature compaction remain the worker's responsibility, never one compact per task.
```

**Aplicación y motivo:** Integrar en lectura/validación/output sin transferir al coder cierre o compaction de feature.

### `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md` (MODIFY)

Anchor verificado: línea 107; ocurrencias exactas = 1; SHA-256 `8d0cba252d68ce19a3c94b389231863a83326c3f0c6d81b342efd3a1b375d2e4`.

```text
### a) Read and Understand Task
```

```text
## Bounded inspection and delivery (FEAT-584)
Preserve wiki-first discovery and the complete task acceptance/file contract.
Batch only independent read-only inspections; inspect every partial error and snapshot hash.
Do not interpret compact payloads, background finished or a log as task acceptance.
Keep validation selectors and full native coder_feedback; do not repeat unchanged checks
without a reason. Commit code only under the existing delivery contract; task closure
and feature compaction remain the worker's responsibility, never one compact per task.
```

**Aplicación y motivo:** Twin empaquetado: conservar firmas/output y restricciones propias.

### `.claude/agents/code-reviewer.md` (MODIFY)

Anchor verificado: línea 24; ocurrencias exactas = 1; SHA-256 `eb3eb9fdf35555c21c09aeeec99fafcb3293f56986e016126b2538246d2aaa11`.

```text
## Your Review Process
```

```text
## Neutral checkpoint handoff (FEAT-584)
Start in a fresh review context with the durable checkpoint and the user's constraints.
Validate HEAD, branch, spec/index/convention hashes and evidence refs before reviewing.
Read the complete immutable diff through bounded references; a compact brief is not the diff.
Keep pending criteria, done-with-issues and findings visible; ignore implementer conclusions.
Reuse valid mechanical evidence when appropriate, but rerun tests after changes or doubts.
Preserve independent adversarial checks, integration coverage and existing severity policy.
Any changed covered revision invalidates the checkpoint and previous approval.
```

**Aplicación y motivo:** Añadir bootstrap desde checkpoint, no fork del historial; conservar revisión independiente.

### `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-codereview.md` (MODIFY)

Anchor verificado: línea 76; ocurrencias exactas = 1; SHA-256 `bf67c39c11fd4abfc8081ae49e6bf76f522d04bf4649516eb2f9e8dcdce224a5`.

```text
## Steps
```

```text
## Neutral checkpoint handoff (FEAT-584)
Start in a fresh review context with the durable checkpoint and the user's constraints.
Validate HEAD, branch, spec/index/convention hashes and evidence refs before reviewing.
Read the complete immutable diff through bounded references; a compact brief is not the diff.
Keep pending criteria, done-with-issues and findings visible; ignore implementer conclusions.
Reuse valid mechanical evidence when appropriate, but rerun tests after changes or doubts.
Preserve independent adversarial checks, integration coverage and existing severity policy.
Any changed covered revision invalidates the checkpoint and previous approval.
```

**Aplicación y motivo:** Este reviewer empaquetado es un gate cualitativo con fixes y JSON, no un twin literal del code-reviewer. Conservar passed/findings/files_modified y re-run de QA después de fix; aplicar solo contrato común de handoff.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_handoff_contract.py` (CREATE)

```python
"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""
import pytest
from pathlib import Path

def test_neutral_review_context_contract(tmp_path: Path) -> None:
    """Reviewer twins require fresh context, complete diff and checkpoint revalidation."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_coder_retains_delivery_scope(tmp_path: Path) -> None:
    """Coder twins retain code-only delivery, full feedback and validation coverage."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError
```

**Aplicación y motivo:** Comprobar relaciones/orden de contrato y retención de reglas, no igualdad literal entre perfiles distintos.

### FILL IN checklist

- [ ] `.claude/agents/sdd-coder.md` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `.claude/agents/code-reviewer.md` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-codereview.md` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_handoff_contract.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.

## Acceptance Criteria

- [ ] AC9/AC17: reviewer recibe evidencia neutral y diff completo; contexto de desarrollo no necesario.
- [ ] AC13: coder no compacta por tool/tarea ni altera rol de aceptación.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_handoff_contract.py -q`

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
