# TASK-4332: Remove the temporary OntologyGraphStore/execute_traversal aliases; migrate remaining tests

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4328, TASK-4329, TASK-4330, TASK-4331, TASK-4318, TASK-4320
**Assigned-to**: unassigned

---

## Context

Spec §7 hard cuts. TASK-4328 left `OntologyGraphStore` and `execute_traversal` aliases so callers could migrate in separate tasks; this task deletes them.

---

## Scope

- Delete both aliases from graph_store.py and the alias from ontology/__init__.py.
- Migrate remaining test references: test_concept_authority_e2e, test_ontology_integration, test_ontology_graph_store, test_entity_extraction_e2e, fixtures/concept_authority/conftest.py, test_ontology_refresh, ontology/test_search_views, _support/graph.py, contracts/test_integration, contracts/test_graph_loader, contracts/test_ontology_domain, manuals/test_support_smoke, graphindex/test_loader, graphindex/test_persist, graphindex/test_persist_commit_protocol.
- `grep -rn 'execute_traversal\|OntologyGraphStore\b' packages/*/src packages/*/tests` returns nothing.

**NOT in scope**: New behaviour.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py` | MODIFY | remove aliases |
| `packages/ai-parrot/src/parrot/knowledge/ontology/__init__.py` | MODIFY | remove alias export |
| `packages/ai-parrot/tests/knowledge/test_concept_authority_e2e.py` | MODIFY | migrate |
| `packages/ai-parrot/tests/knowledge/test_ontology_integration.py` | MODIFY | migrate |
| `packages/ai-parrot/tests/knowledge/test_ontology_graph_store.py` | MODIFY | migrate |
| `packages/ai-parrot/tests/knowledge/test_entity_extraction_e2e.py` | MODIFY | migrate |
| `packages/ai-parrot/tests/knowledge/fixtures/concept_authority/conftest.py` | MODIFY | migrate |
| `packages/ai-parrot/tests/knowledge/test_ontology_refresh.py` | MODIFY | migrate |
| `packages/ai-parrot/tests/knowledge/ontology/test_search_views.py` | MODIFY | migrate |
| `packages/ai-parrot/tests/knowledge/_support/graph.py` | MODIFY | migrate |
| `packages/ai-parrot/tests/knowledge/contracts/test_integration.py` | MODIFY | migrate |
| `packages/ai-parrot/tests/knowledge/contracts/test_graph_loader.py` | MODIFY | migrate |
| `packages/ai-parrot/tests/knowledge/contracts/test_ontology_domain.py` | MODIFY | migrate |
| `packages/ai-parrot/tests/knowledge/manuals/test_support_smoke.py` | MODIFY | migrate |
| `packages/ai-parrot/tests/knowledge/graphindex/test_loader.py` | MODIFY | migrate |
| `packages/ai-parrot/tests/knowledge/graphindex/test_persist.py` | MODIFY | migrate |
| `packages/ai-parrot/tests/knowledge/graphindex/test_persist_commit_protocol.py` | MODIFY | migrate |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.ontology.graph_store import ArangoOntologyGraphStore  # TASK-4328
```

### Existing Signatures to Use
```python
# aliases appended at the end of graph_store.py by TASK-4328
```

### Does NOT Exist
- ~~`OntologyGraphStore` / `execute_traversal` after this task~~

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
      "path": "packages/ai-parrot/tests/knowledge/test_concept_authority_e2e.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/test_ontology_integration.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/test_ontology_graph_store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/test_entity_extraction_e2e.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/fixtures/concept_authority/conftest.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/test_ontology_refresh.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/ontology/test_search_views.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/_support/graph.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/contracts/test_integration.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/contracts/test_graph_loader.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/contracts/test_ontology_domain.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/manuals/test_support_smoke.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/graphindex/test_loader.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/graphindex/test_persist.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/graphindex/test_persist_commit_protocol.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

Pure rename/migration; run the whole knowledge ontology/contracts/manuals test set touched here.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Delete aliases.
2. Migrate tests.
3. grep must be empty.

### `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py` (MODIFY)
```python
# occurrences: n/a — aliases added by TASK-4328
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# DELETE the two alias lines at module end
```
**Why**: Hard cut complete.

### `packages/ai-parrot/src/parrot/knowledge/ontology/__init__.py` (MODIFY)
```python
# occurrences: n/a — lazy map from TASK-4301/4328
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# DELETE the OntologyGraphStore entry from the lazy map and __all__
```
**Why**: Same.

### `packages/ai-parrot/tests/knowledge/test_concept_authority_e2e.py` (MODIFY)
```python
# occurrences: n/a — re-grep
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: OntologyGraphStore -> ArangoOntologyGraphStore; execute_traversal mocks -> typed ops / _execute_aql
```
**Why**: Follow hard cut.

### `packages/ai-parrot/tests/knowledge/test_ontology_integration.py` (MODIFY)
```python
# occurrences: n/a — re-grep
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: OntologyGraphStore -> ArangoOntologyGraphStore; execute_traversal mocks -> typed ops / _execute_aql
```
**Why**: Follow hard cut.

