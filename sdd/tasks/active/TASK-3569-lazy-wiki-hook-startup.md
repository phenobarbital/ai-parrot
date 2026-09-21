# TASK-3569: Diferir ADR y medir arranque del hook wiki

**Feature**: FEAT-584 — Optimización medible del flujo SDD y transición compactada a revisión
**Spec**: `sdd/specs/sdd-execution-optimization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implementa M9 / R9 de la spec aprobada. Baseline de contratos: dev, commit 31f4c47afc72748a387ef8a8e55d0588894668e7.
La optimización conserva aceptación semántica, ownership, cobertura y evidencia explícita; los porcentajes del profiler no son ahorros garantizados.

## Scope

- Registrar ADR lazy conservando CLI y stdout protocolar del hook.
- Medir cold/warm por proceso; no modificar hook.py salvo que se amplíe explícitamente el scope por hallazgo verificado.

**NOT in scope**: cambiar roster/scheduler, relajar sandbox/checks, modificar clients/base.py, introducir dependencias o realizar cambios fuera de los targets. El adaptador específico de host queda diferido por Q1 salvo enmienda aprobada posterior.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/lazy_commands.py` | CREATE | Preservar callback, help, options, errors y completion; si se necesita override invoke/parse_args, tiparlo y testear contra grupo real |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | La ruta claude_hook debe importar solo lo necesario |
| `packages/ai-parrot/tests/knowledge/wiki/test_hook_startup.py` | CREATE | Subprocess real, no medir callback ya importado |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Verificación estática de símbolos existentes por AST y lectura de fuentes; no presupone importación del framework. Los imports nuevos se distinguen abajo y requieren completar sus dependencias.

`from parrot.knowledge.wiki.cli import wiki` — verificado en `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:1371`.

`from parrot.knowledge.wiki.cli import claude_hook` — verificado en `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:5137`.

`from parrot.knowledge.wiki.decisions.cli import adr` — verificado en `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/cli.py:122`.

`from parrot.knowledge.wiki.claude_code.hook import run_pre_tool_use_hook` — verificado en `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/hook.py:222`.

Imports de blueprint (stdlib / dependencias instaladas / símbolos creados por esta tarea o sus predecesoras; **no** APIs existentes inventadas):

```python
from __future__ import annotations
from pathlib import Path
import click
import pytest
```
Pydantic, pytest y Click ya están instalados/declarados; módulos optimization_models/evidence/checkpoint/inspection_models nuevos solo se importan después de sus tareas productoras. Verificar cualquier import adicional antes de introducirlo.

### Existing Signatures to Use

`packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:1371` · SHA-256 `5008aefeee3906edb8dce008776150102ddf9bbd41aa6c249af05e025859cff8`

```python
def wiki(ctx: click.Context, verbose: bool) -> None:
```

`packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:5137` · SHA-256 `5008aefeee3906edb8dce008776150102ddf9bbd41aa6c249af05e025859cff8`

```python
def claude_hook() -> None:
```

`packages/ai-parrot/src/parrot/knowledge/wiki/decisions/cli.py:122` · SHA-256 `55c95907bdbb7ed45dd47d7fb0c8b9eb3995f5aafa08be9b96375866c6864b3b`

```python
def adr() -> None:
```

`packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/hook.py:222` · SHA-256 `ad547ef7ee1b6b06efbcee27e826c702e3383d74dcf8c687b1c950e2d2ee2af2`

```python
def run_pre_tool_use_hook(
    stdin: Optional[TextIO] = None,
    stdout: Optional[TextIO] = None,
) -> int:
```

### Does NOT Exist

- Los símbolos nuevos declarados en los blueprints no existen en el baseline; no confundir contrato propuesto con API instalada.
- No existe un bridge genérico que convierta PID/Bash externo en receipt autoritativo ni una llamada MCP verificada para compactar cualquier subagente.
- No existe garantía de éxito por log vacío, instalación Jev o respuesta background inmediata.

### Task-specific integration constraints

