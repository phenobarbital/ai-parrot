# Ontological Graph RAG — SDD Brainstorm

- **Feature**: `ontological-graph-rag`
- **Date**: 2026-03-19
- **Status**: exploration
- **Author**: Jesus (Lead Developer)
- **Effort**: High
- **Worktree isolation**: per-spec (sequential tasks, heavy cross-module integration)

---

## 1. Problem Statement

### What problem are we solving?

Standard vector-based RAG fails when user queries require **structural reasoning** — questions
whose answers depend on relationships between entities rather than semantic similarity alone.

**Example**: An EPSON field employee asks *"What is my portal?"*. A pure vector search for
"portal" returns generic documentation about all portals. The correct answer requires:

1. Identifying the user (session context → employee record)
2. Traversing relationships: Employee → Project (EPSON) → Portal (`epson.navigator`)
3. Enriching with semantic search: documentation about how to access `epson.navigator`
4. Optionally executing tools: Workday API to get additional employee data

This is a **Graph-First RAG** pattern: structured traversal provides precision, vector search
provides richness, and tool execution provides live data.

### Who is affected?

- **End users**: Enterprise employees interacting with AI-Parrot chatbots
- **Developers**: Teams building domain-specific agents on AI-Parrot
- **Clients**: Organizations (EPSON, HISENSE, etc.) that need ontology-aware assistants

### Why now?

- Existing KB loaders already handle graph construction but lack a **productized ontology layer**
- Client deployments (EPSON, HISENSE) need this capability for accurate employee-facing bots
- The `python-arango-async` integration is already in the codebase

---

## 2. Constraints

| Constraint | Detail |
|-----------|--------|
| Async-first | All I/O must be async (`asyncpg`, `python-arango-async`, `aiohttp`) |
| Pydantic v2 | All schemas, configs, YAML validation use Pydantic v2 models |
| Multi-tenant | Real DB-level isolation per tenant (no shared graphs) |
| Pattern consistency | Must follow `AbstractTool`/`AbstractToolkit` patterns |
| navconfig | All config variables go through `navconfig` + `parrot/conf.py` |
| No new heavy deps | Prefer existing libraries; minimize new dependencies |
| Composable YAML | Ontology definitions must support base + domain + client layering |
| Security | LLM-generated AQL must be validated (read-only, no mutations) |

---

## 3. Options Explored

### Option A: Monolithic OntologyService

Single class that handles YAML parsing, graph operations, intent detection, and query routing.

**Pros**: Simple to implement initially, fewer abstractions.
**Cons**: Violates SRP, hard to test individual components, doesn't scale to multiple tenants,
tight coupling between parsing and execution.
**Effort**: Medium

### Option B: Layered Architecture with Middleware (Recommended)

Separate concerns into distinct modules: schema parsing, graph store, relation discovery,
intent resolution, and a middleware that orchestrates the pipeline. The middleware integrates
with the existing agent pipeline as an interceptor layer.

**Pros**: Each module is independently testable, follows existing AI-Parrot patterns (mixins,
middleware), supports composable YAMLs naturally, clean separation of build-time (ingestion)
vs runtime (query) concerns.
**Cons**: More initial boilerplate, more files to coordinate.
**Effort**: High

### Option C: Tool-Based Approach

Implement the ontology as a specialized `AbstractToolkit` that the agent invokes like any
other tool. The LLM decides when to use `ontology_search` vs `vector_search`.

**Pros**: Minimal changes to agent pipeline, leverages existing tool infrastructure.
**Cons**: Relies entirely on LLM to decide when to use graph vs vector (unreliable), no
middleware-level interception, harder to implement the fast-path optimization, doesn't
naturally support the graph→vector→tool chain.
**Effort**: Medium

### Recommendation: Option B — Layered Architecture with Middleware

The middleware approach gives us the fast-path keyword detection (zero LLM overhead for
obvious queries) while still allowing LLM-driven intent resolution for ambiguous cases.
The layered separation means we can test the YAML parser, graph store, and intent resolver
independently. The middleware pattern already exists in AI-Parrot (e.g., `MCPEnabledMixin`),
so it's a natural fit.

---

## 4. Feature Description (Based on Option B)

### 4.1 Configuration — `parrot/conf.py` Variables

All ontology-related paths and settings are configured via `navconfig` environment variables,
following the established pattern in `parrot/conf.py`.

```python
# ── parrot/conf.py additions ──

# Ontology Configuration Root
# This is the base directory where all ontology YAML files are stored.
# Structure expected:
#   {ONTOLOGY_DIR}/
#   ├── base.ontology.yaml          (ships with ai-parrot)
#   ├── domains/
#   │   ├── field_services.ontology.yaml
#   │   ├── healthcare.ontology.yaml
#   │   └── ...
#   └── clients/
#       ├── epson.ontology.yaml
#       ├── hisense.ontology.yaml
#       └── ...
ONTOLOGY_DIR = config.get(
    'ONTOLOGY_DIR',
    fallback=BASE_DIR.joinpath('ontologies')
)
if isinstance(ONTOLOGY_DIR, str):
    ONTOLOGY_DIR = Path(ONTOLOGY_DIR).resolve()
if not ONTOLOGY_DIR.exists():
    ONTOLOGY_DIR.mkdir(parents=True, exist_ok=True)

# Base ontology file — the foundational layer that all tenants inherit from.
# This file defines universal entities (Employee, Department) and relations
# (reports_to, belongs_to) that are common across all domains.
ONTOLOGY_BASE_FILE = config.get(
    'ONTOLOGY_BASE_FILE',
    fallback='base.ontology.yaml'
)

# Domain ontologies directory — industry-specific extensions.
# Each file adds entities and relations relevant to a specific domain
# (e.g., field_services adds Project, Portal, assigned_to).
ONTOLOGY_DOMAINS_DIR = config.get(
    'ONTOLOGY_DOMAINS_DIR',
    fallback='domains'
)

# Client ontologies directory — client-specific overrides and additions.
# Each file extends the domain ontology with client-specific entities,
# properties, and traversal patterns.
ONTOLOGY_CLIENTS_DIR = config.get(
    'ONTOLOGY_CLIENTS_DIR',
    fallback='clients'
)

# Enable/disable ontology-based RAG globally.
# When False, the OntologyRAGMiddleware is a no-op passthrough.
ENABLE_ONTOLOGY_RAG = config.getboolean(
    'ENABLE_ONTOLOGY_RAG',
    fallback=False
)

# ArangoDB naming convention for tenant databases.
# The {tenant} placeholder is replaced with the tenant ID at runtime.
# Example: "epson_ontology" for tenant "epson"
ONTOLOGY_DB_TEMPLATE = config.get(
    'ONTOLOGY_DB_TEMPLATE',
    fallback='{tenant}_ontology'
)

# PgVector schema naming convention for tenant isolation.
# The {tenant} placeholder is replaced with the tenant ID at runtime.
ONTOLOGY_PGVECTOR_SCHEMA_TEMPLATE = config.get(
    'ONTOLOGY_PGVECTOR_SCHEMA_TEMPLATE',
    fallback='{tenant}'
)

# Redis key prefix for ontology traversal cache.
ONTOLOGY_CACHE_PREFIX = config.get(
    'ONTOLOGY_CACHE_PREFIX',
    fallback='parrot:ontology'
)

# Default TTL for cached full-pipeline results (in seconds).
# 86400 = 24 hours, aligned with daily CRON refresh.
ONTOLOGY_CACHE_TTL = config.getint(
    'ONTOLOGY_CACHE_TTL',
    fallback=86400
)

# Maximum depth for dynamic AQL traversals generated by the LLM.
# This is a security guardrail to prevent unbounded graph walks.
ONTOLOGY_MAX_TRAVERSAL_DEPTH = config.getint(
    'ONTOLOGY_MAX_TRAVERSAL_DEPTH',
    fallback=4
)

# LLM model for dynamic AQL generation and intent detection (LLM path).
# A smaller/faster model is sufficient for structured classification tasks.
# Defaults to gemini-2.5-flash. Falls back to agent's primary LLM if not set.
ONTOLOGY_AQL_MODEL = config.get(
    'ONTOLOGY_AQL_MODEL',
    fallback='gemini-2.5-flash'
)

# Directory for review queue JSON files (ambiguous relation matches).
# Each tenant gets a {tenant}_review_queue.json file here.
ONTOLOGY_REVIEW_DIR = config.get(
    'ONTOLOGY_REVIEW_DIR',
    fallback=None  # Defaults to {ONTOLOGY_DIR}/review/ at runtime
)
```

**Corresponding `.env` / `parrot.ini` entries:**

```ini
# ── Ontology Configuration ──
ONTOLOGY_DIR=/app/config/ontologies
ONTOLOGY_BASE_FILE=base.ontology.yaml
ONTOLOGY_DOMAINS_DIR=domains
ONTOLOGY_CLIENTS_DIR=clients
ENABLE_ONTOLOGY_RAG=true
ONTOLOGY_DB_TEMPLATE={tenant}_ontology
ONTOLOGY_PGVECTOR_SCHEMA_TEMPLATE={tenant}
ONTOLOGY_CACHE_PREFIX=parrot:ontology
ONTOLOGY_CACHE_TTL=86400
ONTOLOGY_MAX_TRAVERSAL_DEPTH=4
ONTOLOGY_AQL_MODEL=gemini-2.5-flash
# ONTOLOGY_REVIEW_DIR=  # defaults to {ONTOLOGY_DIR}/review/
```

