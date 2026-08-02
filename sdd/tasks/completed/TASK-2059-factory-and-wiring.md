# TASK-2059: Extend Factory + Toolkit Wiring for ArangoDB

**Feature**: FEAT-400 — WikiToolkit ArangoDB Backend
**Spec**: `sdd/specs/wikitoolkit-arangodb-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2057, TASK-2058
**Assigned-to**: unassigned

---

## Context

Wires the new `ArangoDBWikiStore` into the factory function and toolkit
initialization. Corresponds to Module 3 in the spec. After this task,
`create_wiki_store(backend="arangodb")` returns a working store and
`LLMWikiToolkit` can be instantiated with an ArangoDB backend.

---

## Scope

- Extend `create_wiki_store()` in `store.py` with an `elif backend == "arangodb"` branch.
- Update `LLMWikiToolkit.__init__` in `toolkit.py` to create `ArangoDBWikiStore`
  and wire the arangodb `SourceCollectionManager` when `storage_backend == "arangodb"`.
- Add `ArangoDBWikiStore` to `_EXPORT_MODULES` in `__init__.py`.
- Write tests for the factory branch.

**NOT in scope**:
- ArangoDBWikiStore implementation (TASK-2057)
- Config changes (TASK-2058)
- SourceCollectionManager arangodb backend (TASK-2060)
- CLI changes (TASK-2061)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | Add `"arangodb"` branch to `create_wiki_store()` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` | MODIFY | Add arangodb wiring in `__init__` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/__init__.py` | MODIFY | Export `ArangoDBWikiStore` |
| `tests/knowledge/wiki/test_factory_arango.py` | CREATE | Factory branch tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.store import create_wiki_store, BaseWikiStore  # verified: store.py:1197, 279
from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore  # CREATED BY TASK-2057
from parrot.knowledge.wiki.project import resolve_arango_params  # CREATED BY TASK-2058
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
def create_wiki_store(storage_dir: str | Path, wiki_name: str = "",
    backend: str = "sqlite") -> BaseWikiStore: ...                      # line 1197

# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py
class LLMWikiToolkit:
    def __init__(self, pageindex_toolkit, graphindex_toolkit, okf_toolkit,
        config: WikiConfig, agent_id: str = "agent", **kwargs) -> None: ...  # line 75
    # Store creation: lines 105-109
    # Sources creation: lines 110-118

# packages/ai-parrot/src/parrot/knowledge/wiki/__init__.py
_EXPORT_MODULES: dict[str, str] = {
    "BaseWikiStore": "parrot.knowledge.wiki.store",          # line 65
    "WikiStore": "parrot.knowledge.wiki.store",              # line 66
    "SQLiteWikiStore": "parrot.knowledge.wiki.store",        # line 67
    "InMemoryWikiStore": "parrot.knowledge.wiki.file_store", # line 68
    "create_wiki_store": "parrot.knowledge.wiki.store",      # line 69
    # ... other exports
}
```

### Does NOT Exist

- ~~`create_wiki_store(backend="arangodb")`~~ — not handled yet; this task adds it
- ~~`_EXPORT_MODULES["ArangoDBWikiStore"]`~~ — not exported yet

---

## Implementation Notes

### Factory Extension (store.py)

In `create_wiki_store()`, add after the `"memory"` branch:

```python
elif backend == "arangodb":
    from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore
    return ArangoDBWikiStore(
        arango_params=kwargs.get("arango_params", {}),
        database=kwargs.get("database", ""),
        wiki_name=wiki_name,
        text_analyzer=kwargs.get("text_analyzer", "text_en"),
    )
```

Note: the factory signature may need `**kwargs` added to pass arango-specific
params. Alternatively, the toolkit can construct `ArangoDBWikiStore` directly
(bypassing the factory for arangodb) — evaluate which is cleaner.

### Toolkit Wiring (toolkit.py)

At lines 105-118, add an `elif` for arangodb:

```python
if config.storage_backend == "arangodb":
    from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore
    from parrot.knowledge.wiki.project import resolve_arango_params
    params = resolve_arango_params(config)  # needs config adaptation
    self._store = ArangoDBWikiStore(params, wiki_name=config.wiki_name)
    self._sources = SourceCollectionManager(sources_dir, backend="arangodb", ...)
```

### Key Constraints

- Lazy import of `ArangoDBWikiStore` (same pattern as `InMemoryWikiStore`)
- Must not break existing sqlite/memory paths

---

## Acceptance Criteria

- [ ] `create_wiki_store(backend="arangodb", ...)` returns `ArangoDBWikiStore`
- [ ] `create_wiki_store(backend="sqlite")` still works unchanged
- [ ] `ArangoDBWikiStore` is importable from `parrot.knowledge.wiki`
- [ ] Tests pass: `pytest tests/knowledge/wiki/test_factory_arango.py -v`
- [ ] No linting errors

---

## Completion Note

Added an `"arangodb"` branch to `create_wiki_store()` in `store.py`
(signature extended with `**kwargs` for `arango_params`/`database`/
`text_analyzer`, lazily importing `ArangoDBWikiStore`), exported
`ArangoDBWikiStore` from `parrot.knowledge.wiki.__init__` via
`_EXPORT_MODULES`, and wired `LLMWikiToolkit.__init__` (`toolkit.py`) to
construct `ArangoDBWikiStore` directly (bypassing the factory) when
`config.storage_backend == "arangodb"`.

**Design decision** — `resolve_arango_params()` (TASK-2058) takes a
`WikiProjectConfig`, but `LLMWikiToolkit` is constructed with a
`WikiConfig` (no arango-specific fields, by design — only
`WikiProjectConfig`/`.parrot/wiki.json` carries them). Rather than adding
arango fields to `WikiConfig` (out of this task's scope) or changing
`resolve_arango_params()`'s signature (would violate TASK-2058's already-
implemented contract), the toolkit wiring constructs a minimal
`WikiProjectConfig(wiki_name=config.wiki_name)` just to reuse
`resolve_arango_params()` unchanged — giving the same `ARANGODB_*`
env-var resolution with sensible defaults, no new fields, no signature
changes.

**Sources wiring**: left the existing `else` branch (`backend="json"`)
covering `storage_backend == "arangodb"` as-is — `SourceCollectionManager`
does not yet accept `"arangodb"` (that is TASK-2060's job, explicitly
listed as NOT in this task's scope, and not in this task's Files to
Create/Modify). No `sources.py` change was made here.

11 unit tests added in `tests/knowledge/wiki/test_factory_arango.py`
(factory dispatch + kwargs passthrough for all 3 backends, unknown-backend
error, package export). Full `tests/knowledge/wiki/` suite (640 tests,
including `test_toolkit.py`) re-run — all passing, no regressions.
`ruff check` on all 3 modified files shows the exact same finding
counts/kinds as their pre-existing baseline (verified via `git show
HEAD~N`) — no new lint debt.

**Bookkeeping fix**: also caught and corrected a gap in the previous
TASK-2058 completion commit, where the deletion of
`sdd/tasks/active/TASK-2058-config-extension.md` was never staged
(leaving git tracking the file at both `active/` and `completed/`) —
fixed in a small dedicated commit before this task's work.
