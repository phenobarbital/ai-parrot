---
title: "Capabilities of an AI Parrot Analytical Agent (PandasAgent)"
---

# Capabilities of an AI Parrot Analytical Agent (PandasAgent)

> Capabilities document for **Porygon**-style agents (`agents/porygon.py`) and
> **TROC Finance** (`agents/troc.py`), built on `PandasAgent` with the full
> AI-Parrot analytical stack: DatasetManager, Skills system, episodic memory,
> Working Memory, WhatIf Toolkit, Infographic Toolkit and a local Knowledge Base
> with FAISS.

---

## Table of contents

1. [Anatomy of an analytical agent](#1-anatomy-of-an-analytical-agent)
2. [DatasetManager: the data catalog](#2-datasetmanager-the-data-catalog)
   - [The "in our end" principle: data never goes to the cloud](#21-the-in-our-end-principle-data-never-goes-to-the-cloud)
   - [Supported dataset types and sources](#22-supported-dataset-types-and-sources)
   - [Adding new datasets on the fly](#23-adding-new-datasets-on-the-fly)
   - [Computed columns and composite datasets](#24-computed-columns-and-composite-datasets)
3. [Skills system](#3-skills-system)
4. [Episodic memory](#4-episodic-memory)
5. [Infographic Toolkit](#5-infographic-toolkit)
6. [Working Memory Toolkit](#6-working-memory-toolkit)
7. [WhatIf Toolkit](#7-whatif-toolkit)
8. [Local Knowledge Base with FAISS](#8-local-knowledge-base-with-faiss)
9. [Overview of capabilities and potential](#9-overview-of-capabilities-and-potential)

---

## 1. Anatomy of an analytical agent

Both Porygon and TROC Finance are declared with the same mixin composition
on top of `PandasAgent`:

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

This hierarchy provides four major blocks of capability:

| Block | Where it comes from | What it provides |
|-------|---------------------|------------------|
| **Analytical execution** | `PandasAgent` (`parrot.bots.data`) | pandas REPL (`python_repl_pandas`), forecasting with Prophet, DataFrame management |
| **Data catalog** | `DatasetManager` (`_dataset_manager`) | Registration, lazy materialization and local manipulation of data sources |
| **Learning and procedures** | `SkillRegistryMixin` + `EpisodicMemoryMixin` | Reusable skills + memory of past experiences |
| **Specialized toolkits** | `WorkingMemoryToolkit`, `WhatIfToolkit`, `InfographicToolkit`, `DatabaseToolkit` | Working memory, scenario simulation, HTML infographics, multi-driver SQL |

`PandasAgent` is the core: it exposes a **pandas REPL** (`PythonPandasTool`)
where registered datasets appear as ready-to-use Python variables.
Each DataFrame is injected with:

- Its **original name** (e.g. `kiosks_daily_summary`).
- A **stable alias** (`df1`, `df2`, …) consistent with what `list_datasets` reports.
- Auxiliary **metadata** (`kiosks_daily_summary_row_count`, `_columns`, `_shape`, …).

```python
# Inside the agent's REPL, all of this is available:
result = kiosks_daily_summary[kiosks_daily_summary['is_empty'] == True]
print(kiosks_daily_summary_columns)   # ['kiosk_id', 'warehouse_id', ...]
```

The `use_tool_llm` flag (Porygon leaves it at `False`) controls whether tool
selection is delegated to an auxiliary LLM; by default the main model itself
reasons about which tool to invoke.

---

## 2. DatasetManager: the data catalog

`DatasetManager` (`parrot/tools/dataset_manager/tool.py`, class `DatasetManager(AbstractToolkit)`)
is the central data component. It works as a **catalog + toolkit**: it registers
sources, describes them to the LLM, materializes them on demand and keeps the
raw data **local**.

Each registered source is wrapped in a `DatasetEntry`, which holds the lifecycle
state (`_df`, `_column_types`, loaded/not loaded, protected) and the LLM-safe
metadata, modeled by `DatasetInfo`.

### 2.1 The "in our end" principle: data never goes to the cloud

This is the most important architectural point for analysis over sensitive
data: **the LLM never receives raw table rows**. It only receives metadata and,
optionally, summaries or small samples.

The `DatasetInfo` model defines exactly what is exposed to the model:

```python
class DatasetInfo(BaseModel):
    name, alias, description, source_type, source_description
    # ✓ This IS sent to the LLM (metadata, not data):
    columns: List[str]                       # column names only
    column_types: Optional[Dict[str, str]]   # types (integer, text, ...)
    row_count_estimate: Optional[int]        # size, to decide strategy
    table_size_warning: str                  # "large table → use GROUP BY"
    usage_do, usage_dont: List[str]          # usage guidance

    # ✗ Only present if loaded=True (the data lives in local memory):
    shape, loaded, memory_usage_mb, null_count
```

How isolation is guaranteed:

1. **Lazy loading with schema prefetch.** A `TableSource` runs a query against
   `INFORMATION_SCHEMA` when registered to learn columns and types.
   **Not a single row is fetched** to expose the schema.
2. **Local materialization.** `fetch_dataset(...)` runs the query (ideally
   aggregated with `GROUP BY`/`SUM`/`AVG` pushed down to the database) and stores the
   result in an in-memory DataFrame in the process, with optional caching in Redis.
   That DataFrame stays local.
3. **Bounded responses.** `fetch_dataset` returns the full data only if the
   result is small; for large results it returns `sample_rows` (a preview of ~20-50
   rows) and sets `"complete": False`, indicating that the full dataset is in memory
   as a Python variable (`python_variable`) for the REPL to manipulate.
4. **Manipulation in the REPL.** All heavy transformation (joins, aggregations,
   pivots, correlations, forecasting) happens in pandas, locally. The LLM only sees
   the code it writes and the summaries/tables it decides to return.

> **Practical consequence:** only schema descriptions, usage guidance
> (`usage_guidance`), the generated pandas code and the **final summaries** the
> agent chooses to show travel to the LLM cloud. Raw data is processed
> entirely within our infrastructure.

### 2.2 Supported dataset types and sources

All sources inherit from `DataSource` (`sources/base.py`). There are two main
modes: **lazy** (schema only, rows on demand) and **eager** (DataFrame
loaded at startup).

#### Lazy sources (schema preloaded, no rows)

| Type | Registration method | Description |
|------|---------------------|-------------|
| **TableSource** | `add_table_source(name, table, driver, ...)` | DB table (BigQuery, Postgres, MySQL). Prefetches the schema via `INFORMATION_SCHEMA`. The LLM must pass a targeted `SELECT`; it validates columns and rejects `SELECT *` on large tables (>10k rows). |
| **QuerySlugSource** | `add_query(name, query_slug, ...)` | Wraps a QuerySource *slug*. Infers types from 1 row; manages its own cache. |
| **MultiQuerySlugSource** | (internal) | Several slugs concatenated, union of schemas. |
| **SQLQuerySource** | `add_sql_source(name, sql, driver, ...)` | SQL template with `{param}` placeholders. `fetch(conditions={...})` substitutes and executes. |
| **IcebergSource** | `add_iceberg_source(name, table_id, catalog_params, ...)` | Apache Iceberg table. |
| **DeltaTableSource** | `add_deltatable_source(name, path, ...)` | Delta Lake table (local, `s3://`, `gs://`). |
| **MongoSource** | `add_mongo_source(name, collection, database, ...)` | MongoDB/DocumentDB collection; requires `filter` and `projection`. |
| **AirtableSource** | `add_airtable_source(name, base_id, table, ...)` | Airtable base/table. |
| **SmartsheetSource** | `add_smartsheet_source(name, sheet_id, ...)` | Smartsheet sheet. |

#### Eager sources (DataFrame loaded immediately)

| Type | Registration method | Description |
|------|---------------------|-------------|
| **InMemorySource** | `add_dataframe(name, df, ...)` | Wraps a pandas DataFrame already in memory. |
| | `add_dataframe_from_file(name, path, ...)` | Reads CSV/Excel with pandas and registers it. |
| | `add_dataset(name, table/query/dataframe/query_slug, ...)` | Runs the source immediately and caches the result as a DataFrame. |

#### Composite sources

| Type | Registration method | Description |
|------|---------------------|-------------|
| **CompositeDataSource** | `add_composite_dataset(name, joins, ...)` | Virtual dataset that **joins** two or more already registered datasets through `JoinSpec` (left/right/on/how/suffixes). |

#### File loading for structural analysis

`load_file(name, path, max_rows_per_table=200, output_format='markdown')` loads a
CSV/Excel file and produces a structural summary in markdown (tables, types), meant
to let the agent understand an uploaded file without yet turning it into a DataFrame.

#### Key parameters of the registration methods

`add_table_source`, `add_dataset` and `add_query` share a common vocabulary:

```python
await dm.add_table_source(
    name="active_employees",            # dataset identifier
    table="troc.troc_employees",        # qualified name in the DB
    driver="pg",                        # "pg" | "bigquery" | "mysql"
    description="Lista de empleados...", # description for the LLM
    query_filter={"region": "POKEMON HIERARCHY"},  # permanent filter always applied
    usage_guidance={                    # do/don't guidance for the LLM
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

- `description` and `usage_guidance` (`do`/`dont`) are the **way to teach the LLM**
  when and how to use each dataset, without exposing data.
- `permanent_filter` / `query_filter`: equality filter always applied (scalar →
  `=`, list → `IN`). Useful for *multi-tenancy* or narrowing the scope.
- `allowed_columns`: restricts access to a subset of columns.
- `cache_ttl` / `no_cache`: Redis (Parquet) cache control.
- `metadata`, `query_slug`, `computed_columns`: extra metadata, QuerySource slug
  and computed columns (see below).

A real example: Porygon registering 8 lazy sources (BigQuery + Postgres) and 2
eager ones, and TROC Finance registering projections, budget and `chart_of_accounts`.

### 2.3 Adding new datasets on the fly

The agent can extend its catalog **during the conversation**, not only at
startup:

- **`fetch_dataset(name, sql=..., conditions=..., force_refresh=...)`** — main
  tool: materializes a registered source. For `TableSource` it requires an
  explicit `SELECT` (preferably aggregated); for composite or SQL sources it accepts
  `conditions`. Returns shape, columns, schema and data/sample + the Python
  variable available in the REPL.
- **`add_source(source, ...)`** — generic entry point to dynamically register any
  `DataSource` subclass.
- **`add_dataframe_from_file(...)` / `load_file(...)`** — bring in uploaded files
  (CSV/Excel) as a dataset or as a structural summary.
- **`store_dataframe` / `add_dataframe`** — save to the catalog a DataFrame
  computed in the REPL so it can be reused in later steps.
- Lifecycle management: `activate_datasets`, `deactivate_datasets`,
  `remove_dataset`, `evict_dataset` (frees memory without losing the definition),
  `check_data_quality`, `list_datasets`, `get_metadata`, `get_source_schema`.

### 2.4 Computed columns and composite datasets

**Computed columns** (`ComputedColumnDef`): virtual columns applied *after*
materialization, locally:

```python
ComputedColumnDef(
    name="margin",
    func="math_operation",        # add | subtract | multiply | divide
    columns=["revenue", "cost"],
    kwargs={"operation": "subtract"},
)
```

Built-in functions: mathematical operations and string concatenation; if
QuerySource is available, additional functions are loaded. They can be added on
the fly with `add_computed_column(...)`.

**Composite datasets** (`CompositeDataSource` + `JoinSpec`): declarative joins
between registered datasets, materialized with sequential `pd.merge()` and
per-component filters. Each component is cached individually.

---

## 3. Skills system

The **SkillRegistryMixin** (`parrot/skills/`) gives the agent a Git-like
versionable registry of **skills**: reusable behavioral instructions,
written as markdown with YAML *frontmatter*.

### What a skill is

A skill is a markdown file with metadata and a body of instructions:

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

There are two formats:

- **Single-file skill** (`agents/<agent>/skills/*.md`).
- **Composite skill** (directory with `SKILL.md` + assets). For example,
  `agents/troc_finance/skills/daily_financial_projection/` contains a `SKILL.md`
  that instructs the agent to **read and execute `compute.py` verbatim** in
  `python_repl_pandas`. This is **skill execution**: the skill carries real Python
  code that the agent loads and runs to produce deterministic DataFrames and output
  blocks.

### Configuration (flags seen in the agents)

| Flag | Default | Meaning |
|------|---------|---------|
| `enable_skill_registry` | `True` | Master switch for the skill registry. |
| `skill_registry_expose_tools` | `True` | Registers the skill tools (search, document, list, load). |
| `skill_registry_inject_context` | `True` | Automatically injects relevant skills into the system prompt before each query. |
| `skill_registry_auto_extract` | `False` | Extracts new skills from conversations (expensive → opt-in). |
| `skill_registry_max_context_skills` | `3` | Maximum number of skills injected per query. |

### How they work (loading, context, execution)

1. **Discovery at startup** (`SkillsDirectoryLoader` + `SkillFileRegistry`):
   scans `agents/<agent>/skills/` (including `learned/`), parses each `.md` and
   indexes them by name and by *trigger*.
2. **Two-tier context injection**:
   - **Static layer** `<available_skills>`: an XML block injected once at
     configuration time, listing all skills with their name, description and triggers.
   - **On-demand loading**: the LLM detects a relevant skill and calls
     `load_skill(name="...")`, which returns the full body + asset manifest.
3. **Trigger activation** (`SkillTriggerMiddleware`): if the user's message
   starts with `/ebitda_breakdown`, the middleware activates that skill and places it
   in context. `/skills` and `/help` list the available ones.
4. **Storage and semantic search** (`SkillRegistry`, `store.py`): versioned
   registry (full v0 + *deltas* as unified diffs), with embeddings
   (`all-mpnet-base-v2`) and a FAISS index for `search_skills`. Relevance combines
   `0.7 * similarity + 0.3 * usefulness`.
5. **Auto-extraction** (if `auto_extract=True`): an LLM analyzes the conversation and, if
   confidence ≥ 0.5, automatically saves a new skill.

### Exposed skill tools

`document_skill`, `update_skill`, `search_skills`, `read_skill`, `list_skills`,
`save_learned_skill` (saves it as `.md` and activates it immediately) and `load_skill`.

---

## 4. Episodic memory

The **EpisodicMemoryMixin** (`parrot/memory/episodic/`) lets the agent **remember and
learn from past interactions**. Each unit of memory is an **episode**.

### What is stored

The `EpisodicMemory` model captures the situation, action, outcome and the lesson
learned:

```python
class EpisodicMemory(BaseModel):
    situation: str                  # what was asked
    action_taken: str               # what the agent did
    outcome: EpisodeOutcome         # SUCCESS | FAILURE | PARTIAL | TIMEOUT
    error_type, error_message       # error classification
    reflection, lesson_learned, suggested_action   # reflection (LLM or heuristic)
    category: EpisodeCategory       # TOOL_EXECUTION | QUERY_RESOLUTION | ERROR_RECOVERY | ...
    importance: int                 # 1-10
    related_tools, related_entities
    embedding: list[float]          # vector for semantic search
    # + multi-tenant scoping: tenant_id, agent_id, user_id, session_id, room_id, crew_id
```

### Configuration (flags seen in the agents)

| Flag | Default | Meaning |
|------|---------|---------|
| `enable_episodic_memory` | `False` (the agents set it to `True`) | Master switch. |
| `episodic_backend` | `"faiss"` | Storage backend: `faiss` (local/dev), `pgvector` (production), `redis_vector` (experimental). |
| `episodic_reflection_enabled` | `True` | Generates a reflection (lesson + suggested action) after each episode. |
| `episodic_inject_warnings` | `True` | Injects warnings about past failures into the system prompt. |
| `episodic_max_warnings` | `3` | Maximum number of injected warnings. |

### How it works

1. **FAISS storage** (`FAISSBackend`): `IndexFlatIP` index (inner product
   = cosine over normalized vectors), with persistence to disk
   (`episodes.faiss` + `episodes.jsonl` + `id_order.json`), an episode cap and
   periodic auto-save. Optional hot cache in Redis.
2. **Embeddings** (`all-MiniLM-L6-v2`, 384 dim): the text
   `situation | action | lesson` is embedded.
3. **Recall** (`recall.py`): semantic search (`SemanticOnlyStrategy`) or hybrid
   lexical+semantic (`HybridBM25Strategy`, fusion `0.4*BM25 + 0.6*semantic`).
4. **Reflection** (`ReflectionEngine`): generates the lesson with an LLM (Gemini flash) and, if
   that fails, with heuristic regex patterns (timeout, rate limit, permissions, etc.).
5. **Importance scoring** (`HeuristicScorer`/`ValueScorer`): failures score
   high (important to remember), trivial successes low.
6. **Warning injection**: before each response, `get_failure_warnings` looks for
   failures similar to the current query and injects them as:

   ```
   MISTAKES TO AVOID:
   - Consulta a API sin comprobar rate limit (tool: fetch_api) — Añade delay entre llamadas
   SUGGESTED APPROACHES:
   - Implementa backoff o reduce la frecuencia de peticiones.
   ```

7. **Automatic recording** (fire-and-forget): every `ask()` and every tool
   execution is recorded as an episode without blocking the response.

### Episodic tools

`search_episodic_memory(query, failures_only)`, `record_lesson(situation, lesson, ...)`
and `get_warnings(context)` (prefix `ep_`).

---

## 5. Infographic Toolkit

The **InfographicToolkit** (`parrot/tools/infographic_toolkit.py`, FEAT-197) generates
**self-contained HTML infographics** from the DataFrames the agent holds in the
REPL. It is linked to the agent with `set_bot(self)` and persists artifacts in the
app's `ArtifactStore`.

In TROC Finance it is registered like this:

```python
artifact_store = app.get("artifact_store")
if artifact_store is not None:
    infographic_toolkit = InfographicToolkit(artifact_store=artifact_store)
    infographic_toolkit.set_bot(self)         # reads the pandas REPL locals
    self.tool_manager.register_toolkit(infographic_toolkit)
```

### Exposed tools

| Tool | Purpose |
|------|---------|
| `infographic_render(template_name, theme, mode, blocks, data_variables, enhance_brief)` | Validates, renders and persists the infographic. Returns `artifact_id` + URL. |
| `infographic_list_templates()` | Lists the available templates. |
| `infographic_get_template_contract(template_name)` | Returns the contract (block order and types, constraints, JS *bundles*). |
| `infographic_validate_blocks(template_name, blocks)` | Dry-run validation; returns `{"ok": ...}` without raising an exception. |

The agent indicates in `data_variables` which REPL DataFrames feed the infographic;
the toolkit reads them via `bot._get_repl_locals()` and validates that they exist and are not empty.

### Types of infographics it can generate

**Built-in templates** (extensible registry):

| Template | Use |
|----------|-----|
| `basic` | Simple infographic: title + hero cards + summary + chart + bullets. |
| `executive` | Executive briefing: KPIs + trends + table + recommendations. |
| `dashboard` | Dense dashboard: 6-8 KPIs + line + pie + table + progress. |
| `comparison` | Side-by-side comparison + table + bars + winner. |
| `timeline` | Chronological report with events + area. |
| `minimal` | Minimal: title + summary + 3 bullets. |
| `multi_tab` | Report with **tabs** (3-7 tabs, each with its own blocks). |
| `financial_variance` | Financial variance dashboard (4 hero cards, DoD bars, cumulative line). |
| `financial_projection_variance` | Financial projection variance (includes an ECharts bundle via CDN). |

**Available blocks** (15): `title`, `hero_card` (KPI with trend), `summary`,
`chart`, `bullet_list`, `table`, `image`, `quote`, `callout`, `divider`, `timeline`,
`progress`, `accordion`, `checklist`, `tab_view`.

**Chart types** (12): `bar`, `line`, `pie`, `donut`, `area`, `scatter`, `radar`,
`heatmap`, `treemap`, `funnel`, `gauge`, `waterfall` — rendered with ECharts.

**Themes** (4): `light`, `dark`, `corporate`, `midnight`.

### Modes and the "enhance pass"

- **`deterministic`**: *skeleton* HTML generated solely from the validated blocks
  (fast, predictable).
- **`enhance`**: optional LLM pass that adds JavaScript interactivity from
  an `enhance_brief`. For safety, only JS *bundles* declared in the
  template are allowed (whitelist with SRI). If validation fails, it falls back to the skeleton.

The result is returned with `return_direct=True`, so it is **not re-summarized by
the LLM**: the persisted infographic is the output. The artifact is stored in the
`ArtifactStore` (with HTML + block envelope + JS bundles) and served by URL
(`/api/v1/artifacts/{id}?format=html`).

---

## 6. Working Memory Toolkit

The **WorkingMemoryToolkit** (`parrot/tools/working_memory/`) is a **store of
intermediate results** for multi-step analysis. It solves a key problem:
during a chain of reasoning, the agent needs to keep DataFrames and intermediate
objects between tool calls **without returning raw data to the LLM**
(saves tokens and keeps context). The LLM only sees **compact summaries** (shape,
dtypes, statistics, a small preview).

It is registered simply:

```python
wm_toolkit = WorkingMemoryToolkit()
self.tool_manager.register_toolkit(wm_toolkit)   # tool prefix: "wm"
```

### Main tools

| Tool | Purpose |
|------|---------|
| `store(key, df, ...)` | Store a DataFrame under a key. |
| `store_result(key, data, data_type="auto", ...)` | Store **any** object (text, dict, list, bytes, Message, object). |
| `get_stored(key, ...)` / `get_result(key, ...)` | Retrieve the compact summary of the item. |
| `list_stored(turn_id=None)` / `search_stored(query, ...)` | List/search stored items. |
| `drop_stored(key)` | Delete an item. |
| `compute_and_store(spec, ...)` | Execute a **declarative operation** (DSL) and store the result. |
| `merge_stored(keys, store_as, ...)` / `summarize_stored(keys, store_as, agg_rules, ...)` | Join / join+aggregate several DataFrames. |
| `import_from_tool(tool_name, variable_name, store_as, ...)` | Bridge: import a DataFrame from the pandas REPL namespace. |
| `save_interaction` / `recall_interaction` | Bridge to AnswerMemory (question-answer pairs by `turn_id`). |

`compute_and_store` uses a **declarative DSL** (`OperationSpecInput`) with 13
operations (filter, aggregate, join, merge, correlate, pivot, rank, window, sort,
select, rename, fillna, drop_duplicates, describe). The agent **never executes
arbitrary code** through this path: only specs validated by Pydantic, which makes it safe and
auditable. Internally, `WorkingMemoryCatalog` stores `CatalogEntry` (DataFrames with
lineage: `parent_keys`, `source_operation`) and `GenericEntry` (other objects).

---

## 7. WhatIf Toolkit

The **WhatIfToolkit** (`parrot_tools/whatif_toolkit.py`) performs
**"what if" scenario analysis** in a decomposed way: it applies hypothetical changes to
the datasets and measures their impact, **all in pandas, locally**.

It is built by linking it to the DatasetManager and the pandas REPL, and is enabled with the
`enable_scenarios=True` flag on the agent:

```python
whatif_toolkit = WhatIfToolkit(
    dataset_manager=dm,
    pandas_tool=getattr(self, 'pandas_tool', None),
)
self.tool_manager.register_toolkit(whatif_toolkit)
```

### Concepts

- **Derived metrics** (`DerivedMetric`): fields computed by formula
  (`revenue_per_visit = revenue / visits`) that are recomputed when the base columns change.
- **Actions** (`Action`): hypothetical operations — exclude rows, scale columns,
  adjust by percentage, scale by entity, proportional scaling.
- **Constraints** (`Constraint`): hard limits (maximum change %, min/max, ratio).
- **Objectives** (`Objective`): minimize, maximize or reach a target value, with
  weights.
- **Optimization**: `greedy` algorithm (iterative improvement) or `genetic` (exhaustive
  search of combinations).

### Tools (decomposed flow)

| Tool | Purpose |
|------|---------|
| `describe_scenario(df_name, scenario_description, derived_metrics)` | Creates and validates a scenario; returns `scenario_id` + column inventory. |
| `add_actions(scenario_id, actions)` | Adds possible actions, validated against the schema. |
| `set_constraints(scenario_id, objectives, constraints)` | Defines objectives and constraints. |
| `simulate(scenario_id, algorithm, max_actions)` | Runs the optimization; registers the resulting DataFrame in the DatasetManager (`whatif_<id>_result`). |
| `compare_scenarios(scenario_ids)` | Compares several solved scenarios side by side. |
| `quick_impact(df_name, action_description, action_type, target, parameters)` | One-step shortcut for simple questions ("what if we remove X?"). |

The result is presented as a baseline vs scenario comparison table (absolute
and % change), applied actions and a verdict. Because the result is registered in the
DatasetManager, it chains with pandas and new simulations.

---

## 8. Local Knowledge Base with FAISS

The **`local_kb=True`** flag gives the agent an **in-memory knowledge base,
backed by FAISS**, that indexes the agent's own documents and retrieves them by
similarity during reasoning (a RAG pattern over its own knowledge).

```python
super().__init__(
    *args,
    local_kb=True,
    kb_embedding_model="sentence-transformers/all-mpnet-base-v2",
    kb_dimension=768,    # Porygon uses 768; the framework default is 384
    ...
)
```

### What it indexes and how

- **Source**: markdown/text files in `AGENTS_DIR/<agent_id>/kb/`. For example,
  Porygon has `agents/porygon/kb/forecasting.md`; TROC Finance has
  `agents/troc_finance/kb/` with brand guides, etc. These are query guides,
  tool usage examples and domain procedures.
- **Loading** (`LocalKB.load_documents`): splits each file respecting markdown
  headings and code blocks (`chunk_size=4096`, `overlap=100`), generates
  embeddings and indexes them.
- **FAISS index**: `LocalKB` uses an **HNSW** index by default with **cosine**
  distance (normalized vectors). `FAISSStore` supports `Flat`, `IVF` and `HNSW`.
  The index is cached to disk (`.kb_cache.faiss`) and file changes are detected by
  modification date.
- **Configuration**: `local_kb` (bool), `kb_embedding_model` (HuggingFace model),
  `kb_dimension` (384 or 768).

### How it is used in reasoning

During `ask()`, `_build_kb_context(question, ...)` activates the eligible KBs (the local
KB is `always_active=True`), runs `kb.search(query, k=5, score_threshold=0.5)`,
formats the relevant fragments and **injects them into the system prompt**. This way the
agent reasons with its domain knowledge without the latency of external services and
in a consistent manner.

> Note: `local_kb` (the agent's markdown KB) is distinct from the FAISS backend of
> **episodic memory** and from the FAISS index of the **skill registry**, even though all three
> use FAISS + sentence-transformers. They are three vector stores with different
> purposes: domain knowledge, past experiences and reusable
> procedures.

---

## 9. Overview of capabilities and potential

A PandasAgent-style agent with the full AI-Parrot stack integrated behaves like an
**autonomous data analyst with memory**, operating on sensitive data without
sending it to the cloud. Summary of capabilities:

### Data and analysis (DatasetManager + PandasAgent)
- Unified catalog over **BigQuery, Postgres, MySQL, Mongo, Iceberg, Delta Lake,
  Airtable, Smartsheet, QuerySource, parameterized SQL, files and DataFrames**.
- **Lazy loading**: the LLM sees schemas, types, size estimates and `do/dont`
  guidance, but **never raw rows**.
- All heavy transformation happens **locally in pandas** (REPL); only code and
  final summaries travel to the cloud.
- New datasets on the fly, computed columns, composite joins, forecasting with
  Prophet, data quality checks.

### Procedures and learning (Skills + Episodic memory)
- **Skills**: reusable procedures in markdown, with `/command` triggers,
  Git-like versioning, semantic search, and even **code execution** (composite
  skills with `compute.py`). The agent can learn new skills.
- **Episodic memory**: remembers successes and failures, reflects on them and **injects
  warnings** ("mistakes to avoid") into future responses, improving with use.

### Multi-step work (Working Memory + WhatIf)
- **Working Memory**: stores intermediate results between steps without saturating the
  context, with a declarative and safe DSL of 13 operations.
- **WhatIf**: simulates hypothetical scenarios (exclude, scale, adjust) with objectives
  and constraints, greedy/genetic optimization, and compares scenarios — all local.

### Communicating results (Infographic Toolkit)
- Generates **HTML infographics** (9 templates, 15 blocks, 12 chart types, 4 themes,
  multi-tab tabs) directly from the agent's DataFrames, with persistence
  as artifacts and an optional *enhance* mode with safe JS interactivity.

### Domain knowledge (Local KB with FAISS)
- RAG over the agent's own knowledge (markdown indexed in FAISS), injected
  into the prompt for consistent, low-latency answers.

### Combined potential

| Scenario | How the agent solves it |
|----------|-------------------------|
| "How is Phoenix doing?" (Porygon) | DatasetManager materializes aggregated KPIs → pandas cross-references them → episodic memory warns about previous errors → `dashboard` infographic. |
| "Compare budget vs actual EBITDA" (TROC) | Skill `/ebitda_breakdown` guides the calculation → Working Memory stores intermediates → WhatIf simulates cuts → `financial_variance` infographic. |
| "What if we close 2 warehouses?" | WhatIf applies exclusion/scaling actions over local data, respects constraints and returns the compared impact. |
| Recurring analysis | Skills capture the procedure; episodic memory retains lessons; the local KB fixes the domain knowledge. |

**Guiding principle:** expert-level analytical capability + privacy by design —
raw data is processed **in our end**, and only descriptions, code and aggregated
summaries reach the LLM in the cloud.
