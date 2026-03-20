# Feature Specification: Ontological Graph RAG

**Feature ID**: FEAT-053
**Date**: 2026-03-19
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Brainstorm**: `sdd/proposals/ontological-graph-rag.brainstorm.md`

---

## 1. Motivation & Business Requirements

> Standard vector-based RAG fails when user queries require **structural reasoning** — answers
> that depend on relationships between entities rather than semantic similarity alone.

### Problem Statement

An EPSON field employee asks *"What is my portal?"*. Pure vector search for "portal" returns
generic documentation about all portals. The correct answer requires:

1. Identifying the user (session context → employee record)
2. Traversing relationships: Employee → Project (EPSON) → Portal (`epson.navigator`)
3. Enriching with semantic search: documentation about `epson.navigator`
4. Optionally executing tools: Workday API to get additional employee data

This is a **Graph-First RAG** pattern: structured traversal provides precision, vector search
provides richness, and tool execution provides live data.

### Goals

- **Composable Ontology YAMLs**: Three-layer system (base → domain → client) with strict
  Pydantic validation and deterministic merge rules.
- **Multi-Tenant Isolation**: Each tenant gets its own ArangoDB database and PgVector schema.
- **Dual-Path Intent Resolution**: Fast-path keyword matching (~0ms) + LLM-based classification
  (~200-800ms) for ambiguous queries.
- **Relation Discovery Engine**: Automatic edge creation from data sources (exact, fuzzy,
  AI-assisted, composite strategies).
- **Agent Mixin Integration**: `OntologyRAGMixin` — agents opt-in via inheritance, hooks into
  `ask()` flow before standard RAG processing.
- **PromptBuilder Integration**: Ontology schema as a composable prompt layer rendered at
  `RenderPhase.CONFIGURE`.
- **CRON Refresh Pipeline**: Delta sync from data sources with cache invalidation.
- **Generic ExtractDataSource**: Reusable structured record extraction (CSV, JSON, SQL, API,
  in-memory) in `parrot/loaders/extractors/`.

### Non-Goals (explicitly out of scope)

- Modifying existing Loaders (`parrot/loaders/`) — extractors are a separate, parallel package.
- Building a UI for the review queue — JSON log files only.
- Implementing all API-specific data sources (Workday, Jira) — only the `APIDataSource` ABC
  and factory pattern. Concrete API sources are follow-up work.
- Real-time streaming graph updates — CRON-based delta sync only.
- Graph visualization or exploration UI.

---

## 2. Architectural Design

### Overview

Layered Architecture with Mixin (Option B from brainstorm):

1. **ExtractDataSource** layer — generic structured record extraction (`parrot/loaders/extractors/`)
2. **Ontology Schema** layer — Pydantic models for YAML validation + merge engine
3. **Graph Store** layer — ArangoDB operations (tenant-isolated)
4. **Relation Discovery** layer — automatic edge creation from data sources
5. **Intent Resolution** layer — dual-path query classification
6. **OntologyRAGMixin** — agent integration (hooks into `ask()` flow)
7. **Refresh Pipeline** — CRON-triggered delta sync

### Component Diagram

