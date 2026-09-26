---
id: F029
query_id: Q029
type: grep
intent: In-flight feature overlap in sdd/tasks/index/*.json for contracts|ontology|pageindex|responses.py|integrations/parser|graph_loader|bookstore; FEAT-539 status; FEAT-600 overlap
executed_at: 2026-09-24T23:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F029 — Only FEAT-539 (nearly done) and FEAT-540 (13 pending) overlap; FEAT-600 has no task index and touches only knowledge/wiki

## Summary
45 of the 489 index files match the pattern. Nearly all are completed. Three are still open and relevant: `contracts-card-ontology.json` (FEAT-539: 30 done, 1 done-with-issues TASK-3054, 1 in-progress TASK-3056 "Record Bob's twelve-case pilot acceptance", completed_at=null); `graphindex-core-seams.json` (FEAT-540: 13 pending; its spec makes `parrot/knowledge/ontology/__init__.py` a PEP 562 lazy root); and `profile-execution-schema-contract.json` (FEAT-596: 1 pending, matched only on the word "contracts"). FEAT-600 sql-schema-plane has a spec but NO `sdd/tasks/index/sql-schema-plane.json` yet; 17 task ids are reserved in 05d5664bd. Its spec touches only `knowledge/wiki/*` and `bots/database/models.py`, so it does not overlap contracts, ontology, pageindex or loaders.

## Citations
- path: `sdd/tasks/index/contracts-card-ontology.json`
  lines: 1-9
  symbol: FEAT-539
  excerpt: |
    "feature": "contracts-card-ontology", "feature_id": "FEAT-539",
    "completed_at": null,
    TASK-3054 done-with-issues Cross-store integration and regression acceptance
    TASK-3056 in-progress Record Bob's twelve-case pilot acceptance
- path: `sdd/tasks/index/graphindex-core-seams.json`
  lines: n/a
  symbol: FEAT-540
  excerpt: |
    {'pending': 13}
- path: `sdd/specs/graphindex-core-seams.spec.md`
  lines: 141-146, 210
  symbol: FEAT-540 lazy roots
  excerpt: |
    1. **Lazy package roots (PEP 562)** — `parrot/knowledge/ontology/__init__.py`
    | `parrot/knowledge/ontology/__init__.py` | modifies | PEP 562 lazy root; `TenantContext` et al. still importable from the package |
- path: `sdd/tasks/index/profile-execution-schema-contract.json`
  lines: n/a
  symbol: FEAT-596
  excerpt: |
    {'pending': 1}  # matched on the word "contracts" only
- path: `sdd/specs/sql-schema-plane.spec.md`
  lines: 161-168, 268
  symbol: FEAT-600 scope
  excerpt: |
    | `knowledge/wiki/store.py::SQLiteWikiStore` | extends | `SchemaStore` subclass ...
    - **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/schema/{__init__,models,ids,render,store}.py` (new); modifies `knowledge/wiki/project.py`, `bots/database/models.py`
- Other matching indexes are fully done (bookstore FEAT-533/531; pageindex FEAT-260/198/379/237/158/159; responses.py FEAT-273/124/197). Every-task-done but completed_at=null: FEAT-159, FEAT-225, FEAT-239, FEAT-240.

## Notes
- No index matched `integrations/parser` or `graph_loader`.
- Risk: FEAT-540 will restructure the ontology package root. New procedures code should import from submodules (`parrot.knowledge.ontology.schema`, `.graph_store`, `.tenant`) and not depend on eager `__init__` re-exports.
- Many "contracts" hits are generic uses of the word ("API contracts"), not the knowledge/contracts package.
