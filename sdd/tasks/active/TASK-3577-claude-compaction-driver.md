# TASK-3577: Implementar driver concreto de compactación (M5b, lector de receipt)

**Feature**: FEAT-584 — Optimización medible del flujo SDD y transición compactada a revisión
**Spec**: `sdd/specs/sdd-execution-optimization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3555, TASK-3567, TASK-3568
**Assigned-to**: unassigned

## Context

Implementa M5b de la spec, decompuesta tras la enmienda Q1/M0 aplicada en el commit
`d80bb0e1b` (§R6, §3 M5, §8 Q1/Q1b). El spike M0 obligatorio (TASK-3555,
`docs/dev_loop/sdd-compaction-capabilities.md`) determinó que **no existe ninguna superficie
Python-side hacia `$.session.compact()`**: ese objeto `$` solo es alcanzable desde dentro de un
hook module registrado del propio motor Claude Code (`hooks/fast-jev.ts`'s
`on('turn.complete', ...)`), nunca desde un tool MCP, Bash o slash-command emitido por un agente.
Por lo tanto el driver de M5 se rescoge de **invocador a lector de receipt**: nunca intenta
"hacer que ocurra" una compactación (no existe llamada para ello); solo (a) verifica que la
instalación está presente por worktree, (b) emite el `WorkflowEvent` `compaction.requested` ya
declarado como marcador de intención/telemetría, y (c) intenta observar, de forma acotada y
honesta, si una compactación automática del host (disparada por su propio umbral de uso del 60%,
fuera del control de esta tarea) dejó algún receipt observable — nunca inferido `completed` por
silencio ni por ausencia de contradicción.

Baseline de contratos: dev, commit 31f4c47afc72748a387ef8a8e55d0588894668e7 (mismo baseline
declarado por las demás tareas M0–M9 de esta feature).
La optimización conserva aceptación semántica, ownership, cobertura y evidencia explícita; los
porcentajes del profiler no son ahorros garantizados.

## Scope

- Implementar `ClaudeMainLoopCompactionDriver` (`PhaseBoundaryDriver` concreto) para
  `context_id=="main"` únicamente — subagente/fork permanece `unsupported_context` (Q1b, sigue
  sin prueba de runtime; no intentar resolverlo aquí).
- Fijar el productor de `context_id` en `checkpoint.py::prepare_review_checkpoint` (único cambio
  autorizado por la enmienda fuera de los archivos nuevos: añadir `context_id="main"` al dict
  `fields` que ya construye — no relajar ningún otro campo ni firma existente).
- Investigar, de forma real y acotada (no simulada), si existe una superficie observable desde el
  rol de un coder (variable de entorno, ruta de transcript/log predecible bajo `~/.claude/` u otra
  ubicación del host) donde aparezca la línea de receipt del plugin
  (`"<percent>% reduction; ..."` / `"fallback to built-in summary (...)"`,
  `hooks/fast-jev.ts:179-190,270-289`, ya hasheado por TASK-3555). **Si no se encuentra una
  superficie real, el driver debe devolver `status="failed"` (backend="unknown") con la investigación documentada en
  el `reason` — nunca fabricar una fuente de observación ni declarar `completed` sin evidencia
  real.** Esto es un resultado honesto válido, no un fallo de la tarea.
- Cablear la referencia concreta de este driver/CLI en la sección "Compact once, between turns" del
  worker prompt (`.claude/agents/sdd-worker.md` + twin empaquetado), reemplazando el texto genérico
  actual ("the runtime's between-turn compaction call, checked for a real receipt") por el comando
  real.

**NOT in scope**: cambiar roster/scheduler, relajar sandbox/checks, modificar clients/base.py,
introducir dependencias, instalar o modificar el plugin Jev externo, resolver el direccionamiento
de subagente/fork (Q1b — spike de seguimiento separado con acceso host interactivo real), ni
declarar AC11 satisfecho — eso es responsabilidad exclusiva de TASK-3576 con evidencia de piloto
real, nunca de esta tarea de implementación de driver.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/claude_compaction_driver.py` | CREATE | `ClaudeMainLoopCompactionDriver` — `supports()`/`compact()` concretos, lector de receipt |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/checkpoint.py` | MODIFY | Añadir `context_id="main"` al dict `fields` de `prepare_review_checkpoint` (una línea) |
| `.claude/agents/sdd-worker.md` | MODIFY | Referenciar el comando/CLI real del driver en el paso "Compact once, between turns" |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` | MODIFY | Twin empaquetado — mismo cambio, byte-idéntico al canónico |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_claude_compaction_driver.py` | CREATE | Tests reales offline: gate por worktree, emisión de evento, resultado honesto `failed` (sin superficie)/`unsupported` |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Verificación estática de símbolos existentes por AST y lectura de fuentes; no presupone
importación del framework. Los imports nuevos se distinguen abajo y requieren completar sus
dependencias.

`from parrot.flows.dev_loop.sdd_coder.phase_boundary import PhaseBoundaryDriver` — verificado en
`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/phase_boundary.py:72`.

`from parrot.flows.dev_loop.sdd_coder.optimization_models import CompactionReceipt, ReviewCheckpoint, WorkflowEvent`
— verificados en `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py:149,225,320`.

`from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore` — verificado en
`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/evidence.py:154`.

`from parrot.knowledge.wiki.claude_code.compaction import compaction_status` — verificado en
`packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/compaction.py:317`.

Imports de blueprint (stdlib / dependencias instaladas / símbolos creados por esta tarea o sus
predecesoras; **no** APIs existentes inventadas):

```python
from __future__ import annotations
import asyncio
import time
from pathlib import Path
import pytest
```

Pydantic, pytest y Click ya están instalados/declarados. Verificar cualquier import adicional
(p. ej. si la investigación de la superficie de receipt requiere `os`, `subprocess` de solo
lectura, etc.) antes de introducirlo, y documentar su verificación aquí mismo en el Completion
Note si diverge de este contrato.

### Existing Signatures to Use

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/phase_boundary.py:72` · el `Protocol` a
implementar (no re-declarar, importar):

