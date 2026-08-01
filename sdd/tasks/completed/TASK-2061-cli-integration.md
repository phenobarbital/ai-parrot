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

Added `"arangodb"` to both `click.Choice` lists (`_store_options`'s
shared `--backend` for read commands, and `build`'s own `--backend`).
Extended `_open_store()` to resolve `arango_params`/`database`/
`text_analyzer` via `resolve_arango_params(config)` when
`config.backend == "arangodb"`. Extended `_open_sources()` with a new
optional `store` param — for `arangodb` it reuses the store's own
`asyncdb` connection (`store._db`) rather than opening a second one, so
callers must `await`/`asyncio.run(store.initialize())` first.
`_resolve_read_store()` gained an early explicit branch for
`backend_opt == "arangodb"` (always resolves via project config —
ArangoDB is server-hosted, there's no local `--store` directory to point
at — and connects eagerly so an unreachable server fails fast with a
clear `click.ClickException`). `build`, `upsert`, and `status` all wrap
their `store.initialize()`/pipeline calls the same way for the same
clear-error acceptance criterion.

**Deviation from the file list (documented, not silent)**: also fixed
`WikiProjectConfig.is_built()` in `project.py` (not in this task's Files
to Create/Modify) to return `True` unconditionally for
`backend == "arangodb"`. Without this, `is_built()`'s pre-existing logic
(`(storage_path / "pages").exists()` — a local filesystem check) would
ALWAYS report an arangodb-backed wiki as "not built" even right after a
successful `build --backend arangodb`, since ArangoDB never creates that
local `pages` directory — permanently blocking `_require_built()` /
`_resolve_read_store()`'s default (no explicit `--backend` flag) path
and making this task's own acceptance criteria unsatisfiable. Server-side
existence is deferred to the store's own idempotent `initialize()`
instead of a synchronous local probe. This is a one-line, tightly-scoped
fix directly required for this task's functionality; TASK-2058 (which
added the `"arangodb"` Literal to `WikiProjectConfig`) did not anticipate
`is_built()`'s branching.

**Interpretation note on Acceptance Criteria**: "`wikitoolkit status
--backend arangodb`" — the `status` command has no `--backend` option
(never did, for any backend) since backend selection there has always
come from the project's saved config, not a per-invocation flag (only
`build` and the `--store`-scoped read commands have `--backend`). Tested
the equivalent, achievable behavior instead: after `build --backend
arangodb`, a plain `wikitoolkit status` correctly reports
`backend: "arangodb"` and live stats — did not add a redundant
`--backend` flag to `status` since no such per-call override pattern
exists elsewhere for a project already configured.

7 CLI tests added in `tests/knowledge/wiki/test_cli_arango.py` (build
routing + collection/view creation, config persistence, query resolution
via project config, unreachable-server error message, status reporting,
sqlite-still-works regression), all passing via `CliRunner` with
`parrot.knowledge.wiki.arango_store.AsyncDB` patched — no real ArangoDB
server needed. Full `tests/knowledge/wiki/` suite (665 tests) re-run —
no regressions. `ruff check` on `cli.py` matches its pre-existing
baseline finding-for-finding except +1 `UP045` (the new
`Optional[BaseWikiStore]` parameter, same convention as everywhere else
in the file); `project.py` unchanged from its TASK-2058 baseline (4
`UP045`, all pre-existing).
