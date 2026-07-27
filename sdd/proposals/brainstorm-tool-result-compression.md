---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: Tool Result Compression Pipeline

**Date**: 2026-07-27
**Author**: <name>
**Status**: exploration
**Recommended Option**: Option B

---

## Problem Statement

Los resultados de herramientas entran al contexto del LLM sin ninguna reducción semántica. Hoy la única defensa existente es el truncado por caracteres del cliente de Google (`MAX_TOOL_RESULT_CHARS = 200_000` en `parrot/clients/google/client.py`), y tiene tres problemas:

1. **Es posicional, no semántico.** `_truncate_large_result()` hace búsqueda binaria sobre listas y se queda con los *primeros N* elementos. No hay garantía de que los primeros N sean los relevantes; en un resultado de tests lo relevante son los fallos, en una búsqueda vectorial son los chunks de mayor score.
2. **Vive en el cliente equivocado.** Solo el cliente de Google trunca. `parrot/clients/claude.py`, `groq.py` y `grok.py` no tienen ninguna protección equivalente. Cada cliente nuevo hereda el problema desde cero.
3. **Pierde información sin escotilla.** Cuando trunca, lo truncado desaparece. El LLM no tiene forma de recuperar lo que se cortó salvo reejecutar la herramienta.

El coste es doble: tokens de entrada desperdiciados en ruido estructural (claves JSON repetidas, campos nulos, valores redundantes) y **degradación de razonamiento** — el contexto se llena de relleno y queda menos espacio útil para el problema real.

El caso más caro medido a ojo en el codebase es `DatabaseQueryToolkit`: `QueryResult.rows` es `list[dict[str, Any]]`, es decir, los nombres de las N columnas se repiten en cada una de las M filas. Para 500 filas × 12 columnas eso son ~6.000 repeticiones de nombres de campo que el modelo no necesita ver más de una vez.

### Quién se ve afectado

- **Agentes con toolkits de datos** (`DatabaseQueryToolkit`, `DatasetManager`, `PythonPandasTool`): payloads tabulares grandes.
- **Agentes RAG** (`MultiStoreSearchTool`, `VectorStoreSearchTool`): chunks casi duplicados entre stores.
- **Toolkits de API** (`OpenAPIToolkit`): respuestas JSON verbosas con nulos y estructuras anidadas repetitivas.
- **Cualquier consumidor de clientes distintos de Google**, que hoy no tiene ninguna red de seguridad.

### Por qué ahora

El ecosistema ya validó la idea. RTK (`rtk-ai/rtk`, Apache-2.0, Rust) demuestra reducciones del 60–90% sobre salida de comandos usando cuatro estrategias deterministas (filtrado, agrupación, truncado con contexto, deduplicación) más un mecanismo `tee` que preserva la salida completa cuando el comando falla. La arquitectura es directamente trasladable; el código no (ver *Options Explored*, nota sobre reutilización de RTK).

Además, dos piezas de ai-parrot ya están listas y sin explotar para esto:
- `WorkingMemoryToolkit` ya implementa exactamente el patrón "resumen compacto al LLM + objeto completo recuperable bajo demanda" (`store_result` / `get_result` / `GenericEntry.compact_summary()`).
- El sistema de eventos FEAT-176 ya emite `AfterToolCallEvent` con `result_size_bytes`, que es la telemetría necesaria para medir el ratio de compresión sin instrumentación adicional.

---

## Constraints & Requirements

- **C1 — Agnóstico de cliente.** La compresión debe aplicarse una sola vez, antes de que el resultado llegue a cualquier `AbstractClient`. No puede duplicarse por cliente.
- **C2 — Opt-out total y por defecto conservador.** Un despliegue existente que no configure nada debe comportarse igual que hoy. La compresión arranca desactivada o en el nivel más suave.
- **C3 — Sin pérdida irrecuperable.** Todo lo que se comprima con pérdida debe ser recuperable por el agente sin reejecutar la herramienta.
- **C4 — Determinista y sin LLM.** Ningún compresor puede invocar un modelo. Además de coste y latencia, la compresión de prompts es una superficie de ataque documentada (*CompressionAttack*, arXiv:2510.22963): un compresor no determinista es un vector de manipulación.
- **C5 — Nunca comprimir errores por defecto.** Cuando `ToolResult.status != "success"`, el nivel de filtrado cae a `NONE` salvo configuración explícita en contra. Un error truncado es un error indepurable.
- **C6 — Extensible sin tocar Python.** Añadir un compresor para una herramienta de terceros (`parrot_tools`, `plugins.tools`) no debe requerir modificar el core.
- **C7 — Presupuesto de latencia con corte automático.** Coste inline (sobre el event loop) ≤ **1 ms p99**. Por encima del umbral de tamaño, el trabajo se desplaza a executor con GIL liberado. Un codec que incumpla su presupuesto de forma sostenida se degrada solo a passthrough. Ver §5 *Presupuesto de latencia*.
- **C8 — Extensión nativa opcional.** Si se introduce una extensión Rust, debe degradar a una implementación Python pura cuando no esté compilada, siguiendo el patrón `lazy_import` ya usado para `faiss` y `sentence_transformers`.
- **C9 — Nunca bloquear el event loop.** ai-parrot es asyncio. Un compresor síncrono de 50 ms no cuesta 50 ms a esa petición: estanca **todas** las peticiones concurrentes en vuelo. Cualquier trabajo por encima del umbral inline debe ejecutarse liberando el GIL, o no ejecutarse.

---

## Options Explored

### Nota previa: ¿cuánto de RTK se puede reutilizar?

Evaluado y descartado como dependencia de código. RTK es un **crate binario**, no una librería: el enrutado es un enum `Commands` de Clap en `src/main.rs`, se lanza el proceso con `std::process::Command` y se filtra stdout. No expone una API pública tipo `rtk::filter(bytes, kind)` a la que enlazar vía PyO3. Forkear para añadir `lib.rs` es legalmente viable (Apache-2.0) pero implica mantener un fork contra un repo con release cada pocas semanas.

Más de fondo: **los filtros de RTK están indexados por semántica de comando, no por forma de dato**. Operan sobre stdout de comandos conocidos (`git status`, `pytest`, `cargo build`). Nuestros payloads son `dict`, `list`, `DataFrame` y modelos Pydantic. La lógica no transfiere.

**Lo que sí se reutiliza de RTK: la arquitectura** (registro declarativo, niveles de filtrado, tee, telemetría de ahorro) y, opcionalmente, **el binario tal cual** para tools que ya invocan subprocesos (`rtk err <cmd>`, `rtk test <cmd>`, `rtk proxy <cmd>` aceptan comandos arbitrarios). Esto último queda fuera de alcance de esta feature y se anota como seguimiento.

---

### Option A: Extender el truncado por cliente

