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

*(Agent fills this in when done)*
