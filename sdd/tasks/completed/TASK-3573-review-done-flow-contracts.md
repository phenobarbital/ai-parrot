# TASK-3573: Actualizar sdd-codereview y sdd-done sin relajar gates

**Feature**: FEAT-584 — Optimización medible del flujo SDD y transición compactada a revisión
**Spec**: `sdd/specs/sdd-execution-optimization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3567, TASK-3568
**Assigned-to**: unassigned

## Context

Implementa M6 review/done de la spec aprobada. Baseline de contratos: dev, commit 31f4c47afc72748a387ef8a8e55d0588894668e7.
La optimización conserva aceptación semántica, ownership, cobertura y evidencia explícita; los porcentajes del profiler no son ahorros garantizados.

## Scope

- Integrar checkpoint/outcome/revalidación en flujos de review y fin.
- Conservar stamping de done separado de cierre de task; no ejecutar close_task sobre base.

**NOT in scope**: cambiar roster/scheduler, relajar sandbox/checks, modificar clients/base.py, introducir dependencias o realizar cambios fuera de los targets. El adaptador específico de host queda diferido por Q1 salvo enmienda aprobada posterior.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-codereview.md` | MODIFY | Integrar secuencia donde corresponda al flujo, sin modificar el carácter task/feature de revisiones existentes |
| `.claude/commands/sdd-done.md` | MODIFY | Integrar secuencia donde corresponda al flujo, sin modificar el carácter task/feature de revisiones existentes |
| `.agent/workflows/sdd-codereview.md` | MODIFY | Integrar secuencia donde corresponda al flujo, sin modificar el carácter task/feature de revisiones existentes |
| `.agent/workflows/sdd-done.md` | MODIFY | Integrar secuencia donde corresponda al flujo, sin modificar el carácter task/feature de revisiones existentes |
| `.agents/skills/sdd-codereview/SKILL.md` | MODIFY | Integrar secuencia donde corresponda al flujo, sin modificar el carácter task/feature de revisiones existentes |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | Integrar secuencia donde corresponda al flujo, sin modificar el carácter task/feature de revisiones existentes |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_done_optimization_contract.py` | CREATE | Verificar semántica y secuencia en seis documentos; no obligar compactación de hosts unsupported. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Verificación estática de símbolos existentes por AST y lectura de fuentes; no presupone importación del framework. Los imports nuevos se distinguen abajo y requieren completar sus dependencias.

`from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine` — verificado en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:684`.

Imports de blueprint (stdlib / dependencias instaladas / símbolos creados por esta tarea o sus predecesoras; **no** APIs existentes inventadas):

```python
from pathlib import Path
import pytest
```
Pydantic, pytest y Click ya están instalados/declarados; módulos optimization_models/evidence/checkpoint/inspection_models nuevos solo se importan después de sus tareas productoras. Verificar cualquier import adicional antes de introducirlo.