Replicar el patrón actual de `parrot/clients/google/client.py` en cada cliente, mejorando `_truncate_large_result()` para que sea semántico en vez de posicional.

✅ **Pros:**
- Cambio mínimo y localizado; no toca la ruta de ejecución de herramientas.
- Cada cliente puede afinar contra su propio límite real de contexto y su propio tokenizer.
- Riesgo de regresión muy bajo — el código que se toca ya existe y ya está en producción.

❌ **Cons:**
- Viola C1 frontalmente: N clientes × M compresores. El coste de mantenimiento crece multiplicativamente.
- Cada cliente nuevo arranca sin protección hasta que alguien se acuerde de portarla.
- El cliente ve el resultado ya serializado y sin el `ToolResult` original: pierde `metadata`, `status` y el nombre de la herramienta, que es justo lo que permite elegir el compresor correcto.
- No hay sitio natural para el tee: el cliente no conoce el `WorkingMemoryToolkit` de la sesión.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | ninguna nueva | usa `datamodel.parsers.json` ya presente |

🔗 **Existing Code to Reuse:**
- `parrot/clients/google/client.py` — `_truncate_large_result()`, `_process_tool_result_for_api()`, constante `MAX_TOOL_RESULT_CHARS`

---

### Option B: Etapa de compresión en `ToolManager` con registro declarativo

Introducir una etapa de transformación en `ToolManager.execute_tool()`, en el punto donde ya se desempaqueta el `ToolResult` y se ejecutan `_postprocess_result()` y `_run_result_hooks()`. Los compresores se resuelven desde un registro poblado por ficheros TOML/YAML declarativos, con un `FilterLevel` por herramienta y un tee automático hacia `WorkingMemoryToolkit`.

Punto clave: `ToolManager.add_result_hook()` tiene la firma `Callable[[str, Any, Dict[str, Any]], None]` — los hooks actuales **observan pero no transforman**. Esta opción añade una cadena de transformadores paralela y separada, sin romper el contrato existente de `_result_hooks`.

✅ **Pros:**
- Un único punto de intercepción para todos los clientes y para las dos rutas de ejecución (`AbstractTool` y `ToolkitTool`). Satisface C1.
- En ese punto se tiene todo lo necesario: `tool_name`, el objeto Python sin serializar, `metadata` y `status`. Permite selección de compresor y decisión de nivel con contexto completo.
- El `ToolManager` es un objeto de sesión (`clone()` existe precisamente para aislamiento por usuario), así que tiene acceso natural al `WorkingMemoryToolkit` de la sesión para el tee.
- El registro declarativo cubre C6: `parrot_tools` y `plugins.tools` declaran sus compresores en su propio TOML sin tocar el core, igual que ya hacen con `TOOL_REGISTRY`.
- Los compresores son unidades puras y testeables en aislamiento (entrada: objeto Python; salida: objeto Python + métricas).

❌ **Cons:**
- Toca `ToolManager.execute_tool()`, que está en la ruta caliente de todos los agentes. Requiere cobertura de tests cuidadosa.
- Introduce un concepto nuevo (compresores) que hay que documentar y que los autores de toolkits deben aprender.
- **Conflicto conocido a resolver**: hoy `execute_tool()` hace `raise ValueError(result.error)` cuando `status == "error"`, descartando `result.result`. El tee de errores necesita capturar el payload *antes* de ese raise, lo que implica reordenar esa rama.
- No cubre resultados que nunca pasan por `ToolManager` (p. ej. `clients/live.py` invoca `tool._execute()` directamente). Requiere una segunda pasada o aceptar la brecha conscientemente.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `tomllib` | parseo de TOML | stdlib desde Python 3.11, sin dependencia nueva |
| `pydantic` | validación del schema de configuración | ya es dependencia core |
| `datamodel.parsers.json` | serialización | ya en uso en `tools/abstract.py` |

🔗 **Existing Code to Reuse:**
- `parrot/tools/manager.py` — `execute_tool()` (punto de inserción), `add_result_hook()` / `_run_result_hooks()` (patrón a imitar), `clone()` (lista de estado no compartido a extender)
- `parrot/tools/abstract.py` — `ToolResult`, `AbstractTool.execute()`
- `parrot/tools/toolkit.py` — `AbstractToolkit._post_execute()`, que **sí** devuelve el resultado transformado; es el precedente del contrato que queremos
- `parrot/tools/discovery.py` + `parrot/tools/registry.py` — mecánica de descubrimiento multi-fuente a replicar para los TOML
- `parrot/tools/working_memory/tool.py` — `store_result()`, `get_result()`
- `parrot/core/events/lifecycle/events.py` — `AfterToolCallEvent.result_size_bytes`

---

### Option C: Compresión declarada por el autor de cada tool

Cada `AbstractTool` / `AbstractToolkit` declara su propio compresor como método o atributo de clase (p. ej. `compress_result()`), invocado por `AbstractTool.execute()` al construir el `ToolResult`.

✅ **Pros:**
- El autor de la herramienta es quien mejor conoce la forma de su payload y qué es descartable.
- Sin registro ni configuración: la compresión viaja con la herramienta.
- Encaja bien con toolkits externos que se distribuyen como paquetes independientes.

❌ **Cons:**
- Adopción voluntaria: las herramientas que más inflan el contexto suelen ser las de terceros, que es justo donde no controlamos el código.
- No hay política central. Imposible responder "¿qué nivel de compresión está activo en este despliegue?" ni desactivarla globalmente para depurar. Compromete C2.
- El tee necesita acceso al `WorkingMemoryToolkit` de la sesión, que el tool individual no tiene.
- Sin punto único de medición, la telemetría de ahorro queda dispersa.
- Duplicación garantizada: la compresión columnar la reimplementarían tres toolkits distintos.

📊 **Effort:** Low-Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | ninguna nueva | |

🔗 **Existing Code to Reuse:**
- `parrot/tools/abstract.py` — `AbstractTool.execute()`
- `parrot/tools/toolkit.py` — `AbstractToolkit._post_execute()`

---

## Recommendation

**Option B** es la recomendada.

El argumento decisivo es C1. Las opciones A y C distribuyen la responsabilidad entre N clientes o N herramientas; el coste no está en escribir el primer compresor sino en garantizar que el compresor número veinte, escrito por otro equipo dentro de un año, sigue las mismas reglas. Un choke point único con registro declarativo es la única de las tres que hace cumplible esa garantía.

El segundo argumento es la disponibilidad de contexto. En `ToolManager.execute_tool()` tenemos simultáneamente el `tool_name`, el objeto Python **sin serializar**, el `status` y la `metadata`. La Opción A ve el payload demasiado tarde (ya serializado, sin identidad de herramienta) y la Opción C demasiado pronto (sin acceso al estado de sesión que necesita el tee).

**Lo que se sacrifica, explícitamente:**

