# TASK-2061: CLI Integration for ArangoDB Backend

**Feature**: FEAT-400 — WikiToolkit ArangoDB Backend
**Spec**: `sdd/specs/wikitoolkit-arangodb-backend.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2057, TASK-2058, TASK-2059
**Assigned-to**: unassigned

---

## Context

Extends the `wikitoolkit` CLI to support `--backend arangodb` for build,
query, and read commands. Corresponds to Module 5 in the spec.

---

## Scope

- Add `"arangodb"` to the `click.Choice` for `--backend` in the `build` command.
- Update `_resolve_read_store()` to handle `backend="arangodb"`.
- Update `_open_sources()` to create `SourceCollectionManager(backend="arangodb")`.
- Wrap async ArangoDB operations in `asyncio.run()` for CLI context.
- Test CLI backend routing.

**NOT in scope**:
- ArangoDBWikiStore implementation (TASK-2057)
- Config model changes (TASK-2058)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | Add arangodb to --backend choice + store resolution |
| `tests/knowledge/wiki/test_cli_arango.py` | CREATE | CLI backend routing tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.store import BaseWikiStore, create_wiki_store  # verified: store.py:279, 1197
from parrot.knowledge.wiki.project import WikiProjectConfig, resolve_arango_params  # TASK-2058 adds resolve_arango_params
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
def _resolve_read_store(path_: Optional[str], store_opt: Optional[str],
    backend_opt: Optional[str]) -> BaseWikiStore: ...                   # line 160

def _open_sources(root: Path,
    config: WikiProjectConfig) -> SourceCollectionManager: ...          # line 115

# build command --backend option: lines 618-623
# click.Choice(["sqlite", "memory"]) — needs "arangodb" added

# build command backend assignment: lines 674-676
# if backend: config.backend = backend
```

### Does NOT Exist

- ~~`cli.py` `_resolve_read_store` handling for `"arangodb"`~~ — not implemented yet

---

## Implementation Notes

### --backend Choice Extension

At lines 618-623 in `cli.py`, change:
```python
type=click.Choice(["sqlite", "memory"])
```
to:
```python
type=click.Choice(["sqlite", "memory", "arangodb"])
```

### _resolve_read_store Extension

Add handling for arangodb backend. Since ArangoDB needs async init, wrap in
`asyncio.run()`:

```python
if backend == "arangodb":
    from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore
    from parrot.knowledge.wiki.project import resolve_arango_params
    config = load_project_config(root)
    params = resolve_arango_params(config)
    store = ArangoDBWikiStore(params, wiki_name=config.wiki_name)
    asyncio.run(store.initialize())
    return store
```

### Key Constraints

- CLI commands are synchronous — use `asyncio.run()` for async init
- Must handle the case where ArangoDB is not reachable (clear error message)
- Connection cleanup at CLI exit

---

## Acceptance Criteria

- [ ] `wikitoolkit build --backend arangodb` builds wiki into ArangoDB
- [ ] `wikitoolkit query --backend arangodb "question"` queries ArangoDB wiki
- [ ] `wikitoolkit status --backend arangodb` shows ArangoDB wiki stats
- [ ] Clear error message when ArangoDB is unreachable
- [ ] Existing sqlite/memory paths unaffected
- [ ] Tests pass

---

## Completion Note

*(Agent fills this in when done)*
