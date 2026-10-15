# TASK-4328: ArangoOntologyGraphStore implements both contracts with typed traversals

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4327, TASK-4301
**Assigned-to**: unassigned

---

## Context

Spec §3 M8. `OntologyGraphStore` (graph_store.py:53) becomes `ArangoOntologyGraphStore(GraphDocumentStore, OntologyTraversalStore)`; typed ops use the AQL current call sites compose, verbatim.

---

## Scope

- Rename class; implement `is_reachable`, `get_document_by_id`, `find_by_field`, `search_by_name`, `execute_pattern`, `execute_query` with AQL moved verbatim from authorization.py:247-251/:334 and entity_resolver.py:370-375/:413-420.
- Rename `execute_traversal` → `_execute_aql`; keep TEMPORARY aliases `OntologyGraphStore = ArangoOntologyGraphStore` and `execute_traversal = _execute_aql` (removed by TASK-4332) so callers keep working between tasks.
- `ontology/__init__.py` lazy map exports `ArangoOntologyGraphStore` (and the temporary alias).
- Tests: golden captured AQL per typed op; dialect mismatch; pattern template selection.

**NOT in scope**: Migrating callers (TASK-4329/4330/4331/4332).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py` | MODIFY | rename + typed ops |
| `packages/ai-parrot/src/parrot/knowledge/ontology/__init__.py` | MODIFY | export |
| `packages/ai-parrot/tests/knowledge/ontology/test_arango_store_typed.py` | CREATE | typed op tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.ontology.contracts import DynamicQuery, GraphDocumentStore, OntologyTraversalStore  # TASK-4327
from parrot.knowledge.ontology.exceptions import QueryDialectMismatch, TraversalPatternUnavailable  # TASK-4327
```

### Existing Signatures to Use
```python
# graph_store.py: class OntologyGraphStore :53; __init__(arango_client=None) :69; execute_traversal(ctx, aql, bind_vars=None, collection_binds=None) :271
# authorization.py:247-251 management-chain AQL; :334 'RETURN DOCUMENT(@target_id).department'
# entity_resolver.py:370-375 exact AQL; :413-420 fuzzy AQL; _scope_filter :315
```

### Does NOT Exist
- ~~typed traversal methods today~~
- ~~`ArangoOntologyGraphStore` (created here)~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/ontology/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/ontology/test_arango_store_typed.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py#OntologyGraphStore"
  ]
}
```

---

## Implementation Notes

Capture the exact AQL strings + bind shapes into the test as goldens (`captured_aql`). Aliases are intra-feature scaffolding and MUST be deleted by TASK-4332.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Rename + aliases.
2. Typed ops with verbatim AQL.
3. execute_pattern/execute_query dialect rules.
4. Export.
5. Golden tests.

### `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class OntologyGraphStore:' parrot/knowledge/ontology/graph_store.py)
# AFTER/AT — anchor `class OntologyGraphStore:` (verified: graph_store.py:53)
# REPLACE with:
class ArangoOntologyGraphStore(GraphDocumentStore, OntologyTraversalStore):
    dialect: ClassVar[str] = "aql"
# FILL IN: rename execute_traversal -> _execute_aql; add typed ops (verbatim AQL); execute_pattern picks pattern.query_templates.get('aql') or pattern.query_template;
#          execute_query raises QueryDialectMismatch unless query.dialect == 'aql'
# AT MODULE END (temporary, removed by TASK-4332):
# OntologyGraphStore = ArangoOntologyGraphStore
# ArangoOntologyGraphStore.execute_traversal = ArangoOntologyGraphStore._execute_aql
```
**Why**: Callers migrate in later tasks without a broken intermediate state.

### `packages/ai-parrot/src/parrot/knowledge/ontology/__init__.py` (MODIFY)
```python
# occurrences: n/a — ontology/__init__.py becomes a lazy map in TASK-4301 (originally `from .graph_store import OntologyGraphStore` at :3)
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# ADD to the lazy map: "ArangoOntologyGraphStore": "parrot.knowledge.ontology.graph_store" (+ __all__)
```
**Why**: New public name.

### `packages/ai-parrot/tests/knowledge/ontology/test_arango_store_typed.py` (CREATE)
```python
"""Typed traversals issue the captured AQL (FEAT-540 M8)."""
import pytest

# FILL IN: mock client capturing execute_query(aql, bind_vars); assert each typed op's AQL equals the strings copied from authorization.py/entity_resolver.py;
# dialect mismatch; execute_pattern with query_templates['aql'] vs implicit query_template; TraversalPatternUnavailable
```
**Why**: Spec §4 test_typed_traversals_arango_aql_verbatim.

### FILL IN checklist
- [ ] typed op bodies
- [ ] pattern/query dialect logic
- [ ] aliases
- [ ] golden tests

---

## Acceptance Criteria

- [ ] store satisfies both contracts
- [ ] typed ops issue the captured AQL verbatim
- [ ] existing ontology graph-store tests pass via aliases

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/ontology/test_arango_store_typed.py -q`
- `pytest packages/ai-parrot/tests/knowledge/test_ontology_graph_store.py -q`

---

## Test Specification

```python
# see block
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug graphindex-core-seams --feature-id FEAT-540 --spec sdd/specs/graphindex-core-seams.spec.md --index sdd/tasks/index/graphindex-core-seams.json`)
2. **Read the spec** (`sdd/specs/graphindex-core-seams.spec.md`) — at least §2 and the module this task implements
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/graphindex-core-seams.json`
4. **Verify the Codebase Contract** — re-run `grep -c` for every anchor in the blueprint; a changed count means the
   anchor moved: re-locate it and fix the blueprint line before editing. A count of 0 means drift — stop and report.
5. **Update status** → `"in-progress"` (`started_at`) and commit only the index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:`; never change a fixed signature or path
7. **Validate** — `ruff check --fix <changed files>` and the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` (worktrees: the shared venv points at the main checkout)
8. **Commit code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close** with `scripts/sdd/close_task.sh TASK-4328 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
