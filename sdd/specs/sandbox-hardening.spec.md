---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Sandbox Hardening — PythonREPLTool a worker persistente

**Feature ID**: FEAT-380
**Date**: 2026-07-27
**Author**: Jesus Lara
**Status**: draft
**Target version**: TBD (next minor)
**Brainstorm**: `sdd/proposals/sandbox-hardening.brainstorm.md` (Recommended Option: B)

---

## 1. Motivation & Business Requirements

### Problem Statement

`PythonREPLTool` ejecuta código generado por un LLM **dentro del proceso del
servidor**, vía `exec()` / `eval()` sobre `self.locals` (`pythonrepl.py:765-825`).
La defensa actual es análisis estático en dos capas antes de ejecutar: un
allowlist (`PythonCodeSanitizer(general_profile())`, `pythonrepl.py:231-233`) y
un denylist AST (`_check_ast_security()`, `:558`). Es una defensa bien
construida, pero hay una **categoría de problema que el análisis estático no
puede tocar**:

- **No hay timeout, ni límite de memoria, ni límite de CPU.** La ejecución se
  despacha con `loop.run_in_executor(None, ...)` (`pythonrepl.py:970`) — el
  ThreadPoolExecutor compartido por defecto. Un bucle no acotado pasa el
  allowlist y el walk AST (es código legítimo), y al ejecutarse **secuestra
  permanentemente un hilo del pool compartido** — en Python un hilo no se puede
  matar desde fuera. Una asignación de memoria desmedida no mata al "sandbox":
  mata al **proceso padre** y con él todas las sesiones concurrentes. No hace
  falta un atacante: basta un bucle mal generado por el propio LLM, un modo de
  fallo rutinario en análisis de datos iterativo.
- **Radio de explosión**: in-process significa que el código del LLM comparte
  espacio de memoria con credenciales y `os.environ`, los pools de conexión de
  `asyncdb`, los DataFrames de otras sesiones en `ToolManager._shared` y las
  superficies nativas de numpy/pandas/matplotlib.
- **Tensión estructural del denylist**: el bloqueo por nombre de atributo no
  tiene información de tipo (`rename`/`replace`/`remove` tuvieron que salir de
  `BLOCKED_ATTRIBUTES` por colisión con pandas — `pythonrepl.py:146-151`).

**Solución (decidida en brainstorm, Option B)**: un proceso worker persistente
por sesión que mantiene el namespace del REPL. El host envía código por un
canal de control; el worker arranca con `preexec_fn` aplicando `setrlimit`
(memoria, CPU, ficheros, sin core dumps). El timeout se implementa donde sí
funciona: `SIGKILL` al hijo.

### Goals

- **G1 (C1)** — El estado del REPL sobrevive entre llamadas: variables de
  usuario, `execution_results` y DataFrames inyectados persisten en el worker.
- **G2 (C2)** — Timeout duro y aplicable: toda ejecución puede terminarse por
  la fuerza (`SIGKILL` al worker).
- **G3 (C3)** — Límite de memoria por sesión: una asignación desmedida mata al
  worker, nunca al servidor.
- **G4 (C4)** — Latencia comparable a la actual: el coste de importar
  pandas/numpy/matplotlib/seaborn (1–3 s) se paga una vez por sesión; con el
  pool pre-calentado (incluido en v1), ni eso.
- **G5 (C5)** — Contrato de salida idéntico: string en éxito, dict
  `{status, result, error}` en error/bloqueo, clasificación vía
  `_ERROR_OUTPUT_RE`. El LLM y el framework dependen de esa forma.
- **G6 (C6)** — El análisis estático se conserva íntegro y corre en **ambos
  lados** (host y worker). La frontera de proceso es una capa adicional.
- **G7 (C7)** — Aislamiento por sesión: un worker por sesión; el código de un
  usuario no alcanza el namespace de otro.
- **G8 (C8)** — Degradación explícita: si el worker no arranca, error claro.
  **Nunca** fallback silencioso a `exec()` in-process.
- **G9 (C9)** — Transferencia de DataFrames sin copia costosa: Arrow IPC /
  memoria compartida; pickle solo como fallback con warning.
- **G10** — Paliativo inmediato (decidido en brainstorm): executor dedicado y
  acotado en `pythonrepl.py:970` que aterriza en `dev` antes del resto de la
  feature.

### Non-Goals (explicitly out of scope)

- **Frontera de seguridad completa / contención adversarial.** El worker
  comparte kernel, red y FS con el host. Se compra acotación de recursos y
  radio de explosión, no contención de un atacante dirigido. El contenedor por
  sesión (Option C del brainstorm) queda como evolución futura — C es
  literalmente B dentro de un contenedor, la puerta queda abierta.
- **Endurecimiento in-process (Option A)** — rechazada en brainstorm: un
  watchdog no puede matar un hilo de Python; `setrlimit` sin frontera de
  proceso apunta al servidor. Ver `proposals/sandbox-hardening.brainstorm.md`.