```python
class PhaseBoundaryDriver(Protocol):
    async def supports(self, context_id: str) -> bool: ...
    async def compact(self, checkpoint: ReviewCheckpoint) -> CompactionReceipt: ...
```

`packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/compaction.py:317`:

```python
def compaction_status(root: Path) -> dict[str, bool]:
    """`compaction_plugin`, `compaction_function_hooks`, `compaction_api_key` — diagnóstico de
    instalación **por worktree**; TASK-3555 confirmó que difiere entre el checkout principal y un
    worktree fresco (`.claude/settings.json` está gitignored). NUNCA se cachea entre worktrees."""
```

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py:149` (constructor
completo, campos obligatorios: `event_id`, `kind`, `execution_id`, `timestamp`, `source`,
`payload`; `kind="compaction.requested"`/`"compaction.finished"` ya están en
`_EVENT_KIND_REQUIRED_IDENTITY` con tupla vacía — sin identidad adicional obligatoria):

```python
class WorkflowEvent(OptimizationModel):
    schema_version: Literal[1] = 1
    event_id: str
    kind: str
    execution_id: str
    task_id: str | None = None
    attempt_uid: str | None = None
    job_id: str | None = None
    timestamp: datetime
    source: Literal["engine", "worker_observation", "transcript_import"]
    payload: dict[str, object] = Field(default_factory=dict)
```

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/evidence.py:163`:

```python
class ExecutionEvidenceStore:
    def __init__(self, root: Path) -> None: ...
    async def append_event(self, event: WorkflowEvent) -> EvidenceRef:
        """Append once per event_id; reject conflicting content and corruption."""
```

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/checkpoint.py:442,561-584` (firma sin
cambios; el único cambio autorizado es una entrada nueva en el dict local `fields` que ya
construye la función, en la línea `578` aproximada `user_constraints=[]`):

```python
async def prepare_review_checkpoint(
    *, feature: str, worktree: Path, execution_id: str, store: ExecutionEvidenceStore
) -> ReviewCheckpoint:
    ...
    fields: dict[str, object] = dict(
        ...,
        user_constraints=[],
        pending_actions=pending_actions,
        settlement_ref=settlement_ref,
        neutral_brief=neutral_brief,
        # AÑADIR: context_id="main" — TASK-3577, spec enmendada (main-loop únicamente por ahora)
    )
    checkpoint_id = ReviewCheckpoint.compute_checkpoint_id(**fields)
    checkpoint = ReviewCheckpoint(checkpoint_id=checkpoint_id, **fields)