### 4.2 Composable YAML System

The ontology definition system uses a three-layer composition model. Each layer can
introduce new entities, extend existing ones, add relations, and define traversal patterns.

#### Layer Resolution Order

```
base.ontology.yaml
    └── domains/{domain}.ontology.yaml
            └── clients/{tenant}.ontology.yaml
```

The `TenantOntologyManager` resolves the YAML chain for a given tenant:

```python
# Pseudo-code — resolution logic
class TenantOntologyManager:
    """
    Resolves and caches the merged ontology for each tenant.
    
    The resolution process:
    1. Start with the base ontology (ONTOLOGY_BASE_FILE)
    2. If the tenant config specifies a domain, layer the domain ontology
    3. Layer the client-specific ontology on top
    4. Validate the merged result for integrity (all relation endpoints exist,
       all vectorize fields reference valid properties, etc.)
    5. Cache the merged ontology in memory (invalidated on CRON refresh)
    """
    
    def __init__(self):
        # In-memory cache of merged ontologies per tenant.
        # Key: tenant_id, Value: MergedOntology
        # This avoids re-parsing and re-merging YAMLs on every request.
        self._cache: dict[str, MergedOntology] = {}
    
    def resolve(self, tenant_id: str, domain: str = None) -> MergedOntology:
        if tenant_id in self._cache:
            return self._cache[tenant_id]
        
        # Build the chain of YAML files to merge
        chain = [ONTOLOGY_DIR / ONTOLOGY_BASE_FILE]
        
        if domain:
            domain_path = ONTOLOGY_DIR / ONTOLOGY_DOMAINS_DIR / f"{domain}.ontology.yaml"
            if domain_path.exists():
                chain.append(domain_path)
        
        client_path = ONTOLOGY_DIR / ONTOLOGY_CLIENTS_DIR / f"{tenant_id}.ontology.yaml"
        if client_path.exists():
            chain.append(client_path)
        
        # Merge all layers in order
        merged = OntologyMerger().merge(chain)
        self._cache[tenant_id] = merged
        return merged
    
    def invalidate(self, tenant_id: str = None):
        """Called by CRON refresh pipeline after data update."""
        if tenant_id:
            self._cache.pop(tenant_id, None)
        else:
            self._cache.clear()
```

#### YAML Schema — Pydantic Models

The YAML is validated against strict Pydantic v2 models. This catches errors at
parse time rather than at query time.

```python
# Pseudo-code — Pydantic models for YAML validation

class PropertyDef(BaseModel):
    """Single property definition for an entity."""
    type: Literal["string", "int", "float", "boolean", "date", "list", "dict"]
    required: bool = False
    unique: bool = False
    default: Any = None
    enum: list[str] | None = None
    description: str | None = None


class EntityDef(BaseModel):
    """
    Definition of a vertex collection (entity) in the ontology.
    
    When `extend` is True, this entity definition is merged with a parent
    layer's definition of the same entity. Properties and vectorize fields
    are concatenated; source is overridden.
    """
    collection: str | None = None          # ArangoDB collection name
    source: str | None = None              # Data source identifier (workday, jira, csv, etc.)
    key_field: str | None = None           # Primary key field name
    properties: list[dict[str, PropertyDef]] = []
    vectorize: list[str] = []              # Fields to embed in PgVector
    extend: bool = False                   # If True, merge with parent layer
    
    model_config = ConfigDict(extra="forbid")


class DiscoveryRule(BaseModel):
    """
    Rule for discovering relationships between entities in source data.
    
    The discovery engine uses these rules during ingestion to automatically
    create edges between nodes. Multiple rules per relation support fallback:
    if exact match fails, fuzzy match is attempted, etc.
    """
    source_field: str                      # e.g., "Employee.project_code"
    target_field: str                      # e.g., "Project.project_id"
    match_type: Literal["exact", "fuzzy", "ai_assisted", "composite"] = "exact"
    threshold: float = 0.85                # For fuzzy matching
    description: str | None = None


class DiscoveryConfig(BaseModel):
    """Configuration for how relations are discovered in source data."""
    strategy: Literal["field_match", "ai_assisted", "composite"] = "field_match"
    rules: list[DiscoveryRule] = []


class RelationDef(BaseModel):
    """
    Definition of an edge collection (relation) in the ontology.
    
    Relations connect two entities. The discovery config tells the ingestion
    pipeline how to find these relationships in raw data.
    """
    from_entity: str = Field(alias="from")   # Source entity name
    to_entity: str = Field(alias="to")       # Target entity name
    edge_collection: str                      # ArangoDB edge collection name
    properties: list[dict[str, PropertyDef]] = []
    discovery: DiscoveryConfig = DiscoveryConfig()
    
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class TraversalPattern(BaseModel):
    """
    Predefined graph traversal pattern for a known query type.
    
    Traversal patterns are the "fast path" — when the user's query matches
    a trigger_intent keyword, the system skips the LLM intent detection step
    and executes the AQL template directly.
    
    The query_template uses ArangoDB bind variables:
    - @param: regular parameters (user_id, etc.)
    - @@collection: collection name bind variables (resolved per-tenant)
    
    Post-actions define what happens after the graph traversal:
    - "vector_search": use a field from the result as PgVector query
    - "tool_call": pass graph context to agent for tool execution
    - "none": return graph result directly to LLM for synthesis
    """
    description: str
    trigger_intents: list[str] = []        # Keywords for fast-path matching
    query_template: str                     # AQL with bind variables
    post_action: Literal["vector_search", "tool_call", "none"] = "none"
    post_query: str | None = None          # Field name to use as vector query
    
    model_config = ConfigDict(extra="forbid")


class OntologyDefinition(BaseModel):
    """
    Root model for a single ontology YAML layer.
    
    Each YAML file is parsed into this model. Multiple OntologyDefinition
    instances are then merged by OntologyMerger to produce a MergedOntology.
    """
    name: str
    version: str = "1.0"
    extends: str | None = None             # Parent ontology name
    description: str | None = None
    entities: dict[str, EntityDef] = {}
    relations: dict[str, RelationDef] = {}
    traversal_patterns: dict[str, TraversalPattern] = {}
    
    model_config = ConfigDict(extra="forbid")


class MergedOntology(BaseModel):
    """
    The fully resolved ontology after merging all YAML layers.
    
    This is the runtime representation used by the intent resolver,
    graph store, and middleware. It contains all entities, relations,
    and traversal patterns from all layers, fully validated for integrity.
    """
    name: str
    version: str
    entities: dict[str, EntityDef]
    relations: dict[str, RelationDef]
    traversal_patterns: dict[str, TraversalPattern]
    # Metadata about the merge
    layers: list[str]                      # List of YAML files that were merged
    merge_timestamp: datetime
    
    def get_entity_collections(self) -> list[str]:
        """Return all vertex collection names."""
        return [e.collection for e in self.entities.values() if e.collection]
    
    def get_edge_collections(self) -> list[str]:
        """Return all edge collection names."""
        return [r.edge_collection for r in self.relations.values()]
    
    def get_vectorizable_fields(self, entity_name: str) -> list[str]:
        """Return fields that should be embedded in PgVector for an entity."""
        entity = self.entities.get(entity_name)
        return entity.vectorize if entity else []
    
    def build_schema_prompt(self) -> str:
        """
        Generate a natural language description of the ontology for the LLM.
        
        This is injected into the system prompt so the LLM understands what
        entities and relations are available for graph queries.
        """
        lines = ["Available ontology:"]
        lines.append("\nEntities:")
        for name, entity in self.entities.items():
            props = [list(p.keys())[0] for p in entity.properties]
            lines.append(f"  - {name}: {', '.join(props)}")
        
        lines.append("\nRelations:")
        for name, rel in self.relations.items():
            lines.append(f"  - {rel.from_entity} --[{name}]--> {rel.to_entity}")
        
        lines.append("\nKnown traversal patterns:")
        for name, pattern in self.traversal_patterns.items():
            lines.append(f"  - {name}: {pattern.description}")
            lines.append(f"    triggers: {', '.join(pattern.trigger_intents)}")
        
        return "\n".join(lines)
```

#### Merge Algorithm — Detailed Rules

The merge algorithm processes YAML layers sequentially, from base to client-specific:

```python
# Pseudo-code — OntologyMerger

class OntologyMerger:
    """
    Merges multiple ontology YAML layers into a single MergedOntology.
    
    Design decisions:
    
    1. ENTITIES with extend=True:
       - properties: CONCATENATED (new fields added, no duplicates by name)
       - vectorize: CONCATENATED (union of all layers)
       - source: OVERRIDDEN (last layer wins — client can override data source)
       - key_field: IMMUTABLE (cannot change after base definition)
       - collection: IMMUTABLE (cannot change after base definition)
    
    2. ENTITIES without extend=True:
       - If entity already exists in a parent layer → ERROR
       - If entity is new → ADDED to the merged result
    
    3. RELATIONS:
       - New relations → ADDED
       - Existing relation with same name → discovery.rules CONCATENATED
       - from/to entities → IMMUTABLE (cannot change the relation endpoints)
    
    4. TRAVERSAL PATTERNS:
       - New patterns → ADDED
       - Existing pattern with same name:
         - trigger_intents: CONCATENATED (client can add more keywords)
         - query_template: OVERRIDDEN (client can customize the AQL)
         - post_action: OVERRIDDEN (client can change post-processing)
    
    Rationale for these rules:
    - Concatenation is safe for additive fields (properties, intents)
    - Override is appropriate for behavioral fields (source, query, post_action)
    - Immutability prevents accidental structural breakage (key_field, collection, endpoints)
    """
    
    def merge(self, yaml_paths: list[Path]) -> MergedOntology:
        result_entities: dict[str, EntityDef] = {}
        result_relations: dict[str, RelationDef] = {}
        result_patterns: dict[str, TraversalPattern] = {}
        layers: list[str] = []
        
        for path in yaml_paths:
            layer = self._load_and_validate(path)
            layers.append(str(path))
            
            # ── Merge Entities ──
            for name, entity in layer.entities.items():
                if name in result_entities:
                    if not entity.extend:
                        raise OntologyMergeError(
                            f"Entity '{name}' exists in parent layer. "
                            f"Set 'extend: true' in {path} to modify it."
                        )
                    self._merge_entity(result_entities[name], entity)
                else:
                    result_entities[name] = entity.model_copy(deep=True)
            
            # ── Merge Relations ──
            for name, relation in layer.relations.items():
                if name in result_relations:
                    # Validate endpoints haven't changed
                    existing = result_relations[name]
                    if (relation.from_entity != existing.from_entity or
                        relation.to_entity != existing.to_entity):
                        raise OntologyMergeError(
                            f"Relation '{name}' endpoints cannot change. "
                            f"Expected {existing.from_entity} → {existing.to_entity}, "
                            f"got {relation.from_entity} → {relation.to_entity} in {path}."
                        )
                    # Concatenate discovery rules
                    existing.discovery.rules.extend(relation.discovery.rules)
                else:
                    # Validate that referenced entities exist
                    self._validate_relation_endpoints(relation, result_entities, path)
                    result_relations[name] = relation.model_copy(deep=True)
            
            # ── Merge Traversal Patterns ──
            for name, pattern in layer.traversal_patterns.items():
                if name in result_patterns:
                    existing = result_patterns[name]
                    # Concatenate trigger intents (dedup)
                    existing.trigger_intents = list(set(
                        existing.trigger_intents + pattern.trigger_intents
                    ))
                    # Override template and post-action
                    if pattern.query_template:
                        existing.query_template = pattern.query_template
                    if pattern.post_action:
                        existing.post_action = pattern.post_action
                    if pattern.post_query:
                        existing.post_query = pattern.post_query
                else:
                    result_patterns[name] = pattern.model_copy(deep=True)
        
        merged = MergedOntology(
            name=layers[-1],  # last layer name
            version="1.0",
            entities=result_entities,
            relations=result_relations,
            traversal_patterns=result_patterns,
            layers=layers,
            merge_timestamp=datetime.utcnow()
        )
        
        # Final integrity check
        self._validate_integrity(merged)
        return merged
    
    def _merge_entity(self, existing: EntityDef, extension: EntityDef):
        """
        Merge an entity extension into the existing entity definition.
        
        Properties are concatenated (no name collisions allowed).
        Vectorize fields are unioned.
        Source is overridden if provided.
        key_field and collection are immutable.
        """
        # Immutability checks
        if extension.key_field and extension.key_field != existing.key_field:
            raise OntologyMergeError(
                f"Cannot change key_field of '{existing.collection}'"
            )
        if extension.collection and extension.collection != existing.collection:
            raise OntologyMergeError(
                f"Cannot change collection name of '{existing.collection}'"
            )
        
        # Concatenate properties (check for name collisions)
        existing_prop_names = {
            list(p.keys())[0] for p in existing.properties
        }
        for prop in extension.properties:
            prop_name = list(prop.keys())[0]
            if prop_name in existing_prop_names:
                raise OntologyMergeError(
                    f"Property '{prop_name}' already exists in entity. "
                    f"Cannot override properties via extend."
                )
            existing.properties.append(prop)
        
        # Union vectorize fields
        existing.vectorize = list(set(existing.vectorize + extension.vectorize))
        
        # Override source if provided
        if extension.source:
            existing.source = extension.source
    
    def _validate_integrity(self, merged: MergedOntology):
        """
        Cross-validate the fully merged ontology:
        1. All relation endpoints reference existing entities
        2. All vectorize fields reference existing properties
        3. All traversal patterns reference valid collections
        4. No circular extends references (already prevented by sequential merge)
        """
        entity_names = set(merged.entities.keys())
        
        for name, rel in merged.relations.items():
            if rel.from_entity not in entity_names:
                raise OntologyIntegrityError(
                    f"Relation '{name}' references unknown entity '{rel.from_entity}'"
                )
            if rel.to_entity not in entity_names:
                raise OntologyIntegrityError(
                    f"Relation '{name}' references unknown entity '{rel.to_entity}'"
                )
        
        for name, entity in merged.entities.items():
            prop_names = {list(p.keys())[0] for p in entity.properties}
            for vec_field in entity.vectorize:
                if vec_field not in prop_names:
                    raise OntologyIntegrityError(
                        f"Entity '{name}' vectorize field '{vec_field}' "
                        f"not found in properties"
                    )
```

### 4.3 Multi-Tenant Graph Store

Each tenant gets its own ArangoDB database and PgVector schema. The `OntologyGraphStore`
wraps `python-arango-async` with tenant-aware operations.

```python
# Pseudo-code — OntologyGraphStore

class TenantContext(BaseModel):
    """
    Runtime context for a specific tenant.
    
    Created by TenantOntologyManager and passed through the entire pipeline.
    Every graph and vector operation is scoped to this context.
    """
    tenant_id: str
    arango_db: str          # e.g., "epson_ontology"
    pgvector_schema: str    # e.g., "epson"
    ontology: MergedOntology


class OntologyGraphStore:
    """
    ArangoDB wrapper for ontology graph operations.
    
    Responsibilities:
    - Create/manage vertex and edge collections per tenant
    - Execute AQL traversals with bind variables
    - Validate dynamic AQL (read-only, depth-limited)
    - CRUD operations for nodes and edges during ingestion
    
    Uses python-arango-async for all operations.
    The store does NOT own the ArangoDB connection — it receives a client
    from the connection pool, scoped to the tenant's database.
    """
    
    async def initialize_tenant(self, ctx: TenantContext):
        """
        Create the ArangoDB database and all collections for a tenant.
        
        Called once during tenant onboarding or when a new ontology YAML
        is added. Idempotent — safe to call multiple times.
        
        Steps:
        1. Create database if not exists (named per ONTOLOGY_DB_TEMPLATE)
        2. Create vertex collections for each entity
        3. Create edge collections for each relation
        4. Create the named graph linking vertex/edge collections
        5. Create indexes for key_field on each vertex collection
        """
        pass
    
    async def execute_traversal(
        self,
        ctx: TenantContext,
        aql: str,
        bind_vars: dict[str, Any],
        collection_binds: dict[str, str] | None = None
    ) -> list[dict]:
        """
        Execute an AQL traversal query against the tenant's graph.
        
        The collection_binds parameter resolves @@collection bind variables.
        This is how the same traversal pattern works across tenants:
        the pattern uses @@employees, @@assigned_to, etc., and the runtime
        resolves these to the actual collection names in the tenant's DB.
        
        Security: if the AQL was generated by the LLM (dynamic), it must
        first pass through validate_aql() which ensures:
        - No write operations (INSERT, UPDATE, REMOVE, REPLACE)
        - Traversal depth <= ONTOLOGY_MAX_TRAVERSAL_DEPTH
        - No system collection access
        - No JavaScript execution (LET ... = (FOR ...))
        """
        pass
    
    async def validate_aql(self, aql: str) -> str:
        """
        Validate LLM-generated AQL for safety.
        
        Checks:
        1. No mutation keywords: INSERT, UPDATE, REMOVE, REPLACE, UPSERT
        2. Traversal depth: max hops <= ONTOLOGY_MAX_TRAVERSAL_DEPTH
        3. No system collections: _system, _graphs, _modules
        4. No inline JavaScript: APPLY, CALL, V8
        5. Query plan analysis: use AQL explain() to verify read-only execution plan
        
        Returns the validated AQL (unchanged) or raises AQLValidationError.
        """
        pass
    
    async def upsert_nodes(
        self,
        ctx: TenantContext,
        collection: str,
        nodes: list[dict],
        key_field: str
    ) -> UpsertResult:
        """
        Upsert nodes into a vertex collection.
        
        Used by the refresh pipeline during delta sync.
        Uses ArangoDB's native UPSERT operation for atomicity.
        Returns counts of inserted, updated, and unchanged nodes.
        """
        pass
    
    async def create_edges(
        self,
        ctx: TenantContext,
        edge_collection: str,
        edges: list[dict]
    ) -> int:
        """
        Create edges in an edge collection.
        
        Each edge dict must contain _from and _to (full document IDs).
        Duplicates are skipped (upsert on _from + _to composite key).
        """
        pass
```