```
Agent (inherits OntologyRAGMixin)
  │
  ├── ask() → OntologyRAGMixin.process()
  │     │
  │     ├── 1. TenantOntologyManager.resolve(tenant_id)
  │     │     └── OntologyMerger.merge([base, domain, client])
  │     │
  │     ├── 2. OntologyIntentResolver.resolve(query, user_context)
  │     │     ├── Fast path: keyword scan against trigger_intents
  │     │     └── LLM path: structured output → pattern or dynamic AQL
  │     │
  │     ├── 3. OntologyGraphStore.execute_traversal(aql, bind_vars)
  │     │     └── AQL validated for safety (read-only, depth-limited)
  │     │
  │     ├── 4. Post-action routing:
  │     │     ├── vector_search → PgVector query with graph context
  │     │     ├── tool_call → hint agent for tool execution
  │     │     └── none → return graph result directly
  │     │
  │     └── 5. Cache result (Redis, TTL = ONTOLOGY_CACHE_TTL)
  │
  └── PromptBuilder: ontology_schema layer (RenderPhase.CONFIGURE)

CRON: OntologyRefreshPipeline
  │
  ├── DataSourceFactory → ExtractDataSource (CSV, JSON, API, SQL)
  ├── Diff → Upsert nodes
  ├── RelationDiscovery → Create edges
  ├── Sync PgVector embeddings
  └── Invalidate cache
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/conf.py` | Modified | Add 12 ONTOLOGY_* config variables |
| `parrot/stores/arango.py` (`ArangoDBStore`) | Consumed | Existing ArangoDB client, extend with ontology-specific methods |
| `parrot/stores/pgvector.py` (`PgVectorStore`) | Consumed | Vector search with graph context |
| `parrot/embeddings/` | Consumed | Embed vectorizable entity fields |
| Agent pipeline (`ask()` flow) | Modified | Mixin hooks before standard RAG |
| PromptBuilder | Modified | New ontology_schema composable layer |
| Redis (existing) | Consumed | Cache full pipeline results |
| `parrot/loaders/` | Extended | New `extractors/` sub-package (no changes to existing loaders) |

### Data Models

**Core Pydantic Models** (`parrot/knowledge/ontology/schema.py`):

```python
class PropertyDef(BaseModel):
    type: Literal["string", "int", "float", "boolean", "date", "list", "dict"]
    required: bool = False
    unique: bool = False
    default: Any = None
    enum: list[str] | None = None
    description: str | None = None

class EntityDef(BaseModel):
    collection: str | None = None
    source: str | None = None
    key_field: str | None = None
    properties: list[dict[str, PropertyDef]] = []
    vectorize: list[str] = []
    extend: bool = False

class DiscoveryRule(BaseModel):
    source_field: str
    target_field: str
    match_type: Literal["exact", "fuzzy", "ai_assisted", "composite"] = "exact"
    threshold: float = 0.85

class RelationDef(BaseModel):
    from_entity: str = Field(alias="from")
    to_entity: str = Field(alias="to")
    edge_collection: str
    properties: list[dict[str, PropertyDef]] = []
    discovery: DiscoveryConfig = DiscoveryConfig()

class TraversalPattern(BaseModel):
    description: str
    trigger_intents: list[str] = []
    query_template: str
    post_action: Literal["vector_search", "tool_call", "none"] = "none"
    post_query: str | None = None

class OntologyDefinition(BaseModel):
    name: str
    version: str = "1.0"
    extends: str | None = None
    entities: dict[str, EntityDef] = {}
    relations: dict[str, RelationDef] = {}
    traversal_patterns: dict[str, TraversalPattern] = {}

class MergedOntology(BaseModel):
    name: str
    version: str
    entities: dict[str, EntityDef]
    relations: dict[str, RelationDef]
    traversal_patterns: dict[str, TraversalPattern]
    layers: list[str]
    merge_timestamp: datetime
```

**ExtractDataSource Models** (`parrot/loaders/extractors/base.py`):

```python
class ExtractedRecord(BaseModel):
    data: dict[str, Any]
    metadata: dict[str, Any] = {}

class ExtractionResult(BaseModel):
    records: list[ExtractedRecord]
    total: int
    errors: list[str] = []
    warnings: list[str] = []
    source_name: str
    extracted_at: datetime
```

**Intent Resolution Models** (`parrot/knowledge/ontology/intent.py`):

```python
class ResolvedIntent(BaseModel):
    action: Literal["graph_query", "vector_only"]
    pattern: str | None = None
    aql: str | None = None
    params: dict[str, Any] = {}
    collection_binds: dict[str, str] = {}
    post_action: str = "none"
    post_query: str | None = None
    source: str = "none"  # "fast_path", "llm", "llm_dynamic"
```

### New Public Interfaces