### Existing Signatures to Use

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
      "path": ".claude/commands/sdd-codereview.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-done.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-codereview.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-done.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-codereview/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-done/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_done_optimization_contract.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.end_execution"
  ]
}
```

## Implementation Notes

Async-first en MCP; I/O bloqueante fuera del event loop. CLI síncrono permitido. Pydantic v2, Black 120 y Ruff. Core no importa parrot_tools. Los blueprints contienen decisiones acotadas pendientes de implementación: no constituyen un Delegation Contract ni permiten entregar placeholders.

## Implementation Blueprint

### Steps (in order)

1. Actualizar preparación de evidencia: revisión no consume conclusiones como verdad.
2. Insertar settlement y revalidación: impedir cleanup prematuro.
3. Verificar seis twins: mantener política específica de cada host.

### `.claude/commands/sdd-codereview.md` (MODIFY)

Anchor verificado: línea 23; ocurrencias exactas = 1; SHA-256 `3770beb2d72e553c824e024bea31adec6c51a8abb8d3438b6c4d1a3050225251`.

```text
## Steps
```

```text
## Durable review boundary (FEAT-584)
Before feature review, settle owned attempts and supervised validations and close execution.
Unknown activity is a blocker, never evidence of an idle worktree. Persist the checkpoint,
record actual supported compaction outcome once per checkpoint/context, revalidate and start
a fresh reviewer. Unsupported contexts continue from checkpoint with an explicit reason.
Keep review criteria, adversarial checks, full lint, integration validation and ledger gates.
Changes after checkpoint require new hashes/evidence and invalidate old review coverage.
For sdd-done, preserve existing verification stamping, approval and push/merge policy;
do not run task closure again on base_branch and do not clean worktrees with unknown activity.
```

**Aplicación y motivo:** Integrar secuencia donde corresponda al flujo, sin modificar el carácter task/feature de revisiones existentes. Mantener política de aprobación/publicación del skill y checks de ledger.

### `.claude/commands/sdd-done.md` (MODIFY)

Anchor verificado: línea 53; ocurrencias exactas = 1; SHA-256 `1dcda980137f85db82727dbfdd214b1dec82c5386ab83376812d6ec22551f6f3`.

```text
## Steps
```

```text
## Durable review boundary (FEAT-584)
Before feature review, settle owned attempts and supervised validations and close execution.
Unknown activity is a blocker, never evidence of an idle worktree. Persist the checkpoint,
record actual supported compaction outcome once per checkpoint/context, revalidate and start
a fresh reviewer. Unsupported contexts continue from checkpoint with an explicit reason.
Keep review criteria, adversarial checks, full lint, integration validation and ledger gates.
Changes after checkpoint require new hashes/evidence and invalidate old review coverage.
For sdd-done, preserve existing verification stamping, approval and push/merge policy;
do not run task closure again on base_branch and do not clean worktrees with unknown activity.
```

**Aplicación y motivo:** Integrar secuencia donde corresponda al flujo, sin modificar el carácter task/feature de revisiones existentes. Mantener política de aprobación/publicación del skill y checks de ledger.

### `.agent/workflows/sdd-codereview.md` (MODIFY)

Anchor verificado: línea 27; ocurrencias exactas = 1; SHA-256 `411d9879d42e2019eb12ba982f684128af4340f1d20813a9dc96e1a80bcf3332`.

```text
## Steps
```

```text
## Durable review boundary (FEAT-584)
Before feature review, settle owned attempts and supervised validations and close execution.
Unknown activity is a blocker, never evidence of an idle worktree. Persist the checkpoint,
record actual supported compaction outcome once per checkpoint/context, revalidate and start
a fresh reviewer. Unsupported contexts continue from checkpoint with an explicit reason.
Keep review criteria, adversarial checks, full lint, integration validation and ledger gates.
Changes after checkpoint require new hashes/evidence and invalidate old review coverage.
For sdd-done, preserve existing verification stamping, approval and push/merge policy;
do not run task closure again on base_branch and do not clean worktrees with unknown activity.
```

**Aplicación y motivo:** Integrar secuencia donde corresponda al flujo, sin modificar el carácter task/feature de revisiones existentes. Mantener política de aprobación/publicación del skill y checks de ledger.

### `.agent/workflows/sdd-done.md` (MODIFY)

Anchor verificado: línea 51; ocurrencias exactas = 1; SHA-256 `507aa52f585111711791e78049df9a03dcc144aacfd320f4527f20793d09ed6a`.

```text
## Steps
```

```text
## Durable review boundary (FEAT-584)
Before feature review, settle owned attempts and supervised validations and close execution.
Unknown activity is a blocker, never evidence of an idle worktree. Persist the checkpoint,
record actual supported compaction outcome once per checkpoint/context, revalidate and start
a fresh reviewer. Unsupported contexts continue from checkpoint with an explicit reason.
Keep review criteria, adversarial checks, full lint, integration validation and ledger gates.
Changes after checkpoint require new hashes/evidence and invalidate old review coverage.
For sdd-done, preserve existing verification stamping, approval and push/merge policy;
do not run task closure again on base_branch and do not clean worktrees with unknown activity.
```

**Aplicación y motivo:** Integrar secuencia donde corresponda al flujo, sin modificar el carácter task/feature de revisiones existentes. Mantener política de aprobación/publicación del skill y checks de ledger.

### `.agents/skills/sdd-codereview/SKILL.md` (MODIFY)

Anchor verificado: línea 28; ocurrencias exactas = 1; SHA-256 `9cce9d421effd1598d0dfd84d995af44e0dc0991945382570da6510d38436b2b`.

```text
## Workflow
```

```text
## Durable review boundary (FEAT-584)
Before feature review, settle owned attempts and supervised validations and close execution.
Unknown activity is a blocker, never evidence of an idle worktree. Persist the checkpoint,
record actual supported compaction outcome once per checkpoint/context, revalidate and start
a fresh reviewer. Unsupported contexts continue from checkpoint with an explicit reason.
Keep review criteria, adversarial checks, full lint, integration validation and ledger gates.
Changes after checkpoint require new hashes/evidence and invalidate old review coverage.
For sdd-done, preserve existing verification stamping, approval and push/merge policy;
do not run task closure again on base_branch and do not clean worktrees with unknown activity.
```

**Aplicación y motivo:** Integrar secuencia donde corresponda al flujo, sin modificar el carácter task/feature de revisiones existentes. Mantener política de aprobación/publicación del skill y checks de ledger.

### `.agents/skills/sdd-done/SKILL.md` (MODIFY)

Anchor verificado: línea 38; ocurrencias exactas = 1; SHA-256 `328670c7ca02a01c17c392cf84b9749b989891564ecc919a7cbaefaa81d3c4bd`.

```text
## Workflow
```

```text
## Durable review boundary (FEAT-584)
Before feature review, settle owned attempts and supervised validations and close execution.
Unknown activity is a blocker, never evidence of an idle worktree. Persist the checkpoint,
record actual supported compaction outcome once per checkpoint/context, revalidate and start
a fresh reviewer. Unsupported contexts continue from checkpoint with an explicit reason.
Keep review criteria, adversarial checks, full lint, integration validation and ledger gates.
Changes after checkpoint require new hashes/evidence and invalidate old review coverage.
For sdd-done, preserve existing verification stamping, approval and push/merge policy;
do not run task closure again on base_branch and do not clean worktrees with unknown activity.
```

**Aplicación y motivo:** Integrar secuencia donde corresponda al flujo, sin modificar el carácter task/feature de revisiones existentes. Mantener política de aprobación/publicación del skill y checks de ledger.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_done_optimization_contract.py` (CREATE)

