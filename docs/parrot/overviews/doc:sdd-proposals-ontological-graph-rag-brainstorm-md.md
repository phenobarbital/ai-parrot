---
type: Wiki Overview
title: Ontological Graph RAG — SDD Brainstorm
id: doc:sdd-proposals-ontological-graph-rag-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Standard vector-based RAG fails when user queries require **structural reasoning**
  — questions
relates_to:
- concept: mod:parrot
  rel: mentions
---

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

…(truncated)…
