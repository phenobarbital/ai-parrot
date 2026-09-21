# TASK-3572: Actualizar sdd-start y workers Codex/Antigravity

**Feature**: FEAT-584 — Optimización medible del flujo SDD y transición compactada a revisión
**Spec**: `sdd/specs/sdd-execution-optimization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3566, TASK-3568
**Assigned-to**: unassigned

## Context

Implementa M6 start/hosts de la spec aprobada. Baseline de contratos: dev, commit 31f4c47afc72748a387ef8a8e55d0588894668e7.
La optimización conserva aceptación semántica, ownership, cobertura y evidencia explícita; los porcentajes del profiler no son ahorros garantizados.

## Scope

- Aplicar cierre determinista y consulta acotada en los cinco puntos de entrada.
- Respetar host capabilities y fallback sin engine, sin instalar ni simular Jev.

**NOT in scope**: cambiar roster/scheduler, relajar sandbox/checks, modificar clients/base.py, introducir dependencias o realizar cambios fuera de los targets. El adaptador específico de host queda diferido por Q1 salvo enmienda aprobada posterior.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-start.md` | MODIFY | Reemplazar cierre mecánico existente en su sección, conservando checks y referencias al índice por spec |
| `.agent/workflows/sdd-start.md` | MODIFY | Reemplazar cierre mecánico existente en su sección, conservando checks y referencias al índice por spec |
| `.agents/skills/sdd-start/SKILL.md` | MODIFY | Reemplazar cierre mecánico existente en su sección, conservando checks y referencias al índice por spec |
| `.codex/agents/sdd-worker.toml` | MODIFY | Insertar instrucciones dentro del valor TOML de instrucciones; preservar sintaxis y capacidades Codex, no copiar frontmatter Markdown. |
| `.agent/agents/sdd-worker/agent.md` | MODIFY | Actualizar cierre y frontera feature con unsupported_host explícito; no exigir MCP inexistente. |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py` | CREATE | Parsear TOML con stdlib tomllib; verificar contratos entre tres skills/workflows y dos workers. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Verificación estática de símbolos existentes por AST y lectura de fuentes; no presupone importación del framework. Los imports nuevos se distinguen abajo y requieren completar sus dependencias.

`from scripts.sdd.select_tests import main` — verificado en `scripts/sdd/select_tests.py:40`.

Imports de blueprint (stdlib / dependencias instaladas / símbolos creados por esta tarea o sus predecesoras; **no** APIs existentes inventadas):

```python
from pathlib import Path
import pytest
```
Pydantic, pytest y Click ya están instalados/declarados; módulos optimization_models/evidence/checkpoint/inspection_models nuevos solo se importan después de sus tareas productoras. Verificar cualquier import adicional antes de introducirlo.

### Existing Signatures to Use

`scripts/sdd/select_tests.py:40` · SHA-256 `0b34397c539488dd47fef5cdb6eb06ef38c59c2672a82acf2adc8ac6e3603e9f`

```python
def main(argv: list[str] | None = None) -> int:
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
      "path": ".claude/commands/sdd-start.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-start.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-start/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".codex/agents/sdd-worker.toml",
      "action": "MODIFY"
    },
    {
      "path": ".agent/agents/sdd-worker/agent.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:scripts/sdd/select_tests.py#main"
  ]
}
```

## Implementation Notes

Async-first en MCP; I/O bloqueante fuera del event loop. CLI síncrono permitido. Pydantic v2, Black 120 y Ruff. Core no importa parrot_tools. Los blueprints contienen decisiones acotadas pendientes de implementación: no constituyen un Delegation Contract ni permiten entregar placeholders.

## Implementation Blueprint

### Steps (in order)

1. Sustituir pasos mecánicos de cierre: reducir turnos sin reducir gates.
2. Actualizar variantes host dentro de sus formatos: mantener TOML válido.
3. Verificar coherencia entre entrypoints: evitar instructions contradictorias.

### `.claude/commands/sdd-start.md` (MODIFY)

Anchor verificado: línea 256; ocurrencias exactas = 1; SHA-256 `045d2597a8571c38c639fdb9f55001ba2b206a14e3ea9f3c1586128ed49a9e92`.

```text
### 8. Mark Done (in place)
```

```text
## Deterministic task inspection and closure (FEAT-584)
Keep wiki-first and read the complete task contract through bounded references.
Prefer task-context inspection when the engine is present; fallback keeps explicit checks.
Use the existing declared test selector, environment protection and semantic delivery review.
Finalize only with structured green evidence and the exact implementation HEAD; call
python -m scripts.sdd.finalize_task, inspect returned staged paths and commit explicitly.
Reject stale evidence and divergent active/completed twins; never reset unrelated staging.
Do not compact for every task. Feature handoff uses a durable checkpoint and fresh reviewer;
Codex/Antigravity without a verified adapter report unsupported_host, never call Claude /compact.
```

**Aplicación y motivo:** Reemplazar cierre mecánico existente en su sección, conservando checks y referencias al índice por spec. No crear twins .codex/skills: no existen en este checkout.

### `.agent/workflows/sdd-start.md` (MODIFY)

Anchor verificado: línea 236; ocurrencias exactas = 1; SHA-256 `e8405e82fc12b7720092be8b388a3ddf5245f79b222e15192cb01e64e3d83006`.

```text
### 8. Mark Done (in place)
```

```text
## Deterministic task inspection and closure (FEAT-584)
Keep wiki-first and read the complete task contract through bounded references.
Prefer task-context inspection when the engine is present; fallback keeps explicit checks.
Use the existing declared test selector, environment protection and semantic delivery review.
Finalize only with structured green evidence and the exact implementation HEAD; call
python -m scripts.sdd.finalize_task, inspect returned staged paths and commit explicitly.
Reject stale evidence and divergent active/completed twins; never reset unrelated staging.
Do not compact for every task. Feature handoff uses a durable checkpoint and fresh reviewer;
Codex/Antigravity without a verified adapter report unsupported_host, never call Claude /compact.
```

**Aplicación y motivo:** Reemplazar cierre mecánico existente en su sección, conservando checks y referencias al índice por spec. No crear twins .codex/skills: no existen en este checkout.

### `.agents/skills/sdd-start/SKILL.md` (MODIFY)

Anchor verificado: línea 29; ocurrencias exactas = 1; SHA-256 `efde63779f9b211bcbfe02014e095520bf6ced173f6bfdc5e23835d47d2f3dc4`.

```text
## Workflow
```

```text
## Deterministic task inspection and closure (FEAT-584)
Keep wiki-first and read the complete task contract through bounded references.
Prefer task-context inspection when the engine is present; fallback keeps explicit checks.
Use the existing declared test selector, environment protection and semantic delivery review.
Finalize only with structured green evidence and the exact implementation HEAD; call
python -m scripts.sdd.finalize_task, inspect returned staged paths and commit explicitly.
Reject stale evidence and divergent active/completed twins; never reset unrelated staging.
Do not compact for every task. Feature handoff uses a durable checkpoint and fresh reviewer;
Codex/Antigravity without a verified adapter report unsupported_host, never call Claude /compact.
```

**Aplicación y motivo:** Reemplazar cierre mecánico existente en su sección, conservando checks y referencias al índice por spec. No crear twins .codex/skills: no existen en este checkout.

### `.codex/agents/sdd-worker.toml` (MODIFY)

Anchor verificado: línea 93; ocurrencias exactas = 1; SHA-256 `c4b8f64a7cf56225bccba3ae14365d837f7c75e681bdee5e268b7cc237abb2e6`.

```text
9. Close the task with scripts/sdd/close_task.sh TASK-NNN <feature-slug> verified.
```

```text
## Deterministic task inspection and closure (FEAT-584)
Keep wiki-first and read the complete task contract through bounded references.
Prefer task-context inspection when the engine is present; fallback keeps explicit checks.
Use the existing declared test selector, environment protection and semantic delivery review.
Finalize only with structured green evidence and the exact implementation HEAD; call
python -m scripts.sdd.finalize_task, inspect returned staged paths and commit explicitly.
Reject stale evidence and divergent active/completed twins; never reset unrelated staging.
Do not compact for every task. Feature handoff uses a durable checkpoint and fresh reviewer;
Codex/Antigravity without a verified adapter report unsupported_host, never call Claude /compact.
```

**Aplicación y motivo:** Insertar instrucciones dentro del valor TOML de instrucciones; preservar sintaxis y capacidades Codex, no copiar frontmatter Markdown.

### `.agent/agents/sdd-worker/agent.md` (MODIFY)

Anchor verificado: línea 273; ocurrencias exactas = 1; SHA-256 `eb861168d46af2188fa86558ce9edb3446411d10d7d7fe9ae3984688b3beef67`.

```text
### g) Update SDD State (in worktree, alongside code — FEAT-145)
```

```text
## Deterministic task inspection and closure (FEAT-584)
Keep wiki-first and read the complete task contract through bounded references.
Prefer task-context inspection when the engine is present; fallback keeps explicit checks.
Use the existing declared test selector, environment protection and semantic delivery review.
Finalize only with structured green evidence and the exact implementation HEAD; call
python -m scripts.sdd.finalize_task, inspect returned staged paths and commit explicitly.
Reject stale evidence and divergent active/completed twins; never reset unrelated staging.
Do not compact for every task. Feature handoff uses a durable checkpoint and fresh reviewer;
Codex/Antigravity without a verified adapter report unsupported_host, never call Claude /compact.
```

**Aplicación y motivo:** Actualizar cierre y frontera feature con unsupported_host explícito; no exigir MCP inexistente.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py` (CREATE)

