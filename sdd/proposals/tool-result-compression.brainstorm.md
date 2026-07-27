---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: Tool Result Compression Pipeline

**Date**: 2026-07-27
**Author**: Jesus Lara
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
- `parrot/core/events/lifecycle/events/tool.py` — `AfterToolCallEvent.result_size_bytes`

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

*Nota: la brecha de `clients/live.py` — que invoca `tool._execute()` saltándose `ToolManager` — se detectó durante este brainstorm y entra en alcance en vez de quedar como deuda. Es exactamente el tipo de ruta que, dejada fuera, invalida la garantía de punto único que justifica esta opción. La verificación del codebase reveló además que la brecha es más grave de lo estimado: ver la fila de `clients/live.py` en **Impact & Integration**.*

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

*Confirmado: el codebase ya integra PyO3 con maturin — dos crates existentes: `yaml-rs` dentro del propio paquete ai-parrot y `packages/navrules`. Ver Code Context §17. No hay coste de arranque de toolchain.*

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
| `parrot/core/events/lifecycle/events/tool.py` | extends | Campos de compresión en `AfterToolCallEvent` (dataclass frozen; los campos nuevos necesitan default) |
| `parrot/tools/discovery.py` | extends | Descubrimiento de TOML de compresores junto al de `TOOL_REGISTRY` |
| `parrot/tools/databasequery/` | depends on | Primer consumidor real del codec columnar |
| `parrot/clients/live.py` | modifies | **En alcance.** `execute_tool()` (live.py:367) invoca el **privado** `tool._execute(**tool_args)` en live.py:401, saltándose no solo `ToolManager` sino también `AbstractTool.execute()` — es decir, sin permisos, sin credential broker, sin redacción y sin `ToolResult` estandarizado. Debe redirigirse al pipeline. Ojo: es la ruta de voz, donde `voice_text` y `display_data` del `ToolResult` tienen tratamiento especial (live.py:416-437) y **no** deben comprimirse |
| Extensión Rust (`parrot_codec`) | new / extends | Nuevo módulo o extensión de un crate existente (`yaml-rs` en el paquete, `navrules` como precedente separado). Ver *Open Questions* |

**Breaking changes:** ninguno previsto. `MINIMAL` por defecto solo aplica transformaciones sin pérdida; el kill switch por variable de entorno restaura el comportamiento exacto.

**Nueva dependencia:** ninguna obligatoria. `tomllib` es stdlib; la extensión Rust es opcional.

---

## Code Context

> ✅ **Verificado el 2026-07-27 contra el codebase real.** Todas las firmas y
> números de línea de abajo se confirmaron leyendo el código fuente.
>
> **Mapeo de rutas**: en todo este documento `parrot/...` significa
> `packages/ai-parrot/src/parrot/...` — el paquete NO vive en la raíz del repo.
> Existe además una copia stale de build en
> `packages/ai-parrot/build/lib.linux-x86_64-cpython-311/parrot/` que debe
> ignorarse: cualquier grep debe restringirse a `packages/ai-parrot/src/`.

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
# From parrot/tools/abstract.py:91
class ToolResult(BaseModel):
    """Standardized tool result format."""
    success: bool = Field(default=True, ...)
    status: str = Field(default="success", ...)
    result: Any = Field(description="The actual result of the tool operation")
    error: Optional[str] = Field(default=None, ...)
    metadata: Dict[str, Any] = Field(default_factory=dict, ...)
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    files: Optional[list] = Field(default_factory=list, ...)
    images: Optional[list] = Field(default_factory=list, ...)
    voice_text: Optional[str] = Field(default=None, ...)          # voz
    display_data: Optional[Dict[str, Any]] = Field(default=None)  # visual

    @property
    def spoken_content(self) -> str: ...       # línea 113
    @property
    def has_display_content(self) -> bool: ... # línea 120
