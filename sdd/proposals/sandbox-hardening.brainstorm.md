---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: Sandbox Hardening — PythonREPLTool a worker persistente

**Date**: 2026-07-27
**Author**: <name>
**Status**: exploration
**Recommended Option**: Option B

---

## Problem Statement

`PythonREPLTool` ejecuta código generado por un LLM **dentro del proceso del servidor**, vía `exec()` / `eval()` sobre `self.locals` (`pythonrepl.py:765-825`). La defensa actual es análisis estático en dos capas antes de ejecutar:

1. Un **allowlist** — `PythonCodeSanitizer(general_profile())` (`pythonrepl.py:231-233`, invocado en `:730-742`).
2. Un **denylist AST** — `_check_ast_security()` (`pythonrepl.py:558-574`) que recorre el árbol contra `BLOCKED_IMPORTS` (`:108-127`), `BLOCKED_NAMES` (`:128-145`) y `BLOCKED_ATTRIBUTES` (`:152-185`).

Es una defensa bien construida y el orden es el correcto: el allowlist es la parte que sostiene y el denylist es respaldo. Pero tiene un agujero que no es un bypass sino una **categoría de problema que el análisis estático no puede tocar**.

### El hallazgo que domina el resto

```
grep -niE "timeout|rlimit|resource\.|signal\.|kill|terminate"  pythonrepl.py  → (vacío)
grep -n  "run_in_executor"                                     pythonrepl.py  → :970
```

No hay timeout. No hay límite de memoria. No hay límite de CPU. Y la ejecución se despacha con `loop.run_in_executor(None, self._execute_code, code, debug)` (`pythonrepl.py:970`) — el `None` significa **el ThreadPoolExecutor compartido por defecto**.

Un bucle no acotado no importa nada, no referencia ningún nombre bloqueado y no toca ningún atributo prohibido. Pasa el allowlist, pasa el walk AST, pasa todo — porque no es un bypass: es código Python perfectamente legítimo. Al ejecutarse **secuestra permanentemente un hilo del pool compartido**, y en Python un hilo no se puede matar desde fuera. Suficientes de esos y se agota el pool que usan todas las herramientas del framework que hacen offload.

Lo mismo con memoria: una asignación grande no mata al "sandbox", mata al **proceso padre**, y con él todas las sesiones concurrentes, los pools de conexión y el servidor entero.

Y no hace falta un atacante: basta un bucle mal generado por el propio LLM, que es un modo de fallo rutinario en análisis de datos iterativo.

### El segundo problema: radio de explosión

In-process significa que el código del LLM comparte espacio de memoria con:

- Las credenciales del proceso y `os.environ`.
- Los pools de conexión de `asyncdb` (`DatabaseQueryToolkit`).
- Los DataFrames de **otras sesiones** en `ToolManager._shared["dataframes"]`.
- Las superficies nativas de numpy / pandas / matplotlib / seaborn, que el análisis del código de usuario no ve en absoluto.

La contención no degrada suavemente. Si falla, falla entera.

### Tensión estructural del denylist

El propio código ya documenta el problema (`pythonrepl.py:146-151`): `rename`, `replace` y `remove` tuvieron que salir de `BLOCKED_ATTRIBUTES` porque colisionaban con `df.rename()`, `df.replace()`, `str.replace()` y `list.remove()`. El bloqueo por nombre de atributo no tiene información de tipo. Esa tensión entre cobertura y usabilidad es permanente y solo va a más conforme crezca el catálogo de librerías.

### Por qué ahora

Es la herramienta más usada en el flujo de análisis de datos, así que la superficie está permanentemente caliente. Y el trabajo de compresión de `ToolResult` (brainstorm previo) va a tocar la ruta de resultados de esta misma herramienta: conviene que la arquitectura de ejecución esté estabilizada antes, no en paralelo.

---

## Constraints & Requirements

- **C1 — El estado del REPL debe sobrevivir entre llamadas.** El agente crea un DataFrame en un turno y lo usa tres turnos después. `execution_results` (`pythonrepl.py:480`), las variables de usuario y los DataFrames inyectados por `PythonPandasTool` persisten hoy y deben seguir persistiendo. Esto descarta el subproceso por llamada.
- **C2 — Timeout duro, aplicable.** Toda ejecución debe poder terminarse por la fuerza. No es negociable y es la razón de ser de esta feature.
- **C3 — Límite de memoria por sesión.** Una asignación desmedida debe matar al worker, nunca al servidor.
- **C4 — Latencia de ejecución comparable a la actual.** Importar pandas + numpy + matplotlib + seaborn cuesta 1–3 s. Ese coste debe pagarse una vez por sesión, no por llamada.
- **C5 — Contrato de salida idéntico.** `_execute()` devuelve hoy un string, o un dict `{status, result, error}` cuando hay error o bloqueo (`pythonrepl.py:955-985`), con clasificación vía `_ERROR_OUTPUT_RE` (`:936`). El LLM y el framework dependen de esa forma. No cambia.
- **C6 — El análisis estático se conserva.** El allowlist y el denylist AST siguen ejecutándose. La frontera de proceso es una capa **adicional**, no un reemplazo. Defensa en profundidad.
- **C7 — Aislamiento por sesión.** Un worker por sesión. El código de un usuario no puede alcanzar el namespace de otro. Esto ya es un problema latente hoy.
- **C8 — Degradación explícita.** Si el worker no puede arrancar, la herramienta falla con un error claro. **Nunca** cae de vuelta a `exec()` in-process — un fallback silencioso a la ruta insegura anula toda la feature.
- **C9 — Transferencia de DataFrames sin copia costosa.** Inyectar un DataFrame de 500 MB no puede pasar por pickle sobre un pipe.