- **`shell-rtk-integration`** — escindida (2026-07-27) a su propio brainstorm:
  `sdd/proposals/shelltool-hardening.brainstorm.md`. Nada de `ShellTool`/rtk
  en esta spec.
- **rlimits en Windows** — v1 es POSIX completo; en Windows el worker corre en
  proceso separado con timeout duro + terminate, sin rlimits de memoria/CPU
  (documentado de forma visible). Job Objects como seguimiento futuro.
- **Compresión de `ToolResult`** — congelada as-is por decisión del equipo
  hasta que esta feature aterrice (colisión conocida en
  `tools/manager.py` y `tools/pythonpandas.py`).
- **Dict-proxy de compatibilidad para `tool.locals`** — descartado
  explícitamente (round-trips por clave, semántica de iteración sutil, la
  referencia viva rompería igual en silencio). Se porta cada call site a la
  API de namespace.

---

## 2. Architectural Design

### Overview

Un proceso hijo de vida larga **por sesión** (spawn, nunca fork) que mantiene
el namespace del REPL. El host conserva el gate estático completo
(sanitizer allowlist + denylist AST) y lo revalida el worker antes de `exec`
— defensa en profundidad, decidido en brainstorm: el host falla barato sin
round-trip; el worker protege incluso si un caller futuro llega sin pasar por
la ruta del host.

`_execute_code()` (`pythonrepl.py:701`) se **mueve tal cual** al worker; es el
corazón y no se reescribe. `_describe_new_var()` (`:871`) también corre en el
worker (inspecciona objetos vivos); solo viaja el texto. El contrato de
retorno de `_execute()` (`:955-985`) es invariante (G5).

Decisiones de diseño ya resueltas (brainstorm 2026-07-27):

- **Gate estático**: corre en ambos lados (host + worker).
- **Closures del namespace** (`save_current_plot`): **worker autónomo** — se
  recrean en el worker apuntando a un directorio compartido visible por ambos
  lados; solo viaja la ruta (o base64 si `return_plot_as_base64`). Sin canal
  RPC worker→host: debilitaría la frontera por comodidad.
- **Acceso al namespace desde el host**: `tool.locals`/`.globals` dejan de ser
  fuente de verdad. Se introduce una **API de namespace explícita**
  (`get_var` / `set_var` / `list_vars` / `snapshot`) respaldada por el
  protocolo del worker, y se portan los 5 call sites auditados (ver §6).
- **Pool de pre-calentado**: incluido en v1, tamaño configurable, default
  pequeño. Primera llamada pasa de 1–3 s a milisegundos.
- **Techo y TTL**: rechazo inmediato con error claro al alcanzar el techo
  (sin cola indefinida). Defaults: techo `max(4, cpu_count)` con tope ~16;
  TTL de inactividad 30 min. Configurables por despliegue.
- **Pérdida de namespace tras kill**: error estructurado `{status, result,
  error}` con causa **diferenciada** (timeout vs memoria), aviso de que TODAS
  las variables se perdieron, la **lista de nombres** que existían (shadow
  barato de solo-nombres en el host vía `list_ns`) y la instrucción de
  recrear estado antes de reintentar.
- **Paliativo inmediato**: sustituir `run_in_executor(None, ...)` por un
  `ThreadPoolExecutor` dedicado y acotado (~4 hilos) — cambio pequeño e
  independiente que aterriza en `dev` primero.

### Component Diagram

```
   HOST (proceso del servidor)                WORKER (uno por sesión)
  ┌───────────────────────────┐             ┌──────────────────────────────┐
  │ PythonREPLTool            │             │ preexec_fn: setrlimit(       │
  │  ├ PythonCodeSanitizer    │             │   AS, CPU, NOFILE, CORE=0)   │
  │  ├ _check_ast_security()  │             │                              │
  │  │  (gate estático, G6)   │             │  gate estático (revalida)    │
  │  │                        │  control    │  ns = locals del worker      │
  │  ├ WorkerHandle ──────────┼────────────►│  _execute_code() ← movido    │
  │  │   spawn / kill / health│  (pipe)     │    exec()/eval() sin cambios │
  │  │   deadline → SIGKILL   │◄────────────┤  _describe_new_var()         │
  │  │                        │             │  _serialize_execution_...()  │
  │  ├ WorkerPool             │             │  save_current_plot() →       │
  │  │   prewarm/TTL/techo    │             │    directorio compartido     │
  │  └ DataFrame injection ───┼────────────►│                              │
  │      (Arrow IPC / shm)    │             │                              │
  └───────────────────────────┘             └──────────────────────────────┘
          directorio de salida compartido (plots, reports)
```

### Control Protocol

Mensajes con longitud prefijada sobre pipe dedicado, uno por petición:

| Mensaje | Dirección | Payload |
|---|---|---|
| `exec` | host → worker | código, `debug`, `deadline_ms` |
| `result` | worker → host | `output` (str) o `{status, result, error}` — forma idéntica a hoy (G5) |
| `inject_df` | host → worker | nombre + handle de Arrow/shm |
| `get_var` / `set_var` | host → worker | nombre (+ valor serializado) — API de namespace |
| `list_ns` | host → worker | — (alimenta el shadow de nombres del host) |
| `snapshot` | host → worker | — (volcado serializable del namespace) |
| `reset` | host → worker | — (equivale a `reset_environment()`) |
| `ping` | host → worker | health check |