```

`ReviewCheckpoint.context_id: str | None = None` (`optimization_models.py:249`) ya acepta el
valor; `compute_checkpoint_id(cls, **fields: object) -> str` (`optimization_models.py:300`) ya
acepta cualquier campo del modelo por `**kwargs` — no requiere cambio de firma.

`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py:320` — **contrato
exacto de `CompactionReceipt`, cerrado, no modificar en esta tarea** (`status` NO incluye
`"unknown"`; ese valor pertenece a `BackgroundStatus`/R8, un modelo distinto — no confundirlos):

```python
class CompactionReceipt(OptimizationModel):
    checkpoint_id: str = Field(pattern=_SHA256_HEX_PATTERN)
    context_id: str = Field(min_length=1)
    status: Literal["completed", "skipped", "unsupported", "failed", "in_progress"]
    reason: str = Field(min_length=1, max_length=2048)
    backend: Literal["jev", "builtin", "unknown"]  # "unknown" lives HERE, on backend, not status
    before_bytes: int | None = Field(default=None, ge=0)
    after_bytes: int | None = Field(default=None, ge=0)
    before_tokens: int | None = Field(default=None, ge=0)
    after_tokens: int | None = Field(default=None, ge=0)
    elapsed_ms: int = Field(ge=0)
```

**No hay valor `status="unknown"` en este modelo.** El resultado honesto de "no se encontró
superficie de receipt observable, o expiró el timeout acotado" es `status="failed"` con
`backend="unknown"` y un `reason` que documente lo investigado — nunca `status="completed"` por
ausencia de contradicción, y nunca inventar un valor de `status` fuera de los cinco listados
arriba.

### Does NOT Exist

- No existe ninguna función/tool/CLI Python-side que invoque `$.session.compact()` — confirmado
  por TASK-3555 leyendo `hooks/fast-jev.ts`/`types/claude-code.d.ts` (hashes en
  `docs/dev_loop/sdd-compaction-capabilities.md`). No inventar una.
- No existe una superficie de observación de receipt ya verificada/documentada en este repositorio
  — es responsabilidad de ESTA tarea investigarla honestamente (ver Scope) y documentar lo que
  encuentre o no encuentre, no asumir que existe.
- No existe mecanismo de reanudación propio del host (`$.session.compact()` reemplaza el
  transcript in-place; no hay checkpoint/handle de resume del host) — la continuidad usa
  `ReviewCheckpoint`/`ExecutionEvidenceStore`, ya implementados, sin cambios adicionales aquí.
- `PhaseBoundaryDriver`/`prepare_review_boundary` (`phase_boundary.py`, TASK-3568) NO se modifican
  por esta tarea — su Protocol ya soporta una implementación concreta que observa en vez de
  invoca, sin cambio de firma.

### Task-specific integration constraints

`compact()` NUNCA debe bloquear indefinidamente: cualquier espera de observación debe tener un
timeout explícito y acotado (segundos, no minutos) y degradar a `status="failed"` (backend="unknown") al expirar —
igual que R8 prohíbe inferir éxito por ausencia de contradicción. `supports()` debe evaluar
`compaction_status` contra el `worktree_root` recibido, nunca contra el checkout principal ni
cacheado entre llamadas (TASK-3555 encontró que difieren). Esta tarea NO declara ni implica que
AC11 esté satisfecho — eso requiere evidencia de piloto real que solo TASK-3576 puede aportar.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/claude_compaction_driver.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/checkpoint.py",
      "action": "MODIFY"
    },
    {
      "path": ".claude/agents/sdd-worker.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_claude_compaction_driver.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/phase_boundary.py#PhaseBoundaryDriver",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/checkpoint.py#prepare_review_checkpoint",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/compaction.py#compaction_status",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/evidence.py#ExecutionEvidenceStore.append_event"
  ]
}
```

## Implementation Notes