---

## Options Explored

### Option A: Endurecer manteniendo la ejecución in-process

Añadir watchdog y límites sin cruzar la frontera de proceso: temporizador que marque la ejecución como expirada, `resource.setrlimit()`, rechazo estático de construcciones no acotadas.

✅ **Pros:**
- Cambio pequeño y localizado en `pythonrepl.py`. Sin protocolo IPC, sin lifecycle, sin transporte de estado.
- Cero riesgo para C1 y C4: el estado y la latencia no se tocan porque la arquitectura no cambia.
- Se podría desplegar en días.

❌ **Cons:**
- **Da mucho menos de lo que aparenta, y esto es decisivo.** Un watchdog puede *detectar* que una ejecución se pasó de tiempo, pero **no puede matar un hilo de Python**. El hilo sigue quemando CPU y ocupando su plaza del pool para siempre. El watchdog devuelve un error al LLM mientras el recurso queda perdido: la apariencia de un timeout sin el efecto de un timeout.
- `resource.setrlimit(RLIMIT_AS, ...)` aplica al **proceso entero**, es decir al servidor. Ponerlo bajo mata el servidor; ponerlo alto no protege de nada. Es la herramienta equivocada sin frontera de proceso.
- Detectar estáticamente "código que no termina" es indecidible en el caso general. Cualquier heurística rechaza análisis legítimo o deja pasar bucles reales, normalmente ambas cosas.
- No hace nada por el radio de explosión: mismo espacio de memoria, mismas credenciales, mismos pools.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `resource` | rlimits | stdlib; ámbito de proceso, no de hilo — ahí está el problema |
| `threading` | watchdog | stdlib; no puede terminar el hilo vigilado |

🔗 **Existing Code to Reuse:**
- `parrot/tools/pythonrepl.py:701-830` — `_execute_code()`
- `parrot/tools/pythonrepl.py:955-985` — `_execute()`

---

### Option B: Worker persistente por sesión con rlimits

Un proceso hijo de vida larga por sesión que mantiene el namespace del REPL. El host envía código por un canal de control y recibe salida estructurada. El worker arranca con `preexec_fn` aplicando `setrlimit` (memoria, CPU, ficheros, sin core dumps). El timeout se implementa donde sí funciona: `SIGKILL` al hijo.

✅ **Pros:**
- **Es la opción mínima que satisface C2 y C3.** El timeout y el cap de memoria requieren una frontera de proceso; no hay atajo.
- Preserva C1: el namespace vive en el worker y persiste entre llamadas de forma natural, sin serializar en cada turno.
- Amortiza C4: el arranque de pandas/matplotlib se paga una vez por sesión. Con un pool pre-calentado, ni eso.
- Cumple C7 casi gratis: un worker por sesión es aislamiento por construcción, no por disciplina.
- Aislamiento de crash: un segfault en una extensión nativa mata al hijo y se reinicia; hoy tumbaría el servidor.
- **Corrige un bug latente de paso**: `_bootstrapped` es una variable de **clase** (`pythonrepl.py:105, 537, 556`), compartida por todas las instancias del proceso. Hoy, la segunda instancia de `PythonREPLTool` nunca ejecuta su bootstrap. Con un worker por sesión el flag pasa a ser por worker, que es lo que siempre debió ser.

❌ **Cons:**
- Es el mayor cambio arquitectónico de los tres. Lifecycle, health checks, reinicio tras crash, política de expulsión por inactividad, límite de workers concurrentes.
- Los closures inyectados en el namespace (`save_current_plot` en `pythonrepl.py:366`, registrado en `:482`) hoy cierran sobre `self.output_dir` del host. Cruzan la frontera y hay que decidir: ¿viven en el worker escribiendo a un directorio compartido, o son stubs RPC de vuelta al host?
- C9 exige un transporte serio para DataFrames (Arrow IPC / memoria compartida), que es trabajo aparte y no trivial.
- Coste de memoria: N sesiones activas = N intérpretes con pandas cargado. Hay que dimensionar y poner techo.
- No es una frontera de seguridad completa: el hijo comparte kernel, red y sistema de ficheros con el host. Mitiga radio de explosión, no lo elimina.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `multiprocessing` / `asyncio.subprocess` | spawn y canal de control | stdlib; `spawn` como método de arranque, no `fork` (matplotlib y los pools no toleran fork) |
| `resource` | `setrlimit` en `preexec_fn` | stdlib; POSIX. En Windows hace falta Job Objects — ver *Open Questions* |
| `pyarrow` | IPC de DataFrames sin copia | ya presente indirectamente vía pandas ≥2 |
| `multiprocessing.shared_memory` | buffers compartidos | stdlib; alternativa a Arrow IPC para el mismo host |
| PyO3 / maturin | transporte / serialización si hace falta acelerar | ya integrado en el codebase |