El `deadline_ms` viaja con la petición y **el host lo hace cumplir**: si el
worker no responde a tiempo → `SIGKILL`, ejecución marcada como expirada,
worker nuevo, y error estructurado de pérdida de namespace al LLM.

### Resource Limits (aplicados en `preexec_fn` del hijo)

| Límite | Propósito |
|---|---|
| `RLIMIT_AS` | Techo de memoria virtual — default configurable y generoso (~4 GiB); calibración empírica como tarea explícita (ver §3) |
| `RLIMIT_CPU` | Red de seguridad si el SIGKILL del host fallara |
| `RLIMIT_NOFILE` | Acota descriptores |
| `RLIMIT_CORE = 0` | Sin core dumps — un volcado con DataFrames es fuga de datos |

### Worker Lifecycle

- **Arranque perezoso**: al primer `_execute()` de la sesión, no en `__init__`.
- **Pre-calentado (v1)**: pool pequeño de workers con librerías ya importadas,
  asignados a demanda.
- **Expulsión por inactividad**: TTL configurable (default 30 min).
- **Techo de concurrencia**: default `max(4, cpu_count)`, tope ~16; superado →
  rechazo inmediato con error claro.
- **Reinicio ante crash**: worker muerto (segfault nativo, OOM) → se levanta
  otro + error estructurado de pérdida de namespace.
- **Recolección de huérfanos**: `PR_SET_PDEATHSIG` en Linux; barrido en el
  apagado como respaldo portable.
- **Método de arranque**: `spawn` obligatorio — matplotlib, los pools de
  conexión y los hilos del padre no toleran `fork`.

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/tools/pythonrepl.py` | modifies | `_execute()` (`:950-985`) pasa a hablar con el worker; `_execute_code()` (`:701`) se mueve tal cual al worker; `reset_environment()` (`:1023`) → reinicio de worker; `_bootstrapped` pasa de variable de clase a estado por worker |
| `parrot/tools/repl_worker/` | new | Paquete nuevo: entrypoint del worker, protocolo, `WorkerHandle`, `WorkerPool` |
| `parrot/tools/pythonpandas.py` | modifies | `add_dataframe()` / `df_locals` (`:122-130, :292-293`) y `clone()` (`:220-236`) pasan del dict local al transporte / API de namespace |
| `parrot/tools/manager.py` | depends on | `share_dataframe()` (`:1749`) / `auto_push_to_pandas` (`:273`) empujan DataFrames; la ruta ahora cruza proceso |
| `parrot/bots/data.py` | modifies | Consumidor principal: lecturas directas de `pandas_tool.locals` en `:1800, :2329, :2626-2628, :2655, :2743-2748, :2810-2815` → portar a la API de namespace |
| `parrot/bots/agent.py` | modifies | Working memory guarda referencia viva `wm._tool_locals[key] = tool.locals` (`:218-219`) — semántica imposible cruzando proceso; portar a snapshot/API |
| `parrot/tools/agent.py` | modifies | Escrituras host→namespace `python_repl.globals['previous_result']` (`:421-427`) → `set_var` |
| `parrot/outputs/formats/base.py` | modifies | Devuelve `tool.locals` (`:137`) → snapshot/API |
| `parrot/security/python_sanitizer.py` | unchanged | El gate se conserva íntegro (G6) |
| Configuración de despliegue | extends | Límites rlimit, deadline, TTL, techo, tamaño de pool de pre-calentado |

### Data Models

```python
# parrot/tools/repl_worker/protocol.py (nuevo)
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

class ExecRequest(BaseModel):
    """Host → worker: execute code under a deadline."""
    op: Literal["exec"] = "exec"
    code: str
    debug: bool = False
    deadline_ms: int = Field(..., gt=0)

class ExecResult(BaseModel):
    """Worker → host: mirrors today's _execute() contract (G5)."""
    op: Literal["result"] = "result"
    output: Optional[str] = None                 # success path (str)
    status: Optional[str] = None                 # "error" | "done_with_errors"
    result: Optional[Any] = None
    error: Optional[str] = None
    new_vars: list[str] = []                     # feeds host name-shadow

class NamespaceLossError(BaseModel):
    """Payload embedded in the {status, result, error} dict after a kill."""
    cause: Literal["timeout", "memory", "crash"]
    lost_variables: list[str]                    # from host name-shadow
    message: str                                 # instructs LLM to recreate state

class WorkerConfig(BaseModel):
    """Deployment-tunable limits (all with working defaults)."""
    rlimit_as_bytes: int = 4 * 1024**3           # ~4 GiB; calibration task pending
    rlimit_cpu_seconds: int = 300
    rlimit_nofile: int = 256
    deadline_ms: int = 60_000
    max_workers: int = 0                         # 0 → max(4, cpu_count), cap 16
    idle_ttl_seconds: int = 1800                 # 30 min
    prewarm_pool_size: int = 2