```

```python
# From parrot/tools/abstract.py:126
class AbstractTool(EventEmitterMixin, ABC):
    return_direct: bool = False                       # línea 144

    async def execute(self, *args, **kwargs) -> ToolResult: ...  # línea 527
    # execute() gestiona _permission_context/_resolver/_broker y puede
    # devolver status='forbidden' antes de llegar a _execute (L559-569).

    async def _execute(self, **kwargs) -> Any: ...    # abstract, línea 293
```

```python
# From parrot/tools/manager.py:229  (class ToolManager)
# Hook API EXISTENTE — observa, NO transforma (devuelve None).
def add_result_hook(self, fn: Callable[[str, Any, Dict[str, Any]], None]) -> None: ...  # línea 1777
def _run_result_hooks(self, tool_name: str, result: Any, metadata: Dict[str, Any]) -> None: ...  # línea 1781
# _result_hooks se inicializa en línea 266; los hooks tragan excepciones con warning.
```

```python
# From parrot/tools/manager.py:1379 — execute_tool(); punto de inserción del pipeline.
async def execute_tool(
    self,
    tool_name: str,
    parameters: Dict[str, Any],
    permission_context: Optional["PermissionContext"] = None,
) -> Any: ...

# Fragmento real, líneas 1490-1506:
result = await tool.execute(**exec_kwargs)
if isinstance(result, ToolResult):
    if result.status == 'forbidden':
        return result                          # forbidden vuelve intacto
    if result.status == "error":
        raise ValueError(result.error)         # ← descarta result.result; bloquea el tee
    out = result.result
    meta = getattr(result, "metadata", {}) or {}
else:
    out = result
    meta = {}
self._postprocess_result(tool_name, out, meta)     # def en línea 1663
self._run_result_hooks(tool_name, out, meta)
return out                                          # ← devuelve el payload DESEMPAQUETADO
```

```python
# From parrot/tools/manager.py:1697 — clone()
def clone(self, *, include_search_tool: bool = False) -> "ToolManager": ...
# Comparte por referencia: instancias de tools (_tools), _resolver, _broker, logger.
# Copia: _categories, auto_share_dataframes (L272), auto_push_to_pandas (L273), pandas_tool_name.
# NO clona (docstring L1707-1712): _shared, _registered_agents, _result_hooks,
# _wired_toolkits, estado MCP. ← lista a extender con el estado de métricas de compresión.
```

```python
# From parrot/tools/toolkit.py:390
# Precedente del contrato transformador que queremos (SÍ devuelve el resultado).
# Nota: `result` es positional-only (marcador `/`).
async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any:
    """... The return value replaces the original result."""
    return result

# ToolkitTool en toolkit.py:32; AbstractToolkit en toolkit.py:207.
```

```python
# From parrot/tools/working_memory/tool.py:44
class WorkingMemoryToolkit(AbstractToolkit):
    name: str = "working_memory"          # línea 77
    tool_prefix: str = "wm"               # línea 78
    exclude_tools: tuple[str, ...] = ("store",)   # línea 86

    @tool_schema(StoreResultInput)        # línea 204
    async def store_result(
        self, key: str, data: Any, data_type: str = "auto",
        description: str = "", metadata: Optional[dict] = None,
        turn_id: Optional[str] = None,
    ) -> dict: ...          # → {"status": "stored", "summary": entry.compact_summary()}

    @tool_schema(DropStoredInput)         # línea 238
    async def drop_stored(self, key: str) -> dict: ...

    @tool_schema(GetResultInput)          # línea 255
    async def get_result(
        self, key: str, max_length: int = 500, include_raw: bool = False,
    ) -> dict: ...
```

```python
# From parrot/tools/working_memory/models.py:15
class EntryType(str, Enum):
    DATAFRAME = "dataframe"
    TEXT      = "text"      # plain str
    JSON      = "json"      # dict or list
    MESSAGE   = "message"   # duck-typed: has .content and .role
    BINARY    = "binary"    # bytes
    OBJECT    = "object"    # fallback