🔗 **Existing Code to Reuse:**
- `parrot/tools/pythonrepl.py:701-830` — `_execute_code()` se mueve **tal cual** al worker; es el corazón y no debería reescribirse
- `parrot/tools/pythonrepl.py:558-574` — `_check_ast_security()` sigue corriendo, en el host **y** en el worker (decidido 2026-07-27: ambos)
- `parrot/tools/pythonrepl.py:231-233, 730-742` — gate del `PythonCodeSanitizer`, se conserva
- `parrot/tools/pythonrepl.py:627-700` — `_serialize_execution_results()`, precedente directo para el protocolo de salida
- `parrot/tools/pythonrepl.py:871` — `_describe_new_var()`, debe ejecutarse **en el worker** (inspecciona objetos vivos); solo viaja el texto
- `parrot/tools/pythonrepl.py:936, 955-985` — `_ERROR_OUTPUT_RE` y el contrato de retorno de `_execute()`, invariantes
- `parrot/tools/pythonrepl.py:1023-1044` — `reset_environment()`, se convierte en "reiniciar worker"
- `parrot/tools/manager.py` — `share_dataframe()` / `auto_push_to_pandas`, ruta host→worker de inyección de DataFrames

---

### Option C: Contenedor por sesión

Cada sesión ejecuta en un contenedor: perfil seccomp, sin red, sistema de ficheros de solo lectura salvo un directorio de salida, cgroups para CPU y memoria, usuario sin privilegios.

✅ **Pros:**
- Es la única opción que constituye una **frontera de seguridad real**. Las anteriores mitigan; esta contiene.
- cgroups da límites de CPU y memoria más finos y fiables que `setrlimit`.
- Sin red por defecto elimina de un golpe toda la clase de exfiltración, que hoy se persigue por nombres en `BLOCKED_IMPORTS` (`socket`, `urllib`, `requests`, `http`, `ftplib`, `ssl`).
- El denylist AST podría relajarse mucho, recuperando usabilidad perdida.

❌ **Cons:**
- Dependencia de runtime de contenedores en el despliegue. Rompe `pip install ai-parrot` y ejecutar; mata el desarrollo local sencillo y complica CI.
- Arranque de contenedor por sesión, incluso con imagen pre-construida y pre-calentado, es notablemente más lento que un `spawn`.
- La transferencia de DataFrames cruza ahora una frontera de contenedor: memoria compartida requiere IPC namespace compartido o bind mounts, lo que erosiona parte del aislamiento que motivaba la opción.
- Coste operativo real: construcción de imágenes, versionado, parcheo de seguridad, recolección de huérfanos.
- **Sobredimensionado para el modelo de amenaza actual.** El adversario dominante hoy no es un atacante decidido, es un LLM que genera un bucle infinito o pide 40 GB de RAM. La Opción B ya cubre eso.

📊 **Effort:** Very High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| Docker / Podman | runtime | dependencia de despliegue, no de librería |
| `nsjail` / `bubblewrap` | aislamiento ligero sin daemon | alternativa más barata que un contenedor completo |

🔗 **Existing Code to Reuse:**
- Todo lo de la Opción B — la Opción C es la Opción B con el worker dentro de un contenedor. **No son excluyentes: C es una evolución de B, no un camino distinto.**

---

## Recommendation

**Option B**, worker persistente por sesión con rlimits. Decisión ya tomada por el equipo; el razonamiento que la respalda:

**Contra A.** La Opción A no es "menos seguridad por menos esfuerzo", es **seguridad aparente**. Un watchdog que no puede matar el hilo que vigila produce logs tranquilizadores mientras el recurso sigue perdido; eso es peor que no tener nada, porque desactiva la urgencia. El único mecanismo que hace cumplir un timeout en Python es terminar el proceso. Si el objetivo es C2, la frontera de proceso no es una elección de diseño: es el requisito.

**Contra C.** El modelo de amenaza dominante hoy es un LLM que genera código malo, no un adversario que persigue una fuga del sandbox. La Opción B cubre íntegramente ese caso a una fracción del coste operativo. Y como C es literalmente B metida en un contenedor, elegir B hoy **no cierra la puerta a C**: si el modelo de amenaza cambia — ejecución de código de terceros, multi-tenant hostil — el worker se envuelve sin rediseñar el protocolo. Elegir C ahora sería pagar por adelantado un aislamiento que nadie está pidiendo todavía, y a cambio romper el desarrollo local.

**Lo que se sacrifica, explícitamente:**

- *No es una frontera de seguridad completa.* El worker comparte kernel, red y FS con el host. Un exploit dirigido con suficiente esfuerzo puede salir. Se acepta conscientemente: lo que se compra es acotación de recursos y radio de explosión, no contención adversarial.
- *Consumo de memoria proporcional a sesiones activas.* N intérpretes con pandas cargado. Exige techo de workers concurrentes y expulsión por inactividad.
- *Complejidad operativa nueva.* Procesos hijo que supervisar, reiniciar y recolectar. Un worker huérfano es una fuga de recursos.
- *Trabajo real en el transporte de DataFrames.* C9 es una capability propia, no un detalle de implementación.

**Sobre el hueco temporal.** El DoS descrito en *Problem Statement* está abierto **hoy** y esta feature tarda semanas. La Opción A no sirve como paliativo porque no puede matar el hilo. Lo único que reduce exposición de forma inmediata sin cambiar arquitectura es operativo, no de código: sustituir el executor por defecto por uno **dedicado y acotado** en `pythonrepl.py:970`, para que un bucle no acotado agote un pool aislado en vez del pool compartido de todo el framework. No arregla nada, pero contiene el daño colateral a la herramienta que lo causa. Anotado como decisión pendiente en *Open Questions*.