Async-first en MCP; I/O bloqueante fuera del event loop (usar `asyncio.to_thread` para cualquier
lectura de archivo/entorno igual que `phase_boundary.py`/`checkpoint.py` ya hacen). Pydantic v2,
Black 120 y Ruff. Core no importa parrot_tools. Los blueprints contienen decisiones acotadas
pendientes de implementación: no constituyen un Delegation Contract ni permiten entregar
placeholders. La investigación de la superficie de receipt es la parte más abierta de esta tarea
— tratarla con el mismo rigor que TASK-3555 (evidencia real, hashes/rutas citadas, o un verdict
explícito de "no encontrado" con lo que se probó).

## Implementation Blueprint

### Steps (in order)

1. Fijar `context_id="main"` en `checkpoint.py::prepare_review_checkpoint` — cambio de una línea,
   verificado contra las pruebas existentes de `test_review_checkpoint.py` (no deben romperse).
2. Implementar `ClaudeMainLoopCompactionDriver.supports()`: `context_id != "main"` ⇒ `False`
   inmediato; si no, `compaction_status(worktree_root)` — todas las claves verdaderas ⇒ `True`,
   cualquiera falsa ⇒ `False`.
3. Investigar honestamente una superficie de observación de receipt real (variables de entorno del
   proceso actual, rutas de sesión/transcript bajo `~/.claude/` u otra ubicación documentable,
   ficheros de log del plugin ya identificados por TASK-3555). Documentar el resultado —
   encontrado (con ruta/hash) o no encontrado (con lo que se probó) — en el Completion Note.
4. Implementar `compact()`: emitir `WorkflowEvent(kind="compaction.requested", ...)` vía
   `store.append_event`; si el paso 3 encontró una superficie real, observarla con timeout acotado
   y parsear a `CompactionReceipt`; si no, devolver `status="failed"` (backend="unknown") honesto de inmediato (sin
   espera artificial que simule una investigación que no ocurre). Emitir
   `WorkflowEvent(kind="compaction.finished", ...)` con el resultado antes de retornar.
5. Cablear el CLI/comando real (si el paso 3 produce uno invocable, p. ej. un pequeño script
   `scripts/sdd/...` o una función expuesta) en la sección "Compact once, between turns" de
   `.claude/agents/sdd-worker.md` + twin, reemplazando el texto genérico actual por instrucciones
   concretas y honestas sobre lo que el driver puede y no puede hacer.

### `claude_compaction_driver.py` (CREATE)

```python
"""Concrete PhaseBoundaryDriver for the main Claude Code conversation (M5b).

Spec `sdd/specs/sdd-execution-optimization.spec.md` R6/M5 (enmienda tras TASK-3555). This driver
NEVER calls `$.session.compact()` -- no such call surface exists outside a registered Claude Code
plugin hook. It only (a) gates on `compaction_status(worktree_root)`, (b) emits the
`compaction.requested` marker event, and (c) makes a bounded, honest attempt to observe whatever
real surface this task's own investigation found -- degrading to `status="failed"` (backend="unknown") rather than
ever inferring `completed` from silence.
"""
from __future__ import annotations
from pathlib import Path
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.optimization_models import CompactionReceipt, ReviewCheckpoint

class ClaudeMainLoopCompactionDriver:
    """PhaseBoundaryDriver: main-loop only, receipt reader, never an invoker."""

    def __init__(self, *, worktree_root: Path, store: ExecutionEvidenceStore) -> None:
        """Bind the worktree whose compaction_status this instance evaluates -- never cached across worktrees."""
        # FILL IN

    async def supports(self, context_id: str) -> bool:
        """True only for context_id=='main' AND compaction_status(worktree_root) fully installed."""
        # FILL IN

    async def compact(self, checkpoint: ReviewCheckpoint) -> CompactionReceipt:
        """Emit compaction.requested, attempt a bounded honest observation, emit compaction.finished, return receipt."""
        # FILL IN: never a blind retry, never completed-by-silence, never a fabricated observation surface.
        raise NotImplementedError
```

**Aplicación y motivo:** el driver concreto que M5a (`phase_boundary.py`) esperaba desde TASK-3568;
lector de receipt honesto, nunca invocador — cierra la brecha que el spike M0 encontró sin
inventar una API que no existe.