- *Afinado por cliente.* Comprimimos una vez con un presupuesto genérico, no contra el límite real de contexto de cada modelo. Es un compromiso aceptable: el objetivo no es apurar el límite sino eliminar el ruido estructural, y el ruido es ruido independientemente del modelo. Si más adelante hace falta, cada cliente puede seguir aplicando su truncado duro como última línea — son capas complementarias, no excluyentes.
- *Un concepto nuevo que documentar.* Se acepta a cambio de que sea un concepto y no veinte implementaciones ad hoc.
- *Un cambio semántico en telemetría.* `AfterToolCallEvent.result_size_bytes` pasa a significar tamaño post-compresión. Se prefiere esto a proliferar eventos, pero exige entrada de changelog.

*Nota: la brecha de `clients/live.py` — que invoca `tool._execute()` saltándose `ToolManager` — se detectó durante este brainstorm y entra en alcance en vez de quedar como deuda. Es exactamente el tipo de ruta que, dejada fuera, invalida la garantía de punto único que justifica esta opción.*

Se toma de la Opción C una idea concreta: el registro permite que un toolkit **declare** su compresor preferido, de modo que el autor de la herramienta conserva la voz sin quedarse con toda la responsabilidad.

---

## Feature Description

Cuatro componentes que se construyen en este orden de dependencia:

```
  ┌──────────────────────────────────────────┐
  │ 1. Registro declarativo + Protocol       │  ← base, bloquea a los demás
  └──────────────┬───────────────────────────┘
                 │
     ┌───────────┼───────────┐
     ▼           ▼           ▼
  ┌───────┐  ┌───────┐  ┌──────────────┐
  │ 2.    │  │ 3.    │  │ 4. Codec     │
  │ Filter│  │ Tee   │  │ columnar     │  ← paralelizables tras congelar el Protocol
  │ Level │  │       │  │ (Rust/Py)    │
  └───────┘  └───────┘  └──────────────┘
```

### 1. Registro declarativo TOML/YAML

**Formato.** Un fichero por paquete declara qué compresor aplica a qué herramienta y con qué parámetros:

```toml
[compressor."execute_database_query"]
codec = "columnar"
level = "normal"
tee = true

  [compressor."execute_database_query".params]
  min_rows = 20          # por debajo, columnar no compensa → passthrough
  drop_null_columns = true

[compressor."search_documents"]
codec = "rag_dedup"
level = "normal"

  [compressor."search_documents".params]
  similarity_threshold = 0.92
  group_by = "source"

# Comodín: se aplica a cualquier tool sin entrada explícita
[compressor."*"]
codec = "json_compact"
level = "minimal"
```

**Resolución.** Idéntica en espíritu a `TomlFilterRegistry::load()` de RTK y al descubrimiento multi-fuente que ya tenéis en `parrot/tools/discovery.py`, con precedencia de más específico a más general:

1. `.parrot/compressors.toml` del proyecto (override del usuario final)
2. `parrot_tools` y `plugins.tools` (declaraciones de paquetes de terceros)
3. Defaults embebidos en el core

Coincidencia exacta de `tool_name` gana sobre patrón glob, que gana sobre `"*"`. Cuando una entrada de usuario ensombrece una built-in, se emite un `logger.warning` — RTK hace exactamente esto y el aviso es lo que evita horas de depuración a ciegas.

**Validación en arranque.** El TOML se valida contra un modelo Pydantic al cargar. Un `codec` inexistente es un error de configuración explícito, no un fallo silencioso en la primera llamada a la herramienta.

**Protocol del compresor.** El contrato que congela el resto del trabajo:

```python
class ResultCompressor(Protocol):
    codec_name: ClassVar[str]

    def compress(
        self,
        result: Any,
        *,
        level: FilterLevel,
        params: dict[str, Any],
    ) -> CompressionOutcome: ...
```

`CompressionOutcome` transporta el payload comprimido, las métricas (bytes antes/después, estimación de tokens) y una bandera `lossy` que indica si hay que activar el tee.

### 2. FilterLevel

Enum de cuatro valores, siguiendo el `FilterLevel {None, Minimal, Aggressive}` de RTK más un nivel intermedio:

| Nivel | Comportamiento |
|---|---|
| `NONE` | Passthrough. El resultado llega intacto. |
| `MINIMAL` | Solo transformaciones **sin pérdida**: compactado de separadores JSON, elisión de claves nulas, deduplicación exacta. Reversible en la práctica. |
| `NORMAL` | Añade transformaciones con pérdida acotada: columnarización, agrupación, recorte de campos largos con marcador. Activa el tee. |
| `AGGRESSIVE` | Solo resumen estructural: esquema, agregados, muestra. El cuerpo completo vive únicamente en working memory. |

**Resolución del nivel efectivo**, de mayor a menor precedencia:

1. Override por llamada (kwarg en `execute_tool`)
2. `status != "success"` → fuerza `NONE` (C5)
3. Entrada de `tool_name` en el TOML
4. Default global de configuración
5. `MINIMAL` cuando no hay nada configurado (C2: por defecto solo sin pérdida)

`MINIMAL` como default es deliberado. Es lo suficientemente conservador para activarse sin configuración en despliegues existentes, y ya recoge la fruta baja.

**Calibración honesta sobre `MINIMAL`.** El compactado de separadores rinde menos de lo que sugiere el diff de bytes: los tokenizers BPE fusionan runs de espacios e indentación, así que un JSON *pretty-printed* cuesta bastante menos de lo que pesa. Esperar del orden de 5–15% en tokens, no el 40% del tamaño en disco. El grueso del ahorro está en `NORMAL` (columnar + dedup), no en `MINIMAL`. Este número hay que medirlo, no asumirlo.

### 3. Tee de errores hacia WorkingMemoryToolkit

Cuando la compresión es con pérdida, o cuando la herramienta falla, el payload íntegro se persiste y el LLM recibe un puntero en vez de un agujero.

`WorkingMemoryToolkit` ya hace justo esto — `store_result()` acepta cualquier objeto Python, autodetecta el `EntryType` y devuelve un `compact_summary()`; `get_result()` lo recupera con `include_raw=True`. La feature solo tiene que conectar el cableado.

**Flujo:**

```
tool falla o comprime con pérdida
   │
   ├─→ wm.store_result(key="__tee__:<tool>:<turn_id>", data=<payload íntegro>,
   │                    metadata={"reason": "error"|"lossy", "tool": ...})
   │
   └─→ el resultado que ve el LLM lleva anexado:
       {"_tee": {"key": "__tee__:execute_database_query:t7",
                 "reason": "lossy",
                 "hint": "usa wm_get_result para el payload completo"}}
```

Frente al fichero en disco de RTK esto es estrictamente mejor: el modelo no necesita una herramienta de lectura de ficheros ni permisos de FS, tiene `wm_get_result` ya registrada como tool con su schema.