---

## Feature Description

### Arquitectura

```
   HOST (proceso del servidor)                WORKER (uno por sesión)
  ┌───────────────────────────┐             ┌──────────────────────────────┐
  │ PythonREPLTool            │             │ preexec_fn: setrlimit(       │
  │  ├ PythonCodeSanitizer    │             │   AS, CPU, NOFILE, CORE)     │
  │  ├ _check_ast_security()  │             │                              │
  │  │  (gate estático, C6)   │             │  ns = self.locals            │
  │  │                        │  control    │  exec()/eval()   ← sin       │
  │  ├ WorkerHandle ──────────┼────────────►│                     cambios  │
  │  │   spawn / kill / health│  (pipe)     │                              │
  │  │                        │◄────────────┤  _describe_new_var()         │
  │  └ DataFrame injection ───┼────────────►│  _serialize_execution_...()  │
  │                           │ Arrow/shm   │                              │
  └───────────────────────────┘             └──────────────────────────────┘
         directorio de salida compartido (plots, reports)
```

El gate estático corre en **ambos lados** (decisión 2026-07-27): el host falla barato, sin pagar un round-trip por código que va a rechazarse igualmente, y el worker revalida antes de `exec` como defensa en profundidad.

### Protocolo de control

Mensajes mínimos, uno por línea, con longitud prefijada sobre un pipe dedicado:

| Mensaje | Dirección | Payload |
|---|---|---|
| `exec` | host → worker | código, `debug`, `deadline_ms` |
| `result` | worker → host | `output` (str) o `{status, result, error}` — forma idéntica a hoy |
| `inject_df` | host → worker | nombre + handle de Arrow/shm |
| `list_ns` | host → worker | — |
| `reset` | host → worker | — |
| `ping` | host → worker | health check |

El `deadline_ms` viaja con la petición y el host lo hace cumplir: si el worker no responde a tiempo, `SIGKILL`, se marca la ejecución como expirada y se levanta uno nuevo. El estado del namespace se pierde en ese caso, y **hay que decírselo al LLM explícitamente** en el mensaje de error, o intentará usar variables que ya no existen.

### Límites de recursos

Aplicados en `preexec_fn` en el arranque del hijo:

| Límite | Propósito |
|---|---|
| `RLIMIT_AS` | Techo de memoria virtual. Una asignación desmedida mata al worker, no al servidor |
| `RLIMIT_CPU` | Red de seguridad por si el `SIGKILL` del host fallara |
| `RLIMIT_NOFILE` | Acota descriptores |
| `RLIMIT_CORE = 0` | Sin core dumps — un volcado de un worker con DataFrames es una fuga de datos |

Valores por defecto configurables por despliegue. `RLIMIT_AS` es el delicado: pandas puede reservar bastante más de lo que toca. Calibrar contra cargas reales, no a ojo.

### Ciclo de vida del worker

- **Arranque perezoso**: al primer `_execute()` de la sesión, no en `__init__`. Muchas sesiones nunca tocan el REPL.
- **Pre-calentado (v1)**: un pool pequeño de workers ya arrancados con las librerías importadas, asignados a demanda. Convierte 1–3 s en milisegundos. **Decisión 2026-07-27: se incluye en v1** (tamaño configurable, default pequeño).
- **Expulsión por inactividad**: TTL configurable. Un worker con pandas cargado no debería sobrevivir a una sesión abandonada.
- **Techo de concurrencia**: máximo de workers vivos; superado, se rechaza con error claro en vez de agotar la memoria del host.
- **Reinicio ante crash**: worker muerto inesperadamente → se levanta otro y se informa al LLM de que el namespace se perdió.
- **Recolección de huérfanos**: los hijos mueren con el padre. `PR_SET_PDEATHSIG` en Linux; barrido en el apagado como respaldo portable.

### Estado y transporte

Lo que hoy vive en `self.locals` (`pythonrepl.py:244-245`) y debe vivir en el worker:

- Variables de usuario y `execution_results` (`:480`)
- Los DataFrames inyectados por `PythonPandasTool`
- El flag de bootstrap — que pasa de variable de clase (`:105`) a estado por worker

**Los closures son el punto delicado.** `save_current_plot` (`:366`, registrado en `:482`) cierra sobre `self.output_dir` del host. Dos caminos:

1. **Worker autónomo** — el closure se recrea en el worker apuntando a un directorio compartido; el worker escribe y devuelve la ruta. Simple, sin round-trips, pero exige que el directorio sea visible desde ambos lados (trivial hoy, relevante si algún día se va a la Opción C).
2. **Stub RPC** — el closure llama de vuelta al host. Más flexible, pero abre un canal worker→host que es exactamente lo que se quería restringir.

**Recomendación: opción 1.** El canal de vuelta debilita la frontera por comodidad.

**DataFrames.** Arrow IPC sobre memoria compartida. `pandas.DataFrame` ≥2 tiene respaldo Arrow para muchos dtypes, así que la conversión suele ser barata o cero-copia. Fallback a pickle solo para dtypes que Arrow no cubre, y registrarlo como advertencia — es la ruta lenta y conviene saber cuándo se usa.

### User-Facing Behavior

