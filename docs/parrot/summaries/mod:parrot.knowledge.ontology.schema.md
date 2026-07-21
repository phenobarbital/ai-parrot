---
type: Wiki Summary
title: parrot.knowledge.ontology.schema
id: mod:parrot.knowledge.ontology.schema
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic v2 models for ontology YAML validation and runtime representation.
relates_to:
- concept: class:parrot.knowledge.ontology.schema.AuthorizationRule
  rel: defines
- concept: class:parrot.knowledge.ontology.schema.AuthorizationSpec
  rel: defines
- concept: class:parrot.knowledge.ontology.schema.ContextEnvelope
  rel: defines
- concept: class:parrot.knowledge.ontology.schema.DiscoveryConfig
  rel: defines
- concept: class:parrot.knowledge.ontology.schema.DiscoveryRule
  rel: defines
- concept: class:parrot.knowledge.ontology.schema.EnrichedContext
  rel: defines
- concept: class:parrot.knowledge.ontology.schema.EntityDef
  rel: defines
- concept: class:parrot.knowledge.ontology.schema.EntityExtractionRule
  rel: defines
- concept: class:parrot.knowledge.ontology.schema.MergedOntology
  rel: defines
- concept: class:parrot.knowledge.ontology.schema.OntologyDefinition
  rel: defines
- concept: class:parrot.knowledge.ontology.schema.PropertyDef
  rel: defines
- concept: class:parrot.knowledge.ontology.schema.RelationDef
  rel: defines
- concept: class:parrot.knowledge.ontology.schema.ResolvedIntent
  rel: defines
- concept: class:parrot.knowledge.ontology.schema.TenantContext
  rel: defines
- concept: class:parrot.knowledge.ontology.schema.ToolCallSpec
  rel: defines
- concept: class:parrot.knowledge.ontology.schema.TraversalPattern
  rel: defines
---

# `parrot.knowledge.ontology.schema`

Pydantic v2 models for ontology YAML validation and runtime representation.

These models define the complete schema for the composable ontology YAML system:
base → domain → client layers, merged into a single MergedOntology at runtime.

## Classes

- **`PropertyDef(BaseModel)`** — Single property definition for an entity.
- **`EntityDef(BaseModel)`** — Definition of a vertex collection (entity) in the ontology.
- **`DiscoveryRule(BaseModel)`** — Rule for discovering relationships between entities in source data.
- **`DiscoveryConfig(BaseModel)`** — Configuration for how relations are discovered in source data.
- **`RelationDef(BaseModel)`** — Definition of an edge collection (relation) in the ontology.
- **`EntityExtractionRule(BaseModel)`** — Rule describing how to extract and resolve a named entity from a query.
- **`AuthorizationRule(BaseModel)`** — Single declarative authorization rule for an intent pattern.
- **`AuthorizationSpec(BaseModel)`** — Declarative authorization specification for a traversal pattern.
- **`ToolCallSpec(BaseModel)`** — Specification for a tool invocation after graph traversal.
- **`TraversalPattern(BaseModel)`** — Predefined graph traversal pattern for a known query type.
- **`OntologyDefinition(BaseModel)`** — Root model for a single ontology YAML layer.
- **`MergedOntology(BaseModel)`** — Fully resolved ontology after merging all YAML layers.
- **`TenantContext(BaseModel)`** — Runtime context for a specific tenant.
- **`ResolvedIntent(BaseModel)`** — Result of intent resolution.
- **`EnrichedContext(BaseModel)`** — Enriched context returned by the ontology pipeline.
- **`ContextEnvelope(BaseModel)`** — Wraps EnrichedContext with state-specific fields for non-happy paths.
