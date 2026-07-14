---
type: Wiki Entity
title: SchemaOverlayService
id: class:parrot.knowledge.ontology.schema_overlay.service.SchemaOverlayService
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Operational truth for per-tenant schema overlays.
---

# SchemaOverlayService

Defined in [`parrot.knowledge.ontology.schema_overlay.service`](../summaries/mod:parrot.knowledge.ontology.schema_overlay.service.md).

```python
class SchemaOverlayService
```

Operational truth for per-tenant schema overlays.

Args:
    pg_pool: asyncpg connection pool.
    tenant_manager: ``TenantOntologyManager`` for dry-run YAML resolution.
    merger: ``OntologyMerger`` instance used in dry-runs.

## Methods

- `async def propose(self, tenant_id: str, overlay_kind: str, name: str, definition: dict[str, Any], asserted_by: str, rationale: str | None=None) -> UUID` — Create a new schema overlay in ``proposed`` state.
- `async def submit(self, overlay_id: UUID, actor: str) -> None` — Transition overlay to ``pending_review``.
- `async def approve(self, overlay_id: UUID, actor: str, reason: str | None=None) -> None` — Approve a schema overlay — dry-run gate is mandatory.
- `async def reject(self, overlay_id: UUID, actor: str, reason: str | None=None) -> None` — Reject an overlay from proposed or pending_review.
- `async def deprecate(self, overlay_id: UUID, actor: str, reason: str | None=None) -> None` — Deprecate an approved overlay.
- `async def restore(self, overlay_id: UUID, actor: str) -> None` — Restore a deprecated or rejected overlay to proposed.
- `async def get_pending(self, tenant_id: str) -> list[SchemaOverlayRow]` — Return overlay rows in ``proposed`` or ``pending_review`` state.
- `async def get_overlay_by_id(self, tenant_id: str, overlay_id: UUID) -> SchemaOverlayRow | None` — Fetch a single schema overlay by primary key, scoped to tenant.
- `async def get_approved(self, tenant_id: str) -> list[SchemaOverlayRow]` — Return overlay rows in ``approved`` state for ontology composition.
- `async def get_history(self, overlay_id: UUID) -> list[dict[str, Any]]` — Return the audit trail for an overlay, newest first.