Para el usuario final: sin cambios visibles, salvo que un análisis desbocado ahora devuelve un error de tiempo excedido en vez de colgar la sesión.

Para el desarrollador que despliega: parámetros nuevos de configuración (límites, TTL, techo de workers, tamaño del pool de pre-calentado). Con valores por defecto que funcionen sin tocar nada.

Para el agente LLM: dos mensajes de error nuevos que debe entender —tiempo excedido y memoria excedida— y, en ambos casos, aviso explícito de que las variables se perdieron.

### Edge Cases & Error Handling

| Caso | Comportamiento |
|---|---|
| Ejecución excede `deadline_ms` | `SIGKILL`, worker nuevo, error que **dice que el namespace se perdió** |
| Worker muere por `RLIMIT_AS` | Error de memoria diferenciado del de tiempo; el LLM debe poder distinguirlos para reintentar distinto |
| Worker muere inesperadamente (segfault nativo) | Reinicio + error claro. El servidor no se entera más allá del log |
| El worker no arranca | Error explícito. **Nunca** fallback a `exec()` in-process (C8) |
| Techo de workers alcanzado | Rechazo con error claro, no cola indefinida |
| Inyección de DataFrame con dtype no soportado por Arrow | Fallback a pickle + warning |
| Código rechazado por el gate estático | Igual que hoy: se rechaza en el host, sin arrancar ni molestar al worker |
| Sesión abandonada | Expulsión por TTL |
| Apagado del host | Todos los workers terminados; barrido de huérfanos |
| `reset_environment()` (`:1023`) | Reinicio de worker |
| Plot generado en el worker | Escrito al directorio compartido; solo viaja la ruta (o el base64 si `return_plot_as_base64`) |

---

## Capabilities

### New Capabilities

- `repl-worker-runtime`: proceso worker, protocolo de control, rlimits vía `preexec_fn`, timeout con `SIGKILL`, lifecycle (arranque perezoso, pre-calentado, TTL, techo, reinicio, huérfanos). Base de la que dependen las demás.
- `repl-state-transport`: transferencia host↔worker de DataFrames vía Arrow/memoria compartida, recreación de los closures del namespace en el worker, directorio de salida compartido, inspección de namespace.
- ~~`shell-rtk-integration`~~ — **escindida (2026-07-27) a su propio brainstorm**: `sdd/proposals/shelltool-hardening.brainstorm.md`, donde se resolvieron sus decisiones (rtk como dependencia dura sin escape hatch, mapa de comandos, guard de sanitizer). Este documento queda reducido a `repl-worker-runtime` + `repl-state-transport`.

### Modified Capabilities