### `test_claude_compaction_driver.py` (CREATE)

```python
"""Regression scenarios for FEAT-584 M5b; use isolated fixtures, never live providers."""
import pytest
from pathlib import Path

def test_supports_gates_on_context_and_per_worktree_installation(tmp_path: Path) -> None:
    """context_id != 'main' is always False; 'main' follows compaction_status(worktree_root) exactly, never cached."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_compact_emits_requested_and_finished_events(tmp_path: Path) -> None:
    """Both WorkflowEvents are durably appended via store.append_event, in order, before compact() returns."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError

def test_honest_failed_never_inferred_completed(tmp_path: Path) -> None:
    """Absent a real observable receipt surface (or on a bounded-timeout expiry), status is 'failed' (backend='unknown'), never 'completed'."""
    # FILL IN: arrange the scenario, invoke the public boundary and assert the stated invariant.
    raise NotImplementedError
```

**Aplicación y motivo:** los tres escenarios mínimos verificables del blueprint; ninguno depende de
un host Claude Code real ni asume que la investigación del paso 3 tuvo éxito — el `failed` honesto
es un resultado igualmente probado.

### FILL IN checklist

- [ ] `claude_compaction_driver.py` — completar el bloque y sus decisiones conforme al scope/AC;
  verificar integraciones reales y eliminar todos los placeholders de implementación.
- [ ] `checkpoint.py` — añadir `context_id="main"` sin tocar ningún otro campo/comportamiento.
- [ ] `.claude/agents/sdd-worker.md` + twin — referenciar el mecanismo real del driver.
- [ ] `test_claude_compaction_driver.py` — completar el bloque y sus decisiones conforme al
  scope/AC; verificar integraciones reales y eliminar todos los placeholders de implementación.

## Acceptance Criteria

- [ ] `supports()` nunca es `True` para un `context_id` distinto de `"main"`.
- [ ] `compaction_status` se evalúa por el `worktree_root` recibido, nunca cacheado ni asumido del
  checkout principal.
- [ ] `compact()` emite `compaction.requested` y `compaction.finished` de forma durable antes de
  retornar, en ambos casos (superficie encontrada o no).
- [ ] Ningún resultado `completed` se produce sin una observación real y documentada; ausencia de
  superficie o timeout produce `status="failed"` (backend="unknown"), nunca inferido `completed` por silencio.
- [ ] `checkpoint.py::prepare_review_checkpoint` sigue pasando `test_review_checkpoint.py` sin
  modificación de ningún otro campo/comportamiento tras añadir `context_id`.
- [ ] Esta tarea NO declara AC11 satisfecho — solo entrega la maquinaria; TASK-3576 decide con
  evidencia de piloto real.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_claude_compaction_driver.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_phase_boundary.py -q`

## Test Specification

Los escenarios en los blueprints son el mínimo verificable. Usar repos/procesos sintéticos
aislados, fallos de persistencia y assertions sobre resultados observables; no servicios de
proveedor en suite offline. Guardar logs en artifacts/logs/. Los tests live se ejecutan aparte y
nunca se presentan como pasados por una simulación.

## Agent Instructions

1. Leer `sdd/specs/sdd-execution-optimization.spec.md` (R6/M5 enmendados) y comprobar dependencias
   en `sdd/tasks/index/sdd-execution-optimization.json`; no usar índice monolítico.
2. Revalidar imports/anchors y convenios antes de editar. Preservar cambios de otras tareas y del
   usuario.
3. Implementar solo targets, completar blueprints y ejecutar Validation Commands. No rebajar ACs
   para cerrar la tarea. Un resultado honesto `failed`/superficie-no-encontrada NO es rebajar un
   AC — es exactamente lo que el contrato pide.
4. Registrar evidencia y revisión; usar el flujo SDD para actualizar estado, mover active→completed
   y commit acotado.
5. Si falta una API o scope, registrar bloqueo/diseño pendiente; no inventar contratos ni declarar
   done sin evidencia.

## Completion Note

Pendiente de ejecución. Registrar autor, fecha, evidencia, validaciones y desviaciones; no rellenar
con éxito anticipado.