### 4.4 Relation Discovery Engine

The discovery engine runs during ingestion (build time, not query time) to automatically
create edges between nodes based on the rules defined in the ontology YAML.

```python
# Pseudo-code — RelationDiscovery

class RelationDiscovery:
    """
    Discovers and creates relationships between entities in the graph.
    
    This is the component that "productizes" graph construction — instead of
    manually writing code to create edges, the discovery rules in the YAML
    tell this engine how to find relationships in the raw data.
    
    Strategies:
    
    1. field_match (exact):
       Direct equality join between source and target fields.
       Example: Employee.project_code == Project.project_id
       Fast, deterministic, no ambiguity.
    
    2. field_match (fuzzy):
       Normalized string matching with configurable threshold.
       Uses: lowercase + strip + Levenshtein ratio OR contains check.
       Example: Employee.job_title ≈ Role.name (threshold: 0.85)
       Good for human-entered data with inconsistencies.
    
    3. ai_assisted:
       Batch LLM resolution for pairs that fuzzy matching can't decide.
       Collects ambiguous pairs (below fuzzy threshold but above a minimum),
       sends them to the LLM in batches, LLM returns confidence scores.
       Pairs above confidence threshold become edges; below go to review queue.
       NOT real-time — only during ingestion pipeline.
    
    4. composite:
       Combines multiple fields to determine a relationship.
       Example: Employee's department + location + title → Team assignment
       Uses weighted scoring across multiple field matches.
    """
    
    async def discover(
        self,
        ctx: TenantContext,
        relation_def: RelationDef,
        source_data: list[dict],
        target_data: list[dict]
    ) -> DiscoveryResult:
        """
        Discover edges between source and target entities.
        
        Process:
        1. For each discovery rule in the relation definition:
           a. Apply the matching strategy (exact, fuzzy, ai_assisted, composite)
           b. Collect matched pairs with confidence scores
        2. Merge results from all rules (union, keeping highest confidence)
        3. Deduplicate (same source→target pair from different rules)
        4. Partition: confirmed (>= threshold) vs review_queue (< threshold)
        
        Returns:
            DiscoveryResult with confirmed edges and review queue entries
        """
        confirmed_edges = []
        review_queue = []
        
        for rule in relation_def.discovery.rules:
            if rule.match_type == "exact":
                # Exact field match — deterministic, no ambiguity
                # Build a lookup dict on target_field for O(n) matching
                matches = self._exact_match(source_data, target_data, rule)
                confirmed_edges.extend(matches)
                
            elif rule.match_type == "fuzzy":
                # Fuzzy matching with threshold
                # For each source record, find best match in target data
                # Uses rapidfuzz for efficient batch computation
                matches, ambiguous = self._fuzzy_match(
                    source_data, target_data, rule, 
                    threshold=rule.threshold
                )
                confirmed_edges.extend(matches)
                review_queue.extend(ambiguous)
                
            elif rule.match_type == "ai_assisted":
                # Collect ambiguous pairs and resolve via LLM
                # This is expensive, so we batch and only use for truly
                # ambiguous cases that fuzzy matching can't resolve
                candidates = self._get_candidates(source_data, target_data, rule)
                resolved = await self._llm_resolve_batch(candidates, relation_def)
                for result in resolved:
                    if result.confidence >= rule.threshold:
                        confirmed_edges.append(result.edge)
                    else:
                        review_queue.append(result)
                        
            elif rule.match_type == "composite":
                # Multi-field weighted scoring
                matches, ambiguous = self._composite_match(
                    source_data, target_data, rule
                )
                confirmed_edges.extend(matches)
                review_queue.extend(ambiguous)
        
        # Deduplicate edges (same from→to pair)
        confirmed_edges = self._deduplicate(confirmed_edges)
        
        return DiscoveryResult(
            confirmed=confirmed_edges,
            review_queue=review_queue,
            stats=DiscoveryStats(
                total_source=len(source_data),
                total_target=len(target_data),
                edges_created=len(confirmed_edges),
                needs_review=len(review_queue)
            )
        )
    
    async def _llm_resolve_batch(
        self,
        candidates: list[tuple[dict, dict]],
        relation_def: RelationDef,
        batch_size: int = 50
    ) -> list[LLMResolution]:
        """
        Send ambiguous pairs to the LLM for resolution.
        
        The LLM receives:
        - The relation description (context about what we're matching)
        - Batch of (source_value, target_value) pairs
        - Request to return match confidence (0-1) for each pair
        
        Uses structured output (Pydantic model) for reliable parsing.
        Processes in batches to manage token usage.
        
        Example prompt:
        "Given these pairs from an enterprise workforce context,
         determine if each pair refers to the same role/concept.
         Source field: Employee.job_title
         Target field: Role.name
         
         Pairs:
         1. ('Field Technician', 'Field Technical Specialist')
         2. ('Sr. Developer', 'Senior Software Engineer')
         ...
         
         Return confidence 0-1 for each."
        """
        pass
```

### 4.5 Intent Resolution — Dual-Path

The intent resolver determines whether a user query requires graph traversal and, if so,
which traversal pattern to use. It implements two paths:

```python
# Pseudo-code — OntologyIntentResolver

class ResolvedIntent(BaseModel):
    """Result of intent resolution."""
    action: Literal["graph_query", "vector_only"]
    pattern: str | None = None         # Name of the traversal pattern
    aql: str | None = None             # AQL to execute
    params: dict[str, Any] = {}        # Bind variables for AQL
    collection_binds: dict[str, str] = {}  # @@collection resolutions
    post_action: str = "none"
    post_query: str | None = None
    source: str = "none"               # "fast_path", "llm", "llm_dynamic"


class OntologyIntentResolver:
    """
    Resolves user queries into graph traversal intents.
    
    Two resolution paths:
    
    FAST PATH (deterministic, ~0ms):
    - Scans query for keywords matching trigger_intents in traversal patterns
    - If match found, immediately returns the predefined pattern
    - No LLM call needed
    - Handles ~80% of ontology-related queries (the obvious ones)
    
    LLM PATH (~200-800ms):
    - Sends query + ontology schema to LLM for classification
    - LLM decides if graph traversal is needed
    - If yes, LLM either selects a known pattern or generates dynamic AQL
    - Dynamic AQL is validated before execution (read-only check)
    - Handles the "long tail" of natural language variations
    
    The fast path is tried first. If no match, the LLM path is used.
    If neither matches, the resolver returns vector_only (standard RAG).
    """
    
    def __init__(self, ontology: MergedOntology, llm_client):
        self.ontology = ontology
        self.llm = llm_client
        # Pre-build the schema prompt once (used for LLM path)
        self._schema_prompt = ontology.build_schema_prompt()
    
    async def resolve(
        self,
        query: str,
        user_context: dict
    ) -> ResolvedIntent:
        """
        Resolve a user query into an intent.
        
        Steps:
        1. Try fast path (keyword match)
        2. If no match, try LLM path (structured output)
        3. If LLM says graph_query with dynamic AQL, validate it
        4. If nothing matches, return vector_only
        
        The user_context provides session data (user_id, tenant, etc.)
        needed to populate AQL bind variables.
        """
        # ── Fast Path ──
        # Simple keyword scan against trigger_intents.
        # Case-insensitive, checks if any keyword is contained in the query.
        query_lower = query.lower()
        for pattern_name, pattern in self.ontology.traversal_patterns.items():
            if any(kw in query_lower for kw in pattern.trigger_intents):
                return ResolvedIntent(
                    action="graph_query",
                    pattern=pattern_name,
                    aql=pattern.query_template,
                    params={"user_id": user_context.get("user_id")},
                    collection_binds=self._build_collection_binds(),
                    post_action=pattern.post_action,
                    post_query=pattern.post_query,
                    source="fast_path"
                )
        
        # ── LLM Path ──
        # The LLM receives the full ontology schema and decides:
        # 1. Does this query need graph traversal? (action)
        # 2. If yes, which pattern? Or generate dynamic AQL?
        # 
        # Uses structured output for reliable parsing.
        llm_response = await self.llm.structured_output(
            system=self._build_intent_prompt(),
            query=query,
            output_schema=IntentDecision  # Pydantic model
        )
        
        if llm_response.action == "graph_query":
            if llm_response.pattern and llm_response.pattern != "dynamic":
                # LLM selected a known pattern
                pattern = self.ontology.traversal_patterns.get(llm_response.pattern)
                if pattern:
                    return ResolvedIntent(
                        action="graph_query",
                        pattern=llm_response.pattern,
                        aql=pattern.query_template,
                        params={"user_id": user_context.get("user_id")},
                        collection_binds=self._build_collection_binds(),
                        post_action=pattern.post_action,
                        post_query=pattern.post_query,
                        source="llm"
                    )
            elif llm_response.aql:
                # LLM generated dynamic AQL — MUST validate
                # validate_aql checks: no writes, depth limit, no system collections
                validated = await self.graph_store.validate_aql(llm_response.aql)
                return ResolvedIntent(
                    action="graph_query",
                    pattern="dynamic",
                    aql=validated,
                    params={"user_id": user_context.get("user_id")},
                    collection_binds=self._build_collection_binds(),
                    post_action=llm_response.suggested_post_action or "none",
                    source="llm_dynamic"
                )
        
        # ── Fallback: standard RAG ──
        return ResolvedIntent(action="vector_only")
    
    def _build_collection_binds(self) -> dict[str, str]:
        """
        Build @@collection bind variables from the ontology.
        
        Maps collection reference names to actual ArangoDB collection names.
        Example: {"@employees": "employees", "@assigned_to": "assigned_to"}
        
        This is what enables the same AQL template to work across tenants —
        the collection names are resolved at runtime.
        """
        binds = {}
        for entity in self.ontology.entities.values():
            if entity.collection:
                binds[f"@{entity.collection}"] = entity.collection
        for relation in self.ontology.relations.values():
            binds[f"@{relation.edge_collection}"] = relation.edge_collection
        return binds
    
    def _build_intent_prompt(self) -> str:
        """
        Build the system prompt for LLM-based intent detection.
        
        Includes:
        - The ontology schema (entities, relations, patterns)
        - Instructions for the LLM to classify the query
        - The expected output format (IntentDecision schema)
        - Examples of graph-requiring vs vector-only queries
        """
        return f"""You have access to an ontology graph with the following structure:

{self._schema_prompt}

Given a user query, determine if it requires graph traversal to answer accurately.

Rules:
- If the query asks about relationships between entities (who reports to whom,
  what project someone is on, what portal to use), it needs graph traversal.
- If the query asks for general information that can be found via text search
  (how to use a tool, documentation, procedures), it's vector-only.
- If you can match the query to a known traversal pattern, use that pattern name.
- If the query needs graph traversal but doesn't match a known pattern,
  generate a read-only AQL query using the available collections.

Respond with a JSON object matching the IntentDecision schema."""
```

