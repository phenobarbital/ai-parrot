# TASK-4331: parrot_tools legal/procedures/contracts use execute_pattern / explicit Arango store

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4328, TASK-4329
**Assigned-to**: unassigned

---

## Context

Spec §3 M8 + §8 Q3. 12 `execute_traversal` call sites in parrot_tools; `aql_for()` returns AQL strings.

---

## Scope

- `procedures/retrieval.py`, `contracts/retrieval.py`: `aql_for` → `pattern_for` returning `TraversalPattern`; call `execute_pattern`.
- `legal/boe/queries.py` (2 sites): `execute_pattern`.
- `legal/wiki_store.py` (8 sites) + `legal/boe/sync.py`: construct `ArangoOntologyGraphStore`; `execute_query(ctx, DynamicQuery(dialect='aql', ...))` (explicitly Arango-bound, Q3 follow-up).
- Update tests: legal (conftest, test_wiki_store, test_temporal_resolution, test_boe_integration), contracts (test_authorization, test_retrieval), procedures (_doubles, test_toolkit, test_end_to_end, test_retrieval).

**NOT in scope**: Making legal portable (Q3 later).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/procedures/retrieval.py` | MODIFY | pattern_for |
| `packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py` | MODIFY | pattern_for |
| `packages/ai-parrot-tools/src/parrot_tools/legal/boe/queries.py` | MODIFY | execute_pattern |
| `packages/ai-parrot-tools/src/parrot_tools/legal/wiki_store.py` | MODIFY | explicit Arango store |
| `packages/ai-parrot-tools/src/parrot_tools/legal/boe/sync.py` | MODIFY | explicit Arango store |
| `packages/ai-parrot-tools/tests/legal/conftest.py` | MODIFY | doubles |
| `packages/ai-parrot-tools/tests/legal/test_wiki_store.py` | MODIFY | mocks |
| `packages/ai-parrot-tools/tests/legal/test_temporal_resolution.py` | MODIFY | mocks |
| `packages/ai-parrot-tools/tests/legal/test_boe_integration.py` | MODIFY | mocks |
| `packages/ai-parrot-tools/tests/contracts/test_authorization.py` | MODIFY | mocks |
| `packages/ai-parrot-tools/tests/contracts/test_retrieval.py` | MODIFY | pattern_for |
| `packages/ai-parrot-tools/tests/procedures/_doubles.py` | MODIFY | doubles |
| `packages/ai-parrot-tools/tests/procedures/test_toolkit.py` | MODIFY | mocks |
| `packages/ai-parrot-tools/tests/procedures/test_end_to_end.py` | MODIFY | mocks |
| `packages/ai-parrot-tools/tests/procedures/test_retrieval.py` | MODIFY | pattern_for |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.ontology.graph_store import ArangoOntologyGraphStore  # TASK-4328
from parrot.knowledge.ontology.contracts import DynamicQuery  # TASK-4327
```

### Existing Signatures to Use
```python
# procedures/retrieval.py: execute_traversal :292; def aql_for(self, pattern) -> str :311
# contracts/retrieval.py: def aql_for :681; execute_traversal :719
# legal/boe/queries.py: execute_traversal :72 (article_in_force), :176 (search); legal/wiki_store.py: OntologyGraphStore(arango_client=client) :209; 8 calls :265-486; legal/boe/sync.py:62
```

### Does NOT Exist
- ~~`pattern_for` today~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/procedures/retrieval.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/legal/boe/queries.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/legal/wiki_store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/legal/boe/sync.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/legal/conftest.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/legal/test_wiki_store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/legal/test_temporal_resolution.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/legal/test_boe_integration.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/contracts/test_authorization.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/contracts/test_retrieval.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/procedures/_doubles.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/procedures/test_toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/procedures/test_end_to_end.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/procedures/test_retrieval.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

Allowlist checks in `aql_for` (procedures/contracts) must keep rejecting unknown/unsafe patterns — move them into `pattern_for`.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. pattern_for in procedures/contracts.
2. boe/queries.
3. legal explicit store.
4. Tests.

