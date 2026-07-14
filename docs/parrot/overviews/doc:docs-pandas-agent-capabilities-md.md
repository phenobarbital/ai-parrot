---
type: Wiki Overview
title: Capacidades de un Agente Analítico AI-Parrot (PandasAgent)
id: doc:docs-pandas-agent-capabilities-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: 1. [Anatomía de un agente analítico](#1-anatomía-de-un-agente-analítico)
relates_to:
- concept: mod:parrot.bots.data
  rel: mentions
---

# Capacidades de un Agente Analítico AI-Parrot (PandasAgent)

> Documento de capacidades para agentes tipo **Porygon** (`agents/porygon.py`) y
> **TROC Finance** (`agents/troc.py`), construidos sobre `PandasAgent` con todo el
> stack analítico de AI-Parrot: DatasetManager, sistema de Skills, memoria
> episódica, Working Memory, WhatIf Toolkit, Infographic Toolkit y Knowledge Base
> local con FAISS.

---

## Índice

1. [Anatomía de un agente analítico](#1-anatomía-de-un-agente-analítico)
2. [DatasetManager: el catálogo de datos](#2-datasetmanager-el-catálogo-de-datos)
   - [El principio "in our end": los datos no salen a la nube](#21-el-principio-in-our-end-los-datos-no-salen-a-la-nube)
   - [Tipos de datasets / fuentes soportadas](#22-tipos-de-datasets--fuentes-soportadas)
   - [Incorporar nuevos datasets en caliente](#23-incorporar-nuevos-datasets-en-caliente)
   - [Columnas calculadas y datasets compuestos](#24-columnas-calculadas-y-datasets-compuestos)
3. [Sistema de Skills](#3-sistema-de-skills)
4. [Memoria episódica](#4-memoria-episódica)
5. [Infographic Toolkit](#5-infographic-toolkit)
6. [Working Memory Toolkit](#6-working-memory-toolkit)
7. [WhatIf Toolkit](#7-whatif-toolkit)
8. [Knowledge Base local con FAISS](#8-knowledge-base-local-con-faiss)
9. [Resumen general de capacidades y potencial](#9-resumen-general-de-capacidades-y-potencial)

---

## 1. Anatomía de un agente analítico

Tanto Porygon como TROC Finance se declaran con la misma composición de mixins
sobre `PandasAgent`:

```python
@register_agent(name="porygon", at_startup=True)
class Porygon(SkillRegistryMixin, EpisodicMemoryMixin, PandasAgent):
    agent_id: str = "porygon"
    model = 'gemini-3.1-pro-preview'
    enable_episodic_memory: bool = True
    episodic_backend: str = "faiss"
    enable_skill_registry: bool = True
    ...
```

Esta jerarquía aporta cuatro grandes bloques de capacidad:

| Bloque | De dónde viene | Qué aporta |
|--------|----------------|------------|
| **Ejecución analítica** | `PandasAgent` (`parrot.bots.data`) | REPL de pandas (`python_repl_pandas`), forecasting con Prophet, gestión de DataFrames |
| **Catálogo de datos** | `DatasetManager` (`_dataset_manager`) | Registro, materialización perezosa y manipulación local de fuentes de datos |
| **Aprendizaje y procedimientos** | `SkillRegistryMixin` + `EpisodicMemoryMixin` | Skills reutilizables + memoria de experiencias pasadas |
| **Toolkits especializados** | `WorkingMemoryToolkit`, `WhatIfToolkit`, `InfographicToolkit`, `DatabaseToolkit` | Memoria de trabajo, simulación de escenarios, infografías HTML, SQL multi-driver |

El `PandasAgent` es el núcleo: expone un **REPL de pandas** (`PythonPandasTool`)
donde los datasets registrados aparecen como variables Python listas para usar.
Cada DataFrame se inyecta con:

- Su **nombre original** (p. ej. `kiosks_daily_summary`).
- Un **alias estable** (`df1`, `df2`, …) coherente con lo que reporta `list_datasets`.
- **Metadatos** auxiliares (`kiosks_daily_summary_row_count`, `_columns`, `_shape`, …).

```python
# Dentro del REPL del agente, todo esto está disponible:
result = kiosks_daily_summary[kiosks_daily_summary['is_empty'] == True]
print(kiosks_daily_summary_columns)   # ['kiosk_id', 'warehouse_id', ...]
```

El flag `use_tool_llm` (Porygon lo deja en `False`) controla si la elección de
herramientas se delega a un LLM auxiliar; por defecto el propio modelo principal
razona sobre qué herramienta invocar.

---

## 2. DatasetManager: el catálogo de datos

`DatasetManager` (`parrot/tools/dataset_manager/tool.py`, clase `DatasetManager(AbstractToolkit)`)
es la pieza central de datos. Funciona como un **catálogo + toolkit**: registra
fuentes, las describe al LLM, las materializa bajo demanda y mantiene los datos
crudos **en local**.

Cada fuente registrada queda envuelta en un `DatasetEntry`, que guarda el estado
de ciclo de vida (`_df`, `_column_types`, cargado/no cargado, protegido) y los
metadatos seguros para el LLM, modelados por `DatasetInfo`.

### 2.1 El principio "in our end": los datos no salen a la nube

Este es el punto arquitectónico más importante para análisis sobre datos
sensibles: **el LLM nunca recibe filas crudas de las tablas**. Solo recibe
metadatos y, opcionalmente, resúmenes o muestras pequeñas.

El modelo `DatasetInfo` define exactamente qué se expone al modelo:

```python
class DatasetInfo(BaseModel):
    name, alias, description, source_type, source_description
    # ✓ Esto SÍ se envía al LLM (metadatos, no datos):
    columns: List[str]                       # solo nombres de columnas
    column_types: Optional[Dict[str, str]]   # tipos (integer, text, ...)
    row_count_estimate: Optional[int]        # tamaño, para decidir estrategia
    table_size_warning: str                  # "tabla grande → usa GROUP BY"
    usage_do, usage_dont: List[str]          # guías de uso

    # ✗ Solo presente si loaded=True (los datos viven en memoria local):
    shape, loaded, memory_usage_mb, null_count
```

Cómo se garantiza el aislamiento:

1. **Carga perezosa con prefetch de esquema.** Una `TableSource` ejecuta una
   consulta a `INFORMATION_SCHEMA` al registrarse para conocer columnas y tipos.
   **No se trae ni una fila** para exponer el esquema.
2. **Materialización local.** `fetch_dataset(...)` ejecuta la consulta (idealmente
   agregada con `GROUP BY`/`SUM`/`AVG` empujadas a la base de datos) y guarda el
   resultado en un DataFrame en memoria del proceso, con caché opcional en Redis.
   Ese DataFrame se queda local.
3. **Respuestas acotadas.** `fetch_dataset` devuelve los datos completos solo si el
   resultado es pequeño; para resultados grandes devuelve un `sample_rows` (vista
   previa de ~20-50 filas) y marca `"complete": False`, indicando que el dataset
   completo está en memoria como variable de Python (`python_variable`) para que el
   REPL lo manipule.
4. **Manipulación en el REPL.** Toda transformación pesada (joins, agregaciones,
   pivots, correlaciones, forecasting) ocurre en pandas, localmente. El LLM solo ve
   el código que escribe y los resúmenes/tablas que decide devolver.

> **Consecuencia práctica:** a la nube del LLM solo viajan descripciones de
> esquema, guías de uso (`usage_guidance`), el código pandas generado y los
> **resúmenes finales** que el agente elige mostrar. Los datos crudos se procesan
> íntegramente en nuestra infraestructura.

### 2.2 Tipos de datasets / fuentes soportadas

Todas las fuentes heredan de `DataSource` (`sources/base.py`). Hay dos grandes
modos: **perezoso** (solo esquema, filas bajo demanda) y **eager** (DataFrame
cargado en el arranque).

#### Fuentes perezosas (esquema precargado, sin filas)

| Tipo | Método de registro | Descripción |
|------|--------------------|-------------|
| **TableSource** | `add_table_source(name, table, driver, ...)` | Tabla de BD (BigQuery, Postgres, MySQL). Hace prefetch del esquema vía `INFORMATION_SCHEMA`. El LLM debe pasar un `SELECT` dirigido; valida columnas y rechaza `SELECT *` en tablas grandes (>10k filas). |
| **QuerySlugSource** | `add_query(name, query_slug, ...)` | Envuelve un *slug* de QuerySource. Infiere tipos con 1 fila; gestiona su propia caché. |
| **MultiQuerySlugSource** | (interno) | Varios slugs concatenados, unión de esquemas. |
| **SQLQuerySource** | `add_sql_source(name, sql, driver, ...)` | Plantilla SQL con marcadores `{param}`. `fetch(conditions={...})` sustituye y ejecuta. |
| **IcebergSource** | `add_iceberg_source(name, table_id, catalog_params, ...)` | Tabla Apache Iceberg. |
| **DeltaTableSource** | `add_deltatable_source(name, path, ...)` | Tabla Delta Lake (local, `s3://`, `gs://`). |
| **MongoSource** | `add_mongo_source(name, collection, database, ...)` | Colección MongoDB/DocumentDB; requiere `filter` y `projection`. |
| **AirtableSource** | `add_airtable_source(name, base_id, table, ...)` | Base/tabla de Airtable. |
| **SmartsheetSource** | `add_smartsheet_source(name, sheet_id, ...)` | Hoja de Smartsheet. |

#### Fuentes eager (DataFrame cargado de inmediato)

| Tipo | Método de registro | Descripción |
|------|--------------------|-------------|
| **InMemorySource** | `add_dataframe(name, df, ...)` | Envuelve un DataFrame de pandas ya en memoria. |
| | `add_dataframe_from_file(name, path, ...)` | Lee CSV/Excel con pandas y lo registra. |
| | `add_dataset(name, table/query/dataframe/query_slug, ...)` | Ejecuta la fuente al instante y cachea el resultado como DataFrame. |

#### Fuentes compuestas

| Tipo | Método de registro | Descripción |
|------|--------------------|-------------|
| **CompositeDataSource** | `add_composite_dataset(name, joins, ...)` | Dataset virtual que **une** dos o más datasets ya registrados mediante `JoinSpec` (left/right/on/how/suffixes). |

#### Carga de ficheros para análisis estructural

`load_file(name, path, max_rows_per_table=200, output_format='markdown')` carga un
CSV/Excel y produce un resumen estructural en markdown (tablas, tipos), pensado
para que el agente entienda un fichero subido sin convertirlo aún en DataFrame.

#### Parámetros clave de los métodos de registro

`add_table_source`, `add_dataset` y `add_query` comparten un vocabulario común:

```python
await dm.add_table_source(
    name="active_employees",            # identificador del dataset
    table="troc.troc_employees",        # nombre cualificado en la BD
    driver="pg",                        # "pg" | "bigquery" | "mysql"
    description="Lista de empleados...", # descripción para el LLM
    query_filter={"region": "POKEMON HIERARCHY"},  # filtro permanente siempre aplicado
    usage_guidance={                    # guías do/don't para el LLM
        "do": [
            "Análisis de headcount, cálculos FTE",
            "Filtrado por estado activo, departamento, rol",
        ],
        "dont": [
            "No usar para datos financieros (revenue, expenses, EBITDA)",
        ],
    },
)
```

- `description` y `usage_guidance` (`do`/`dont`) son la **forma de enseñar al LLM**
  cuándo y cómo usar cada dataset, sin exponer datos.
- `permanent_filter` / `query_filter`: filtro de igualdad siempre aplicado (escalar →
  `=`, lista → `IN`). Útil para *multi-tenancy* o recortar el alcance.
- `allowed_columns`: restringe el acceso a un subconjunto de columnas.
- `cache_ttl` / `no_cache`: control de la caché en Redis (Parquet).
- `metadata`, `query_slug`, `computed_columns`: metadatos extra, slug de QuerySource
  y columnas calculadas (ver abajo).

Ejemplo real de Porygon registrando 8 fuentes perezosas (BigQuery + Postgres) y 2
eager, y de TROC Finance registrando proyecciones, presupuesto y `chart_of_accounts`.

### 2.3 Incorporar nuevos datasets en caliente

El agente puede ampliar su catálogo **durante la conversación**, no solo en el
arranque:

- **`fetch_dataset(name, sql=..., conditions=..., force_refresh=...)`** — herramienta
  principal: materializa una fuente registrada. Para `TableSource` exige un `SELECT`
  explícito (preferiblemente agregado); para fuentes compuestas o SQL acepta
  `conditions`. Devuelve forma, columnas, esquema y datos/muestra + la variable
  Python disponible en el REPL.
- **`add_source(source, ...)`** — punto de entrada genérico para registrar cualquier
  subclase de `DataSource` dinámicamente.
- **`add_dataframe_from_file(...)` / `load_file(...)`** — incorporar ficheros subidos
  (CSV/Excel) como dataset o como resumen estructural.
- **`store_dataframe` / `add_dataframe`** — guardar en el catálogo un DataFrame
  calculado en el REPL para reutilizarlo en pasos posteriores.
- Gestión del ciclo de vida: `activate_datasets`, `deactivate_datasets`,
  `remove_dataset`, `evict_dataset` (libera memoria sin perder la definición),
  `check_data_quality`, `list_datasets`, `get_metadata`, `get_source_schema`.

### 2.4 Columnas calculadas y datasets compuestos

**Columnas calculadas** (`ComputedColumnDef`): columnas virtuales aplicadas *después*
de materializar, en local:

```python
ComputedColumnDef(
    name="margin",
    func="math_operation",        # add | subtract | multiply | divide
    columns=["revenue", "cost"],
    kwargs={"operation": "subtract"},
)
```

Funciones integradas: operaciones matemáticas y concatenación de strings; si está
disponible QuerySource, se cargan funciones adicionales. Se pueden añadir en
caliente con `add_computed_column(...)`.

**Datasets compuestos** (`CompositeDataSource` + `JoinSpec`): joins declarativos
entre datasets registrados, materializados con `pd.merge()` secuencial y filtros por
componente. Cada componente se cachea de forma individual.

---

## 3. Sistema de Skills

El **SkillRegistryMixin** (`parrot/skills/`) dota al agente de un registro de
**skills** versionables tipo Git: instrucciones de comportamiento reutilizables,
escritas como markdown con *frontmatter* YAML.

### Qué es una skill

Una skill es un fichero markdown con metadatos y un cuerpo de instrucciones:

```markdown
---
name: ebitda_breakdown
description: Procedimiento estándar de desglose de EBITDA por proyecto/programa/mes
triggers:
  - /ebitda
  - /ebitda_breakdown
source: authored          # authored | learned
category: workflow         # tool_usage | workflow | domain | error_handling | ...
priority: 90
version: 1.0
---

# Cuerpo de la skill
Pasos, fórmulas, datasets a usar, contrato de salida, "qué NO hacer"...
```

Existen dos formatos:

- **Skill de fichero único** (`agents/<agente>/skills/*.md`).
- **Skill compuesta** (directorio con `SKILL.md` + activos). Por ejemplo,
  `agents/troc_finance/skills/daily_financial_projection/` contiene un `SKILL.md`
  que instruye al agente a **leer y ejecutar `compute.py` verbatim** en
  `python_repl_pandas`. Esto es la **ejecución de skills**: la skill transporta
  código Python real que el agente carga y ejecuta para generar DataFrames y bloques
  de salida deterministas.

### Configuración (flags vistos en los agentes)

| Flag | Default | Significado |
|------|---------|-------------|
| `enable_skill_registry` | `True` | Interruptor maestro del registro de skills. |
| `skill_registry_expose_tools` | `True` | Registra las herramientas de skills (buscar, documentar, listar, cargar). |
| `skill_registry_inject_context` | `True` | Inyecta automáticamente las skills relevantes en el system prompt antes de cada consulta. |
| `skill_registry_auto_extract` | `False` | Extrae skills nuevas de las conversaciones (costoso → opt-in). |
| `skill_registry_max_context_skills` | `3` | Máximo de skills inyectadas por consulta. |

### Cómo funcionan (carga, contexto, ejecución)

1. **Descubrimiento al arrancar** (`SkillsDirectoryLoader` + `SkillFileRegistry`):
   escanea `agents/<agente>/skills/` (incluido `learned/`), parsea cada `.md` y los
   indexa por nombre y por *trigger*.
2. **Inyección de contexto en dos niveles**:
   - **Capa estática** `<available_skills>`: bloque XML inyectado una vez al
     configurar, que lista todas las skills con su nombre, descripción y triggers.
   - **Carga bajo demanda**: el LLM detecta una skill relevante y llama a
     `load_skill(name="...")`, que devuelve el cuerpo completo + manifiesto de activos.
3. **Activación por trigger** (`SkillTriggerMiddleware`): si el mensaje del usuario
   empieza con `/ebitda_breakdown`, el middleware activa esa skill y la coloca en el
   contexto. `/skills` y `/help` listan las disponibles.
4. **Almacenamiento y búsqueda semántica** (`SkillRegistry`, `store.py`): registro
   versionado (v0 completo + *deltas* en diff unificado), con embeddings
   (`all-mpnet-base-v2`) e índice FAISS para `search_skills`. La relevancia combina
   `0.7 * similitud + 0.3 * utilidad`.
5. **Auto-extracción** (si `auto_extract=True`): un LLM analiza la conversación y, si
   la confianza ≥ 0.5, guarda automáticamente una skill nueva.

### Herramientas de skills expuestas

`document_skill`, `update_skill`, `search_skills`, `read_skill`, `list_skills`,
`save_learned_skill` (la guarda como `.md` y la activa al instante) y `load_skill`.

---

## 4. Memoria episódica

El **EpisodicMemoryMixin** (`parrot/memory/episodic/`) permite al agente **recordar y
aprender de interacciones pasadas**. Cada unidad de memoria es un **episodio**.

### Qué se almacena

El modelo `EpisodicMemory` captura situación, acción, resultado y la lección
aprendida:

```python
class EpisodicMemory(BaseModel):
    situation: str                  # qué se le pidió
    action_taken: str               # qué hizo el agente
    outcome: EpisodeOutcome         # SUCCESS | FAILURE | PARTIAL | TIMEOUT
    error_type, error_message       # clasificación del error
    reflection, lesson_learned, suggested_action   # reflexión (LLM o heurística)
    category: EpisodeCategory       # TOOL_EXECUTION | QUERY_RESOLUTION | ERROR_RECOVERY | ...
    importance: int                 # 1-10
    related_tools, related_entities
    embedding: list[float]          # vector para búsqueda semántica
    # + scoping multi-tenant: tenant_id, agent_id, user_id, session_id, room_id, crew_id
```

### Configuración (flags vistos en los agentes)

| Flag | Default | Significado |
|------|---------|-------------|
| `enable_episodic_memory` | `False` (los agentes lo activan a `True`) | Interruptor maestro. |
| `episodic_backend` | `"faiss"` | Backend de almacenamiento: `faiss` (local/dev), `pgvector` (producción), `redis_vector` (experimental). |
| `episodic_reflection_enabled` | `True` | Genera reflexión (lección + acción sugerida) tras cada episodio. |
| `episodic_inject_warnings` | `True` | Inyecta avisos de fallos pasados en el system prompt. |
| `episodic_max_warnings` | `3` | Máximo de avisos inyectados. |

### Cómo funciona

1. **Almacenamiento FAISS** (`FAISSBackend`): índice `IndexFlatIP` (producto interno
   = coseno sobre vectores normalizados), con persistencia a disco
   (`episodes.faiss` + `episodes.jsonl` + `id_order.json`), tope de episodios y
   auto-guardado periódico. Caché caliente opcional en Redis.
2. **Embeddings** (`all-MiniLM-L6-v2`, 384 dim): se embebe el texto
   `situación | acción | lección`.
3. **Recall** (`recall.py`): búsqueda semántica (`SemanticOnlyStrategy`) o híbrida
   léxica+semántica (`HybridBM25Strategy`, fusión `0.4*BM25 + 0.6*semántico`).
4. **Reflexión** (`ReflectionEngine`): genera la lección con LLM (Gemini flash) y, si
   falla, con patrones heurísticos por regex (timeout, rate limit, permisos, etc.).
5. **Scoring de importancia** (`HeuristicScorer`/`ValueScorer`): los fallos puntúan
   alto (importantes de recordar), los éxitos triviales bajo.
6. **Inyección de avisos**: antes de cada respuesta, `get_failure_warnings` busca
   fallos similares al query actual y los inyecta como:

   ```
   MISTAKES TO AVOID:
   - Consulta a API sin comprobar rate limit (tool: fetch_api) — Añade delay entre llamadas
   SUGGESTED APPROACHES:
   - Implementa backoff o reduce la frecuencia de peticiones.
   ```

7. **Grabación automática** (fire-and-forget): cada `ask()` y cada ejecución de
   herramienta se graban como episodios sin bloquear la respuesta.

### Herramientas episódicas

`search_episodic_memory(query, failures_only)`, `record_lesson(situation, lesson, ...)`
y `get_warnings(context)` (prefijo `ep_`).

---

## 5. Infographic Toolkit

El **InfographicToolkit** (`parrot/tools/infographic_toolkit.py`, FEAT-197) genera
**infografías HTML autocontenidas** a partir de los DataFrames que el agente tiene en
el REPL. Se enlaza al agente con `set_bot(self)` y persiste los artefactos en el
`ArtifactStore` de la app.

En TROC Finance se registra así:

```python
artifact_store = app.get("artifact_store")
if artifact_store is not None:
    infographic_toolkit = InfographicToolkit(artifact_store=artifact_store)
    infographic_toolkit.set_bot(self)         # lee los locals del REPL pandas
    self.tool_manager.register_toolkit(infographic_toolkit)
```

### Herramientas expuestas

| Herramienta | Propósito |
|-------------|-----------|
| `infographic_render(template_name, theme, mode, blocks, data_variables, enhance_brief)` | Valida, renderiza y persiste la infografía. Devuelve `artifact_id` + URL. |
| `infographic_list_templates()` | Lista las plantillas disponibles. |
| `infographic_get_template_contract(template_name)` | Devuelve el contrato (orden y tipos de bloques, constraints, *bundles* JS). |
| `infographic_validate_blocks(template_name, blocks)` | Validación en seco; devuelve `{"ok": ...}` sin lanzar excepción. |

El agente indica en `data_variables` qué DataFrames del REPL alimentan la infografía;
el toolkit los lee vía `bot._get_repl_locals()` y valida que existan y no estén vacíos.

### Tipos de infografía que puede generar

**Plantillas integradas** (registro extensible):

| Plantilla | Uso |
|-----------|-----|
| `basic` | Infografía simple: título + tarjetas hero + resumen + gráfico + bullets. |
| `executive` | Briefing ejecutivo: KPIs + tendencias + tabla + recomendaciones. |
| `dashboard` | Dashboard denso: 6-8 KPIs + línea + tarta + tabla + progreso. |
| `comparison` | Comparativa lado a lado + tabla + barras + ganador. |
| `timeline` | Informe cronológico con eventos + área. |
| `minimal` | Mínima: título + resumen + 3 bullets. |
| `multi_tab` | Informe con **pestañas** (3-7 tabs, cada una con sus propios bloques). |
| `financial_variance` | Dashboard de varianza financiera (4 hero cards, barras DoD, línea acumulada). |
| `financial_projection_variance` | Varianza de proyección financiera (incluye bundle de ECharts vía CDN). |

**Bloques disponibles** (15): `title`, `hero_card` (KPI con tendencia), `summary`,
`chart`, `bullet_list`, `table`, `image`, `quote`, `callout`, `divider`, `timeline`,
`progress`, `accordion`, `checklist`, `tab_view`.

**Tipos de gráfico** (12): `bar`, `line`, `pie`, `donut`, `area`, `scatter`, `radar`,
`heatmap`, `treemap`, `funnel`, `gauge`, `waterfall` — renderizados con ECharts.

**Temas** (4): `light`, `dark`, `corporate`, `midnight`.

### Modos y "enhance pass"

- **`deterministic`**: HTML *esqueleto* generado solo a partir de los bloques
  validados (rápido, predecible).
- **`enhance`**: pasada opcional con LLM que añade interactividad JavaScript a partir
  de un `enhance_brief`. Por seguridad, solo se permiten *bundles* JS declarados en la
  plantilla (whitelist con SRI). Si la validación falla, hace *fallback* al esqueleto.

El resultado se devuelve con `return_direct=True`, de modo que **no se re-resume por
el LLM**: la infografía persistida es el output. El artefacto se guarda en el
`ArtifactStore` (con HTML + envelope de bloques + bundles JS) y se sirve por URL
(`/api/v1/artifacts/{id}?format=html`).

---

## 6. Working Memory Toolkit

El **WorkingMemoryToolkit** (`parrot/tools/working_memory/`) es un **almacén de
resultados intermedios** para análisis de varios pasos. Resuelve un problema clave:
durante una cadena de razonamiento, el agente necesita guardar DataFrames y objetos
intermedios entre llamadas a herramientas **sin devolver datos crudos al LLM**
(ahorra tokens y mantiene contexto). El LLM solo ve **resúmenes compactos** (forma,
dtypes, estadísticas, vista previa pequeña).

Se registra de forma sencilla:

```python
wm_toolkit = WorkingMemoryToolkit()
self.tool_manager.register_toolkit(wm_toolkit)   # prefijo de herramientas: "wm"
```

### Herramientas principales

| Herramienta | Propósito |
|-------------|-----------|
| `store(key, df, ...)` | Guardar un DataFrame bajo una clave. |
| `store_result(key, data, data_type="auto", ...)` | Guardar **cualquier** objeto (texto, dict, list, bytes, Message, objeto). |
| `get_stored(key, ...)` / `get_result(key, ...)` | Recuperar el resumen compacto del elemento. |
| `list_stored(turn_id=None)` / `search_stored(query, ...)` | Listar/buscar elementos guardados. |
| `drop_stored(key)` | Eliminar un elemento. |
| `compute_and_store(spec, ...)` | Ejecutar una **operación declarativa** (DSL) y guardar el resultado. |
| `merge_stored(keys, store_as, ...)` / `summarize_stored(keys, store_as, agg_rules, ...)` | Unir / unir+agregar varios DataFrames. |

…(truncated)…