### 4.6 OntologyRAGMixin — Pipeline Orchestrator

The ontology integration is implemented as a **mixin** (`OntologyRAGMixin`), consistent
with the established pattern in AI-Parrot (`MCPEnabledMixin`, `NotificationMixin`,
`EpisodicMemoryMixin`). Agents opt-in by inheriting the mixin.

The ontology schema prompt is integrated as a **PromptBuilder composable layer**,
rendered at `RenderPhase.CONFIGURE` time since the ontology schema is static per-tenant.

```python
# Pseudo-code — OntologyRAGMixin

class OntologyRAGMixin:
    """
    Mixin that adds Ontological Graph RAG capabilities to any agent.
    
    Usage:
        class MyAgent(OntologyRAGMixin, BasicAgent):
            pass
    
    The mixin hooks into the agent's ask() flow:
    1. Before standard RAG, resolves the query against the ontology graph
    2. If graph traversal is needed, enriches the context
    3. The enriched context is passed to the standard RAG/LLM pipeline
    
    The mixin also registers an ontology schema layer with PromptBuilder
    during configure(), so the LLM always knows the available ontology
    structure for the LLM intent detection path.
    
    Pipeline flow:
    1. Check if ontology is enabled (ENABLE_ONTOLOGY_RAG + agent config)
    2. Resolve intent (fast path or LLM path)
    3. If graph_query: execute AQL traversal
    4. Apply post-action (vector_search, tool_call, or none)
    5. Check cache (full pipeline result cached by tenant+user+intent)
    6. Build enriched context for the LLM
    
    Cache strategy:
    - Cache key: hash(tenant_id + user_id + resolved_intent_pattern)
    - Cache value: full pipeline result (graph + vector contexts)
    - TTL: ONTOLOGY_CACHE_TTL (aligned with CRON refresh frequency)
    - Invalidation: CRON pipeline busts cache after data refresh
    - This gives ~99.7% latency reduction for repeated queries
    
    PromptBuilder integration:
    - At configure() time, the mixin registers an "ontology_schema" layer
    - This layer renders the ontology schema into the system prompt
    - Rendered at RenderPhase.CONFIGURE (static, not per-request)
    - The LLM path uses this schema to classify intents and generate AQL
    """
    
    def __init__(
        self,
        tenant_manager: TenantOntologyManager,
        graph_store: OntologyGraphStore,
        vector_store,  # Existing PgVector store
        intent_resolver_factory,  # Creates IntentResolver per tenant
        cache  # Redis client
    ):
        self.tenant_manager = tenant_manager
        self.graph_store = graph_store
        self.vector_store = vector_store
        self.intent_resolver_factory = intent_resolver_factory
        self.cache = cache
    
    async def process(
        self,
        query: str,
        user_context: dict,
        tenant_id: str
    ) -> EnrichedContext:
        """
        Main entry point: process a query through the ontology pipeline.
        
        Returns an EnrichedContext that the agent can use to augment its
        LLM prompt with structural + semantic information.
        
        Steps:
        1. Get tenant context (merged ontology + DB references)
        2. Check cache for this query pattern
        3. If not cached: resolve intent → traverse → post-action
        4. Cache the result
        5. Return enriched context
        """
        # 1. Resolve tenant
        tenant_ctx = self.tenant_manager.resolve(tenant_id)
        
        # 2. Resolve intent
        resolver = self.intent_resolver_factory(tenant_ctx.ontology)
        intent = await resolver.resolve(query, user_context)
        
        if intent.action == "vector_only":
            return EnrichedContext(source="vector_only")
        
        # 3. Check cache
        cache_key = self._cache_key(tenant_id, user_context["user_id"], intent.pattern)
        cached = await self.cache.get(cache_key)
        if cached:
            return EnrichedContext.from_cache(cached)
        
        # 4. Execute graph traversal
        graph_result = await self.graph_store.execute_traversal(
            ctx=tenant_ctx,
            aql=intent.aql,
            bind_vars=intent.params,
            collection_binds=intent.collection_binds
        )
        
        # 5. Post-action routing
        vector_result = None
        tool_hint = None
        
        if intent.post_action == "vector_search" and graph_result:
            # Use a field from graph result as vector search query
            search_query = self._extract_post_query(graph_result, intent.post_query)
            if search_query:
                vector_result = await self.vector_store.search(
                    query=search_query,
                    schema=tenant_ctx.pgvector_schema
                )
        elif intent.post_action == "tool_call":
            # Don't execute tools here — just hint the agent
            # The agent's ToolManager will handle actual execution
            tool_hint = (
                f"Graph context is available. The user is associated with: "
                f"{self._summarize_graph(graph_result)}. "
                f"Use available tools to enrich the response."
            )
        
        # 6. Build enriched context
        enriched = EnrichedContext(
            source="ontology",
            graph_context=graph_result,
            vector_context=vector_result,
            tool_hint=tool_hint,
            intent=intent,
            metadata={
                "pattern": intent.pattern,
                "source": intent.source,
                "tenant": tenant_id
            }
        )
        
        # 7. Cache the result
        await self.cache.set(
            cache_key,
            enriched.to_cache(),
            ttl=ONTOLOGY_CACHE_TTL
        )
        
        return enriched
    
    def _cache_key(self, tenant_id: str, user_id: str, pattern: str) -> str:
        """
        Build cache key for full pipeline results.
        
        Format: {ONTOLOGY_CACHE_PREFIX}:{tenant}:{user}:{pattern}
        Example: parrot:ontology:epson:emp_001:find_portal
        
        This caching strategy works because:
        - Same user + same intent = same graph traversal result
        - Graph data changes only on CRON refresh (which busts cache)
        - Different users may have different traversal results
        """
        return f"{ONTOLOGY_CACHE_PREFIX}:{tenant_id}:{user_id}:{pattern}"
```

### 4.7 Refresh Pipeline — CRON-Triggered Delta Sync

The refresh pipeline updates the graph when source data changes. It runs as a CRON job
and performs delta sync: only changed data is processed.