| Interface | Location | Description |
|---|---|---|
| `ExtractDataSource` (ABC) | `parrot/loaders/extractors/base.py` | Generic structured record extraction |
| `DataSourceFactory` | `parrot/loaders/extractors/factory.py` | Resolve source names to implementations |
| `OntologyRAGMixin` | `parrot/knowledge/ontology/mixin.py` | Agent mixin for ontology pipeline |
| `TenantOntologyManager` | `parrot/knowledge/ontology/tenant.py` | Multi-tenant YAML resolution |
| `OntologyIntentResolver` | `parrot/knowledge/ontology/intent.py` | Dual-path intent resolution |
| `OntologyGraphStore` | `parrot/knowledge/ontology/graph_store.py` | ArangoDB operations |
| `OntologyRefreshPipeline` | `parrot/knowledge/ontology/refresh.py` | CRON delta sync |

---

## 3. Module Breakdown

### Module 1: Configuration Variables

- **Path**: `parrot/conf.py`
- **Responsibility**: Add ONTOLOGY_* config variables via navconfig pattern.
- **Depends on**: None
- **Details**: 12 variables — `ONTOLOGY_DIR`, `ONTOLOGY_BASE_FILE`, `ONTOLOGY_DOMAINS_DIR`,
  `ONTOLOGY_CLIENTS_DIR`, `ENABLE_ONTOLOGY_RAG`, `ONTOLOGY_DB_TEMPLATE`,
  `ONTOLOGY_PGVECTOR_SCHEMA_TEMPLATE`, `ONTOLOGY_CACHE_PREFIX`, `ONTOLOGY_CACHE_TTL`,
  `ONTOLOGY_MAX_TRAVERSAL_DEPTH`, `ONTOLOGY_AQL_MODEL`, `ONTOLOGY_REVIEW_DIR`.

### Module 2: ExtractDataSource ABC

- **Path**: `parrot/loaders/extractors/base.py`
- **Responsibility**: Abstract base class for structured record extraction. Defines
  `ExtractedRecord`, `ExtractionResult`, and the `ExtractDataSource` contract
  (`extract()`, `list_fields()`, `validate()`).
- **Depends on**: None
- **Details**: Generic, reusable beyond ontology. All implementations must be async-first.

### Module 3: Data Source Implementations

- **Path**: `parrot/loaders/extractors/{csv_source,json_source,records_source,sql_source,api_source}.py`
- **Responsibility**: Concrete ExtractDataSource implementations.
- **Depends on**: Module 2
- **Details**:
  - `CSVDataSource` — csv.DictReader, async via `asyncio.to_thread()`
  - `JSONDataSource` — supports nested `records_path` navigation
  - `RecordsDataSource` — in-memory `list[dict]` wrapper (for testing)
  - `SQLDataSource` — asyncpg-based, read-only validated
  - `APIDataSource` (ABC) — paginated REST extraction with auth support

### Module 4: DataSourceFactory

- **Path**: `parrot/loaders/extractors/factory.py`
- **Responsibility**: Resolve source names to ExtractDataSource implementations.
- **Depends on**: Modules 2, 3
- **Details**: Registry of built-in types + custom source registration.

### Module 5: Ontology Pydantic Schema

- **Path**: `parrot/knowledge/ontology/schema.py`
- **Responsibility**: All Pydantic v2 models for YAML validation — `PropertyDef`,
  `EntityDef`, `RelationDef`, `TraversalPattern`, `OntologyDefinition`, `MergedOntology`,
  `TenantContext`, `DiscoveryRule`, `DiscoveryConfig`.
- **Depends on**: None
- **Details**: Strict validation with `extra="forbid"`. `MergedOntology.build_schema_prompt()`
  generates natural language description for LLM.

### Module 6: YAML Parser

- **Path**: `parrot/knowledge/ontology/parser.py`
- **Responsibility**: Load YAML files and validate against Pydantic schema. Default ontology
  files loaded via `importlib.resources` or `Path(__file__).parent / "defaults"`.
- **Depends on**: Module 5
- **Details**: `OntologyParser.load(path) -> OntologyDefinition`.

### Module 7: YAML Merger

