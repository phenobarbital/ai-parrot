"""Pydantic v2 models for ontology YAML validation and runtime representation.

These models define the complete schema for the composable ontology YAML system:
base → domain → client layers, merged into a single MergedOntology at runtime.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ── YAML Definition Models ──


class PropertyDef(BaseModel):
    """Single property definition for an entity.

    Args:
        type: Data type of the property.
        required: Whether the property is required.
        unique: Whether values must be unique.
        default: Default value when not provided.
        enum: Allowed values (optional constraint).
        description: Human-readable description.
    """

    type: Literal["string", "int", "float", "boolean", "date", "list", "dict"]
    required: bool = False
    unique: bool = False
    default: Any = None
    enum: list[str] | None = None
    description: str | None = None

    model_config = ConfigDict(extra="forbid")


class EntityDef(BaseModel):
    """Definition of a vertex collection (entity) in the ontology.

    When ``extend`` is True, this entity definition is merged with a parent
    layer's definition of the same entity. Properties and vectorize fields
    are concatenated; source is overridden.

    Args:
        collection: ArangoDB collection name.
        source: Data source identifier (workday, jira, csv, etc.).
        key_field: Primary key field name.
        properties: List of property definitions (each dict maps name → PropertyDef).
        vectorize: Fields to embed in PgVector.
        extend: If True, merge with parent layer's definition.
    """

    collection: str | None = None
    source: str | None = None
    key_field: str | None = None
    properties: list[dict[str, PropertyDef]] = Field(default_factory=list)
    vectorize: list[str] = Field(default_factory=list)
    extend: bool = False

    model_config = ConfigDict(extra="forbid")

    def get_property_names(self) -> set[str]:
        """Return the set of all property names defined on this entity."""
        names: set[str] = set()
        for prop_dict in self.properties:
            names.update(prop_dict.keys())
        return names


class DiscoveryRule(BaseModel):
    """Rule for discovering relationships between entities in source data.

    Args:
        source_field: Field on the source entity (e.g. "Employee.project_code").
        target_field: Field on the target entity (e.g. "Project.project_id").
        match_type: Matching strategy to use.
        threshold: Confidence threshold for fuzzy/AI matching.
        description: Human-readable description of the rule.
    """

    source_field: str
    target_field: str
    match_type: Literal["exact", "fuzzy", "ai_assisted", "composite"] = "exact"
    threshold: float = 0.85
    description: str | None = None

    model_config = ConfigDict(extra="forbid")


class DiscoveryConfig(BaseModel):
    """Configuration for how relations are discovered in source data.

    Args:
        strategy: Overall discovery strategy.
        rules: List of discovery rules to apply.
    """

    strategy: Literal["field_match", "ai_assisted", "composite"] = "field_match"
    rules: list[DiscoveryRule] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class RelationDef(BaseModel):
    """Definition of an edge collection (relation) in the ontology.

    Uses ``from`` and ``to`` as YAML keys via aliases.

    Args:
        from_entity: Source entity name.
        to_entity: Target entity name.
        edge_collection: ArangoDB edge collection name.
        properties: Edge properties.
        discovery: How to discover this relation in source data.
    """

    from_entity: str = Field(alias="from")
    to_entity: str = Field(alias="to")
    edge_collection: str
    properties: list[dict[str, PropertyDef]] = Field(default_factory=list)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
    )


class TraversalPattern(BaseModel):
    """Predefined graph traversal pattern for a known query type.

    Traversal patterns are the "fast path" — when the user's query matches
    a trigger_intent keyword, the system skips LLM intent detection and
    executes the AQL template directly.

    Args:
        description: Human-readable description of what this pattern does.
        trigger_intents: Keywords for fast-path matching.
        query_template: AQL with bind variables.
        post_action: What happens after graph traversal.
        post_query: Field name to use as vector query (for vector_search).
    """

    description: str
    trigger_intents: list[str] = Field(default_factory=list)
    query_template: str
    post_action: Literal["vector_search", "tool_call", "none"] = "none"
    post_query: str | None = None

    model_config = ConfigDict(extra="forbid")


class OntologyDefinition(BaseModel):
    """Root model for a single ontology YAML layer.

    Each YAML file is parsed into this model. Multiple OntologyDefinition
    instances are then merged by OntologyMerger to produce a MergedOntology.

    Args:
        name: Ontology layer name.
        version: Schema version.
        extends: Parent ontology name (for documentation).
        description: Human-readable description.
        entities: Entity definitions keyed by name.
        relations: Relation definitions keyed by name.
        traversal_patterns: Traversal pattern definitions keyed by name.
    """

    name: str
    version: str = "1.0"
    extends: str | None = None
    description: str | None = None
    entities: dict[str, EntityDef] = Field(default_factory=dict)
    relations: dict[str, RelationDef] = Field(default_factory=dict)
    traversal_patterns: dict[str, TraversalPattern] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


# ── Runtime Models ──


class MergedOntology(BaseModel):
    """Fully resolved ontology after merging all YAML layers.

    This is the runtime representation used by the intent resolver,
    graph store, and mixin.

    Args:
        name: Name of the last merged layer.
        version: Schema version.
        entities: All entity definitions.
        relations: All relation definitions.
        traversal_patterns: All traversal patterns.
        layers: List of YAML file paths that were merged.
        merge_timestamp: When the merge was performed.
    """

    name: str
    version: str
    entities: dict[str, EntityDef]
    relations: dict[str, RelationDef]
    traversal_patterns: dict[str, TraversalPattern]
    layers: list[str]
    merge_timestamp: datetime

    def get_entity_collections(self) -> list[str]:
        """Return all vertex collection names."""
        return [e.collection for e in self.entities.values() if e.collection]

    def get_edge_collections(self) -> list[str]:
        """Return all edge collection names."""
        return [r.edge_collection for r in self.relations.values()]

    def get_vectorizable_fields(self, entity_name: str) -> list[str]:
        """Return fields that should be embedded in PgVector for an entity.

        Args:
            entity_name: Name of the entity.

        Returns:
            List of field names to vectorize.
        """
        entity = self.entities.get(entity_name)
        return entity.vectorize if entity else []

    def build_schema_prompt(self) -> str:
        """Generate a natural language description of the ontology for the LLM.

        This is injected into the system prompt so the LLM understands what
        entities and relations are available for graph queries.

        Returns:
            Formatted string describing the ontology schema.
        """
        lines = ["Available ontology:"]
        lines.append("\nEntities:")
        for name, entity in self.entities.items():
            props = list(entity.get_property_names())
            lines.append(f"  - {name}: {', '.join(sorted(props))}")

        lines.append("\nRelations:")
        for name, rel in self.relations.items():
            lines.append(
                f"  - {rel.from_entity} --[{name}]--> {rel.to_entity}"
            )

        lines.append("\nKnown traversal patterns:")
        for name, pattern in self.traversal_patterns.items():
            lines.append(f"  - {name}: {pattern.description}")
            if pattern.trigger_intents:
                lines.append(
                    f"    triggers: {', '.join(pattern.trigger_intents)}"
                )

        return "\n".join(lines)


class TenantContext(BaseModel):
    """Runtime context for a specific tenant.

    Created by TenantOntologyManager and passed through the entire pipeline.

    Args:
        tenant_id: Unique tenant identifier.
        arango_db: ArangoDB database name for this tenant.
        pgvector_schema: PgVector schema name for this tenant.
        ontology: The fully merged ontology for this tenant.
    """

    tenant_id: str
    arango_db: str
    pgvector_schema: str
    ontology: MergedOntology


class ResolvedIntent(BaseModel):
    """Result of intent resolution.

    Args:
        action: Whether the query needs graph traversal or vector-only.
        pattern: Name of the matched traversal pattern (if any).
        aql: AQL query to execute (if graph_query).
        params: Bind variables for the AQL query.
        collection_binds: @@collection resolutions for AQL.
        post_action: What to do after graph traversal.
        post_query: Field to use as vector search query.
        source: How the intent was resolved.
    """

    action: Literal["graph_query", "vector_only"]
    pattern: str | None = None
    aql: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    collection_binds: dict[str, str] = Field(default_factory=dict)
    post_action: str = "none"
    post_query: str | None = None
    source: str = "none"


class EnrichedContext(BaseModel):
    """Enriched context returned by the ontology pipeline.

    Contains structural (graph) and semantic (vector) information that
    the agent uses to augment its LLM prompt.

    Args:
        source: How the context was produced.
        graph_context: Results from graph traversal.
        vector_context: Results from vector search.
        tool_hint: Hint for tool execution from graph context.
        intent: The resolved intent that produced this context.
        metadata: Additional metadata.
    """

    source: str = "none"
    graph_context: list[dict[str, Any]] | None = None
    vector_context: list[dict[str, Any]] | None = None
    tool_hint: str | None = None
    intent: ResolvedIntent | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_cache(self) -> str:
        """Serialize to JSON string for Redis caching.

        Returns:
            JSON string representation.
        """
        return self.model_dump_json()

    @classmethod
    def from_cache(cls, cached: str) -> EnrichedContext:
        """Deserialize from cached JSON string.

        Args:
            cached: JSON string from Redis.

        Returns:
            EnrichedContext instance.
        """
        return cls.model_validate_json(cached)