**Ventaja sobre el diseño de RTK: la recuperación es parcial.** RTK escribe el log completo; leerlo devuelve al agente todo el ruido de golpe. Con working memory, si el payload es un DataFrame el agente puede aplicarle el DSL declarativo (`compute_and_store` con `filter`, `aggregate`, `describe`) y recuperar *solo la parte que necesita*.

**Ciclo de vida.** Las entradas de tee se etiquetan con `turn_id` y son descartables. Política inicial: retención por número de turnos (últimos N), con `drop_stored()` en la limpieza de sesión. Sin persistencia a disco en v1.

**Conflicto a resolver.** Hoy `ToolManager.execute_tool()` hace `raise ValueError(result.error)` cuando `status == "error"`, descartando `result.result`. El tee de errores necesita capturar el payload antes. Hay que reordenar esa rama preservando el comportamiento observable para los llamantes actuales (la excepción se sigue lanzando; solo se guarda el payload antes de lanzarla).

**Degradación.** Si no hay `WorkingMemoryToolkit` registrado en el `ToolManager`, el tee se desactiva y el nivel efectivo cae a `MINIMAL`. Nunca se comprime con pérdida sin destino de recuperación (C3).

### 4. Codec columnar

La transformación central, y la de mayor retorno medible.

**Entrada** (forma *row-oriented*, la que produce hoy `QueryResult.rows`):

```json
[{"store_id": "TCTX", "revenue": 801467.93, "region": "south", "active": true},
 {"store_id": "OMNE", "revenue": 587654.26, "region": "south", "active": true}]
```

**Salida** (forma *split*, idéntica a `PandasTable`):

```json
{"columns": ["store_id", "revenue", "region", "active"],
 "rows": [["TCTX", 801467.93, "south", true],
          ["OMNE", 587654.26, "south", true]],
 "constants": {"region": "south", "active": true}}
```

Tres reducciones acumuladas: los nombres de columna aparecen una vez en lugar de M veces; las columnas de valor constante se factorizan fuera de las filas; las claves con valor nulo en todas las filas se eliminan (registrándolo en metadata).

**Por qué este formato y no otro.** No estamos inventando nada: `PandasTable` en `parrot/bots/data.py` ya es exactamente `columns: List[str]` + `rows: List[List[Scalar]]`, y el prompt de `PandasAgentResponse` ya instruye al modelo sobre ese formato ("Use this format: `{'columns': [...], 'rows': [[...], ...]}`"). El LLM ya está entrenado por vuestro propio prompt para leerlo. Reutilizarlo elimina el riesgo de que el modelo malinterprete una forma nueva.

**Cuándo NO columnarizar.** El codec debe hacer passthrough cuando no gana:
- Menos de **20 filas** (`min_rows`, decidido). Con pocas filas el overhead del wrapper supera al ahorro.
- Filas heterogéneas (unión de claves mucho mayor que la intersección). La matriz resultante se llena de nulos y crece.
- Anidamiento profundo. Si los valores son a su vez dicts o listas, aplanar rompe la estructura; en ese caso se aplica solo elisión de nulos.

El umbral de heterogeneidad sí queda por calibrar; `min_rows = 20` está fijado y es configurable por herramienta en el TOML.

**Implementación Rust: dónde paga y dónde no.**

*Confirmado: el codebase ya integra PyO3 con maturin, así que no hay coste de arranque de toolchain.*

El criterio de diseño que decide la arquitectura: **no cruzar la frontera FFI con estructuras Python**. Si el payload ya es un `dict` materializado, `PyO3::extract()` sobre cada `PyDict` cruza la frontera una vez por fila con el GIL tomado — para grafos de objetos esto puede salir **más lento que Python puro**. La ganancia de Rust se evapora si se paga en conversiones.

Rust rinde en tres escenarios, y el tercero es el decisivo:

1. **El origen ya son bytes.** Body de respuesta HTTP en `OpenAPIToolkit`, stdout de subproceso, resultado crudo de driver. Se parsea, transforma y devuelve buffer sin materializar nunca el dict en Python: **un solo cruce FFI**. `serde_json` (o `simd-json`) en ese camino sí compensa.
2. **Volumen alto.** Decenas de miles de filas, donde el walk en Python empieza a notarse de verdad.
3. **Liberación del GIL — el argumento real.** Un compresor en Python puro mantiene el GIL tomado, así que mandarlo a `run_in_executor` **no compra paralelismo**: solo mueve el bloqueo de sitio. El mismo trabajo en Rust bajo `py.allow_threads()` sí corre en paralelo de verdad, y convierte el offload a executor en una mitigación real en vez de cosmética.

El punto 3 es lo que hace que Rust deje de ser una optimización opcional y pase a ser la única forma de cumplir C9 para payloads grandes. Precedente en el codebase: `PythonREPLTool._execute()` ya hace `loop.run_in_executor(None, self._execute_code, code, debug)` precisamente para no bloquear el loop — mismo patrón, pero ahí el GIL sigue tomado durante el `exec()`.

**Diseño resultante:** el codec expone dos caminos con la misma semántica.

```
compress(result)
   │
   ├── result es bytes/str      → parrot_codec.to_columnar_bytes()   [Rust, si disponible]
   │                              fallback → json.loads + camino Python
   │
   └── result es dict/list      → camino Python sobre el grafo de objetos
                                  (cruzar FFI aquí sería contraproducente)
```

La extensión Rust es **opcional y detectada en runtime** (C8), siguiendo el patrón `lazy_import` que ya usáis para `faiss`. Sin ella, todo funciona igual, más lento en el camino de bytes y sin liberación de GIL.

### 5. Presupuesto de latencia

La ejecución de herramientas ya es ruta crítica. Esta sección fija el contrato de latencia para que la compresión no pueda degradarla nunca.

**Por qué el `<10ms` de RTK no es la referencia correcta.** Ese número es el *overhead de arranque de un binario separado*: spawn de proceso, parseo de argumentos, carga de config. RTK lo paga porque **es** otro proceso, y se amortiza contra un comando (`git`, `pytest`, `cargo`) que de por sí tarda entre cientos de milisegundos y varios segundos. Nosotros llamamos in-process vía PyO3: sin spawn, sin exec, sin pipes. Nuestro suelo son microsegundos. **Si nuestra etapa costase 10 ms, sería un fallo de diseño, no un objetivo alcanzado.**

**Por qué la compresión probablemente es latencia NEGATIVA.** Los tokens de entrada ahorrados son tiempo de prefill ahorrado. A ritmos típicos de prefill, del orden de 10–50k tok/s, eliminar 8.000 tokens de contexto recorta aproximadamente 150–800 ms de TTFT. Si comprimir cuesta 1–2 ms, el retorno es de dos órdenes de magnitud. El marco mental "ahorro tokens a costa de latencia" es, con alta probabilidad, **al revés**: se ahorran tokens *y* tiempo. Pero esto hay que **medirlo, no asumirlo**, y solo se cumple si no se bloquea el event loop.