### `packages/ai-parrot/tests/knowledge/test_ontology_graph_store.py` (MODIFY)
```python
# occurrences: n/a — re-grep
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: OntologyGraphStore -> ArangoOntologyGraphStore; execute_traversal mocks -> typed ops / _execute_aql
```
**Why**: Follow hard cut.

### `packages/ai-parrot/tests/knowledge/test_entity_extraction_e2e.py` (MODIFY)
```python
# occurrences: n/a — re-grep
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: OntologyGraphStore -> ArangoOntologyGraphStore; execute_traversal mocks -> typed ops / _execute_aql
```
**Why**: Follow hard cut.

### `packages/ai-parrot/tests/knowledge/fixtures/concept_authority/conftest.py` (MODIFY)
```python
# occurrences: n/a — re-grep
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: OntologyGraphStore -> ArangoOntologyGraphStore; execute_traversal mocks -> typed ops / _execute_aql
```
**Why**: Follow hard cut.

### `packages/ai-parrot/tests/knowledge/test_ontology_refresh.py` (MODIFY)
```python
# occurrences: n/a — re-grep
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: OntologyGraphStore -> ArangoOntologyGraphStore; execute_traversal mocks -> typed ops / _execute_aql
```
**Why**: Follow hard cut.

### `packages/ai-parrot/tests/knowledge/ontology/test_search_views.py` (MODIFY)
```python
# occurrences: n/a — re-grep
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: OntologyGraphStore -> ArangoOntologyGraphStore; execute_traversal mocks -> typed ops / _execute_aql
```
**Why**: Follow hard cut.

### `packages/ai-parrot/tests/knowledge/_support/graph.py` (MODIFY)
```python
# occurrences: n/a — re-grep
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: OntologyGraphStore -> ArangoOntologyGraphStore; execute_traversal mocks -> typed ops / _execute_aql
```
**Why**: Follow hard cut.

### `packages/ai-parrot/tests/knowledge/contracts/test_integration.py` (MODIFY)
```python
# occurrences: n/a — re-grep
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: OntologyGraphStore -> ArangoOntologyGraphStore; execute_traversal mocks -> typed ops / _execute_aql
```
**Why**: Follow hard cut.

### `packages/ai-parrot/tests/knowledge/contracts/test_graph_loader.py` (MODIFY)
```python
# occurrences: n/a — re-grep
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: OntologyGraphStore -> ArangoOntologyGraphStore; execute_traversal mocks -> typed ops / _execute_aql
```
**Why**: Follow hard cut.

### `packages/ai-parrot/tests/knowledge/contracts/test_ontology_domain.py` (MODIFY)
```python
# occurrences: n/a — re-grep
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: OntologyGraphStore -> ArangoOntologyGraphStore; execute_traversal mocks -> typed ops / _execute_aql
```
**Why**: Follow hard cut.

### `packages/ai-parrot/tests/knowledge/manuals/test_support_smoke.py` (MODIFY)
```python
# occurrences: n/a — re-grep
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: OntologyGraphStore -> ArangoOntologyGraphStore; execute_traversal mocks -> typed ops / _execute_aql
```
**Why**: Follow hard cut.

### `packages/ai-parrot/tests/knowledge/graphindex/test_loader.py` (MODIFY)
```python
# occurrences: n/a — re-grep
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: OntologyGraphStore -> ArangoOntologyGraphStore; execute_traversal mocks -> typed ops / _execute_aql
```
**Why**: Follow hard cut.

### `packages/ai-parrot/tests/knowledge/graphindex/test_persist.py` (MODIFY)
```python
# occurrences: n/a — re-grep
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: OntologyGraphStore -> ArangoOntologyGraphStore; execute_traversal mocks -> typed ops / _execute_aql
```
**Why**: Follow hard cut.

### `packages/ai-parrot/tests/knowledge/graphindex/test_persist_commit_protocol.py` (MODIFY)
```python
# occurrences: n/a — re-grep
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: OntologyGraphStore -> ArangoOntologyGraphStore; execute_traversal mocks -> typed ops / _execute_aql
```
**Why**: Follow hard cut.

### FILL IN checklist
- [ ] alias deletion
- [ ] fifteen test migrations
- [ ] empty grep

---

## Acceptance Criteria

- [ ] no `OntologyGraphStore`/`execute_traversal` anywhere
- [ ] all migrated tests pass

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/test_ontology_graph_store.py -q`
- `pytest packages/ai-parrot/tests/knowledge/test_concept_authority_e2e.py -q`
- `pytest packages/ai-parrot/tests/knowledge/test_ontology_integration.py -q`
- `pytest packages/ai-parrot/tests/knowledge/test_entity_extraction_e2e.py -q`
- `pytest packages/ai-parrot/tests/knowledge/contracts/test_integration.py -q`
- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_loader.py -q`

---

## Test Specification

```python
# existing tests updated
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
9. **Close** with `scripts/sdd/close_task.sh TASK-4332 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