```

```python
# From parrot/tools/working_memory/internals.py:70
@dataclass
class GenericEntry:
    key: str
    data: Any
    entry_type: EntryType
    created_at: float = field(default_factory=time.time)
    description: str = ""
    turn_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def compact_summary(self, max_length: int = 500) -> dict: ...  # línea 96

def _detect_entry_type(data: Any) -> EntryType: ...  # línea 34
# Orden de detección: str→TEXT, bytes→BINARY, dict|list→JSON,
# .content+.role→MESSAGE, DataFrame→DATAFRAME, resto→OBJECT.

# También en internals.py: CatalogEntry (línea 175, compact_summary con OTRA firma:
# max_rows/max_cols), WorkingMemoryCatalog (línea 458; put_generic en 499 —
# sobrescribe silenciosamente, relevante para la colisión de claves del tee).
```

```python
# From parrot/tools/databasequery/base.py:148
# OBJETIVO PRINCIPAL del codec columnar: rows es list[dict], claves repetidas por fila.
class QueryResult(BaseModel):
    driver: str
    rows: list[dict[str, Any]]      # línea 160
    row_count: int
    columns: list[str]
    execution_time_ms: float
```

```python
# From parrot/bots/data.py:70
# FORMATO DESTINO del codec columnar — ya existe y el prompt ya lo enseña al LLM.
Scalar = Union[str, int, float, bool, None]   # línea 62

class PandasTable(BaseModel):
    columns: List[str]              # línea 72
    rows: List[List[Scalar]]        # línea 75

    @field_validator('rows')        # línea 85
    @classmethod
    def validate_rows_alignment(cls, v, info): ...
    # Ojo: NO lanza en desalineación — rellena filas cortas con None y trunca largas.
```

```python
# From parrot/clients/google/client.py
# Truncado actual — posicional, solo en este cliente.
# ATRIBUTO DE CLASE del cliente, no constante de módulo:
MAX_TOOL_RESULT_CHARS: int = 200_000                                    # línea 1197

def _truncate_large_result(self, data: Any, max_chars: int) -> Any: ... # línea 1199
def _process_tool_result_for_api(self, result) -> dict: ...             # línea 1358
def _summarize_tool_result(self, result: Any, max_length: int = 1200) -> str: ...  # línea 1444
```

```python
# From parrot/core/events/lifecycle/events/tool.py
# OJO: `events` es un PAQUETE (core/events/lifecycle/events/), no events.py.
# Los eventos de tool viven en events/tool.py y se re-exportan en events/__init__.py.
# Son @dataclass(frozen=True) sobre navigator_eventbus.lifecycle.base.LifecycleEvent
# → los campos nuevos de compresión necesitarán default.

class BeforeToolCallEvent(...): ...   # línea 12

class AfterToolCallEvent(...):        # línea 30
    tool_name: str = ""               # línea 42
    duration_ms: float = 0.0
    result_status: str = ""           # "success" | "partial"
    result_size_bytes: int = 0        # línea 45 ← pasa a significar tamaño POST-compresión

class ToolCallFailedEvent(...): ...   # línea 49  (tool_name, duration_ms, error_type, error_message)
```

```python
# From parrot/tools/pythonrepl.py:950
# Ejecución IN-PROCESS — confirma que rtk NO aplica aquí (no hay subproceso).
# También es el precedente de offload a executor que imita el pipeline.
async def _execute(self, code: str, debug: bool = False, **kwargs) -> Any:
    ...
    loop = asyncio.get_event_loop()                                      # línea 969
    output = await loop.run_in_executor(None, self._execute_code, code, debug)

# _execute_code (línea 701) tiene un tercer parámetro con default:
def _execute_code(self, query: str, debug: bool = False, enforce_security: bool = True) -> str: ...
# Usa redirect_stdout(io_buffer) (línea 768) + exec() (líneas 773, 825).
```

```python
# From parrot/clients/claude_agent.py:231
# OBJETIVO CORRECTO de rtk: envuelve el CLI `claude` como SUBPROCESO con capacidad bash.
class ClaudeAgentClient(AbstractClient):
    client_type: str = "claude_agent"                     # línea 247
    _default_model: str = "claude-sonnet-4-6"             # línea 250
    _lightweight_model: str = "claude-haiku-4-5-20251001" # línea 251