- **Path**: `parrot/knowledge/ontology/merger.py`
- **Responsibility**: Merge multiple ontology layers (base + domain + client) into
  `MergedOntology`. Enforces merge rules: entities concatenate properties (with extend),
  relations concatenate discovery rules, traversal patterns concatenate intents / override templates.
- **Depends on**: Modules 5, 6
- **Details**: Integrity validation — all relation endpoints reference existing entities,
  all vectorize fields reference existing properties.

### Module 8: Graph Store

- **Path**: `parrot/knowledge/ontology/graph_store.py`
- **Responsibility**: ArangoDB wrapper for ontology operations — tenant initialization,
  AQL traversals, node upsert, edge creation.
- **Depends on**: Module 5, existing `parrot/stores/arango.py`
- **Details**: Uses `python-arango-async`. Tenant-isolated (each tenant = separate DB).

### Module 9: AQL Validator

- **Path**: `parrot/knowledge/ontology/validators.py`
- **Responsibility**: Validate LLM-generated AQL for safety — no mutations, depth limit,
  no system collections, no JS execution.
- **Depends on**: Module 8
- **Details**: Uses AQL `explain()` for query plan analysis when available.

### Module 10: Relation Discovery Engine

- **Path**: `parrot/knowledge/ontology/discovery.py`
- **Responsibility**: Automatic edge creation from data sources. Strategies: exact field match,
  fuzzy match (rapidfuzz), AI-assisted (batch LLM resolution), composite (multi-field weighted).
- **Depends on**: Modules 5, 8
- **Details**: Ambiguous pairs written to `{ONTOLOGY_REVIEW_DIR}/{tenant}_review_queue.json`.

### Module 11: Intent Resolver

- **Path**: `parrot/knowledge/ontology/intent.py`
- **Responsibility**: Dual-path intent resolution. Fast path: keyword scan against
  `trigger_intents`. LLM path: structured output using `ONTOLOGY_AQL_MODEL`.
- **Depends on**: Modules 5, 7, 9
- **Details**: `ResolvedIntent` model with action, pattern, AQL, params, post_action.

### Module 12: OntologyRAGMixin

- **Path**: `parrot/knowledge/ontology/mixin.py`
- **Responsibility**: Agent mixin that orchestrates the full ontology pipeline — tenant
  resolution, intent detection, graph traversal, post-action routing, caching.
- **Depends on**: Modules 8, 10, 11, 14, 16
- **Details**: `process(query, user_context, tenant_id) -> EnrichedContext`. Cache key:
  `{prefix}:{tenant}:{user}:{pattern}`.

### Module 13: PromptBuilder Integration

- **Path**: `parrot/knowledge/ontology/mixin.py` (within `configure()`)
- **Responsibility**: Register ontology schema as PromptBuilder composable layer at
  `RenderPhase.CONFIGURE`. Static per-tenant.
- **Depends on**: Modules 5, 7, 12

### Module 14: Tenant Manager

- **Path**: `parrot/knowledge/ontology/tenant.py`
- **Responsibility**: Resolve and cache merged ontology per tenant. YAML chain resolution:
  base → domain → client. In-memory cache with explicit invalidation.
- **Depends on**: Modules 7, 8

### Module 15: Refresh Pipeline

- **Path**: `parrot/knowledge/ontology/refresh.py`
- **Responsibility**: CRON-triggered delta sync — extract, diff, upsert nodes, rediscover
  edges, sync PgVector embeddings, invalidate cache.
- **Depends on**: Modules 4, 8, 10, 14

### Module 16: Cache Helpers

- **Path**: `parrot/knowledge/ontology/cache.py`
- **Responsibility**: Redis cache key building, serialization, TTL management, pattern-based
  invalidation.
- **Depends on**: Module 12

### Module 17: Default Ontology Files

- **Path**: `parrot/knowledge/ontology/defaults/`
- **Responsibility**: Base ontology YAML (`base.ontology.yaml`) and example domain ontologies.
  Ship as package resources.
- **Depends on**: Module 5