```python
"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""
import pytest
from pathlib import Path

def test_review_variants_validate_checkpoint(tmp_path: Path) -> None:
    """Review twins require valid neutral evidence and fresh independent reviewer."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_done_variants_keep_release_gates(tmp_path: Path) -> None:
    """Done twins preserve verification/ledger/release gates and prohibit cleanup of unknown work."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError
```

**Aplicación y motivo:** Verificar semántica y secuencia en seis documentos; no obligar compactación de hosts unsupported.

### FILL IN checklist

- [ ] `.claude/commands/sdd-codereview.md` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `.claude/commands/sdd-done.md` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `.agent/workflows/sdd-codereview.md` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `.agent/workflows/sdd-done.md` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `.agents/skills/sdd-codereview/SKILL.md` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `.agents/skills/sdd-done/SKILL.md` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_done_optimization_contract.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.

## Acceptance Criteria

- [ ] AC9/AC10/AC17: contexto fresco, snapshot válido y actividad asentada antes de review/cleanup.
- [ ] Conservar lint final, revisión adversarial, severidades y blockers de release.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_done_optimization_contract.py -q`

## Test Specification

Los escenarios en los blueprints son el mínimo verificable. Usar repos/procesos sintéticos aislados, fallos de persistencia y assertions sobre resultados observables; no servicios de proveedor en suite offline. Guardar logs en artifacts/logs/. Los tests live se ejecutan aparte y nunca se presentan como pasados por una simulación.

## Agent Instructions

1. Leer `sdd/specs/sdd-execution-optimization.spec.md` y comprobar dependencias en `sdd/tasks/index/sdd-execution-optimization.json`; no usar índice monolítico.
2. Revalidar imports/anchors y convenios antes de editar. Preservar cambios de otras tareas y del usuario.
3. Implementar solo targets, completar blueprints y ejecutar Validation Commands. No rebajar ACs para cerrar la tarea.
4. Registrar evidencia y revisión; usar el flujo SDD para actualizar estado, mover active→completed y commit acotado.
5. Si falta una API o scope, registrar bloqueo/diseño pendiente; no inventar contratos ni declarar done sin evidencia.

## Completion Note

Completado 2026-09-21 por coder nativo sonnet (attempt `8cfd538850754702be7c4945298596f0`). Tocó solo
los siete targets listados (6 MODIFY + 1 CREATE):

- `.claude/commands/sdd-codereview.md`, `.claude/commands/sdd-done.md`,
  `.agent/workflows/sdd-codereview.md`, `.agent/workflows/sdd-done.md`,
  `.agents/skills/sdd-codereview/SKILL.md`, `.agents/skills/sdd-done/SKILL.md` — subsección "##
  Durable review boundary (FEAT-584)" insertada tras cada anchor verificado ('## Steps'/'##
  Workflow'), antes del primer paso numerado existente, texto idéntico byte-a-byte en los seis
  archivos: asienta attempts/validaciones propios y cierra la ejecución antes del review de
  feature; actividad desconocida es bloqueante; persistencia de checkpoint; como mucho una
  compactación registrada por checkpoint/contexto; revalidación antes de un reviewer fresco;
  continuación sin soporte con razón explícita; y, específico para sdd-done, preserva la política
  existente de stamping de verificación/aprobación/push-merge y nunca re-ejecuta el cierre de tarea
  en `base_branch` ni limpia worktrees con actividad desconocida. Ningún contenido existente
  (criterios de review, cross-check adversarial, gate de hallazgos diferidos al ledger, pasos de
  stamping de verificación, checks de bloqueo, política push/PR de hotfix) fue eliminado o alterado
  — verificado vía `git diff --stat` (10 inserciones por archivo, 0 eliminaciones, 60 total).
- `test_done_optimization_contract.py` CREATE — `test_review_variants_validate_checkpoint` y
  `test_done_variants_keep_release_gates` (mismo patrón que los tests hermanos FEAT-584 ya en este
  worktree): leen los archivos reales, verifican el heading y cada marcador requerido presente,
  verifican que el bloque precede al primer paso real, y verifican que los marcadores de gates
  preexistentes (cross-check adversarial, hallazgos diferidos/ledger, stamping de verificación,
  bloqueos de ledger, rechazo de push a main en hotfix, cleanup de worktree solo tras éxito) siguen
  presentes intactos.

Sin desviaciones del blueprint. Nada bajo `sdd/` tocado.

Validación:
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_done_optimization_contract.py -q`
  (Validation Command exacto) → 2 passed.
- Regresión adicional (no requerida): `test_done_optimization_contract.py
  test_start_optimization_contract.py test_review_handoff_contract.py -q` → 6 passed (sin ruptura
  colateral de los contract tests hermanos).
- `ruff check` → clean (lint autofix del engine: commit `04d54e7c4`).
- `git status --porcelain --untracked-files=all` limpio salvo artefactos gitignored.

Review: `coder-review:2a7b07e2b0eda6bc3c3ea5b5`.

Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: ~446s · Tokens: 153449 (subagent total, in/out no separado para native).