```

```python
# From parrot/clients/live.py:367 — la brecha, verificada y PEOR de lo estimado.
# execute_tool() del adaptador live devuelve (FunctionResponse, display_data):
async def execute_tool(...): ...                          # línea 367

# Línea 401 — llama al PRIVADO _execute, saltándose AbstractTool.execute() entero:
if hasattr(tool, '_execute'):
    # AbstractTool
    result = await tool._execute(**tool_args)
# Consecuencia: sin permisos (_permission_context/_resolver), sin credential
# broker, sin redacción, sin lifecycle events y sin ToolResult estandarizado.
# El isinstance(result, ToolResult) de la línea 419 rara vez es True porque
# _execute devuelve Any crudo.

# voice_text / display_data — tratamiento especial, líneas 416-437:
if isinstance(result, ToolResult):
    if result.status == "success":
        if result.display_data:
            display_data = result.display_data
        if result.voice_text:
            response_data = {"output": result.voice_text}
        elif isinstance(result.result, dict):
            response_data = result.result
# display_data se propaga a metadata del mensaje en líneas 924/956-957 y 1227/1252-1255.
```

```python
# From parrot/_imports.py:84 — patrón para la extensión Rust opcional.
def lazy_import(
    module_path: str,
    package_name: str | None = None,
    extra: str | None = None,
) -> ModuleType: ...
```

```python
# From parrot/tools/discovery.py — mecánica multi-fuente a replicar para los TOML.
DEFAULT_SOURCES = [...]                                              # línea 22
def discover_from_registry(sources=None) -> Dict[str, str]: ...      # línea 31
def discover_from_walk(sources=None, filter_fn=None) -> Dict[str, Type]: ...  # línea 64
def discover_all(sources=None) -> Dict[str, Union[str, Type]]: ...   # línea 111
def resolve_class(dotted_path: str) -> Type: ...                     # línea 139
# TOOL_REGISTRY es una CONVENCIÓN (dict declarado en el __init__.py de paquetes
# externos), no un símbolo definido en discovery.py/registry.py.
# registry.py: ToolkitRegistry (línea 42), get_supported_toolkits (línea 78).
```

#### Verified Imports

```python
# Confirmados contra los __init__.py reales (2026-07-27):
from parrot.tools import AbstractTool, ToolResult, AbstractToolkit, ToolkitTool
    # re-export en tools/__init__.py:142-143; __all__ en 216-219
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.decorators import tool_schema        # decorators.py:37
from parrot.tools.working_memory import (
    WorkingMemoryToolkit, EntryType, GenericEntry,     # todos en __all__
)
from parrot.tools.working_memory.internals import (
    WorkingMemoryCatalog, CatalogEntry, _detect_entry_type,   # sin __all__, import directo OK
)
from parrot.memory import AnswerMemory                 # memory/__init__.py:5
from parrot._imports import lazy_import                # _imports.py:84
from datamodel.parsers.json import json_decoder, json_encoder, JSONContent
    # ya usado en tools/abstract.py:13