Baseline actualizado durante planificación: 121090047 difiere anotaciones AbstractClient; d454a65e0 elimina imports eager de pandas/PythonREPLTool y 92c3c7dce difiere aiohttp en documents.py. El informe 785e4a10b marca el hotfix del hook hecho y aporta ~0,32s, no los 2,05s originales. Esos cambios ya existen: NO reimplementarlos ni tocar clients/base.py/documents.py. La spec aprobada aún pide registro ADR lazy y pruebas de compatibilidad/imports: medir primero el beneficio residual sobre esta base y reportar honestamente si no alcanza 300ms. No atribuir al trabajo nuevo el ahorro de los commits previos.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/lazy_commands.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_hook_startup.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/hook.py#run_pre_tool_use_hook",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#claude_hook",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#wiki",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/cli.py#adr"
  ]
}
```

## Implementation Notes

Async-first en MCP; I/O bloqueante fuera del event loop. CLI síncrono permitido. Pydantic v2, Black 120 y Ruff. Core no importa parrot_tools. Los blueprints contienen decisiones acotadas pendientes de implementación: no constituyen un Delegation Contract ni permiten entregar placeholders.

## Implementation Blueprint

### Steps (in order)

1. Copiar contrato Click visible sin import eager: evitar cadena pesada.
2. Delegar carga real solo en ruta ADR: preservar semántica.
3. Ejecutar subprocess y regresión de comandos: medir coste total y protocolo.

### `packages/ai-parrot/src/parrot/knowledge/wiki/lazy_commands.py` (CREATE)

```python
"""Lazy ADR registration preserving the real Click command contract."""
from __future__ import annotations
import click

class LazyAdrGroup(click.Group):
    """Load decisions.cli only when the ADR command tree is actually used."""
    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        """Delegate ADR subcommand resolution to the lazily imported group."""
        # FILL IN: import/cache real group; preserve context/callback/options.
        raise NotImplementedError

    def list_commands(self, ctx: click.Context) -> list[str]:
        """List real ADR commands for ADR help/completion, never hook startup."""
        # FILL IN: delegate to cached real group only on the ADR branch.
        raise NotImplementedError
```

**Aplicación y motivo:** Preservar callback, help, options, errors y completion; si se necesita override invoke/parse_args, tiparlo y testear contra grupo real. No cargar ADR recorriendo todos los grupos en fast path.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)

Anchor verificado: línea 2250; ocurrencias exactas = 1; SHA-256 `5008aefeee3906edb8dce008776150102ddf9bbd41aa6c249af05e025859cff8`.

```text
from parrot.knowledge.wiki.decisions.cli import adr as _adr_group
```

```python
# Replace eager ADR import/registration with LazyAdrGroup(name="adr", ...).
# Preserve visible help from the verified ADR group without importing it.
# Keep business callbacks and all other command registration unchanged.
```

**Aplicación y motivo:** La ruta claude_hook debe importar solo lo necesario. Revalidar CLI al ejecutar: hay trabajo concurrente del usuario en wiki. No tocar servicio ADR ni clients/base.py.

### `packages/ai-parrot/tests/knowledge/wiki/test_hook_startup.py` (CREATE)

```python
"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""
import pytest
from pathlib import Path

def test_hook_process_protocol_and_imports(tmp_path: Path) -> None:
    """A fresh hook process emits only protocol JSON and does not import ADR service, pandas or clients.base."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_adr_help_options_and_completion(tmp_path: Path) -> None:
    """Lazy ADR delegates every subcommand with unchanged callback, options, help and completion."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_warm_process_startup(tmp_path: Path) -> None:
    """Twenty warm filesystem process launches report median below 300ms, p95 and a separate cold observation."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError
```

**Aplicación y motivo:** Subprocess real, no medir callback ya importado. Invocar cada subcomando en fixtures/mocks de servicios sin escrituras externas. Si fast path sigue lento, causa documentada y rollout off; no omitir regresión funcional.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/lazy_commands.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_hook_startup.py` — completar el bloque y sus decisiones conforme al scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.

## Acceptance Criteria

- [ ] AC23: ruta hook no carga ADR/client/pandas por registro; ayuda y subcomandos compatibles.
- [ ] 20 arranques warm, p50<300ms o rollout desactivado con causa; reportar p95/cold y runner.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_hook_startup.py -q`

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