**Presupuesto operativo:**

| Franja | Ruta | Presupuesto |
|---|---|---|
| `MINIMAL`, cualquier tamaño | Inline, síncrono | ≤ 0,3 ms p99 |
| `NORMAL` / `AGGRESSIVE`, payload < umbral | Inline, síncrono | ≤ 1 ms p99 |
| `NORMAL` / `AGGRESSIVE`, payload ≥ umbral | `run_in_executor` + Rust con `allow_threads()` | ≤ 15 ms p99, fuera del loop |
| Sin extensión Rust y payload ≥ umbral | **Passthrough** | 0 ms |

Umbral inicial propuesto: **256 KB serializados o 5.000 filas**, el que se alcance primero. A calibrar con payloads reales.

La última fila es deliberada y es la regla que más protege: sin Rust no hay liberación de GIL, y sin liberación de GIL el offload es teatro. En ese caso **no se comprime**. Enviar un payload gordo es siempre preferible a estancar el event loop.

**Circuit breaker.** Cada codec lleva su p99 móvil por ventana. Si supera su presupuesto tres ventanas consecutivas, se degrada solo a passthrough y emite un `logger.warning` con el nombre del codec y la medición. Se rearma tras un periodo de enfriamiento. Un compresor mal escrito no puede convertirse en un incidente de latencia; como mucho deja de ahorrar.

**Medición desde el día uno.** Las métricas de duración viajan en `AfterToolCallEvent` junto con las de tamaño, de modo que el reporte de ahorro muestre siempre las dos caras: tokens ahorrados **y** milisegundos gastados. Un ahorro que no se pueda contrastar contra su coste no es evaluable.

### User-Facing Behavior

Para el **usuario final del agente**: nada visible, salvo respuestas mejores en tareas con resultados voluminosos, por tener más contexto útil disponible.

Para el **desarrollador que integra ai-parrot**:

- Sin configuración → `MINIMAL` global, solo transformaciones sin pérdida. Comportamiento actual preservado en lo esencial.
- Un `.parrot/compressors.toml` en el proyecto para subir el nivel por herramienta.
- Kill switch: `PARROT_COMPRESSION_DISABLED=1` desactiva todo y devuelve el comportamiento exacto de hoy. Imprescindible para depurar.
- Un reporte de ahorro por herramienta y sesión, derivado de eventos de ciclo de vida (equivalente funcional de `rtk gain`).

Para el **autor de un toolkit**: declara su compresor en el TOML de su paquete. Si no declara nada, cae al comodín.

### Internal Behavior

**Puertas de entrada — el pipeline ni se plantea si se cumple alguna:**

- `PARROT_COMPRESSION_DISABLED=1` (kill switch global).
- `tool.return_direct is True`. El resultado va directo al usuario sin pasar por el LLM; comprimirlo alteraría una salida que el autor de la herramienta emite deliberadamente tal cual. **Decidido: se salta el pipeline por completo**, incluido el tee.
- El resultado no procede de una **ejecución fresca**. **Decidido: solo se comprime en ejecución fresca.** Replay de historial conversacional, resultados rehidratados desde memoria y payloads con marcador `_compressed` en metadata pasan intactos. Consecuencia de diseño: el resultado ya comprimido es el que se persiste en memoria conversacional, así que se comprime una vez y viaja comprimido el resto de su vida.

Secuencia en `ToolManager.execute_tool()`, tras obtener el `ToolResult` y pasar las puertas:

1. **Resolver nivel efectivo** — precedencia descrita en §2. Si es `NONE`, saltar al paso 7.
2. **Resolver codec** — lookup en el registro por `tool_name`, con fallback a glob y a `"*"`. Sin coincidencia → passthrough.
3. **Ejecutar** `codec.compress(payload, level=..., params=...)` dentro de un `try/except`. **Cualquier excepción del compresor devuelve el payload original intacto** y registra un warning. Un compresor roto nunca puede romper una llamada a herramienta.
4. **Tee condicional** — si `outcome.lossy` o `status != "success"`, persistir el payload íntegro en working memory y anexar el bloque `_tee` al resultado comprimido.
5. **Métricas** — adjuntar bytes antes/después, codec aplicado, duración y marcador `_compressed` a `ToolResult.metadata`.
6. **Emitir telemetría** — **decidido: extender `AfterToolCallEvent`**, no crear evento nuevo. Campos añadidos: `compression_codec`, `compression_level`, `result_size_bytes_original`, `compression_duration_ms`, `compression_teed`. El campo `result_size_bytes` existente pasa a significar el tamaño *post*-compresión, que es el que realmente llega al modelo; el original va en el campo nuevo. Consumidores actuales del evento siguen leyendo un tamaño válido, aunque cambie de significado — **esto hay que anotarlo en el changelog**, es el único cambio semántico de la feature.
7. **Continuar** al `_postprocess_result()` / `_run_result_hooks()` existente, sin cambios en su contrato.

El paso 3 se ejecuta inline o en executor según el presupuesto de §5. La decisión se toma con el tamaño estimado antes de comprimir, no después.

El registro se carga una vez por proceso y se cachea. `ToolManager.clone()` comparte el registro por referencia (es inmutable tras la carga) pero **no** comparte el estado de métricas acumuladas, que debe añadirse a la lista de "no clonado" documentada en su docstring.

### Edge Cases & Error Handling

| Caso | Comportamiento |
|---|---|
| El compresor lanza excepción | Payload original intacto + `logger.warning`. Nunca propaga. |
| `status != "success"` | Nivel forzado a `NONE`; tee del payload íntegro antes del `raise` existente. |
| No hay `WorkingMemoryToolkit` en el manager | Tee desactivado; nivel efectivo topado a `MINIMAL`. Nunca pérdida sin recuperación. |
| Payload no serializable (objeto arbitrario) | Solo codecs que operen sobre el objeto sin serializar. Si ninguno aplica → passthrough. |
| Colisión de clave en el tee | Clave incluye `tool_name` + `turn_id` + contador. `put_generic` ya sobrescribe silenciosamente; el contador evita perder un tee previo del mismo turno. |
| Resultado ya comprimido (reejecución, replay de historial) | Marcador `_compressed` en metadata; el pipeline es idempotente y no recomprime. |
| Filas heterogéneas en el codec columnar | Detección por ratio unión/intersección de claves; passthrough con solo elisión de nulos. |
| Payload por debajo de `min_rows` | Passthrough, registrado como "sin ganancia" para el reporte de descubrimiento. |
| Extensión Rust ausente | Fallback Python transparente; se registra una vez a nivel debug, no por llamada. |
| TOML malformado o codec inexistente | Error en arranque con la ruta del fichero y la entrada culpable. Nunca fallo silencioso. |
| `return_direct is True` | Pipeline omitido por completo, tee incluido. El resultado sale tal cual lo emitió la herramienta. |
| Payload ≥ umbral y sin extensión Rust | Passthrough. Nunca compresión síncrona pesada sobre el event loop (C9). |
| Codec excede su presupuesto 3 ventanas seguidas | Circuit breaker → passthrough automático + warning con codec y medición. Rearme tras enfriamiento. |
| Resultado ya comprimido (`_compressed` en metadata) | Passthrough. Solo se comprime en ejecución fresca. |