from parrot.core.events.lifecycle.events import (
    BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent,
    # `events` es paquete; símbolos en events/tool.py, re-export en events/__init__.py.
    # tools/abstract.py:22 ya usa exactamente este import.
)
```

#### Key Attributes & Constants

- `ToolResult.status` → `str` — literales verificados en `parrot/tools/`: `"success"`, `"error"`, `"forbidden"`, `"pending"`, `"authorization_required"`, `"not_found"` (manager.py:1403, tool desconocido), `"done_with_errors"`; además `"cancelled"` / `"timeout"` alcanzables vía `status=confirm_decision.status` (manager.py:1460)
- `ToolResult.metadata` → `Dict[str, Any]` — destino de las métricas de compresión
- `WorkingMemoryToolkit.tool_prefix` → `"wm"` — los tools quedan como `wm_store_result`, `wm_get_result`
- `AbstractTool.return_direct` → `bool = False` (abstract.py:144) — si es `True` el pipeline se salta por completo
- `ToolManager.auto_share_dataframes` → `bool = True` (manager.py:272) / `auto_push_to_pandas` → `bool = True` (manager.py:273) — interacción a resolver: `_postprocess_result()` (manager.py:1663) extrae DataFrames de resultados; el orden respecto a la compresión importa
- `GoogleGenAIClient.MAX_TOOL_RESULT_CHARS` → `200_000` (google/client.py:1197, **atributo de clase**, no constante de módulo)

#### Rust / PyO3 (verificado — C8 tiene precedente real)

- **`parrot/yaml-rs/`** — crate PyO3 dentro del propio paquete ai-parrot: `pyo3 = "0.29"` con `extension-module`, `crate-type = ["cdylib"]`, serde/serde_json/serde_yaml. Config maturin en `packages/ai-parrot/pyproject.toml:617-621` (`module-name = "parrot.yaml_rs._yaml_rs"`). ⚠️ Discrepancia a vigilar si el codec se cuelga de este setup: `python-source = "src/parrot/yaml_rs"` (guion bajo) vs directorio real `src/parrot/yaml-rs` (guion).
- **`packages/navrules/`** — segundo crate maturin/PyO3 (`pyo3 0.24`, `abi3-py311`), precedente de paquete satélite con extensión nativa.
- `maturin==1.9.6` pineado como dependencia dev en el `pyproject.toml` raíz (línea 69).

### Does NOT Exist (Anti-Hallucination)

*Verificado por búsqueda exhaustiva el 2026-07-27 (restringida a `packages/ai-parrot/src/`):*

- ~~`rtk` como crate librería / `rtk::filter()`~~ — RTK es crate **binario**; enrutado vía enum `Commands` de Clap en `src/main.rs`. No hay API pública enlazable desde PyO3
- ~~`ToolManager.add_result_hook` con retorno transformador~~ — la firma es `Callable[[str, Any, Dict[str, Any]], None]`. Los hooks **observan**, no transforman. Hace falta una cadena nueva y separada
- ~~`ToolResult.compress()` / `ToolResult.compressed`~~ — cero apariciones; no existe ningún método ni campo de compresión en `ToolResult` hoy
- ~~`AbstractTool.compress_result()`~~ — cero apariciones (era la Opción C, descartada)
- ~~`MAX_TOOL_RESULT_CHARS` fuera de `clients/google/client.py`~~ — verificado: solo aparece en ese fichero. `claude.py`, `groq.py` y `grok.py` **no** tienen truncado equivalente de tool results (los únicos hits son slices `[:100]` de logging y un warning de max-tokens, nada de tool results)
- ~~`FilterLevel` en el codebase~~ — cero apariciones; el nombre viene de RTK, no existe en ai-parrot
- ~~`parrot.tools.compression`~~ — ni el paquete ni ningún import; a crear desde cero
- ~~Un tokenizer en el pipeline~~ — no hay ninguno disponible. Las estimaciones de tokens serán `bytes/4`, igual que RTK. **Los porcentajes son fiables; los valores absolutos son aproximados** y hay que documentarlo así
- ~~`AbstractToolkit._post_execute()` invocado para `AbstractTool` plano~~ — es un hook de toolkit; los tools no-toolkit no pasan por él
- ~~Subproceso o shell en `PythonREPLTool` / `PythonPandasTool`~~ — ejecutan **in-process** con `exec()` (pythonrepl.py:773, 825) y `redirect_stdout` a `StringIO` (línea 768). **RTK no aplica ahí**: no hay comando que interceptar
- ~~Un "Sandbox" verificado en el codebase~~ — no localizado en lo indexado. Confirmar existencia y ruta antes de asumir que lanza procesos
- ~~`py.allow_threads()` disponible desde Python puro~~ — la liberación del GIL solo es posible desde la extensión Rust. Sin extensión compilada, `run_in_executor` no compra paralelismo real
- ~~`parrot/core/events/lifecycle/events.py` como fichero~~ — `events` es un **paquete**; los eventos de tool viven en `events/tool.py`. El import documentado funciona igual vía re-export
- ~~`parrot/` en la raíz del repo~~ — el paquete vive en `packages/ai-parrot/src/parrot/`. Cualquier ruta de este documento se resuelve contra ese prefijo

---

## Parallelism Assessment

- **Internal parallelism**: Alta, tras una fase de bloqueo. `tool-result-compression` debe completarse primero porque congela el `ResultCompressor` Protocol y el `CompressionOutcome`. Una vez fusionado ese contrato, `compression-tee` y `columnar-codec` avanzan en worktrees independientes: tocan ficheros disjuntos (`compression/tee.py` vs `compression/codecs/columnar.py`) y solo comparten la definición del Protocol, que ya es inmutable en ese punto. Dentro de `columnar-codec`, el camino Python y el binding Rust también se separan — el Python es la referencia y el Rust debe pasar exactamente los mismos tests.
- **Cross-feature independence**: El fichero de riesgo es `parrot/tools/manager.py`, que es central y probablemente tenga otras specs en vuelo tocándolo. `execute_tool()` en concreto acumula lógica de permisos, credenciales y autorización. Antes de arrancar hay que revisar specs activas que lo modifiquen. Riesgo secundario menor: `parrot/tools/abstract.py` (solo se añaden claves a `metadata`, sin cambio de firma) y `parrot/core/events/lifecycle/events/tool.py`.
- **Recommended isolation**: mixed — un worktree secuencial para `tool-result-compression`, y luego dos worktrees paralelos para `compression-tee` y `columnar-codec`. `rtk-subprocess-filter` es totalmente independiente (no toca Python del pipeline) y puede ir en cualquier momento por cualquiera.
- **Nota sobre el orden dentro de `columnar-codec`**: el camino Python se implementa **primero** y es la especificación ejecutable; el binding Rust debe pasar exactamente la misma suite. Esto permite además que el presupuesto de latencia se mida contra una referencia real en vez de contra una estimación.
- **Rationale**: El coste de paralelizar prematuramente es alto: si las tres capabilities arrancan a la vez, las tres redefinen el Protocol y el merge es doloroso. El coste de serializar la primera fase es bajo — es la capability más pequeña de las tres (registro + enum + Protocol + una etapa en el pipeline). Serializar lo barato para paralelizar lo caro.

---

## Open Questions

### Resueltas

- [x] ¿Qué mecanismo usa el soporte Rust ya integrado? — *Owner: Jesus Lara*: **PyO3 con maturin, ya integrado en ai-parrot** — verificado: crate `yaml-rs` dentro del propio paquete (pyo3 0.29 + config maturin en pyproject) y crate `navrules` como paquete satélite (pyo3 0.24, abi3-py311). El codec se construye como módulo de ese mismo setup. Sin coste de arranque de toolchain.
- [x] ¿Extendemos `AfterToolCallEvent` o emitimos evento nuevo? — *Owner: Jesus Lara*: **Extender `AfterToolCallEvent`.** Sin evento nuevo. Implica que `result_size_bytes` pasa a ser el tamaño post-compresión y el original va en campo aparte — anotar en changelog. Nota de implementación: es `@dataclass(frozen=True)`, los campos nuevos necesitan default.
- [x] ¿Se recomprime al reproducir historial? — *Owner: Jesus Lara*: **Solo ejecución fresca.** El payload comprimido es el que se persiste en memoria conversacional; se comprime una vez y viaja comprimido. Marcador `_compressed` en metadata como guarda de idempotencia.
- [x] ¿Cuál es el `min_rows` real del codec columnar? — *Owner: Jesus Lara*: **20.** Fijado como default, configurable por herramienta en el TOML.
- [x] ¿Reordenar la rama `status == "error"` de `execute_tool()`? — *Owner: Jesus Lara*: **Sí.** El payload se captura para el tee antes del `raise`; la excepción se sigue lanzando igual, sin cambio observable para los llamantes.
- [x] ¿`clients/live.py` es deuda o entra en alcance? — *Owner: Jesus Lara*: **Entra en alcance.** Brecha inadvertida hasta ahora — y verificada como más grave: live.py:401 llama al privado `_execute()`, saltándose también permisos, credenciales y redacción. Cuidado con `voice_text` y `display_data`, que en esa ruta tienen tratamiento especial (live.py:416-437) y no deben comprimirse.
- [x] ¿`return_direct = True` salta el pipeline? — *Owner: Jesus Lara*: **Sí, lo salta por completo**, tee incluido. Comprimir alteraría un resultado que la herramienta emite deliberadamente directo al usuario.
- [x] ¿Usar el binario `rtk` para tools que lanzan subprocesos? — *Owner: Jesus Lara*: **Sí, como capability de seguimiento** — pero **el objetivo correcto no es `PythonREPLTool`**. Ver nota de corrección abajo.

### Abiertas

- [ ] Interacción con `_postprocess_result()` y `auto_share_dataframes`: ¿la compresión va antes o después de la extracción de DataFrames? Si va antes, la extracción puede no encontrar el DataFrame que esperaba. — *Owner: Jesus Lara*
- [ ] Calibrar el umbral inline/executor (propuesta inicial: 256 KB o 5.000 filas) y el ratio unión/intersección de claves que dispara el passthrough por heterogeneidad. — *Owner: Jesus Lara*
- [ ] ¿Qué ventana y qué política de rearme para el circuit breaker de latencia? — *Owner: Jesus Lara*
- [ ] En `clients/live.py`, ¿el pipeline se aplica antes o después de la extracción de `voice_text` / `display_data`? Nota: redirigir esa ruta al pipeline arrastra además la corrección del bypass de `AbstractTool.execute()` (permisos/credenciales/redacción) — decidir si esa corrección va en esta feature o en una propia. — *Owner: Jesus Lara*
- [ ] La extensión Rust del codec: ¿módulo nuevo dentro del setup maturin de ai-parrot (junto a `yaml-rs`) o crate satélite tipo `navrules`? Resolver antes la discrepancia `python-source` guion/guion-bajo del pyproject. — *Owner: Jesus Lara*

### Nota de corrección: dónde aplica realmente `rtk`

Se verificó el codebase y la premisa inicial era incorrecta en dos de los tres objetivos propuestos:

- **`PythonREPLTool` — NO aplica.** `_execute_code()` ejecuta **in-process** vía `exec()` con `redirect_stdout` hacia un `StringIO`. No hay subproceso ni shell que interceptar. RTK filtra stdout de comandos que él mismo lanza; aquí no hay comando.
- **`PythonPandasTool` — NO aplica.** Hereda de `PythonREPLTool`; mismo motor de ejecución, misma conclusión.
- **Sandbox — sin verificar.** No se localizó un componente de sandbox en lo indexado. Si existe y lanza procesos (docker exec, subprocess), sí sería objetivo válido. Pendiente de confirmar la ruta.

**El objetivo correcto es `ClaudeAgentClient`** (`parrot/clients/claude_agent.py:231`), que envuelve el CLI `claude` como subproceso para delegar trabajo "file-aware, bash-capable" a un sub-agente de Claude Code. Ese sub-agente ejecuta comandos bash reales, que es exactamente el caso de uso para el que RTK está diseñado: un `rtk init` en el entorno del sub-agente comprime su salida sin tocar una línea de ai-parrot.

Para lo que sí genera ruido dentro de `PythonREPLTool`, el camino no es RTK sino un codec propio: su `_execute_code()` ya devuelve `output` más un `context_report` de variables creadas, y ese stdout capturado (trazas largas, prints en bucle, warnings repetidos de pandas) es un objetivo natural para un codec `repl_stdout` con deduplicación y recorte de traceback — dentro del mismo pipeline, sin dependencia externa.