```python
# Pseudo-code — OntologyRefreshPipeline

class OntologyRefreshPipeline:
    """
    CRON-triggered pipeline that keeps the ontology graph in sync with
    source data.
    
    The pipeline runs per-tenant and follows these stages:
    
    1. EXTRACT: Pull fresh data from configured sources (Workday, Jira, CSV, etc.)
    2. DIFF: Compare new data vs existing graph nodes (by key_field)
    3. APPLY: Upsert changed nodes, soft-delete removed ones
    4. REDISCOVER: Re-run relation discovery for changed nodes only
    5. SYNC: Update PgVector embeddings for changed vectorizable fields
    6. INVALIDATE: Bust Redis cache for the affected tenant
    
    Design decisions:
    - Delta sync (not full rebuild) to minimize processing time and DB load
    - Soft delete (mark inactive) instead of hard delete to preserve audit trail
    - Only rediscover edges for changed/new nodes (not the entire graph)
    - PgVector sync only for nodes with changed vectorizable fields
    
    Integration with ExtractDataSource:
    - The pipeline uses DataSourceFactory to resolve entity sources
    - Each entity's `source` field in the YAML maps to an ExtractDataSource
    - ExtractDataSource.extract() returns list[ExtractedRecord] (structured records)
    - This is intentionally separate from existing Loaders (which produce text chunks for RAG)
    """
    
    async def run(self, tenant_id: str):
        """
        Execute the full refresh pipeline for a tenant.
        
        This is the entry point called by the CRON scheduler.
        """
        ctx = self.tenant_manager.resolve(tenant_id)
        report = RefreshReport(tenant=tenant_id, started_at=datetime.utcnow())
        
        for entity_name, entity_def in ctx.ontology.entities.items():
            if not entity_def.source:
                continue  # Skip entities without a data source
            
            # 1. EXTRACT
            source = self.datasource_factory.get(
                entity_def.source, source_config=self.source_configs.get(entity_def.source, {})
            )
            extraction = await source.extract(
                fields=[list(p.keys())[0] for p in entity_def.properties]
            )
            new_data = [record.data for record in extraction.records]
            
            # 2. DIFF
            existing = await self.graph_store.get_all_nodes(
                ctx, entity_def.collection
            )
            diff = self._compute_diff(
                new_data, existing, key_field=entity_def.key_field
            )
            # diff = { to_add: [...], to_update: [...], to_remove: [...] }
            
            # 3. APPLY
            if diff.to_add or diff.to_update:
                result = await self.graph_store.upsert_nodes(
                    ctx, entity_def.collection,
                    diff.to_add + diff.to_update,
                    key_field=entity_def.key_field
                )
                report.add_entity_result(entity_name, result)
            
            if diff.to_remove:
                await self.graph_store.soft_delete_nodes(
                    ctx, entity_def.collection,
                    [d[entity_def.key_field] for d in diff.to_remove]
                )
            
            # 4. REDISCOVER EDGES (only for changed nodes)
            changed_nodes = diff.to_add + diff.to_update
            if changed_nodes:
                for rel_name, rel_def in ctx.ontology.relations.items():
                    if rel_def.from_entity == entity_name:
                        # This entity is the source of the relation
                        target_entity = ctx.ontology.entities[rel_def.to_entity]
                        target_data = await self.graph_store.get_all_nodes(
                            ctx, target_entity.collection
                        )
                        discovery_result = await self.discovery.discover(
                            ctx, rel_def, changed_nodes, target_data
                        )
                        await self.graph_store.create_edges(
                            ctx, rel_def.edge_collection,
                            discovery_result.confirmed
                        )
                        report.add_discovery_result(rel_name, discovery_result)
            
            # 5. SYNC PGVECTOR (only vectorizable fields that changed)
            vec_fields = entity_def.vectorize
            if vec_fields and changed_nodes:
                await self._sync_vectors(ctx, entity_def, changed_nodes)
        
        # 6. INVALIDATE CACHE
        await self.cache.delete_pattern(
            f"{ONTOLOGY_CACHE_PREFIX}:{tenant_id}:*"
        )
        self.tenant_manager.invalidate(tenant_id)
        
        report.completed_at = datetime.utcnow()
        return report
    
    def _compute_diff(
        self, new_data: list[dict], existing: list[dict], key_field: str
    ) -> DiffResult:
        """
        Compute delta between new data and existing graph nodes.
        
        Uses key_field as the identifier for matching.
        A node is "changed" if any of its field values differ.
        
        Complexity: O(n + m) using dict lookup by key_field.
        """
        existing_map = {d[key_field]: d for d in existing}
        new_map = {d[key_field]: d for d in new_data}
        
        to_add = [d for k, d in new_map.items() if k not in existing_map]
        to_remove = [d for k, d in existing_map.items() if k not in new_map]
        to_update = [
            d for k, d in new_map.items()
            if k in existing_map and d != existing_map[k]
        ]
        
        return DiffResult(
            to_add=to_add,
            to_update=to_update,
            to_remove=to_remove
        )
```

### 4.8 ExtractDataSource — Structured Record Extraction Layer

The existing AI-Parrot Loaders (`parrot/loaders/`) are designed for RAG: they convert
documents into text chunks for vector stores. The ontology refresh pipeline needs something
different: **structured record extraction** — pulling rows/records from data sources and
returning them as `list[dict]`.

`ExtractDataSource` is a generic abstraction that lives in `parrot/loaders/extractors/`,
separate from the ontology package. This makes it reusable for any future feature that
needs structured data extraction (PandasAgent data ingestion, data pipelines, ETL, etc.).

```python
# Pseudo-code — ExtractDataSource abstraction

class ExtractedRecord(BaseModel):
    """
    A single extracted record with its raw data and metadata.
    
    The data dict contains the actual field values from the source.
    Metadata tracks provenance (source name, extraction timestamp, etc.)
    for auditability and debugging.
    """
    data: dict[str, Any]
    metadata: dict[str, Any] = {}


class ExtractionResult(BaseModel):
    """
    Result of an extraction operation.
    
    Contains the extracted records plus statistics about the extraction
    (total count, errors, warnings) for pipeline reporting.
    """
    records: list[ExtractedRecord]
    total: int
    errors: list[str] = []
    warnings: list[str] = []
    source_name: str
    extracted_at: datetime


class ExtractDataSource(ABC):
    """
    Abstract base class for structured data extraction.
    
    Unlike AI-Parrot's existing Loaders (which produce text chunks for RAG),
    ExtractDataSource produces structured records (list[dict]) from various
    data sources. This is the foundation for:
    
    - Ontology graph node ingestion (primary use case)
    - PandasAgent data source feeding
    - ETL pipelines
    - Any scenario where structured records are needed
    
    Contract:
    - extract(): Pull all records from the source → ExtractionResult
    - list_fields(): Introspect available fields → list[str]
    - validate(): Check source accessibility and schema compatibility
    
    All implementations must be async-first.
    
    Subclasses:
    - CSVDataSource: Extract records from CSV files
    - JSONDataSource: Extract records from JSON files/arrays
    - ExcelDataSource: Extract records from XLSX files
    - APIDataSource: Base for REST API extraction (Workday, Jira, etc.)
    - SQLDataSource: Extract records from SQL queries
    - RecordsDataSource: Wrap an in-memory list[dict] (for testing/programmatic use)
    """
    
    def __init__(self, name: str, config: dict[str, Any] = None):
        """
        Initialize the data source.
        
        Args:
            name: Human-readable name for logging and reporting.
            config: Source-specific configuration (paths, credentials, etc.)
        """
        self.name = name
        self.config = config or {}
        self.logger = logging.getLogger(f'Parrot.Extractors.{self.__class__.__name__}')
    
    @abstractmethod
    async def extract(
        self,
        fields: list[str] | None = None,
        filters: dict[str, Any] | None = None
    ) -> ExtractionResult:
        """
        Extract structured records from the data source.
        
        Args:
            fields: Optional list of fields to extract (None = all fields).
                    This allows the caller to request only the fields defined
                    in the ontology entity, reducing memory and processing.
            filters: Optional key-value filters to pre-filter records at source.
                     For CSV/JSON this filters in-memory after loading.
                     For API/SQL sources this translates to query parameters.
        
        Returns:
            ExtractionResult with the list of ExtractedRecord instances.
        """
        ...
    
    @abstractmethod
    async def list_fields(self) -> list[str]:
        """
        Return the available field names from this data source.
        
        Used during ontology validation to check that entity properties
        and discovery rules reference fields that actually exist in the source.
        
        For CSV: returns column headers.
        For JSON: returns keys from the first record.
        For API: returns known response fields from the schema.
        """
        ...
    
    async def validate(self, expected_fields: list[str] | None = None) -> bool:
        """
        Validate that the source is accessible and has the expected schema.
        
        Args:
            expected_fields: If provided, checks that all these fields exist
                            in the source. Used during ontology build to catch
                            YAML ↔ source mismatches early.
        
        Returns:
            True if validation passes.
        
        Raises:
            DataSourceValidationError with details on what's wrong.
        """
        available = await self.list_fields()
        if expected_fields:
            missing = set(expected_fields) - set(available)
            if missing:
                raise DataSourceValidationError(
                    f"Source '{self.name}' missing expected fields: {missing}. "
                    f"Available: {available}"
                )
        return True


class CSVDataSource(ExtractDataSource):
    """
    Extract structured records from CSV files.
    
    Config:
        path: str          — Path to the CSV file
        delimiter: str     — Column delimiter (default: ',')
        encoding: str      — File encoding (default: 'utf-8')
        skip_rows: int     — Number of header rows to skip (default: 0)
    
    Uses csv.DictReader for memory-efficient row-by-row reading.
    For very large CSVs (>100MB), uses chunked reading via asyncio.to_thread().
    """
    
    async def extract(self, fields=None, filters=None) -> ExtractionResult:
        """
        Read CSV and return each row as an ExtractedRecord.
        
        Process:
        1. Open file with configured encoding
        2. Use csv.DictReader to get field names from header
        3. For each row: build dict, apply filters, wrap in ExtractedRecord
        4. If fields is specified, project only those columns
        """
        # Implementation delegates to asyncio.to_thread for blocking I/O
        pass
    
    async def list_fields(self) -> list[str]:
        """Read only the header row to get column names."""
        pass


class JSONDataSource(ExtractDataSource):
    """
    Extract structured records from JSON files or arrays.
    
    Config:
        path: str               — Path to JSON file
        records_path: str|None  — JSONPath to the array of records
                                  (e.g., "data.employees" for nested JSON)
                                  None means the root is the array.
    
    Supports both flat arrays [{"name": "John"}, ...] and nested
    structures {"data": {"employees": [...]}} via records_path.
    """
    
    async def extract(self, fields=None, filters=None) -> ExtractionResult:
        """
        Parse JSON and extract records from the configured path.
        
        Process:
        1. Load JSON file
        2. Navigate to records_path (if specified)
        3. Validate that the target is a list
        4. For each record: apply filters, project fields, wrap
        """
        pass
    
    async def list_fields(self) -> list[str]:
        """Load first record and return its keys."""
        pass


class RecordsDataSource(ExtractDataSource):
    """
    Wrap an in-memory list[dict] as a data source.
    
    Useful for:
    - Unit testing (pass test data directly)
    - Programmatic ingestion (data already in memory)
    - Chaining with other extractors (transform → re-extract)
    
    Config:
        records: list[dict]  — The records to serve
    """
    
    def __init__(self, name: str, records: list[dict], **kwargs):
        super().__init__(name=name, **kwargs)
        self._records = records
    
    async def extract(self, fields=None, filters=None) -> ExtractionResult:
        """Return the in-memory records, optionally filtered/projected."""
        pass
    
    async def list_fields(self) -> list[str]:
        """Return keys from first record, or empty list."""
        return list(self._records[0].keys()) if self._records else []


class APIDataSource(ExtractDataSource):
    """
    Base class for REST API data extraction.
    
    Subclass this for specific APIs (Workday, Jira, etc.).
    Handles pagination, authentication, rate limiting.
    
    Config:
        base_url: str       — API base URL
        auth_type: str      — "bearer", "basic", "oauth2"
        credentials: dict   — Auth credentials
        headers: dict       — Additional headers
        page_size: int      — Records per page (default: 100)
        max_pages: int      — Safety limit on pagination (default: 100)
    
    Subclasses implement:
    - _build_request(): Construct the API request
    - _parse_response(): Extract records from API response
    - _get_next_page(): Determine next page token/URL
    """
    
    @abstractmethod
    async def _build_request(
        self, fields: list[str] | None, filters: dict | None, page_token: str | None
    ) -> tuple[str, dict]:
        """Return (url, params) for the API request."""
        ...
    
    @abstractmethod
    def _parse_response(self, response_data: dict) -> list[dict]:
        """Extract records from the API response body."""
        ...
    
    @abstractmethod
    def _get_next_page(self, response_data: dict) -> str | None:
        """Return next page token, or None if no more pages."""
        ...
    
    async def extract(self, fields=None, filters=None) -> ExtractionResult:
        """
        Paginated extraction from the API.
        
        Process:
        1. Build initial request
        2. Loop: fetch page → parse records → check next page
        3. Respect rate limits (configurable delay between pages)
        4. Stop at max_pages safety limit
        """
        all_records = []
        page_token = None
        page_count = 0
        max_pages = self.config.get("max_pages", 100)
        
        while page_count < max_pages:
            url, params = await self._build_request(fields, filters, page_token)
            # ... aiohttp request, parse, collect records
            page_token = self._get_next_page(response_data)
            if not page_token:
                break
            page_count += 1
        
        return ExtractionResult(
            records=[ExtractedRecord(data=r) for r in all_records],
            total=len(all_records),
            source_name=self.name,
            extracted_at=datetime.utcnow()
        )


class SQLDataSource(ExtractDataSource):
    """
    Extract structured records from SQL queries.
    
    Config:
        dsn: str            — Database connection string
        query: str          — SQL SELECT query to execute
        params: dict        — Query parameters (for parameterized queries)
    
    Uses asyncpg for PostgreSQL, or a generic async DB adapter.
    The query MUST be read-only (SELECT only) — validated before execution.
    """
    
    async def extract(self, fields=None, filters=None) -> ExtractionResult:
        """Execute SQL query and return rows as records."""
        pass
    
    async def list_fields(self) -> list[str]:
        """Execute query with LIMIT 0 to get column names."""
        pass
```