```

### New Public Interfaces

```python
# parrot/tools/repl_worker/handle.py (nuevo)
class WorkerHandle:
    """Host-side handle to one per-session REPL worker process."""
    async def start(self) -> None: ...
    async def execute(self, code: str, debug: bool = False) -> str | dict: ...
    async def inject_dataframe(self, name: str, df: "pd.DataFrame") -> None: ...
    async def get_var(self, name: str) -> Any: ...
    async def set_var(self, name: str, value: Any) -> None: ...
    async def list_vars(self) -> list[str]: ...
    async def snapshot(self) -> dict[str, Any]: ...
    async def reset(self) -> None: ...
    async def ping(self) -> bool: ...
    async def kill(self) -> None: ...

class WorkerPool:
    """Prewarmed pool + lifecycle (TTL eviction, ceiling, orphan reaping)."""
    async def acquire(self, session_id: str) -> WorkerHandle: ...
    async def release(self, session_id: str) -> None: ...
    async def shutdown(self) -> None: ...
```

```python
# PythonREPLTool — API de namespace que sustituye el acceso directo a .locals
class PythonREPLTool(AbstractTool):
    async def get_var(self, name: str) -> Any: ...
    async def set_var(self, name: str, value: Any) -> None: ...
    async def list_vars(self) -> list[str]: ...
    async def snapshot(self) -> dict[str, Any]: ...