---

## Capabilities

### New Capabilities

- `tool-result-compression`: registro declarativo TOML/YAML, `FilterLevel`, `ResultCompressor` Protocol y etapa de pipeline en `ToolManager.execute_tool()`. Base de la que dependen las otras dos.
- `compression-tee`: persistencia del payload íntegro en `WorkingMemoryToolkit` para resultados con pérdida o fallidos, con puntero recuperable en el resultado que ve el LLM.
- `columnar-codec`: transformación row-oriented → split (`columns`/`rows`), con elisión de nulos y factorización de constantes. Camino Rust (PyO3/maturin) con `allow_threads()` para entradas en bytes, fallback Python puro. Incluye el presupuesto de latencia y el circuit breaker.
- `rtk-subprocess-filter` *(seguimiento, baja prioridad)*: integrar el binario `rtk` en el entorno del sub-agente lanzado por `ClaudeAgentClient`. Independiente de las tres anteriores — no toca el pipeline ni comparte código. Puede hacerse antes, después o nunca.

### Modified Capabilities

<!-- Verificar contra docs/sdd/specs/ antes de rellenar. Candidatos: la spec de
     working_memory (si existe) se extiende con el namespace de claves de tee. -->

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/tools/manager.py` | modifies | Etapa de compresión en `execute_tool()`; reordenar la rama de `status == "error"` para permitir tee; extender la lista de estado no clonado en `clone()` |
| `parrot/tools/abstract.py` | extends | `ToolResult.metadata` gana campos de compresión. Sin cambios de firma |
| `parrot/tools/compression/` | new | Paquete nuevo: registro, `FilterLevel`, Protocol, codecs |
| `parrot/tools/working_memory/tool.py` | depends on | Consumidor de `store_result()` / `get_result()`. Sin cambios de API |
| `parrot/clients/google/client.py` | modifies | `MAX_TOOL_RESULT_CHARS` pasa a ser última línea de defensa, no primera. Evaluar si sube el umbral |
| `parrot/core/events/lifecycle/events.py` | extends | Campos de compresión en `AfterToolCallEvent` o evento nuevo |
| `parrot/tools/discovery.py` | extends | Descubrimiento de TOML de compresores junto al de `TOOL_REGISTRY` |
| `parrot/tools/databasequery/` | depends on | Primer consumidor real del codec columnar |
| `parrot/clients/live.py` | modifies | **En alcance.** Invoca `tool._execute()` saltándose `ToolManager` — brecha real detectada en este brainstorm. Debe redirigirse al pipeline. Ojo: es la ruta de voz, donde `voice_text` y `display_data` del `ToolResult` tienen tratamiento especial y **no** deben comprimirse |
| Extensión Rust (`parrot_codec`) | new / extends | Nuevo módulo o extensión del crate existente. Ver *Open Questions* |

**Breaking changes:** ninguno previsto. `MINIMAL` por defecto solo aplica transformaciones sin pérdida; el kill switch por variable de entorno restaura el comportamiento exacto.

**Nueva dependencia:** ninguna obligatoria. `tomllib` es stdlib; la extensión Rust es opcional.

---

## Code Context

> ⚠️ **Los números de línea NO están verificados.** Las rutas de fichero y las
> firmas de abajo se han confirmado leyendo el codebase, pero las líneas exactas
> deben verificarse con `grep`/`rg` en el repo antes de convertir este brainstorm
> en spec. Se marcan como `:TBD` deliberadamente en lugar de inventarlas — un
> número de línea falso en esta sección es peor que ninguno, porque el objetivo
> de la sección es prevenir alucinaciones aguas abajo.

### User-Provided Code

```python
# Source: user-provided (esbozo de diseño, no es código del repo)
class ResultCompressor(Protocol):
    def compress(self, result: Any, *, level: Literal["off","normal","aggressive"]) -> tuple[Any, dict]:
        """Devuelve (resultado_comprimido, métricas)."""

COMPRESSORS: dict[str, ResultCompressor] = {}  # keyed por tool_name o por tipo de payload

def compressor_for(*names: str):
    def deco(cls):
        for n in names:
            COMPRESSORS[n] = cls()
        return cls
    return deco
```

### Verified Codebase References

#### Classes & Signatures

```python
# From parrot/tools/abstract.py:TBD
class ToolResult(BaseModel):
    success: bool = Field(default=True)
    status: str = Field(default="success")
    result: Any
    error: Optional[str] = Field(default=None)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str
    files: Optional[list] = Field(default_factory=list)
    images: Optional[list] = Field(default_factory=list)
    voice_text: Optional[str] = Field(default=None)
    display_data: Optional[Dict[str, Any]] = Field(default=None)

    @property
    def spoken_content(self) -> str: ...
    @property
    def has_display_content(self) -> bool: ...
```

```python
# From parrot/tools/manager.py:TBD
# Hook API EXISTENTE — observa, NO transforma (devuelve None).
def add_result_hook(self, fn: Callable[[str, Any, Dict[str, Any]], None]) -> None:
    """Register a function(tool_name, result, metadata) -> None run after each tool."""

def _run_result_hooks(self, tool_name: str, result: Any, metadata: Dict[str, Any]) -> None: ...
```

```python
# From parrot/tools/manager.py:TBD — punto de inserción del pipeline.
# Fragmento real de execute_tool():
result = await tool.execute(**exec_kwargs)
if isinstance(result, ToolResult):
    if result.status == 'forbidden':
        return result
    if result.status == "error":
        raise ValueError(result.error)     # ← descarta result.result; bloquea el tee
    out = result.result
    meta = getattr(result, "metadata", {}) or {}
else:
    out = result
    meta = {}
self._postprocess_result(tool_name, out, meta)
self._run_result_hooks(tool_name, out, meta)
return out
```

```python
# From parrot/tools/toolkit.py:TBD
# Precedente del contrato transformador que queremos (SÍ devuelve el resultado).
async def _post_execute(self, tool_name: str, result: Any, **kwargs) -> Any:
    """The return value replaces the original result."""
    return result