### Module 18: Exceptions

- **Path**: `parrot/knowledge/ontology/exceptions.py`
- **Responsibility**: `OntologyMergeError`, `OntologyIntegrityError`, `AQLValidationError`,
  `UnknownDataSourceError`, `DataSourceValidationError`.
- **Depends on**: None

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_property_def_validation` | 5 | PropertyDef rejects unknown types |
| `test_entity_def_extend_flag` | 5 | EntityDef extend=True merges; extend=False on duplicate errors |
| `test_relation_def_alias` | 5 | RelationDef from/to field aliases work |
| `test_traversal_pattern_post_actions` | 5 | Valid/invalid post_action literals |
| `test_merged_ontology_schema_prompt` | 5 | build_schema_prompt() returns formatted string |
| `test_parser_loads_yaml` | 6 | Valid YAML → OntologyDefinition |
| `test_parser_rejects_invalid` | 6 | Invalid YAML raises ValidationError |
| `test_parser_loads_defaults` | 6 | Default base.ontology.yaml loads from package resources |
| `test_merger_entities_extend` | 7 | Properties concatenated, source overridden |
| `test_merger_entities_no_extend_error` | 7 | Duplicate entity without extend raises OntologyMergeError |
| `test_merger_immutable_key_field` | 7 | Changing key_field raises error |
| `test_merger_relations_concat_rules` | 7 | Discovery rules concatenated on same relation |
| `test_merger_relations_immutable_endpoints` | 7 | Changing from/to raises error |
| `test_merger_patterns_concat_intents` | 7 | Trigger intents merged, template overridden |
| `test_merger_integrity_validation` | 7 | Missing entity in relation raises OntologyIntegrityError |
| `test_merger_vectorize_fields_check` | 7 | Vectorize referencing unknown property raises error |
| `test_aql_validator_blocks_mutations` | 9 | INSERT/UPDATE/REMOVE/REPLACE rejected |
| `test_aql_validator_blocks_depth` | 9 | Traversal depth > MAX rejected |
| `test_aql_validator_blocks_system_collections` | 9 | _system, _graphs access rejected |
| `test_aql_validator_allows_read_only` | 9 | Valid FOR/RETURN AQL passes |
| `test_discovery_exact_match` | 10 | Exact field match produces correct edges |
| `test_discovery_fuzzy_match` | 10 | Fuzzy match with threshold partitions confirmed/review |
| `test_discovery_deduplication` | 10 | Same source→target from multiple rules deduped |
| `test_discovery_review_queue_json` | 10 | Ambiguous pairs written to JSON file |
| `test_intent_fast_path` | 11 | Keyword match returns predefined pattern |
| `test_intent_llm_path_known_pattern` | 11 | LLM selects existing pattern |
| `test_intent_llm_path_dynamic_aql` | 11 | LLM generates AQL, validated before return |
| `test_intent_fallback_vector_only` | 11 | No match returns vector_only |
| `test_tenant_manager_resolve` | 14 | Resolves merged ontology for tenant |
| `test_tenant_manager_cache` | 14 | Second resolve returns cached |
| `test_tenant_manager_invalidate` | 14 | Invalidation clears cache |
| `test_extract_csv` | 3 | CSVDataSource returns ExtractedRecords |
| `test_extract_json` | 3 | JSONDataSource with records_path |
| `test_extract_records` | 3 | RecordsDataSource wraps in-memory data |
| `test_extract_validate_fields` | 2 | validate() catches missing fields |
| `test_datasource_factory` | 4 | Factory resolves by type |
| `test_mixin_process_graph_query` | 12 | Full pipeline: resolve → traverse → enrich |
| `test_mixin_process_vector_only` | 12 | vector_only skips graph traversal |
| `test_mixin_cache_hit` | 12 | Cached result returned without traversal |
| `test_refresh_delta_sync` | 15 | Changed nodes upserted, removed soft-deleted |
| `test_refresh_rediscover_edges` | 15 | Only changed nodes trigger edge rediscovery |
| `test_refresh_invalidates_cache` | 15 | Cache busted after refresh |
| `test_config_variables_present` | 1 | All ONTOLOGY_* variables resolve correctly |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_yaml_to_graph` | Load YAML → merge → initialize tenant → upsert nodes → discover edges |
| `test_e2e_intent_to_context` | Query → intent → traversal → enriched context |
| `test_e2e_refresh_pipeline` | Extract → diff → upsert → rediscover → cache invalidation |