```

---

## 3. Module Breakdown

> `repl-worker-runtime` (Modules 1–4) debe llegar primero: congela el
> protocolo de control y el contrato del handle. `repl-state-transport`
> (Modules 5–7) depende de ese protocolo.

### Module 1: Paliativo — executor dedicado y acotado
- **Path**: `packages/ai-parrot/src/parrot/tools/pythonrepl.py` (`:970`)
- **Responsibility**: Sustituir `run_in_executor(None, ...)` por un
  `ThreadPoolExecutor` dedicado (~4 hilos, configurable). Un bucle desbocado
  agota solo el pool del REPL, no el compartido del framework. **Aterriza en
  `dev` de inmediato, independiente del resto.**
- **Depends on**: nada.

### Module 2: Protocolo de control + entrypoint del worker
- **Path**: `packages/ai-parrot/src/parrot/tools/repl_worker/` (nuevo:
  `protocol.py`, `worker.py`)
- **Responsibility**: Mensajes Pydantic con longitud prefijada; entrypoint del
  worker (spawn) con `preexec_fn` aplicando rlimits; bucle de servicio
  `exec`/`list_ns`/`reset`/`ping`; `_execute_code()` y `_describe_new_var()`
  movidos tal cual; gate estático revalidado en el worker; bootstrap por
  worker (elimina la variable de clase `_bootstrapped`).
- **Depends on**: nada (congela el protocolo).

### Module 3: WorkerHandle + enforcement de deadline
- **Path**: `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py`
- **Responsibility**: spawn/kill/health; envío de `exec` con `deadline_ms`;
  `SIGKILL` al expirar; shadow de solo-nombres del namespace; construcción del
  error estructurado de pérdida de namespace (causa diferenciada
  timeout/memoria/crash + lista de variables perdidas).
- **Depends on**: Module 2.

### Module 4: WorkerPool — lifecycle
- **Path**: `packages/ai-parrot/src/parrot/tools/repl_worker/pool.py`
- **Responsibility**: arranque perezoso, pool de pre-calentado (v1), TTL de
  inactividad, techo con rechazo inmediato, reinicio ante crash,
  `PR_SET_PDEATHSIG` + barrido de huérfanos en apagado; `WorkerConfig` desde
  configuración de despliegue.
- **Depends on**: Module 3.

### Module 5: Integración en PythonREPLTool + API de namespace
- **Path**: `packages/ai-parrot/src/parrot/tools/pythonrepl.py`
- **Responsibility**: `_execute()` habla con el `WorkerHandle` preservando el
  contrato G5; `reset_environment()` → reinicio de worker; degradación
  explícita sin fallback in-process (G8); API pública
  `get_var`/`set_var`/`list_vars`/`snapshot`; closures recreados en el worker
  con directorio de salida compartido (plots: viaja la ruta o base64).
- **Depends on**: Modules 3–4.

### Module 6: Port de los 5 call sites del namespace
- **Path**: `parrot/bots/data.py`, `parrot/bots/agent.py`,
  `parrot/tools/agent.py`, `parrot/outputs/formats/base.py`,
  `parrot/tools/pythonpandas.py`
- **Responsibility**: portar todos los accesos directos a
  `tool.locals`/`.globals` (auditados en §6) a la API de namespace. Sin
  dict-proxy de compatibilidad (decidido).
- **Depends on**: Module 5.

### Module 7: Transporte de DataFrames (Arrow IPC / shm)
- **Path**: `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py` +
  `pythonpandas.py`, `manager.py`
- **Responsibility**: `inject_df` vía Arrow IPC sobre memoria compartida;
  fallback a pickle solo para dtypes no cubiertos por Arrow, con warning
  registrado; integración con `share_dataframe()` / `auto_push_to_pandas`.
- **Depends on**: Module 5.

### Module 8: Calibración de RLIMIT_AS
- **Path**: `artifacts/logs/` (evidencia) + defaults en `WorkerConfig`
- **Responsibility**: medir cargas reales de pandas (carga de datasets,
  merges, plots) y fijar el default definitivo de `RLIMIT_AS`. Trabajo
  empírico decidido en brainstorm — no se calibra a ojo.
- **Depends on**: Modules 2–5 operativos.

### Module 9: Documentación y configuración
- **Path**: `docs/`
- **Responsibility**: nuevo modelo de ejecución y sus modos de fallo;
  parámetros de despliegue; **documentar de forma visible la degradación en
  Windows** (proceso separado + timeout duro, sin rlimits).
- **Depends on**: Modules 1–7.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_protocol_roundtrip` | 2 | Serialización/parseo de todos los mensajes del protocolo |
| `test_worker_rlimits_applied` | 2 | El hijo arranca con AS/CPU/NOFILE/CORE=0 (POSIX) |
| `test_worker_revalidates_gate` | 2 | Código bloqueado llega al worker → rechazado antes de `exec` |
| `test_bootstrap_per_worker` | 2 | Dos workers → ambos ejecutan su bootstrap (bug de variable de clase corregido) |
| `test_deadline_sigkill` | 3 | Bucle infinito → SIGKILL al expirar `deadline_ms`, worker nuevo |
| `test_namespace_loss_error_shape` | 3 | Error tras kill: forma `{status, result, error}`, causa diferenciada, lista de variables |
| `test_memory_limit_kills_worker` | 3 | Asignación > RLIMIT_AS mata al worker, no al test runner; error de memoria ≠ error de timeout |
| `test_pool_ceiling_rejects` | 4 | Techo alcanzado → rechazo inmediato con error claro, sin cola |
| `test_pool_ttl_eviction` | 4 | Worker inactivo > TTL → expulsado |
| `test_pool_prewarm` | 4 | Worker pre-calentado asignado sin pagar import de pandas |
| `test_crash_restart` | 4 | Worker muerto inesperadamente → reinicio + error de pérdida de namespace |
| `test_orphan_reaping` | 4 | Apagado del host → cero workers vivos |
| `test_execute_contract_invariant` | 5 | String en éxito; dict en error; `_ERROR_OUTPUT_RE` clasifica igual que hoy (G5) |
| `test_no_inprocess_fallback` | 5 | Worker no arranca → error explícito, `exec()` in-process jamás invocado (G8) |
| `test_state_persists_across_calls` | 5 | Variable creada en llamada N visible en llamada N+1 (G1) |
| `test_reset_environment_restarts_worker` | 5 | `reset_environment()` → worker nuevo, namespace limpio |
| `test_plot_via_shared_dir` | 5 | `save_current_plot` escribe en dir compartido; viaja solo la ruta / base64 |
| `test_namespace_api` | 5 | `get_var`/`set_var`/`list_vars`/`snapshot` contra worker vivo |
| `test_session_isolation` | 5 | Dos sesiones → dos workers; variables de una invisible para la otra (G7) |
| `test_callsites_use_namespace_api` | 6 | Los 5 call sites portados; grep sin accesos directos a `.locals` desde el host |
| `test_df_arrow_roundtrip` | 7 | DataFrame host→worker vía Arrow sin corrupción de dtypes |
| `test_df_pickle_fallback_warns` | 7 | Dtype no-Arrow → pickle + warning registrado |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_data_analysis_session` | Sesión completa: inject_df → exec multi-turno → plot → snapshot; estado persiste |
| `test_e2e_runaway_loop_recovery` | Bucle infinito → timeout → el LLM recibe error con variables perdidas → sesión sigue usable |
| `test_e2e_pandas_agent` | `PandasAgent` (`bots/data.py`) opera end-to-end sobre la API de namespace |
| `test_e2e_concurrent_sessions` | N sesiones concurrentes bajo el techo; techo+1 rechazada |

### Test Data / Fixtures
```python
@pytest.fixture
def worker_config():
    """Low limits for fast tests."""
    return WorkerConfig(
        rlimit_as_bytes=512 * 1024**2,
        deadline_ms=2_000,
        max_workers=2,
        idle_ttl_seconds=5,
        prewarm_pool_size=0,
    )

@pytest.fixture
def sample_df():
    return pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **AC1 (G10, paliativo)**: `pythonrepl.py:970` ya no usa el executor
      compartido por defecto — pool dedicado y acotado, mergeado a `dev` como
      primer entregable independiente.
- [ ] **AC2 (G2)**: un bucle infinito generado por el LLM termina en
      `SIGKILL` al expirar `deadline_ms`; el hilo/proceso no queda perdido.
- [ ] **AC3 (G3)**: una asignación por encima de `RLIMIT_AS` mata al worker;
      el proceso servidor no se ve afectado.
