# TASK-4323: WikiBackendSpec registry in wiki/store.py; backend-neutral namespace dispatch

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4312
**Assigned-to**: unassigned

---

## Context

Spec §2 wiki/store.py + absorbed FEAT-670 S1/S8. `create_wiki_store` (store.py:2665) branches by name; `federation.py:418-425` passes `arango_params` to every extra backend.

---

## Scope

- Add `WikiBackendSpec`, built-in table (sqlite/memory local; arangodb/postgres server), `wiki_backend_names`, `wiki_backend_spec`, `resolve_wiki_backend`, `is_server_backend`; extend `register_wiki_backend(name, factory, *, kind='server', resolve_options=None)`.
- `create_wiki_store` dispatches through the table (behaviour identical for the four built-ins).
- `open_namespace_store`: `spec.resolve_options(cfg)` instead of `arango_params` for non-Arango backends.
- Tests.

**NOT in scope**: Config Literals / is_built (TASK-4324); CLI choices (TASK-4325).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | WikiBackendSpec + table |
| `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` | MODIFY | dispatch |
| `packages/ai-parrot/tests/knowledge/wiki/test_wiki_backend_spec.py` | CREATE | registry tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.graphindex.pg_schema import resolve_pg_settings  # TASK-4312 (lazy, inside the postgres factory)
```

### Existing Signatures to Use
```python
# store.py: _EXTRA_BACKENDS :529; register_wiki_backend(name, factory) :539; create_wiki_store(storage_dir, wiki_name='', backend='sqlite', **kwargs) :2665 (branches :2707-2745)
# federation.py: factory = wiki_store._EXTRA_BACKENDS.get(cfg.backend) :418; arango_params=resolve_arango_params(_arango_config_for(cfg)) :425
# parrot_tools/legal/__init__.py:16-20 register_wiki_backend('ontology_legal', OntologyLegalWikiStore.factory)
```

### Does NOT Exist
- ~~`WikiBackendSpec`, `wiki_backend_names`, `resolve_wiki_backend`, `is_server_backend` (created here)~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/federation.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_wiki_backend_spec.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#create_wiki_store",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#register_wiki_backend"
  ]
}
```

---

## Implementation Notes

`parrot_tools.legal` registers with the old two-arg signature — keep it valid (default kind='server', resolve_options falls back to Arango params for backward compatibility of that one satellite).

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Spec model + table — *why*: S1.
2. create_wiki_store via table.
3. Namespace dispatch — *why*: S8.
4. Tests.

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def register_wiki_backend(name: str, factory: Callable[..., BaseWikiStore]) -> None:' parrot/knowledge/wiki/store.py)
# AFTER/AT — anchor `def register_wiki_backend(name: str, factory: Callable[..., BaseWikiStore]) -> None:` (verified: store.py:539)
# INSERT ABOVE register_wiki_backend:
class WikiBackendSpec(BaseModel):
    """One wiki backend (spec §2)."""

    name: str
    kind: Literal["local", "server"]
    factory: str
    resolve_options: str | None = None
    is_built: str | None = None
    extra: str | None = None


# FILL IN: _BUILTIN_WIKI_BACKENDS for sqlite/memory/arangodb/postgres; wiki_backend_names(); wiki_backend_spec(name);
#          resolve_wiki_backend(name) -> factory callable; is_server_backend(name); register_wiki_backend(..., kind, resolve_options)
# FILL IN: create_wiki_store body -> resolve_wiki_backend(backend)(storage_dir=storage_dir, wiki_name=wiki_name, **kwargs)
```
**Why**: Registry replaces name branches; error text still lists known backends.

### `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'factory = wiki_store._EXTRA_BACKENDS.get(cfg.backend)' parrot/knowledge/wiki/federation.py)
# AFTER/AT — anchor `factory = wiki_store._EXTRA_BACKENDS.get(cfg.backend)` (verified: federation.py:418)
# REPLACE with:
        factory = resolve_wiki_backend(cfg.backend)
# FILL IN: options = spec.resolve_options(cfg) if set else (arango params for the legacy satellite only)
```
**Why**: S8.

### `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'arango_params=resolve_arango_params(_arango_config_for(cfg)),' parrot/knowledge/wiki/federation.py)
# AFTER/AT — anchor `arango_params=resolve_arango_params(_arango_config_for(cfg)),` (verified: federation.py:425)
# REPLACE with `**options,` from the spec's resolve_options
```
**Why**: Never Arango params to another backend.

### `packages/ai-parrot/tests/knowledge/wiki/test_wiki_backend_spec.py` (CREATE)
```python
"""Wiki backend registry (FEAT-540 M7)."""

from parrot.knowledge.wiki.store import is_server_backend, wiki_backend_names


def test_builtins() -> None:
    assert {"sqlite", "memory", "arangodb", "postgres"} <= set(wiki_backend_names())
    assert is_server_backend("arangodb") and not is_server_backend("sqlite")

# FILL IN: registered server backend gets resolve_options(cfg), not arango_params; legacy 2-arg register still works
```
**Why**: Spec §4.

### FILL IN checklist
- [ ] built-in table
- [ ] registry functions
- [ ] create_wiki_store + federation dispatch
- [ ] tests

---

## Acceptance Criteria

- [ ] create_wiki_store behaviour unchanged for built-ins
- [ ] namespace dispatch passes resolve_options
- [ ] existing `test_extra_backends.py` and federation tests pass

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_wiki_backend_spec.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_extra_backends.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py -q`

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
9. **Close** with `scripts/sdd/close_task.sh TASK-4323 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