### How to Run

```bash
source .venv/bin/activate
pytest tests/knowledge/test_ontology_schema.py -v
pytest tests/knowledge/test_ontology_merger.py -v
pytest tests/knowledge/test_ontology_intent.py -v
pytest tests/loaders/test_extractors.py -v
pytest tests/knowledge/ -v  # all ontology tests
```

---

## 5. Acceptance Criteria

- [ ] `ExtractDataSource` ABC defined with `extract()`, `list_fields()`, `validate()` — CSV, JSON, Records, SQL, API implementations pass tests.
- [ ] `DataSourceFactory` resolves source names to implementations.
- [ ] All Pydantic models validate YAML strictly (`extra="forbid"`).
- [ ] `OntologyMerger` correctly merges base + domain + client layers with documented rules (concatenation, override, immutability).
- [ ] Merge integrity validation catches: missing entity references, invalid vectorize fields.
- [ ] `OntologyGraphStore` creates tenant-isolated databases, executes AQL, upserts nodes, creates edges.
- [ ] `validate_aql()` rejects mutations, excessive depth, system collections, JS execution.
- [ ] `RelationDiscovery` supports exact, fuzzy, AI-assisted, composite strategies.
- [ ] Ambiguous relation matches written to `{ONTOLOGY_REVIEW_DIR}/{tenant}_review_queue.json`.
- [ ] Fast-path intent resolution matches keywords in ~0ms.
- [ ] LLM-path intent resolution uses structured output with `ONTOLOGY_AQL_MODEL`.
- [ ] Dynamic AQL from LLM is validated before execution.
- [ ] `OntologyRAGMixin.process()` returns `EnrichedContext` with graph + vector + tool hint.
- [ ] Pipeline results cached in Redis with `ONTOLOGY_CACHE_TTL`.
- [ ] Ontology schema registered as PromptBuilder layer at `RenderPhase.CONFIGURE`.
- [ ] `TenantOntologyManager` resolves and caches merged ontology per tenant.
- [ ] `OntologyRefreshPipeline` performs delta sync: extract → diff → upsert → rediscover → sync vectors → invalidate cache.
- [ ] `base.ontology.yaml` ships as package resource and loads correctly.
- [ ] All ONTOLOGY_* config variables added to `parrot/conf.py` via navconfig.
- [ ] No changes to existing Loaders.
- [ ] `rapidfuzz` added as dependency.
- [ ] All unit and integration tests pass.

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- **Async-first**: All I/O through async/await. Use `asyncio.to_thread()` for blocking operations (CSV reading, file I/O).
- **Pydantic v2**: All schemas use `model_config = ConfigDict(extra="forbid")`. Use `Field(alias=...)` for YAML keys like `from`/`to`.
- **navconfig**: All config via `config.get()` in `parrot/conf.py`.
- **Mixin pattern**: Follow `MCPEnabledMixin`, `EpisodicMemoryMixin` for agent integration.
- **Logger convention**: `self.logger = logging.getLogger(f'Parrot.{self.__class__.__name__}')`.
- **No blocking I/O**: Never use `requests` or synchronous file reads in async methods.

### YAML Merge Rules

| Field | Rule | Rationale |
|---|---|---|
| Entity properties | Concatenated (no name collisions) | Additive — safe |
| Entity vectorize | Union | Additive — safe |
| Entity source | Overridden | Client controls data source |
| Entity key_field, collection | Immutable | Prevents structural breakage |
| Relation from/to | Immutable | Prevents structural breakage |
| Relation discovery.rules | Concatenated | Client adds matching rules |
| Pattern trigger_intents | Concatenated (deduped) | Client adds keywords |
| Pattern query_template | Overridden | Client customizes AQL |
| Pattern post_action | Overridden | Client changes behavior |