- [ ] **AC4 (G1)**: variables, `execution_results` y DataFrames inyectados
      persisten entre llamadas de la misma sesión.
- [ ] **AC5 (G5)**: contrato de salida byte-compatible — string en éxito,
      `{status, result, error}` en error; `_ERROR_OUTPUT_RE` clasifica igual.
- [ ] **AC6 (G6)**: sanitizer allowlist + denylist AST corren en host **y**
      worker; código rechazado en host nunca arranca worker.
- [ ] **AC7 (G7)**: dos sesiones concurrentes usan workers distintos y no
      comparten namespace.
- [ ] **AC8 (G8)**: si el worker no arranca, la herramienta devuelve error
      explícito; `exec()` in-process es inalcanzable en esa ruta.
- [ ] **AC9 (G9)**: DataFrames viajan por Arrow IPC/shm; pickle solo como
      fallback con warning.
- [ ] **AC10 (G4)**: con pool pre-calentado, la primera ejecución de una
      sesión no paga el import de pandas (milisegundos, no 1–3 s).
- [ ] **AC11**: tras un kill (timeout o memoria), el error indica causa
      diferenciada, lista de variables perdidas e instrucción de recrear
      estado.
- [ ] **AC12**: techo de workers → rechazo inmediato con error claro;
      TTL expulsa workers inactivos; apagado del host no deja huérfanos.
- [ ] **AC13**: los 5 call sites auditados portados a la API de namespace;
      ningún acceso host directo a `PythonREPLTool.locals`/`.globals` como
      fuente de verdad.
- [ ] **AC14**: bootstrap por worker — dos instancias/sesiones ejecutan cada
      una su bootstrap (bug de `_bootstrapped` de clase corregido).
- [ ] **AC15**: default de `RLIMIT_AS` respaldado por calibración empírica
      documentada (Module 8), no fijado a ojo.
- [ ] **AC16**: degradación Windows documentada de forma visible (proceso
      separado + timeout duro; sin rlimits).
- [ ] All unit tests pass (`pytest tests/ -v`); no breaking changes en la API
      pública (respetando G5).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verificado contra HEAD de `dev` el 2026-07-27. Rutas reales:
> `packages/ai-parrot/src/parrot/...` (las rutas cortas `parrot/...` de abajo
> son relativas a ese prefijo).

### Verified Imports

```python
from parrot.security.python_sanitizer import PythonCodeSanitizer, general_profile
# verified: parrot/tools/pythonrepl.py:231 (import local dentro de __init__)
# general_profile → parrot/security/python_sanitizer.py:273
# PythonCodeSanitizer → parrot/security/python_sanitizer.py:321

from parrot.security.redaction import redact_text   # pythonrepl.py:36
```

### Existing Class Signatures

```python
# parrot/tools/pythonrepl.py (1208 líneas)
class PythonREPLTool(AbstractTool):
    name = "python_repl"                          # :100
    args_schema = PythonREPLArgs                  # :102
    _bootstrapped = False   # ← VARIABLE DE CLASE, compartida en el proceso  # :105
                            #    leída en :537, escrita en :556, reseteada :1041
    BLOCKED_IMPORTS: set    # :108 (17 módulos)
    BLOCKED_NAMES: set      # :128 (15 nombres)
    BLOCKED_ATTRIBUTES: set # :152 (~28 atributos; tensión con pandas :146-151)

    def __init__(self, locals_dict=None, globals_dict=None, report_dir=None,
                 plt_style="seaborn-v0_8-whitegrid", palette="Set2",
                 setup_code=None, sanitize_input_enabled=True,
                 auto_save_plots=True, return_plot_as_base64=False,
                 debug=False, policy=None, **kwargs): ...   # :187-201
        # self.locals = locals_dict or {}         # :244
        # self.globals = globals_dict or {}       # :245
        # self._code_sanitizer = PythonCodeSanitizer(_policy)  # :233

    def _check_ast_security(self, tree: ast.AST) -> Optional[str]: ...  # :558
    def _serialize_execution_results(self, results: Dict) -> Dict: ...  # :627
    def _execute_code(self, query: str, debug: bool = False,
                      enforce_security: bool = True) -> str: ...        # :701
        # ns = self.locals; self.globals = ns     # :765-766
        # exec(...)/eval(...) sobre ns            # :773, :786, :803, :825
    def _describe_new_var(self, var_name: str, val: Any) -> str: ...    # :871
    _ERROR_OUTPUT_RE = re.compile(
        r"^[A-Z][A-Za-z0-9_]*(Error|Exception): ")                      # :936
    async def _execute(self, code: str, debug: bool = False,
                       **kwargs) -> Any: ...                            # :950
        # output = await loop.run_in_executor(None, self._execute_code,
        #                                     code, debug)              # :970
        # ← el None = ThreadPoolExecutor COMPARTIDO por defecto (Module 1)
    def reset_environment(self) -> None: ...                            # :1023
```