<!-- Verificar contra docs/sdd/specs/. Candidata: la spec de FEAT-252 / TASK-1614
     (gate allowlist del PythonCodeSanitizer) — sus requisitos no cambian, pero
     el contexto de ejecución sí, y conviene que la spec lo refleje. -->

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/tools/pythonrepl.py` | modifies | `_execute()` (`:955`) pasa a hablar con el worker. `_execute_code()` (`:701`) se **mueve tal cual** al worker |
| `parrot/tools/pythonpandas.py` | modifies | `add_dataframe()` pasa de escribir en `self.locals` a enviar por el transporte |
| `parrot/tools/manager.py` | depends on | `share_dataframe()` / `auto_push_to_pandas` empujan DataFrames al REPL; la ruta ahora cruza proceso |
| `parrot/tools/repl_worker/` | new | Paquete nuevo: entrypoint del worker, protocolo, handle del host |
| `parrot/security/python_sanitizer.py` | unchanged | El gate se conserva íntegro (C6) |
| `parrot/tools/shell/tool.py` | modifies | Prefijo `rtk` en `_make_action_from_cmdobj` (`:186-198`) |
| `parrot/tools/shell/security.py` | modifies | **`assert_command_safe()` debe rechazar `rtk` como entrada de usuario** — ver nota de seguridad |
| `parrot/bots/data.py` | depends on | `PandasAgent` es el consumidor principal; verificar que no toca `self.locals` directamente |
| Configuración de despliegue | extends | Límites, TTL, techo de workers, pool de pre-calentado |
| Documentación | extends | Nuevo modelo de ejecución y sus modos de fallo |

**Breaking changes:** ninguno en la API pública si se respeta C5. Sí lo hay para **cualquier código que toque `PythonREPLTool.locals` o `.globals` directamente desde el host** — dejan de ser la fuente de verdad. Hay que auditar los usos antes de empezar.

---

## Code Context

> ✅ **Números de línea verificados** contra los ficheros subidos
> (`pythonrepl.py`, 1.208 líneas; `shell/tool.py`, 467 líneas).
> Pueden haber derivado respecto a HEAD — confirmar con `rg` antes de implementar.
>
> ⚠️ **Corrección de rutas (2026-07-27, verificado contra HEAD de `dev`)**: las rutas
> reales en el repo son `packages/ai-parrot/src/parrot/tools/pythonrepl.py` (1.208
> líneas — coincide; `run_in_executor` sigue en `:970`) y
> `packages/ai-parrot-tools/src/parrot_tools/shell_tool/tool.py` (467 líneas —
> coincide). Las referencias `parrot/tools/shell/*` de este documento apuntan al
> paquete satélite `parrot_tools`; el sanitizer genérico vive ahora en core:
> `packages/ai-parrot/src/parrot/security/command_sanitizer.py` (FEAT-252).

### User-Provided Code

```python
# Source: parrot/tools/pythonrepl.py:955-985 (subido por el usuario)
# CONTRATO DE RETORNO INVARIANTE (C5) — string en éxito, dict en error.
try:
    self.logger.info(f"Executing Python code: {code[:100]}...")
    loop = asyncio.get_event_loop()
    output = await loop.run_in_executor(None, self._execute_code, code, debug)   # ← :970
except Exception as e:
    self.logger.error(f"Error executing Python code: {e}")
    msg = f"ToolError: {type(e).__name__}: {str(e)}"
    return {"status": "error", "result": msg, "error": str(e)}

if self._is_error_output(output):
    self.logger.warning(
        "Tool %s code execution returned an error: %s", self.name, str(output)[:200],
    )
    return {"status": "done_with_errors", "result": output, "error": output}
return output
```

```python
# Source: parrot/tools/pythonrepl.py:765-766 (subido por el usuario)
# El namespace unificado. Esto es lo que debe vivir en el worker.
ns = self.locals
self.globals = ns
# ... exec(ast.unparse(module), ns, ns)      → :773
# ... ret = eval(module_end_str, ns, ns)     → :786, :803
# ... exec(module_end_str, ns, ns)           → :825
```

```python
# Source: parrot/tools/shell/tool.py:186-198 (subido por el usuario)
# PUNTO DE INSERCIÓN de rtk. `assert_command_safe` ya corrió antes (:145-146, :254).
raw = spec.command.strip()
common = dict(
    cmd=raw, work_dir=work_dir, timeout=timeout, env=env,
    pty_mode=pty_mode, stdin_lines=spec.stdin or [],
    non_interactive=non_interactive, ignore_errors=ignore_errors,
    live_callback=self._live_cb, sanitizer=self._sanitizer,
)
if raw.startswith("ls") or raw == "ls":
    return ListFiles(type_name="list_files", **common)
elif raw.endswith(".sh") or raw.startswith("./") or raw.startswith("/"):
    return ExecFile(type_name="exec_file", **common)
else:
    return RunCommand(type_name="run_command", **common)
```

### Verified Codebase References

#### Classes & Signatures

```python
# From parrot/tools/pythonrepl.py:100-105
class PythonREPLTool(AbstractTool):
    name = "python_repl"                                                    # :100
    description = "Execute Python code with pre-loaded data science libraries (pandas, numpy, matplotlib, seaborn)"
    args_schema = PythonREPLArgs                                            # :102
    _bootstrapped = False   # ← VARIABLE DE CLASE, compartida en el proceso  # :105
```

```python
# From parrot/tools/pythonrepl.py:187-201
def __init__(
    self,
    locals_dict: Optional[Dict] = None,
    globals_dict: Optional[Dict] = None,
    report_dir: Optional[Path] = None,
    plt_style: str = "seaborn-v0_8-whitegrid",
    palette: str = "Set2",
    setup_code: Optional[str] = None,
    sanitize_input_enabled: bool = True,
    auto_save_plots: bool = True,
    return_plot_as_base64: bool = False,
    debug: bool = False,
    policy=None,  # FEAT-252 (TASK-1614): PythonExecutionPolicy | None      # :199
    **kwargs,
): ...
```

```python
# From parrot/tools/pythonrepl.py:231-233 — gate allowlist, SE CONSERVA (C6)
from parrot.security.python_sanitizer import PythonCodeSanitizer, general_profile
_policy = policy if policy is not None else general_profile()
self._code_sanitizer = PythonCodeSanitizer(_policy)
```

```python
# From parrot/tools/pythonrepl.py:701-705 — el corazón; se MUEVE al worker sin reescribir
def _execute_code(
    self, query: str, debug: bool = False, enforce_security: bool = True,
) -> str: ...
```

```python
# From parrot/tools/pythonrepl.py:558 — denylist AST, SE CONSERVA (C6)
def _check_ast_security(self, tree: ast.AST) -> Optional[str]: ...
```

```python
# From parrot/tools/shell/tool.py:33-64
class ShellTool(SecureShellMixin, AbstractTool):
    name: str = "shell"                                                     # :46
    args_schema = ShellToolArgs                                             # :48

    def __init__(self, security_policy: Any = _NO_POLICY, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if security_policy is _NO_POLICY:
            self.set_security_policy(SecurityPolicy.moderate())              # :61
        elif security_policy is not None:
            self.set_security_policy(security_policy)
        # else: explicit None → _sanitizer stays None (all commands allowed)  # :64
```

#### Verified Imports

```python
# Confirmados en los ficheros subidos:
from parrot.security.redaction import redact_text                    # pythonrepl.py:36
from parrot.security.python_sanitizer import (
    PythonCodeSanitizer, general_profile,
)                                                                    # pythonrepl.py:231
from .security import SecurityPolicy, SecureShellMixin               # shell/tool.py:24-27
from .actions import (
    BaseAction, ActionResult, RunCommand, ExecFile, ListFiles,
    ReadFile, WriteFile, DeleteFile, CopyFile, MoveFile, CheckExists,
)                                                                    # shell/tool.py:10-22
from .engine import EvalAction                                       # shell/tool.py:23
from .models import CommandObject, ShellToolArgs, PlanStep           # shell/tool.py:9
```

#### Key Attributes & Constants

- `PythonREPLTool._bootstrapped` → `bool`, **variable de clase** (`:105`, leída en `:537`, escrita en `:556`). Migra a estado por worker; corrige el bug latente de multi-instancia
- `PythonREPLTool.locals` / `.globals` → `Dict` (`:244-245`). Namespace unificado en `:765-766`. **Deja de ser la fuente de verdad en el host**
- `PythonREPLTool.BLOCKED_IMPORTS` → `set` de 17 módulos (`:108-127`)
- `PythonREPLTool.BLOCKED_NAMES` → `set` de 15 nombres (`:128-145`)
- `PythonREPLTool.BLOCKED_ATTRIBUTES` → `set` de ~28 atributos (`:152-185`). Comentario sobre la tensión con pandas en `:146-151`
- `PythonREPLTool._ERROR_OUTPUT_RE` → `re.Pattern` (`:936`). Clasifica salida como error; el worker debe preservar el formato exacto
- `locals["execution_results"]` → `dict` (`:480`, `:431`, `:1031`, `:1063`)
- `locals["save_current_plot"]` → closure sobre `self.output_dir` (`:366`, registrado `:482`, usado `:617`)
- `ShellTool._sanitizer` → establecido por `set_security_policy()`; `None` significa **todo permitido** (`:64`)
- `ShellTool.assert_command_safe()` → invocado en `:146` (modo comando) y `:254` (modo plan), **antes** de construir la acción

### Does NOT Exist (Anti-Hallucination)

- ~~Cualquier timeout, `signal`, `resource`, `rlimit`, `kill` o `terminate` en `pythonrepl.py`~~ — verificado por grep: **cero ocurrencias**. No hay nada que extender; hay que construirlo
- ~~Un executor dedicado para el REPL~~ — `pythonrepl.py:970` usa `run_in_executor(None, ...)`, el **pool compartido por defecto**
- ~~Una forma de matar un hilo de Python desde fuera~~ — no existe en el lenguaje. Es la razón por la que la Opción A no puede cumplir C2
- ~~`resource.setrlimit()` con ámbito de hilo~~ — es por proceso. Sin frontera de proceso, apunta al servidor
- ~~Aislamiento por sesión en el REPL actual~~ — `self.locals` es por instancia de tool, y `_bootstrapped` es por clase. No hay noción de sesión hoy
- ~~Un filtro de RTK para salida arbitraria de REPL~~ — RTK filtra stdout de comandos de desarrollo conocidos. `PythonREPLTool` emite stdout arbitrario de usuario. **La migración a subproceso NO habilita RTK para el REPL**; ese ruido lo cubre el codec `repl_stdout` del otro brainstorm
- ~~`fork` como método de arranque seguro~~ — matplotlib, los pools de conexión y los hilos del padre no toleran `fork`. Debe ser `spawn`

---

## Parallelism Assessment

- **Internal parallelism**: Media, con una dependencia dura. `repl-worker-runtime` debe llegar primero: congela el protocolo de control y el contrato del handle. `repl-state-transport` depende de ese protocolo y no puede arrancar antes sin reinventarlo. `shell-rtk-integration` es **totalmente independiente** — otro fichero, otro problema, cero código compartido; puede ir en paralelo desde el minuto uno o por otra persona.
- **Cross-feature independence**: **Colisión conocida con el brainstorm de compresión de `ToolResult`.** Aquel toca `ToolManager.execute_tool()` y el contrato de resultados; este cambia el contexto de ejecución de la herramienta que más resultados voluminosos produce. Ambos incluyen a `PythonREPLTool` en su radio. Por decisión del equipo, la compresión se congela **as-is** hasta que estos cambios aterricen. Ficheros compartidos a vigilar: `parrot/tools/manager.py` (`share_dataframe` / `auto_push_to_pandas`) y `parrot/tools/pythonpandas.py`.
- **Recommended isolation**: mixed — un worktree secuencial para `repl-worker-runtime`, luego `repl-state-transport`; `shell-rtk-integration` en worktree propio desde el principio.
- **Rationale**: El protocolo de control es la superficie de acoplamiento de toda la feature. Dos worktrees definiéndolo a la vez producen un merge caro y un protocolo de compromiso. Serializar esa pieza y paralelizar lo que cuelga de ella es el reparto barato. `shell-rtk-integration` no comparte nada y no debería esperar a nadie.

---

## Open Questions

> Todas resueltas interactivamente con el usuario el 2026-07-27 (sesión /sdd-brainstorm).

- [x] **Paliativo inmediato**: ¿se sustituye `run_in_executor(None, ...)` en `pythonrepl.py:970` por un `ThreadPoolExecutor` dedicado y acotado, mientras se construye el worker? — *Owner: Jesus Lara*: **Sí, se despliega ya.** Cambio pequeño e independiente que aterriza en `dev` antes de la feature (executor dedicado y acotado, p.ej. 4 hilos). Un bucle desbocado agota solo el pool del REPL, no el pool compartido del framework.
- [x] Auditar todos los accesos externos a `PythonREPLTool.locals` / `.globals`. — *Owner: Jesus Lara*: **Auditoría hecha (2026-07-27, verificada por grep sobre `packages/ai-parrot/src/parrot/`).** Superficie real — 5 módulos: (1) `bots/data.py` — lecturas directas múltiples de `pandas_tool.locals` (`:1800, :2329, :2626-2628, :2655, :2743-2748, :2810-2815`), incluye `execution_results`; (2) `bots/agent.py:174-219` — la working memory guarda una **referencia viva** a `tool.locals` (`wm._tool_locals[key] = tool.locals`), semántica imposible de preservar cruzando proceso; (3) `tools/agent.py:421-427` — **escrituras** host→namespace (`python_repl.globals['previous_result']`, `f'{safe_name}_result'`); (4) `outputs/formats/base.py:137` — devuelve `tool.locals`; (5) `tools/pythonpandas.py:218-236, 292` — `clone()` copia locals/globals y fusiona `df_locals`. **Decisión: API de namespace explícita** (`get_var` / `set_var` / `list_vars` / `snapshot`) respaldada por el protocolo del worker, y portar los 5 call sites. Sin dict-proxy de compatibilidad (round-trips por clave, semántica de iteración sutil, y la referencia viva rompería igual en silencio).
- [x] Closures del namespace: ¿worker autónomo o stubs RPC? — *Owner: Jesus Lara*: **Worker autónomo escribiendo a directorio compartido** (lo ya recomendado). Los closures se recrean en el worker apuntando a un directorio visible por el host; solo viaja la ruta (o base64). Sin canal RPC worker→host.
- [x] ¿Dónde corre el gate estático? — *Owner: Jesus Lara*: **Ambos.** El host rechaza barato y temprano (sin round-trip para código condenado); el worker revalida antes de `exec` como defensa en profundidad — protege incluso si algún caller futuro llega al worker sin pasar por la ruta del host. Coste: un parse AST extra, despreciable.
- [x] Calibrar `RLIMIT_AS`. — *Owner: Jesus Lara*: **Default configurable y generoso (~4 GiB) + tarea explícita de calibración** en la spec que mida cargas reales de pandas (cargas de datasets, merges, plots) antes de fijar el default definitivo. La calibración es trabajo empírico, no decisión de brainstorm.
- [x] Windows. — *Owner: Jesus Lara*: **POSIX completo, Windows degradado.** v1: rlimits completos en Linux/macOS; en Windows el worker corre igualmente en proceso separado con timeout duro + terminate (funciona en todas partes), pero sin rlimits de memoria/CPU. Documentado de forma visible. Job Objects anotado como seguimiento si aparece demanda Windows.
- [x] Techo de workers y TTL. — *Owner: Jesus Lara*: **Rechazo inmediato al alcanzar el techo** con error claro al LLM (sin cola indefinida, como ya decía la tabla de edge cases). Defaults: techo `max(4, cpu_count)` con tope ~16; TTL de inactividad 30 min. Los tres valores configurables por despliegue.
- [x] ¿Pool de pre-calentado en v1? — *Owner: Jesus Lara*: **Sí, se incluye en v1** (tamaño configurable, default pequeño). La primera llamada en producción pasa de 1–3 s a milisegundos. *(Decisión del usuario, asumiendo el coste extra de lifecycle en la primera release.)*
- [x] ¿Cómo se comunica la pérdida de namespace tras un kill? — *Owner: Jesus Lara*: **Error estructurado con lista de variables.** Mantiene la forma `{status, result, error}` (C5); el mensaje indica: causa **diferenciada** (timeout vs memoria — el LLM debe reintentar distinto), que TODAS las variables se perdieron, la **lista de nombres** que existían antes del kill (el host mantiene un shadow barato de solo-nombres vía `list_ns`), y la instrucción de recrear estado antes de reintentar.

---

## Nota de seguridad: `rtk` como bypass de allowlist en `ShellTool`

> **Trasladada (2026-07-27)**: la versión normativa de esta nota, con las decisiones
> ya tomadas, vive ahora en `sdd/proposals/shelltool-hardening.brainstorm.md`.
> Se conserva aquí como contexto histórico.

Va aparte porque no es un detalle de implementación, es un requisito de seguridad de `shell-rtk-integration`.

`rtk <cualquier-comando>` es un **envoltorio universal de ejecución**: lanza por debajo el comando que se le pase. Si `rtk` acaba en el allowlist de `SecurityPolicy`, el sanitizer valida `rtk` y **no ve lo que `rtk` va a ejecutar**. El allowlist entero queda anulado por un solo prefijo.

El orden actual del código es el correcto y hay que preservarlo: `assert_command_safe()` valida el comando original en `shell/tool.py:146` (modo comando) y `:254` (modo plan), **antes** de que `_make_action_from_cmdobj` (`:167-198`) construya la acción. Insertar el prefijo dentro de `_make_action_from_cmdobj` es limpio porque la validación ya ocurrió sobre el comando real.

Hacen falta las dos mitigaciones, no una:

1. **El prefijo lo añade solo la herramienta**, en `_make_action_from_cmdobj`. Nunca el agente, nunca el usuario.
2. **`assert_command_safe()` debe rechazar `rtk` como entrada**, o pelarlo y validar el remanente recursivamente. Sin esto, `rtk <lo-que-sea>` escrito por el agente pasa el sanitizer.

Y una condición de alcance: la reescritura debe ser un **prefijo puro** (`cmd` → `rtk cmd`), nunca una transformación que pueda reintroducir algo que el sanitizer rechazó. Cualquier reescritura más lista que un prefijo exige revalidar el resultado.
