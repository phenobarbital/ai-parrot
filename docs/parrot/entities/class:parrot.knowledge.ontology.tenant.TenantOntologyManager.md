---
type: Wiki Entity
title: TenantOntologyManager
id: class:parrot.knowledge.ontology.tenant.TenantOntologyManager
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Resolve and cache merged ontology per tenant.
---

# TenantOntologyManager

Defined in [`parrot.knowledge.ontology.tenant`](../summaries/mod:parrot.knowledge.ontology.tenant.md).

```python
class TenantOntologyManager
```

Resolve and cache merged ontology per tenant.

Resolution process:
    1. Start with the base ontology (ONTOLOGY_BASE_FILE).
    2. If a domain is specified, layer the domain ontology.
    3. Layer the client-specific ontology on top.
    4. Merge all layers via OntologyMerger.
    5. Cache the result in memory (invalidated on CRON refresh).

Args:
    ontology_dir: Base directory for ontology YAML files.
    base_file: Filename of the base ontology.
    domains_dir: Subdirectory for domain ontologies.
    clients_dir: Subdirectory for client ontologies.
    db_template: ArangoDB database name template ({tenant} placeholder).
    pgvector_schema_template: PgVector schema name template.

## Methods

- `def resolve(self, tenant_id: str, domain: str | None=None) -> TenantContext` — Resolve the merged ontology for a tenant.
- `def invalidate(self, tenant_id: str | None=None) -> None` — Invalidate cached ontology for a tenant or all tenants.
- `def list_tenants(self) -> list[str]` — Return list of currently cached tenant IDs.
- `async def resolve_with_overlay(self, tenant_id: str, domain: str | None=None) -> TenantContext` — Resolve ontology composing YAML chain + PG overlay (async).