```

```python
# From parrot/tools/working_memory/tool.py:TBD
class WorkingMemoryToolkit(AbstractToolkit):
    name: str = "working_memory"
    tool_prefix: str = "wm"

    @tool_schema(StoreResultInput)
    async def store_result(
        self, key: str, data: Any, data_type: str = "auto",
        description: str = "", metadata: Optional[dict] = None,
        turn_id: Optional[str] = None,
    ) -> dict: ...          # → {"status": "stored", "summary": entry.compact_summary()}

    @tool_schema(GetResultInput)
    async def get_result(
        self, key: str, max_length: int = 500, include_raw: bool = False,
    ) -> dict: ...

    @tool_schema(DropStoredInput)
    async def drop_stored(self, key: str) -> dict: ...
```

```python
# From parrot/tools/working_memory/models.py:TBD
class EntryType(str, Enum):
    DATAFRAME = "dataframe"
    TEXT      = "text"
    JSON      = "json"
    MESSAGE   = "message"
    BINARY    = "binary"
    OBJECT    = "object"
```

```python
# From parrot/tools/working_memory/internals.py:TBD
@dataclass
class GenericEntry:
    key: str
    data: Any
    entry_type: EntryType
    created_at: float
    description: str = ""
    turn_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def compact_summary(self, max_length: int = 500) -> dict: ...

def _detect_entry_type(data: Any) -> EntryType: ...
```

```python
# From parrot/tools/databasequery/base.py:TBD
# OBJETIVO PRINCIPAL del codec columnar: rows es list[dict], claves repetidas por fila.
class QueryResult(BaseModel):
    driver: str
    rows: list[dict[str, Any]]
    row_count: int
    columns: list[str]
    execution_time_ms: float
```

```python
# From parrot/bots/data.py:TBD
# FORMATO DESTINO del codec columnar — ya existe y el prompt ya lo enseña al LLM.
Scalar = Union[str, int, float, bool, None]

class PandasTable(BaseModel):
    columns: List[str]
    rows: List[List[Scalar]]

    @field_validator('rows')
    @classmethod
    def validate_rows_alignment(cls, v, info): ...
```

```python
# From parrot/clients/google/client.py:TBD
# Truncado actual — posicional, solo en este cliente.
MAX_TOOL_RESULT_CHARS: int = 200_000

def _truncate_large_result(self, data: Any, max_chars: int) -> Any: ...
def _process_tool_result_for_api(self, result) -> dict: ...
def _summarize_tool_result(self, result: Any, max_length: int = 1200) -> str: ...
```

```python
# From parrot/core/events/lifecycle/events.py:TBD
# Telemetría ya existente — base del reporte de ahorro. Se EXTIENDE (no se sustituye).
AfterToolCallEvent(
    trace_context=..., tool_name=..., duration_ms=...,
    result_status=..., result_size_bytes=...,
    source_type="tool", source_name=...,
)
```

```python
# From parrot/tools/pythonrepl.py:TBD
# Ejecución IN-PROCESS — confirma que rtk NO aplica aquí (no hay subproceso).
# También es el precedente de offload a executor que imita el pipeline.
async def _execute(self, code: str, debug: bool = False, **kwargs) -> Dict[str, Any]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, self._execute_code, code, debug)

# _execute_code() usa: redirect_stdout(io_buffer) + exec() sobre self.locals/self.globals
# Devuelve: output (stdout capturado) + context_report (vars nuevas creadas)
```

```python
# From parrot/clients/claude_agent.py:TBD
# OBJETIVO CORRECTO de rtk: envuelve el CLI `claude` como SUBPROCESO con capacidad bash.
class ClaudeAgentClient(AbstractClient):
    client_type: str = "claude_agent"
    _default_model: str = "claude-sonnet-4-6"
    # "wraps the bundled `claude` CLI as a subprocess ... file-aware, bash-capable"