**Integration with the Ontology Refresh Pipeline:**

The `OntologyRefreshPipeline` uses a factory to resolve the entity's `source` field
to the appropriate `ExtractDataSource` implementation:

```python
# Pseudo-code — how refresh.py uses ExtractDataSource

class DataSourceFactory:
    """
    Maps entity source names to ExtractDataSource implementations.
    
    Resolution order:
    1. Check registered custom sources (client-provided implementations)
    2. Check built-in sources by type:
       - "csv"     → CSVDataSource
       - "json"    → JSONDataSource
       - "sql"     → SQLDataSource
       - "records" → RecordsDataSource
    3. Check API source registry:
       - "workday" → WorkdayDataSource (extends APIDataSource)
       - "jira"    → JiraDataSource (extends APIDataSource)
    4. Raise UnknownDataSourceError
    
    Source configuration comes from a separate sources.yaml per tenant:
    
        sources:
          workday:
            type: api
            base_url: "https://wd5.myworkday.com/api/v1"
            auth_type: oauth2
            credentials_secret: "workday_oauth"
          employees_csv:
            type: csv
            path: "/data/imports/employees.csv"
            delimiter: ","
            encoding: "utf-8"
    """
    
    _builtin_types = {
        "csv": CSVDataSource,
        "json": JSONDataSource,
        "sql": SQLDataSource,
        "records": RecordsDataSource,
    }
    
    def get(self, source_name: str, source_config: dict) -> ExtractDataSource:
        source_type = source_config.get("type", source_name)
        
        if source_type in self._builtin_types:
            cls = self._builtin_types[source_type]
            return cls(name=source_name, config=source_config)
        
        if source_type in self._api_registry:
            cls = self._api_registry[source_type]
            return cls(name=source_name, config=source_config)
        
        raise UnknownDataSourceError(f"No extractor for source: {source_name}")
```

---

## 5. Module Map — File Structure

```
parrot/
├── loaders/
│   ├── extractors/
│   │   ├── __init__.py              # Public API: ExtractDataSource, CSVDataSource, etc.
│   │   ├── base.py                  # ExtractDataSource ABC, ExtractedRecord, ExtractionResult
│   │   ├── csv_source.py            # CSVDataSource implementation
│   │   ├── json_source.py           # JSONDataSource implementation
│   │   ├── records_source.py        # RecordsDataSource (in-memory)
│   │   ├── api_source.py            # APIDataSource ABC for REST APIs
│   │   ├── sql_source.py            # SQLDataSource implementation
│   │   ├── factory.py               # DataSourceFactory — source resolution
│   │   └── exceptions.py            # DataSourceValidationError, etc.
│   └── ...existing loaders...
│
├── knowledge/
│   └── ontology/
│       ├── __init__.py              # Public API exports
│       ├── schema.py                # Pydantic models (OntologyDefinition, MergedOntology, etc.)
│       ├── parser.py                # OntologyParser — YAML loading and validation
│       ├── merger.py                # OntologyMerger — multi-layer YAML composition
│       ├── discovery.py             # RelationDiscovery — edge creation strategies
│       ├── graph_store.py           # OntologyGraphStore — ArangoDB operations
│       ├── intent.py                # OntologyIntentResolver — dual-path intent detection
│       ├── mixin.py                 # OntologyRAGMixin — agent mixin for ontology pipeline
│       ├── tenant.py                # TenantOntologyManager — multi-tenant resolution
│       ├── refresh.py               # OntologyRefreshPipeline — CRON delta sync
│       ├── cache.py                 # Cache helpers (key building, invalidation)
│       ├── validators.py            # AQL validation, security checks
│       ├── exceptions.py            # OntologyMergeError, AQLValidationError, etc.
│       └── defaults/                # Package resources (ship with ai-parrot)
│           ├── base.ontology.yaml   # Base ontology (Employee, Department, reports_to, etc.)
│           └── domains/
│               └── field_services.ontology.yaml
│
├── conf.py                          # + ONTOLOGY_* config variables
│
ontologies/                          # Default ONTOLOGY_DIR (configurable)
├── base.ontology.yaml               # Ships with ai-parrot
├── domains/
│   ├── field_services.ontology.yaml
│   └── ...
└── clients/
    ├── epson.ontology.yaml
    └── ...
```

---

## 6. Capabilities — New and Modified

### New Capabilities

| ID | Name | Description |
|----|------|-------------|
| `extract-datasource` | Structured record extraction | Generic `ExtractDataSource` ABC + CSV, JSON, Records, API, SQL implementations |
| `extract-datasource-factory` | Data source factory | Resolve source names to `ExtractDataSource` implementations |
| `ontology-yaml-schema` | YAML schema definition | Pydantic models for composable ontology YAMLs |
| `ontology-yaml-merge` | YAML layer composition | Merge base + domain + client ontology YAMLs |
| `ontology-graph-store` | Graph store operations | ArangoDB CRUD, traversal, validation |
| `ontology-discovery` | Relation discovery engine | Automatic edge creation from data sources |
| `ontology-intent-resolver` | Intent resolution | Dual-path (fast + LLM) query classification; LLM path uses `ONTOLOGY_AQL_MODEL` (defaults to gemini-2.5-flash) |
| `ontology-mixin` | Agent mixin | `OntologyRAGMixin` — agents opt-in via inheritance, hooks into ask() flow |
| `ontology-prompt-layer` | PromptBuilder layer | Ontology schema as composable prompt layer, rendered at `RenderPhase.CONFIGURE` |
| `ontology-tenant-mgr` | Tenant management | Multi-tenant isolation and YAML resolution |
| `ontology-refresh` | CRON refresh pipeline | Delta sync from data sources |
| `ontology-cache` | Pipeline caching | Full-pipeline Redis cache with CRON invalidation |
| `ontology-aql-validator` | AQL security | Validate LLM-generated AQL for safety |