### `packages/ai-parrot-tools/src/parrot_tools/procedures/retrieval.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def aql_for(self, pattern: str) -> str:' parrot_tools/procedures/retrieval.py)
# AFTER/AT — anchor `def aql_for(self, pattern: str) -> str:` (verified: retrieval.py:311)
# REPLACE with `def pattern_for(self, pattern: str) -> TraversalPattern:` keeping the allowlist; caller :292 -> execute_pattern
```
**Why**: Portable patterns.

### `packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def aql_for(self, pattern: str) -> str:' parrot_tools/contracts/retrieval.py)
# AFTER/AT — anchor `def aql_for(self, pattern: str) -> str:` (verified: retrieval.py:681)
# REPLACE with pattern_for; caller :719 -> execute_pattern
```
**Why**: Same.

### `packages/ai-parrot-tools/src/parrot_tools/legal/boe/queries.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c 'rows = await store.execute_traversal(' parrot_tools/legal/boe/queries.py)
# FILL IN: disambiguate — occurrences at lines [72, 176]; the target one is the occurrence both (:72, :176)
# REPLACE both with `rows = await store.execute_pattern(ctx, pattern, params, collection_binds)`
```
**Why**: Same.

### `packages/ai-parrot-tools/src/parrot_tools/legal/wiki_store.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'self._store = OntologyGraphStore(arango_client=client)' parrot_tools/legal/wiki_store.py)
# AFTER/AT — anchor `self._store = OntologyGraphStore(arango_client=client)` (verified: wiki_store.py:209)
# REPLACE with ArangoOntologyGraphStore(arango_client=client); FILL IN: 8 calls -> execute_query(self._ctx, DynamicQuery(dialect="aql", ...))
```
**Why**: Q3: explicitly Arango-bound.

### `packages/ai-parrot-tools/src/parrot_tools/legal/boe/sync.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'graph_store = OntologyGraphStore()' parrot_tools/legal/boe/sync.py)
# AFTER/AT — anchor `graph_store = OntologyGraphStore()` (verified: sync.py:62)
# REPLACE with ArangoOntologyGraphStore()
```
**Why**: Explicit.

### `packages/ai-parrot-tools/tests/legal/conftest.py` (MODIFY)
```python
# occurrences: n/a — re-grep execute_traversal|aql_for|OntologyGraphStore
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: replace execute_traversal/aql_for usage per the new API
```
**Why**: Follow API change.

### `packages/ai-parrot-tools/tests/legal/test_wiki_store.py` (MODIFY)
```python
# occurrences: n/a — re-grep execute_traversal|aql_for|OntologyGraphStore
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: replace execute_traversal/aql_for usage per the new API
```
**Why**: Follow API change.

### `packages/ai-parrot-tools/tests/legal/test_temporal_resolution.py` (MODIFY)
```python
# occurrences: n/a — re-grep execute_traversal|aql_for|OntologyGraphStore
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: replace execute_traversal/aql_for usage per the new API
```
**Why**: Follow API change.

### `packages/ai-parrot-tools/tests/legal/test_boe_integration.py` (MODIFY)
```python
# occurrences: n/a — re-grep execute_traversal|aql_for|OntologyGraphStore
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: replace execute_traversal/aql_for usage per the new API
```
**Why**: Follow API change.

### `packages/ai-parrot-tools/tests/contracts/test_authorization.py` (MODIFY)
```python
# occurrences: n/a — re-grep execute_traversal|aql_for|OntologyGraphStore
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: replace execute_traversal/aql_for usage per the new API
```
**Why**: Follow API change.

### `packages/ai-parrot-tools/tests/contracts/test_retrieval.py` (MODIFY)
```python
# occurrences: n/a — re-grep execute_traversal|aql_for|OntologyGraphStore
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: replace execute_traversal/aql_for usage per the new API
```
**Why**: Follow API change.

### `packages/ai-parrot-tools/tests/procedures/_doubles.py` (MODIFY)
```python
# occurrences: n/a — re-grep execute_traversal|aql_for|OntologyGraphStore
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: replace execute_traversal/aql_for usage per the new API
```
**Why**: Follow API change.

### `packages/ai-parrot-tools/tests/procedures/test_toolkit.py` (MODIFY)
```python
# occurrences: n/a — re-grep execute_traversal|aql_for|OntologyGraphStore
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: replace execute_traversal/aql_for usage per the new API
```
**Why**: Follow API change.

### `packages/ai-parrot-tools/tests/procedures/test_end_to_end.py` (MODIFY)
```python
# occurrences: n/a — re-grep execute_traversal|aql_for|OntologyGraphStore
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: replace execute_traversal/aql_for usage per the new API
```
**Why**: Follow API change.

### `packages/ai-parrot-tools/tests/procedures/test_retrieval.py` (MODIFY)
```python
# occurrences: n/a — re-grep execute_traversal|aql_for|OntologyGraphStore
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: replace execute_traversal/aql_for usage per the new API
```
**Why**: Follow API change.

### FILL IN checklist
- [ ] pattern_for with allowlist
- [ ] legal 8 call sites
- [ ] ten test files

---

## Acceptance Criteria

- [ ] no `execute_traversal` / `aql_for` in parrot_tools src
- [ ] legal/contracts/procedures suites pass

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/legal/test_wiki_store.py -q`
- `pytest packages/ai-parrot-tools/tests/legal/test_temporal_resolution.py -q`
- `pytest packages/ai-parrot-tools/tests/contracts/test_retrieval.py -q`
- `pytest packages/ai-parrot-tools/tests/contracts/test_authorization.py -q`
- `pytest packages/ai-parrot-tools/tests/procedures/test_retrieval.py -q`
- `pytest packages/ai-parrot-tools/tests/procedures/test_toolkit.py -q`
- `pytest packages/ai-parrot-tools/tests/procedures/test_end_to_end.py -q`

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
9. **Close** with `scripts/sdd/close_task.sh TASK-4331 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: codex gpt-5.6-terra (attempt 1d8637b5), consolidated by sdd-worker
**Date**: 2026-10-15
**Notes**: parrot_tools consumers (procedures/retrieval.py, legal wiki/temporal paths, contracts) and their tests migrated to the typed ontology store API / `query` + `dialect` fields (15 files). All seven task validation files run directly: wiki_store 13, temporal_resolution 9, contracts/test_retrieval 41, contracts/test_authorization 18, procedures/test_retrieval 8, test_toolkit 6, test_end_to_end 2 — all passed; ruff F821/F401 clean on the changed sources. No live Arango. No review corrections.

**Deviations from spec**: none.