```python
# CONTRATO DE RETORNO INVARIANTE (G5) — parrot/tools/pythonrepl.py:955-985
try:
    loop = asyncio.get_event_loop()
    output = await loop.run_in_executor(None, self._execute_code, code, debug)
except Exception as e:
    msg = f"ToolError: {type(e).__name__}: {str(e)}"
    return {"status": "error", "result": msg, "error": str(e)}
if self._is_error_output(output):
    return {"status": "done_with_errors", "result": output, "error": output}
return output   # string en éxito
```

### Key Attributes & Namespace Surface

- `locals["execution_results"]` → `dict` (`:480`, escrito `:431`, limpiado
  `:1031`, leído `:1011, :1063, :1110-1115`).
- `locals["save_current_plot"]` → closure sobre `self.output_dir` del host
  (definido `:366`, registrado `:482`, usado `:617`). **Debe recrearse en el
  worker** apuntando al directorio compartido (decidido).
- `PythonPandasTool.df_locals` → `dict` (`pythonpandas.py:122`), fusionado en
  `locals_dict` en `:128-130` y en `self.locals/globals` en `:292-293`;
  `clone()` copia locals/globals en `:220-236`.
- `ToolManager._shared` → `{"dataframes": {}}` (`manager.py:264`);
  `share_dataframe()` (`:1749-1756`), `auto_push_to_pandas` (`:273`).

### Audited External Access to `.locals` / `.globals` (port targets, Module 6)

Auditoría 2026-07-27 verificada por grep sobre `packages/ai-parrot/src/parrot/`
— superficie real, 5 módulos:

1. `bots/data.py` — lecturas directas múltiples de `pandas_tool.locals`
   (`:1800, :2329, :2626-2628, :2655, :2743-2748, :2810-2815`), incluye
   `execution_results`.
2. `bots/agent.py:218-219` — la working memory guarda una **referencia viva**:
   `wm._tool_locals[key] = tool.locals`. Semántica imposible de preservar
   cruzando proceso → portar a snapshot/API.
3. `tools/agent.py:421-427` — **escrituras** host→namespace
   (`python_repl.globals['previous_result']`, `f'{safe_name}_result'`) →
   `set_var`.
4. `outputs/formats/base.py:137` — devuelve `tool.locals` tras
   `execute_sync` → snapshot/API.
5. `tools/pythonpandas.py:220-236, :292-293` — `clone()` copia locals/globals
   y fusiona `df_locals`.

### Does NOT Exist (Anti-Hallucination)

- ~~Timeout, `signal`, `resource`, `rlimit`, `kill` o `terminate` en
  `pythonrepl.py`~~ — verificado por grep: **cero ocurrencias**. No hay nada
  que extender; hay que construirlo.
- ~~Un executor dedicado para el REPL~~ — `pythonrepl.py:970` usa
  `run_in_executor(None, ...)`, el pool compartido por defecto.
- ~~Una forma de matar un hilo de Python desde fuera~~ — no existe en el
  lenguaje. Es la razón por la que la Option A no puede cumplir G2.
- ~~`resource.setrlimit()` con ámbito de hilo~~ — es por proceso. Sin frontera
  de proceso, apunta al servidor.
- ~~Aislamiento por sesión en el REPL actual~~ — `self.locals` es por
  instancia de tool y `_bootstrapped` es por clase. No hay noción de sesión.
- ~~`fork` como método de arranque seguro~~ — matplotlib, pools de conexión e
  hilos del padre no lo toleran. Debe ser `spawn`.
- ~~`parrot/tools/repl_worker/`~~ — no existe todavía; lo crea esta feature.
- ~~Filtro RTK para salida del REPL~~ — fuera de alcance; RTK pertenece a
  `shelltool-hardening` (brainstorm aparte).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Async-first en el lado host (`WorkerHandle`/`WorkerPool` con
  `asyncio.subprocess` o `multiprocessing` + executor propio); el worker es
  síncrono por diseño (un `exec` a la vez).
- Pydantic para todos los mensajes del protocolo (`protocol.py`).
- Logging con `self.logger`; el warning de fallback a pickle (G9) es
  obligatorio, no opcional.
- `_serialize_execution_results()` (`pythonrepl.py:627`) es el precedente
  directo para el protocolo de salida — reutilizar su enfoque.
- `_execute_code()` se mueve, **no se reescribe**. Diferencias de
  comportamiento entre el REPL viejo y el worker son bugs.
- Configuración: `WorkerConfig` con defaults que funcionen sin tocar nada
  (requisito del brainstorm para el desarrollador que despliega).

### Known Risks / Gotchas