### Modified Capabilities

| ID | Component | Change |
|----|-----------|--------|
| `parrot-conf` | `parrot/conf.py` | Add ONTOLOGY_* config variables (including `ONTOLOGY_AQL_MODEL`, `ONTOLOGY_REVIEW_DIR`) |
| `agent-pipeline` | Agent mixin inheritance | Agents inherit `OntologyRAGMixin` to opt-in |
| `prompt-builder` | PromptBuilder layers | New `ontology_schema` composable layer at `RenderPhase.CONFIGURE` |

---

## 7. Impact & Integration

| Component | Impact | Notes |
|-----------|--------|-------|
| `parrot/conf.py` | Modified | Add 10+ ONTOLOGY_* config variables |
| `parrot/loaders/extractors/` | New package | `ExtractDataSource` ABC + implementations (CSV, JSON, API, SQL, Records) |
| `parrot/knowledge/` | New package | New `ontology/` sub-package |
| Agent pipeline | Modified | Middleware hook in ask() or mixin |
| Existing Loaders | Unchanged | NOT modified — extractors are a separate, parallel package |
| PgVector store | Consumed | Middleware calls vector search with graph context |
| ToolManager | Consumed | Middleware hints tool execution from graph context |
| ArangoDB client | Consumed | `python-arango-async` already in deps |
| Redis | Consumed | Cache layer for pipeline results |

---

## 8. Libraries & Tools

| Library | Purpose | Notes |
|---------|---------|-------|
| `python-arango-async` | ArangoDB async client | Already in project |
| `pydantic` v2 | YAML schema validation | Already in project |
| `pyyaml` | YAML parsing | Already in project |
| `rapidfuzz` | Fuzzy string matching | New dep — lightweight, MIT license |
| `asyncpg` | PgVector operations | Already in project |
| `redis`/`aioredis` | Pipeline caching | Already in project |

---

## 9. Existing Code to Reuse

| Path | What | How |
|------|------|-----|
| `parrot/conf.py` | Config pattern | Follow same `config.get()` + Path resolution pattern |
| `parrot/loaders/` | Loader structure | Place extractors as sub-package alongside existing loaders |
| `parrot/knowledge/` | KB structure | Place ontology as sub-package within knowledge |
| `parrot/tools/abstract.py` | Tool patterns | If ontology tools are needed later |
| Existing ArangoDB integration | Graph operations | Extend with ontology-specific methods |
| Existing PgVector store | Vector search | Consume via middleware, no changes needed |
| `parrot/handlers/chat.py` | Factory pattern | `_get_loader()` / `get_loader_class()` as reference for `DataSourceFactory` |

---

## 10. Parallelism Assessment

### Internal Parallelism

This feature has **moderate internal parallelism**. Some modules are independent:

| Task Group | Independent? | Notes |
|------------|-------------|-------|
| extractors (base + CSV + JSON + Records) | YES | Generic package, no ontology dependencies |
| schema.py + parser.py + merger.py | YES | Pure data models, no I/O dependencies |
| graph_store.py + validators.py | YES | ArangoDB operations, independent of YAML parsing |
| discovery.py | PARTIAL | Depends on schema.py models, but logic is independent |
| intent.py | PARTIAL | Depends on schema.py (MergedOntology) |
| middleware.py | NO | Depends on all other modules |
| refresh.py | PARTIAL | Depends on graph_store.py, discovery.py, and extractors |
| conf.py changes | YES | Independent, can be done first |

### Cross-Feature Independence

- No conflicts with in-flight specs (ontology is a new package)
- Shared file: `parrot/conf.py` (minor addition, low conflict risk)
- Shared package: `parrot/knowledge/` (new sub-package, no existing conflicts)

### Recommended Isolation

**`per-spec`** — All tasks sequential in one worktree.

**Rationale**: While some modules are independently testable, the integration between
them is tight (middleware depends on everything). Sequential development ensures the
schema models are stable before building consumers. The `parrot/conf.py` changes are
minimal and low-risk.

---

## 11. Open Questions — All Resolved

| # | Question | Resolution |
|---|----------|------------|
| ~~1~~ | ~~How to integrate OntologyRAGMiddleware with the agent?~~ | **RESOLVED** — Mixin pattern (`OntologyRAGMixin`), consistent with existing mixins like `MCPEnabledMixin`, `NotificationMixin`, `EpisodicMemoryMixin`. The mixin hooks into the agent's `ask()` flow, intercepting queries before standard RAG processing. Agents opt-in by inheriting the mixin. |
| ~~2~~ | ~~Should the base.ontology.yaml ship as a package resource or as a template that gets copied?~~ | **RESOLVED** — Package resource. The YAML files ship inside the `parrot` package (e.g., `parrot/knowledge/ontology/defaults/base.ontology.yaml`) and are loaded via `importlib.resources` or `Path(__file__).parent / "defaults"`. No copying, no file management headaches. Client overrides live in `ONTOLOGY_DIR` (external, configurable). |
| ~~3~~ | ~~What existing Loader classes can be reused directly for the refresh pipeline?~~ | **RESOLVED** — Existing Loaders are NOT reused. New `ExtractDataSource` abstraction in `parrot/loaders/extractors/` handles structured record extraction with a different contract (`list[dict]` vs text chunks). |
| ~~4~~ | ~~Should dynamic AQL generation use a separate (cheaper) LLM model?~~ | **RESOLVED** — Yes, defaults to `gemini-2.5-flash`. Dynamic AQL generation is a structured classification task, not a creative task — a smaller/faster model is sufficient. Configurable via `ONTOLOGY_AQL_MODEL` in `parrot/conf.py` so deployments can override. Falls back to the agent's primary LLM if not set. |
| ~~5~~ | ~~Review queue for ambiguous relations — UI? CLI? Log file?~~ | **RESOLVED** — JSON log file. The `RelationDiscovery` engine writes ambiguous pairs to a structured JSON file at `{ONTOLOGY_DIR}/review/{tenant}_review_queue.json`. Simple, no UI dependencies, easy to inspect manually or process programmatically. Each entry includes source/target values, confidence scores, and suggested action. |
| ~~6~~ | ~~Should the schema prompt (for LLM path) be part of the PromptBuilder composable layers?~~ | **RESOLVED** — Yes, integrate with the PromptBuilder composable layer system. The ontology schema prompt is a layer that gets composed into the agent's system prompt at `configure()` time (`RenderPhase.CONFIGURE`), since the ontology schema is static per-tenant and doesn't change per-request. This follows the established two-phase rendering pattern. |

---

## 12. Task Decomposition (Suggested for /sdd-spec)

| # | Task | Dependencies | Effort |
|---|------|-------------|--------|
| 1 | Add ONTOLOGY_* variables to `parrot/conf.py` (incl. `ONTOLOGY_AQL_MODEL`, `ONTOLOGY_REVIEW_DIR`) | None | Low |
| 2 | Implement `parrot/loaders/extractors/base.py` — `ExtractDataSource` ABC, `ExtractedRecord`, `ExtractionResult` | None | Medium |
| 3 | Implement extractors: `csv_source.py`, `json_source.py`, `records_source.py`, `sql_source.py`, `api_source.py` | Task 2 | Medium |
| 4 | Implement `parrot/loaders/extractors/factory.py` — `DataSourceFactory` | Tasks 2, 3 | Low |
| 5 | Implement `schema.py` — all Pydantic models for ontology YAML | None | Medium |
| 6 | Implement `parser.py` — YAML loading + validation (with `importlib.resources` for package defaults) | Task 5 | Low |
| 7 | Implement `merger.py` — multi-layer YAML composition | Tasks 5, 6 | Medium |
| 8 | Implement `graph_store.py` — ArangoDB operations | Task 5 | Medium |
| 9 | Implement `validators.py` — AQL security validation | Task 8 | Low |
| 10 | Implement `discovery.py` — relation discovery engine + JSON review queue output | Tasks 5, 8 | High |
| 11 | Implement `intent.py` — dual-path intent resolver (LLM path uses `ONTOLOGY_AQL_MODEL`) | Tasks 5, 7 | Medium |
| 12 | Implement `mixin.py` — `OntologyRAGMixin` pipeline orchestrator | Tasks 8, 10, 11 | High |
| 13 | Implement ontology schema as PromptBuilder composable layer (`RenderPhase.CONFIGURE`) | Tasks 5, 7, 12 | Medium |
| 14 | Implement `tenant.py` — multi-tenant manager | Tasks 7, 8 | Medium |
| 15 | Implement `refresh.py` — CRON delta sync pipeline (uses `DataSourceFactory`) | Tasks 4, 8, 10, 14 | High |
| 16 | Implement `cache.py` — Redis cache helpers | Task 12 | Low |
| 17 | Create `defaults/base.ontology.yaml` + `defaults/domains/` examples (package resources) | Task 5 | Medium |
| 18 | Integration tests — full E2E pipeline | All | High |

---