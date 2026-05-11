"""Pydantic v2 models for ontology YAML validation and runtime representation.

These models define the complete schema for the composable ontology YAML system:
base → domain → client layers, merged into a single MergedOntology at runtime.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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

    @field_validator("key_field")
    @classmethod
    def _validate_key_field(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", v):
            raise ValueError(
                f"key_field must be a valid identifier (letters, digits, underscore only), got {v!r}"
            )
        return v

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


# ── FEAT-158: Entity Extraction, Authorization, and Tool-Call Dispatch Models ──


class EntityExtractionRule(BaseModel):
    """Rule describing how to extract and resolve a named entity from a query.

    Args:
        type: Ontology entity type (e.g., ``"Employee"``).
        resolver: Resolution strategy to use.
        scope: Scope of the search: ``same_tenant``, ``same_department``, or
            ``anywhere``.
        ambiguity_strategy: What to do when multiple candidates match.
        required: If True, failure to resolve raises ``EntityNotFoundError``.
        description: Human-readable description of this rule.
    """

    type: str
    resolver: Literal[
        "exact_id_match",
        "fuzzy_name_match",
        "ai_assisted",
        "hybrid_concept_match",
    ]
    scope: Literal["same_tenant", "same_department", "anywhere"] = "same_tenant"
    ambiguity_strategy: Literal[
        "ask_user",
        "pick_first",
        "use_context",
        "fail",
        "rerank_by_authority",
    ] = "ask_user"
    required: bool = True
    description: str | None = None

    model_config = ConfigDict(extra="forbid")


class AuthorizationRule(BaseModel):
    """Single declarative authorization rule for an intent pattern.

    Args:
        rule: Which rule to evaluate.
        role: Required when ``rule == "has_role"``; the role name to check.
        description: Human-readable description.
    """

    rule: Literal[
        "target_is_self",
        "target_in_management_chain",
        "has_role",
        "same_department",
        "always",
    ]
    role: str | None = None
    description: str | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _require_role_for_has_role(self) -> "AuthorizationRule":
        """Validate that has_role rule includes a role field.

        Returns:
            Self after validation.

        Raises:
            ValueError: If rule is ``has_role`` but ``role`` is not set.
        """
        if self.rule == "has_role" and not self.role:
            raise ValueError("rule='has_role' requires a non-empty 'role' field")
        return self


class AuthorizationSpec(BaseModel):
    """Declarative authorization specification for a traversal pattern.

    Rules are evaluated with OR semantics: the first matching rule allows access.
    If no rule matches and ``default_deny=True``, access is denied.

    Args:
        rules: List of authorization rules to evaluate in order.
        default_deny: Whether to deny when no rule matches (default True).
    """

    rules: list[AuthorizationRule] = Field(default_factory=list)
    default_deny: bool = True

    model_config = ConfigDict(extra="forbid")


class ToolCallSpec(BaseModel):
    """Specification for a tool invocation after graph traversal.

    Args:
        toolkit: Toolkit class name (e.g., ``"JiraToolkit"``).
        method: Method name on the toolkit (e.g., ``"jira_search_issues"``).
        credential_mode: How credentials are resolved for the call.
        parameters: Jinja2-templated parameters rendered with
            ``(graph, ctx, extras)`` namespaces.
        result_binding: Key under which the result is stored in
            ``ContextEnvelope.tool_result``.
        empty_team_behavior: What to do when the graph result is empty.
    """

    toolkit: str
    method: str
    credential_mode: Literal[
        "requesting_user",
        "service_account",
        "agent_owner",
    ] = "requesting_user"
    parameters: dict[str, Any] = Field(default_factory=dict)
    result_binding: str
    empty_team_behavior: Literal[
        "short_circuit",
        "call_anyway",
        "fail",
    ] = "short_circuit"

    model_config = ConfigDict(extra="forbid")


class TraversalPattern(BaseModel):
    """Predefined graph traversal pattern for a known query type.

    Traversal patterns are the "fast path" — when the user's query matches
    a trigger_intent keyword, the system skips LLM intent detection and
    executes the AQL template directly.

    New optional sections (FEAT-158):
    - ``entity_extraction``: Named entity rules keyed by rule name.
    - ``authorization``: Declarative access rules for this pattern.
    - ``tool_call``: Tool invocation spec run after graph traversal.

    Patterns without new sections load unchanged (backwards compatible).

    Args:
        description: Human-readable description of what this pattern does.
        trigger_intents: Keywords for fast-path matching.
        query_template: AQL with bind variables.
        post_action: What happens after graph traversal.
        post_query: Field name to use as vector query (for vector_search).
        entity_extraction: Named entity extraction rules (FEAT-158).
        authorization: Declarative authorization spec (FEAT-158).
        tool_call: Tool invocation spec (FEAT-158).
    """

    description: str
    trigger_intents: list[str] = Field(default_factory=list)
    query_template: str
    post_action: Literal["vector_search", "tool_call", "none"] = "none"
    post_query: str | None = None
    entity_extraction: dict[str, EntityExtractionRule] = Field(default_factory=dict)
    authorization: AuthorizationSpec | None = None
    tool_call: ToolCallSpec | None = None

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

    New optional fields (FEAT-158):
    - ``resolved_entities``: Mapping from rule name to resolved ``_id``.
    - ``tool_call``: Tool invocation spec from the matched pattern.
    - ``denial_reason``: Human-readable reason for authorization denial.

    Args:
        action: Whether the query needs graph traversal or vector-only.
        pattern: Name of the matched traversal pattern (if any).
        aql: AQL query to execute (if graph_query).
        params: Bind variables for the AQL query.
        collection_binds: @@collection resolutions for AQL.
        post_action: What to do after graph traversal.
        post_query: Field to use as vector search query.
        source: How the intent was resolved.
        resolved_entities: Rule name → resolved graph ``_id`` (FEAT-158).
        tool_call: Tool invocation spec linked to this intent (FEAT-158).
        denial_reason: Reason for authorization denial, if applicable (FEAT-158).
    """

    action: Literal["graph_query", "vector_only"]
    pattern: str | None = None
    aql: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    collection_binds: dict[str, str] = Field(default_factory=dict)
    post_action: str = "none"
    post_query: str | None = None
    source: str = "none"
    resolved_entities: dict[str, str] = Field(default_factory=dict)
    tool_call: ToolCallSpec | None = None
    denial_reason: str | None = None


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


