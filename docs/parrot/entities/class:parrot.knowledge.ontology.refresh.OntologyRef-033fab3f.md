---
type: Wiki Entity
title: OntologyRefreshPipeline
id: class:parrot.knowledge.ontology.refresh.OntologyRefreshPipeline
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: CRON-triggered pipeline that keeps the ontology graph in sync.
---

# OntologyRefreshPipeline

Defined in [`parrot.knowledge.ontology.refresh`](../summaries/mod:parrot.knowledge.ontology.refresh.md).

```python
class OntologyRefreshPipeline
```

CRON-triggered pipeline that keeps the ontology graph in sync.

Runs per-tenant and performs delta sync: only changed data is processed.

Args:
    tenant_manager: TenantOntologyManager instance.
    graph_store: OntologyGraphStore instance.
    discovery: RelationDiscovery instance.
    datasource_factory: DataSourceFactory instance.
    cache: OntologyCache instance.
    vector_store: Optional PgVector store for embedding sync.
    source_configs: Optional dict mapping source names to config dicts.

## Methods

- `async def run(self, tenant_id: str, domain: str | None=None) -> RefreshReport` — Execute the full refresh pipeline for a tenant.