| Riesgo | Mitigación |
|---|---|
| `RLIMIT_AS` mal calibrado: pandas reserva más de lo que toca | Default generoso (~4 GiB) + Module 8 de calibración empírica antes de fijar el definitivo |
| Consumo de memoria N sesiones × intérprete con pandas | Techo de workers + TTL de expulsión (defaults decididos) |
| Worker huérfano = fuga de recursos | `PR_SET_PDEATHSIG` (Linux) + barrido en apagado como respaldo portable |
| Fallback silencioso a in-process anularía la feature | G8/AC8: la ruta in-process debe ser inalcanzable cuando el worker falla; test explícito |
| El LLM reutiliza variables tras un kill | Error estructurado con lista de variables perdidas + instrucción de recrear estado (AC11) |
| Referencia viva `wm._tool_locals` (`bots/agent.py:219`) rompería en silencio | Port explícito en Module 6; sin dict-proxy de compatibilidad (decidido) |
| Colisión con la compresión de `ToolResult` | Congelada as-is por decisión del equipo; vigilar `tools/manager.py` y `tools/pythonpandas.py` en merges |
| Windows sin rlimits | Degradación documentada de forma visible (AC16); Job Objects como seguimiento |
| Dtypes no cubiertos por Arrow | Fallback pickle + warning (ruta lenta, debe ser observable) |
| Plot/base64: `return_plot_as_base64` cruza la frontera | El worker produce el base64; solo viaja el string |

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `multiprocessing` / `asyncio.subprocess` | stdlib | spawn (nunca fork) + canal de control |
| `resource` | stdlib (POSIX) | `setrlimit` en `preexec_fn`; ausente el enforcement en Windows |
| `pyarrow` | ya presente vía pandas ≥2 | Arrow IPC de DataFrames, cero-copia donde el dtype lo permite |
| `multiprocessing.shared_memory` | stdlib | buffers compartidos, alternativa/complemento a Arrow IPC |

---

## 8. Open Questions

> Las 9 preguntas del brainstorm fueron resueltas interactivamente el
> 2026-07-27 (sesión /sdd-brainstorm). Se registran aquí para el audit trail;
> sus resoluciones ya están integradas en el cuerpo de esta spec.

- [x] Paliativo inmediato (executor dedicado en `pythonrepl.py:970`) —
      *Resolved in brainstorm*: Sí, se despliega ya; cambio pequeño e
      independiente que aterriza en `dev` antes de la feature (→ Module 1, AC1).
- [x] Auditoría de accesos externos a `.locals`/`.globals` — *Resolved in
      brainstorm*: hecha y verificada por grep; 5 módulos; decisión: API de
      namespace explícita (`get_var`/`set_var`/`list_vars`/`snapshot`) y port
      de los 5 call sites; sin dict-proxy (→ Module 6, AC13, §6).
- [x] Closures: ¿worker autónomo o stubs RPC? — *Resolved in brainstorm*:
      worker autónomo escribiendo a directorio compartido; sin canal RPC
      worker→host (→ §2 Overview).
- [x] ¿Dónde corre el gate estático? — *Resolved in brainstorm*: ambos lados;
      host rechaza barato, worker revalida como defensa en profundidad
      (→ AC6).
- [x] Calibrar `RLIMIT_AS` — *Resolved in brainstorm*: default configurable y
      generoso (~4 GiB) + tarea explícita de calibración empírica
      (→ Module 8, AC15).
- [x] Windows — *Resolved in brainstorm*: POSIX completo; Windows degradado
      (proceso separado + timeout duro + terminate, sin rlimits), documentado
      visiblemente; Job Objects como seguimiento (→ AC16).
- [x] Techo de workers y TTL — *Resolved in brainstorm*: rechazo inmediato al
      techo con error claro; defaults techo `max(4, cpu_count)` tope ~16, TTL
      30 min; configurables (→ Module 4, AC12).
- [x] ¿Pool de pre-calentado en v1? — *Resolved in brainstorm*: sí, tamaño
      configurable, default pequeño (→ Module 4, AC10).
- [x] ¿Cómo se comunica la pérdida de namespace tras un kill? — *Resolved in
      brainstorm*: error estructurado `{status, result, error}` con causa
      diferenciada (timeout vs memoria), lista de nombres perdidos (shadow
      host vía `list_ns`) e instrucción de recrear estado (→ AC11).
- [ ] ¿Debe actualizarse la spec de FEAT-252 / TASK-1614 (gate allowlist del
      `PythonCodeSanitizer`) para reflejar el nuevo contexto de ejecución
      (host + worker)? Sus requisitos no cambian; solo el contexto. Decidible
      durante la implementación. — *Owner: Jesus Lara*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — un único worktree, tasks
  secuenciales.
- **Rationale**: el protocolo de control (Module 2) es la superficie de
  acoplamiento de toda la feature; `repl-state-transport` (Modules 6–7)
  depende de él. Dos worktrees definiendo el protocolo a la vez producirían
  un merge caro. La excepción es **Module 1 (paliativo)**: cambio de una
  línea + config, independiente, que puede aterrizar en `dev` de inmediato
  incluso antes de crear el worktree.
- **Cross-feature dependencies**:
  - `shelltool-hardening` (brainstorm aparte) — totalmente independiente,
    puede ir en paralelo desde el minuto uno.
  - Compresión de `ToolResult` — **congelada as-is** hasta que esta feature
    aterrice (decisión del equipo). Ficheros compartidos a vigilar:
    `parrot/tools/manager.py`, `parrot/tools/pythonpandas.py`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-27 | Jesus Lara | Initial draft from sandbox-hardening brainstorm (Option B; all 9 open questions pre-resolved) |