```

#### Verified Imports

```python
# Confirmados leyendo el codebase (verificar rutas exactas en el repo):
from parrot.tools import AbstractTool, ToolResult, AbstractToolkit, ToolkitTool
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.decorators import tool_schema
from parrot.tools.working_memory import (
    WorkingMemoryToolkit, EntryType, GenericEntry,
)
from parrot.tools.working_memory.internals import (
    WorkingMemoryCatalog, CatalogEntry, _detect_entry_type,
)
from parrot.memory import AnswerMemory
from parrot._imports import lazy_import        # patrón para la extensión Rust opcional
from datamodel.parsers.json import json_decoder, json_encoder, JSONContent
from parrot.core.events.lifecycle.events import (
    BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent,
)
```

#### Key Attributes & Constants

- `ToolResult.status` → `str` — valores observados: `"success"`, `"error"`, `"forbidden"`, `"pending"`, `"authorization_required"`
- `ToolResult.metadata` → `Dict[str, Any]` — destino de las métricas de compresión
- `WorkingMemoryToolkit.tool_prefix` → `"wm"` — los tools quedan como `wm_store_result`, `wm_get_result`
- `AbstractTool.return_direct` → `bool` — **revisar**: si es `True` el resultado puede saltarse el pipeline
- `ToolManager.auto_share_dataframes` / `auto_push_to_pandas` → `bool` — interacción a verificar: `_postprocess_result()` ya extrae DataFrames de resultados; el orden respecto a la compresión importa
- `google/client.py::MAX_TOOL_RESULT_CHARS` → `200_000`

### Does NOT Exist (Anti-Hallucination)

- ~~`rtk` como crate librería / `rtk::filter()`~~ — RTK es crate **binario**; enrutado vía enum `Commands` de Clap en `src/main.rs`. No hay API pública enlazable desde PyO3
- ~~`ToolManager.add_result_hook` con retorno transformador~~ — la firma es `Callable[[str, Any, Dict[str, Any]], None]`. Los hooks **observan**, no transforman. Hace falta una cadena nueva y separada
- ~~`ToolResult.compress()` / `ToolResult.compressed`~~ — no existe ningún método ni campo de compresión en `ToolResult` hoy
- ~~`AbstractTool.compress_result()`~~ — no existe (era la Opción C, descartada)
- ~~`MAX_TOOL_RESULT_CHARS` fuera de `clients/google/client.py`~~ — Claude, Groq y Grok **no** tienen equivalente
- ~~`FilterLevel` en el codebase~~ — el nombre viene de RTK, no existe en ai-parrot
- ~~`parrot.tools.compression`~~ — paquete a crear, no existe
- ~~Un tokenizer en el pipeline~~ — no hay ninguno disponible. Las estimaciones de tokens serán `bytes/4`, igual que RTK. **Los porcentajes son fiables; los valores absolutos son aproximados** y hay que documentarlo así
- ~~`AbstractToolkit._post_execute()` invocado para `AbstractTool` plano~~ — es un hook de toolkit; los tools no-toolkit no pasan por él
- ~~Subproceso o shell en `PythonREPLTool` / `PythonPandasTool`~~ — ejecutan **in-process** con `exec()` y `redirect_stdout` a `StringIO`. **RTK no aplica ahí**: no hay comando que interceptar
- ~~Un "Sandbox" verificado en el codebase~~ — no localizado en lo indexado. Confirmar existencia y ruta antes de asumir que lanza procesos
- ~~`py.allow_threads()` disponible desde Python puro~~ — la liberación del GIL solo es posible desde la extensión Rust. Sin extensión compilada, `run_in_executor` no compra paralelismo real

---

## Parallelism Assessment

- **Internal parallelism**: Alta, tras una fase de bloqueo. `tool-result-compression` debe completarse primero porque congela el `ResultCompressor` Protocol y el `CompressionOutcome`. Una vez fusionado ese contrato, `compression-tee` y `columnar-codec` avanzan en worktrees independientes: tocan ficheros disjuntos (`compression/tee.py` vs `compression/codecs/columnar.py`) y solo comparten la definición del Protocol, que ya es inmutable en ese punto. Dentro de `columnar-codec`, el camino Python y el binding Rust también se separan — el Python es la referencia y el Rust debe pasar exactamente los mismos tests.
- **Cross-feature independence**: El fichero de riesgo es `parrot/tools/manager.py`, que es central y probablemente tenga otras specs en vuelo tocándolo. `execute_tool()` en concreto acumula lógica de permisos, credenciales y autorización. Antes de arrancar hay que revisar specs activas que lo modifiquen. Riesgo secundario menor: `parrot/tools/abstract.py` (solo se añaden claves a `metadata`, sin cambio de firma) y `parrot/core/events/lifecycle/events.py`.
- **Recommended isolation**: mixed — un worktree secuencial para `tool-result-compression`, y luego dos worktrees paralelos para `compression-tee` y `columnar-codec`. `rtk-subprocess-filter` es totalmente independiente (no toca Python del pipeline) y puede ir en cualquier momento por cualquiera.
- **Nota sobre el orden dentro de `columnar-codec`**: el camino Python se implementa **primero** y es la especificación ejecutable; el binding Rust debe pasar exactamente la misma suite. Esto permite además que el presupuesto de latencia se mida contra una referencia real en vez de contra una estimación.
- **Rationale**: El coste de paralelizar prematuramente es alto: si las tres capabilities arrancan a la vez, las tres redefinen el Protocol y el merge es doloroso. El coste de serializar la primera fase es bajo — es la capability más pequeña de las tres (registro + enum + Protocol + una etapa en el pipeline). Serializar lo barato para paralelizar lo caro.

---

## Open Questions

### Resueltas

- [x] ¿Qué mecanismo usa el soporte Rust ya integrado? — *Owner: <name>*: **PyO3 con maturin, ya integrado en ai-parrot.** El codec se construye como módulo de ese mismo setup. Sin coste de arranque de toolchain.
- [x] ¿Extendemos `AfterToolCallEvent` o emitimos evento nuevo? — *Owner: <name>*: **Extender `AfterToolCallEvent`.** Sin evento nuevo. Implica que `result_size_bytes` pasa a ser el tamaño post-compresión y el original va en campo aparte — anotar en changelog.
- [x] ¿Se recomprime al reproducir historial? — *Owner: <name>*: **Solo ejecución fresca.** El payload comprimido es el que se persiste en memoria conversacional; se comprime una vez y viaja comprimido. Marcador `_compressed` en metadata como guarda de idempotencia.
- [x] ¿Cuál es el `min_rows` real del codec columnar? — *Owner: <name>*: **20.** Fijado como default, configurable por herramienta en el TOML.
- [x] ¿Reordenar la rama `status == "error"` de `execute_tool()`? — *Owner: <name>*: **Sí.** El payload se captura para el tee antes del `raise`; la excepción se sigue lanzando igual, sin cambio observable para los llamantes.
- [x] ¿`clients/live.py` es deuda o entra en alcance? — *Owner: <name>*: **Entra en alcance.** Brecha inadvertida hasta ahora. Cuidado con `voice_text` y `display_data`, que en esa ruta tienen tratamiento especial y no deben comprimirse.
- [x] ¿`return_direct = True` salta el pipeline? — *Owner: <name>*: **Sí, lo salta por completo**, tee incluido. Comprimir alteraría un resultado que la herramienta emite deliberadamente directo al usuario.
- [x] ¿Usar el binario `rtk` para tools que lanzan subprocesos? — *Owner: <name>*: **Sí, como capability de seguimiento** — pero **el objetivo correcto no es `PythonREPLTool`**. Ver nota de corrección abajo.

### Abiertas

- [ ] Interacción con `_postprocess_result()` y `auto_share_dataframes`: ¿la compresión va antes o después de la extracción de DataFrames? Si va antes, la extracción puede no encontrar el DataFrame que esperaba. — *Owner: <name>*
- [ ] Calibrar el umbral inline/executor (propuesta inicial: 256 KB o 5.000 filas) y el ratio unión/intersección de claves que dispara el passthrough por heterogeneidad. — *Owner: <name>*
- [ ] ¿Qué ventana y qué política de rearme para el circuit breaker de latencia? — *Owner: <name>*
- [ ] En `clients/live.py`, ¿el pipeline se aplica antes o después de la extracción de `voice_text` / `display_data`? — *Owner: <name>*

### Nota de corrección: dónde aplica realmente `rtk`

Se verificó el codebase y la premisa inicial era incorrecta en dos de los tres objetivos propuestos:

- **`PythonREPLTool` — NO aplica.** `_execute_code()` ejecuta **in-process** vía `exec()` con `redirect_stdout` hacia un `StringIO`. No hay subproceso ni shell que interceptar. RTK filtra stdout de comandos que él mismo lanza; aquí no hay comando.
- **`PythonPandasTool` — NO aplica.** Hereda de `PythonREPLTool`; mismo motor de ejecución, misma conclusión.
- **Sandbox — sin verificar.** No se localizó un componente de sandbox en lo indexado. Si existe y lanza procesos (docker exec, subprocess), sí sería objetivo válido. Pendiente de confirmar la ruta.

**El objetivo correcto es `ClaudeAgentClient`** (`parrot/clients/claude_agent.py`), que envuelve el CLI `claude` como subproceso para delegar trabajo "file-aware, bash-capable" a un sub-agente de Claude Code. Ese sub-agente ejecuta comandos bash reales, que es exactamente el caso de uso para el que RTK está diseñado: un `rtk init` en el entorno del sub-agente comprime su salida sin tocar una línea de ai-parrot.

Para lo que sí genera ruido dentro de `PythonREPLTool`, el camino no es RTK sino un codec propio: su `_execute_code()` ya devuelve `output` más un `context_report` de variables creadas, y ese stdout capturado (trazas largas, prints en bucle, warnings repetidos de pandas) es un objetivo natural para un codec `repl_stdout` con deduplicación y recorte de traceback — dentro del mismo pipeline, sin dependencia externa.
