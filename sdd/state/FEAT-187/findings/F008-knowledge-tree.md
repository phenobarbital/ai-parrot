---
id: F008
query: Q009, Q011
type: tree+grep
target: packages/ai-parrot/src/parrot/knowledge/
---

# F008 — Knowledge Module Tree and Anti-Hallucination Check

**Status**: Confirmed

## Directory structure
```
packages/ai-parrot/src/parrot/knowledge/
└── ontology/
    ├── __init__.py
    ├── schema.py, parser.py, discovery.py, graph_store.py
    ├── refresh.py, validators.py, intent.py, authorization.py
    ├── tool_dispatcher.py, concept_embedding.py, entity_resolver.py
    ├── mixin.py, cache.py, exceptions.py, merger.py, tenant.py
    ├── defaults/
    │   └── domains/
    ├── concept_catalog/
    │   └── __init__.py, http.py, models.py, reconcile.py, seed.py, service.py, worker.py
    └── schema_overlay/
        └── __init__.py, http.py, models.py, service.py, validator.py, worker.py
```

## Anti-hallucination check
- `graphindex` directory does NOT exist under knowledge/
- `grep -r "graphindex" packages/ai-parrot/src/parrot/` → zero matches
- Clean namespace confirmed

## Recent additions (FEAT-158, FEAT-concept-authority)
- concept_catalog/ — concept seed, reconciliation, HTTP routes
- schema_overlay/ — schema validation, overlay service
- concept_embedding.py, entity_resolver.py, tool_dispatcher.py, authorization.py
