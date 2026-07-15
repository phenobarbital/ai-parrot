---
type: Wiki Entity
title: ConceptCatalogService
id: class:parrot.knowledge.ontology.concept_catalog.service.ConceptCatalogService
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Operational truth for per-tenant Concept entities and is_a edges.
---

# ConceptCatalogService

Defined in [`parrot.knowledge.ontology.concept_catalog.service`](../summaries/mod:parrot.knowledge.ontology.concept_catalog.service.md).

```python
class ConceptCatalogService
```

Operational truth for per-tenant Concept entities and is_a edges.

All state-changing calls follow strict transactional discipline:
  1. SELECT ... FOR UPDATE row lock.
  2. Validate transition (state machine + invariants).
  3. UPDATE row.
  4. INSERT audit row.
  5. INSERT outbox row.
All within a single transaction.

Args:
    pg_pool: asyncpg connection pool.

## Methods

- `async def propose_concept(self, tenant_id: str, slug: str, label: str, asserted_by: str, synonyms: list[str] | None=None, description: str | None=None, domain: str | None=None, rationale: str | None=None) -> UUID` — Propose a new Concept entity.
- `async def propose_isa_edge(self, tenant_id: str, child_id: UUID, parent_tier: Literal['framework', 'tenant'], parent_ref: str, asserted_by: str, rationale: str | None=None) -> UUID` — Propose a new is_a (sub-class) edge.
- `async def submit_for_review(self, target_id: UUID, target_kind: str, actor: str) -> None` — Submit a proposed concept or edge for review.
- `async def approve(self, target_id: UUID, target_kind: str, actor: str, reason: str | None=None) -> None` — Approve a proposed or pending_review concept/edge.
- `async def reject(self, target_id: UUID, target_kind: str, actor: str, reason: str | None=None) -> None` — Reject a proposed or pending_review concept/edge.
- `async def deprecate(self, target_id: UUID, target_kind: str, actor: str, reason: str | None=None) -> CascadeAlert | None` — Deprecate an approved concept or edge.
- `async def restore(self, target_id: UUID, target_kind: str, actor: str, reason: str | None=None) -> None` — Restore a deprecated or rejected concept/edge to proposed state.
- `async def modify_metadata(self, concept_id: UUID, actor: str, synonyms: list[str] | None=None, description: str | None=None, domain: str | None=None) -> None` — Update mutable metadata on an approved concept (synonyms, description, domain).
- `async def get_live_concepts(self, tenant_id: str, domain: str | None=None) -> list[ConceptRow]` — Return all approved concepts for a tenant.
- `async def get_concept_by_id(self, tenant_id: str, concept_id: UUID) -> ConceptRow | None` — Fetch a single concept by its primary key.
- `async def get_isa_subgraph(self, tenant_id: str, concept_id: UUID) -> dict[str, Any]` — Return the is_a ancestor/descendant subgraph for a concept.
- `async def get_history(self, target_id: UUID, target_kind: str) -> list[dict[str, Any]]` — Return the audit trail for a concept or isa_edge.