class ContextEnvelope(BaseModel):
    """Wraps EnrichedContext with state-specific fields for non-happy paths.

    Introduced by FEAT-158 to widen the return type of
    ``OntologyRAGMixin.ontology_process`` so all code paths — happy, ambiguous,
    denied, auth-required, render-error, tool-failed — share a single return
    type.

    Callers previously reading ``result.graph_context`` directly must migrate
    to ``result.context.graph_context`` (``context`` is ``None`` for non-``ok``
    states).

    States:
    - ``ok``: Pipeline completed successfully; ``context`` is populated.
    - ``ambiguous``: EntityResolver found multiple candidates for a required
      rule; ``clarification`` carries ``rule``, ``mention``, and
      ``candidates``.
    - ``entity_not_found``: EntityResolver found no candidates for a required
      rule; ``error`` carries the rule name.
    - ``denied``: AuthorizationChecker denied access; ``denial_reason`` is set.
    - ``auth_required``: Tool raised ``AuthorizationRequired``; ``auth_prompt``
      carries ``auth_url``, ``provider``, and ``scopes``.
    - ``render_error``: Jinja2 template rendering failed (``StrictUndefined``);
      ``error`` carries the template field name and message.
    - ``tool_failed``: Tool invocation raised an unexpected exception;
      ``error`` carries the message.

    Args:
        state: Current pipeline state.
        context: Populated ``EnrichedContext`` on ``state="ok"``; ``None``
            otherwise.
        clarification: On ``state="ambiguous"``: mapping with keys
            ``rule``, ``mention``, ``candidates``.
        denial_reason: On ``state="denied"``: human-readable denial reason.
        auth_prompt: On ``state="auth_required"``: mapping with keys
            ``auth_url``, ``provider``, ``scopes``.
        tool_result: On ``state="ok"`` with a tool_call post-action: the
            result dict keyed by ``ToolCallSpec.result_binding``.
        error: On error states: description of what went wrong.
    """

    state: Literal[
        "ok",
        "disabled",
        "not_configured",
        "ambiguous",
        "entity_not_found",
        "denied",
        "auth_required",
        "render_error",
        "tool_failed",
    ]
    context: EnrichedContext | None = None
    clarification: dict[str, Any] | None = None
    denial_reason: str | None = None
    auth_prompt: dict[str, Any] | None = None
    tool_result: dict[str, Any] | None = None
    error: str | None = None

    model_config = ConfigDict(extra="forbid")
