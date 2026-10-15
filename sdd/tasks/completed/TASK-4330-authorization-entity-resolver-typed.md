# TASK-4330: AuthorizationChecker and EntityResolver call typed traversals

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4328
**Assigned-to**: unassigned

---

## Context

Spec §3 M8. Core composes AQL inline: authorization.py:247-262/:334-345, entity_resolver.py:370-386/:413-429; contexts fabricated with synthetic Arango names.

---

## Scope

- Replace the four `execute_traversal` calls with typed ops; delete the AQL strings from these modules.
- `_scope_filter` returns a filters mapping instead of an AQL clause.
- Constructors typed `OntologyTraversalStore`; centralise the synthetic `TenantContext` fabrication in one helper.
- Update test_authorization.py, test_entity_resolver.py (mocks).

**NOT in scope**: Security policy changes — semantics must be identical (adversarial review mandatory).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py` | MODIFY | typed ops |
| `packages/ai-parrot/src/parrot/knowledge/ontology/entity_resolver.py` | MODIFY | typed ops |
| `packages/ai-parrot/tests/knowledge/test_authorization.py` | MODIFY | mocks |
| `packages/ai-parrot/tests/knowledge/test_entity_resolver.py` | MODIFY | mocks |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.ontology.contracts import OntologyTraversalStore  # TASK-4327 (TYPE_CHECKING)
```

### Existing Signatures to Use
```python
# authorization.py: import :39; class AuthorizationChecker :43; __init__(graph_store) :53-58; calls :257 (management chain), :339 (department)
# entity_resolver.py: import :25; class EntityResolver :93; __init__ :116-122; _scope_filter :315; calls :384 (exact), :427 (fuzzy)
```

### Does NOT Exist
- ~~AQL text in these modules after this task~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/ontology/entity_resolver.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/test_authorization.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/test_entity_resolver.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py#AuthorizationChecker",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/entity_resolver.py#EntityResolver"
  ]
}
```

---

## Implementation Notes

Keep exception handling (log + continue) exactly as today. `same_department` scope → `filters={'department': dept}`.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. authorization typed ops.
2. entity_resolver typed ops + filters.
3. Tests.

### `packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c 'results = await self._graph_store.execute_traversal(' parrot/knowledge/ontology/authorization.py)
# FILL IN: disambiguate — occurrences at lines [257, 339]; the target one is the occurrence at :257 (preceded by bind_vars with asker_id) — the department call at :339 becomes get_document_by_id(...)['department']
# REPLACE the management-chain call with:
#   results = await self._graph_store.is_reachable(ctx, user_id, target_id, edge_collection=self._reports_to, max_depth=10)
# and delete the AQL string above it
```
**Why**: Same semantics, no AQL.

### `packages/ai-parrot/src/parrot/knowledge/ontology/entity_resolver.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c 'return await self._graph_store.execute_traversal(' parrot/knowledge/ontology/entity_resolver.py)
# FILL IN: disambiguate — occurrences at lines [384, 427]; the target one is the occurrence :384 is _exact_id_match, :427 is _fuzzy_name_match — replace both
# REPLACE exact match with find_by_field(ctx, collection, key_field, mention, filters=..., limit=2)
# and fuzzy with search_by_name(ctx, collection, mention, filters=..., limit=10)
```
**Why**: Typed ops.

### `packages/ai-parrot/tests/knowledge/test_authorization.py` (MODIFY)
```python
# occurrences: n/a — re-grep `execute_traversal`
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: mock is_reachable/get_document_by_id instead of execute_traversal
```
**Why**: Follow.

### `packages/ai-parrot/tests/knowledge/test_entity_resolver.py` (MODIFY)
```python
# occurrences: n/a — re-grep `execute_traversal`
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: mock find_by_field/search_by_name
```
**Why**: Follow.

### FILL IN checklist
- [ ] four call replacements
- [ ] scope filters mapping
- [ ] context helper
- [ ] test mocks

---

## Acceptance Criteria

- [ ] `grep -n 'FOR \|RETURN ' authorization.py entity_resolver.py` empty
- [ ] authorization/entity-resolver tests pass

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/test_authorization.py -q`
- `pytest packages/ai-parrot/tests/knowledge/test_entity_resolver.py -q`

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
9. **Close** with `scripts/sdd/close_task.sh TASK-4330 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: codex gpt-5.6-terra (attempt b373c5a7), consolidated by sdd-worker
**Date**: 2026-10-15
**Notes**: ontology authorization.py and entity_resolver.py migrated off `execute_traversal(aql=...)` to the typed OntologyTraversalStore operations (4 files; tests test_authorization/test_entity_resolver updated). Validation run directly: test_authorization + test_entity_resolver + tests/knowledge/ontology + mixin + degradation_chain = 276 passed; ruff F821/F401 clean; no remaining `execute_traversal` callers outside graph_store.py (alias deleted by TASK-4332). No live Arango. No review corrections.

**Deviations from spec**: none.