```python
"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""
import pytest
from pathlib import Path

def test_start_twins_preserve_semantic_gates(tmp_path: Path) -> None:
    """Every start variant requires semantic green evidence before deterministic closure."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_host_variants_remain_honest(tmp_path: Path) -> None:
    """Codex TOML parses and unsupported hosts do not advertise Claude compaction."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError
```

**Aplicación y motivo:** Parsear TOML con stdlib tomllib; verificar contratos entre tres skills/workflows y dos workers.

### FILL IN checklist

- [ ] `.claude/commands/sdd-start.md` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `.agent/workflows/sdd-start.md` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `.agents/skills/sdd-start/SKILL.md` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `.codex/agents/sdd-worker.toml` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `.agent/agents/sdd-worker/agent.md` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.

## Acceptance Criteria

- [ ] AC8/AC17: solo cerrar con revisión y checks ligados al SHA; twins conservan reglas de seguridad.
- [ ] AC12/AC13: unsupported_host explícito y sin compaction por tarea.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py -q`

## Test Specification

Los escenarios en los blueprints son el mínimo verificable. Usar repos/procesos sintéticos aislados, fallos de persistencia y assertions sobre resultados observables; no servicios de proveedor en suite offline. Guardar logs en artifacts/logs/. Los tests live se ejecutan aparte y nunca se presentan como pasados por una simulación.

## Agent Instructions

1. Leer `sdd/specs/sdd-execution-optimization.spec.md` y comprobar dependencias en `sdd/tasks/index/sdd-execution-optimization.json`; no usar índice monolítico.
2. Revalidar imports/anchors y convenios antes de editar. Preservar cambios de otras tareas y del usuario.
3. Implementar solo targets, completar blueprints y ejecutar Validation Commands. No rebajar ACs para cerrar la tarea.
4. Registrar evidencia y revisión; usar el flujo SDD para actualizar estado, mover active→completed y commit acotado.
5. Si falta una API o scope, registrar bloqueo/diseño pendiente; no inventar contratos ni declarar done sin evidencia.

## Completion Note

Completado 2026-09-21 por coder nativo sonnet (attempt `a346bc66cb4847c3981e257ecd006fc3`). Tocó solo
los seis targets listados (5 MODIFY + 1 CREATE):

- `.claude/commands/sdd-start.md`, `.agent/workflows/sdd-start.md`,
  `.agents/skills/sdd-start/SKILL.md`, `.codex/agents/sdd-worker.toml`,
  `.agent/agents/sdd-worker/agent.md` — bloque "## Deterministic task inspection and closure
  (FEAT-584)" del blueprint insertado tras cada anchor verificado byte-a-byte, como una nueva
  subsección preliminar, sin borrar/reescribir los pasos existentes — mismo patrón establecido por
  TASK-3570/3571 (ya mergeadas, verificadas primero en este worktree). Para el TOML (host Codex)
  confirmado parseable con `tomllib` stdlib, sin referencias `mcp__...` que ese host no puede
  invocar. Para `agent.md` (Antigravity, sin MCP) confirmado que sigue sin referencias `mcp__` y que
  el lenguaje `unsupported_host`/"never call Claude /compact" satisface AC12/AC13 también para ese
  host.
- `test_start_optimization_contract.py` CREATE — `test_start_twins_preserve_semantic_gates`
  (bloque de cierre y sus marcadores presentes en los cuatro twins Markdown; referencias
  preexistentes a `close_task.sh`/índice per-spec y el invariante sin-MCP de `agent.md`
  sobreviven) y `test_host_variants_remain_honest` (parsea el TOML Codex con `tomllib`, asserts
  `unsupported_host` + "never call Claude /compact" + "Do not compact for every task." + sin
  referencia `mcp__` en TOML y agent.md).

Interpretación flagueada por el coder (aceptada, consistente con el precedente ya mergeado): el
blueprint no especificaba nivel de línea más allá de "insertar" vs "reemplazar"; se resolvió
insertando como nueva subsección (preservando "conservando checks y referencias al índice por
spec" literalmente) en vez de una reescritura mayor que sustituya el bloque mecánico close_task.sh/
jq por una llamada a `finalize_task` (eso ocurrió solo dentro de `sdd-worker.md` por TASK-3570, un
archivo distinto fuera del scope de esta tarea). No se tocó `.claude/agents/sdd-worker.md` (ya
cubierto por TASK-3570) ni ningún twin `.codex/skills` (no existe en este checkout).

Sin desviaciones fuera de lo flagueado. Nada bajo `sdd/` tocado.

Validación:
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py -q`
  (Validation Command exacto) → 2 passed.
- `python3 -c "import tomllib; tomllib.load(open('.codex/agents/sdd-worker.toml','rb'))"` → parsea
  limpio.
- `ruff check` → clean.
- `git status --porcelain --untracked-files=all` limpio salvo artefactos gitignored.

Review: `coder-review:dd3b967bc35193753d7cafce`.

Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: ~397s · Tokens: 144478 (subagent total, in/out no separado para native).