### Security

- **AQL validation is mandatory** for LLM-generated queries — no bypass path.
- **Multi-tenant isolation** via separate ArangoDB databases — no shared graphs.
- **No credentials in YAML** — data source credentials resolved via environment/secrets.
- **Read-only graph access at query time** — mutations only during CRON refresh.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `rapidfuzz` | latest | Fuzzy string matching for relation discovery |
| `python-arango-async` | existing | ArangoDB async client |
| `pyyaml` | existing | YAML parsing |
| `asyncpg` | existing | PgVector / SQL data source |

### Known Risks

- **ArangoDB availability**: Graph store requires ArangoDB. When unavailable, `OntologyRAGMixin` must gracefully degrade to `vector_only`.
- **LLM-generated AQL quality**: Dynamic AQL may be syntactically valid but semantically wrong. The validator catches safety issues but not logic errors.
- **YAML complexity**: Deeply layered ontologies (base + domain + client) can produce subtle merge issues. The integrity validator mitigates this.
- **`rapidfuzz` is a new dependency**: Lightweight (MIT, C++ backed), but adds to the dependency tree.

---

## 7. Open Questions

All questions resolved during brainstorm (see brainstorm section 11).

---

## 8. File Structure

```
parrot/
├── loaders/
│   ├── extractors/
│   │   ├── __init__.py
│   │   ├── base.py              # ExtractDataSource ABC, ExtractedRecord, ExtractionResult
│   │   ├── csv_source.py        # CSVDataSource
│   │   ├── json_source.py       # JSONDataSource
│   │   ├── records_source.py    # RecordsDataSource (in-memory)
│   │   ├── api_source.py        # APIDataSource ABC
│   │   ├── sql_source.py        # SQLDataSource
│   │   ├── factory.py           # DataSourceFactory
│   │   └── exceptions.py        # DataSourceValidationError, etc.
│   └── ...existing loaders...
│
├── knowledge/
│   └── ontology/
│       ├── __init__.py
│       ├── schema.py            # Pydantic models
│       ├── parser.py            # YAML loading + validation
│       ├── merger.py            # Multi-layer composition
│       ├── discovery.py         # Relation discovery engine
│       ├── graph_store.py       # ArangoDB operations
│       ├── intent.py            # Dual-path intent resolver
│       ├── mixin.py             # OntologyRAGMixin
│       ├── tenant.py            # TenantOntologyManager
│       ├── refresh.py           # CRON delta sync
│       ├── cache.py             # Redis cache helpers
│       ├── validators.py        # AQL security validation
│       ├── exceptions.py        # Custom exceptions
│       └── defaults/
│           ├── base.ontology.yaml
│           └── domains/
│               └── field_services.ontology.yaml
│
├── conf.py                      # + ONTOLOGY_* config variables
│
tests/
├── knowledge/
│   ├── test_ontology_schema.py
│   ├── test_ontology_parser.py
│   ├── test_ontology_merger.py
│   ├── test_ontology_graph_store.py
│   ├── test_ontology_validators.py
│   ├── test_ontology_discovery.py
│   ├── test_ontology_intent.py
│   ├── test_ontology_mixin.py
│   ├── test_ontology_tenant.py
│   └── test_ontology_refresh.py
└── loaders/
    └── test_extractors.py
```

---

## Worktree Strategy

- **Isolation**: `per-spec` — all tasks sequential in one worktree.
- **Rationale**: While some modules are independently testable (extractors, schema models),
  the integration between them is tight. Sequential development ensures schema models are
  stable before building consumers. The `parrot/conf.py` changes are minimal and low-risk.
- **Cross-feature dependencies**: None — ontology is a new package. Only shared file is
  `parrot/conf.py` (minor addition).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-19 | Claude | Initial draft from brainstorm (Option B — Layered Architecture with Mixin) |
