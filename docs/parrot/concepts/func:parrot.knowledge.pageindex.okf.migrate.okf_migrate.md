---
type: Concept
title: okf_migrate()
id: func:parrot.knowledge.pageindex.okf.migrate.okf_migrate
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Retrofit an existing PageIndex tree with OKF fields.
---

# okf_migrate

```python
async def okf_migrate(tree_name: str, tree_store: JSONTreeStore, content_store: NodeContentStore, adapter: Any, *, force_reclassify: bool=False) -> MigrationReport
```

Retrofit an existing PageIndex tree with OKF fields.

Steps:
1. Load authoritative JSON.
2. Assign concept_ids (idempotent, deterministic).
3. For each node: classify type (cached), build source, parse links.
4. Save enriched tree JSON.
5. Project sidecars (rename to concept_id keys).
6. Write root index.md.
7. Return MigrationReport.

Args:
    tree_name: Name of the PageIndex tree to migrate.
    tree_store: ``JSONTreeStore`` instance.
    content_store: ``NodeContentStore`` instance.
    adapter: LLM adapter for type classification, or ``None`` for fallback.
    force_reclassify: If ``True``, ignore existing type cache entries.

Returns:
    ``MigrationReport`` with migration statistics.
