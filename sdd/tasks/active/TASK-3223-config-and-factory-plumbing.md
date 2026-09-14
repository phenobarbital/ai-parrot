# TASK-3223: Forward the SQLite policy through construction sites

**Feature**: FEAT-557 — wikitoolkit SQLite concurrency hardening
**Spec**: `sdd/specs/wikitoolkit-sqlite-optimizations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3217, TASK-3221, TASK-3222
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (the plumbing half). TASK-3222 persists the two settings and TASK-3217 /
TASK-3221 accept them; this task connects the two so a configured value actually reaches a
connection.

**The defaults already work without this task.** Every store and manager built anywhere in
the repo now gets `busy_timeout=15.0` automatically, because both constructors default it.
This task is strictly about honouring a *non-default* value the operator wrote into
`.parrot/wiki.json`. That framing matters: it means you only need to touch construction
sites that have a `WikiProjectConfig` in hand, and spec §7 explicitly warns against adding
policy kwargs blindly to every backend.

---

## Scope

- `create_wiki_store()` accepts `sqlite_policy` and forwards it to the SQLite branch ONLY.
- Forward config → policy at the construction sites that hold a `WikiProjectConfig`:
  `cli.py` (`_open_store`, `_open_sources`), `mcp_server.py`, `structural/toolkit.py`,
  `sync.py` (`_open_plane`).
- `federation.py`: give the read-only foreign store the busy timeout, and nothing else.
- Add one shared helper that turns a `WikiProjectConfig` into a `SQLitePragmaPolicy`, so
  the mapping exists in exactly one place.

**NOT in scope**: `execution.py:162`, `toolkit.py:124-149`, `roblox/ingest.py:136/145`,
`cli.py:840`, `bookstore/wiki_export.py`, `memory/dream/brain.py`,
`tools/repo/graph_search.py`, `flows/dev_loop/wiki_search.py`,
`agents/meeting_registry.py`, `scripts/build_llm_wiki.py` — none of these has a
`WikiProjectConfig`, and all correctly inherit the 15 s default. Do NOT thread a policy
into them. Also out of scope: the `status` display (TASK-3225) and the CLI checkpoint
calls (TASK-3224).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | `create_wiki_store(sqlite_policy=...)` → SQLite branch |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | Add the `config → policy` helper |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `_open_store`, `_open_sources` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` | MODIFY | Both `create_wiki_store` calls |
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py` | MODIFY | Both `create_wiki_store` calls |
| `packages/ai-parrot/src/parrot/knowledge/wiki/sync.py` | MODIFY | `_open_plane` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` | MODIFY | Read-only foreign store timeout |
| `tests/knowledge/wiki/test_sqlite_policy_plumbing.py` | CREATE | Config value reaches a connection |

---

## Codebase Contract (Anti-Hallucination)

### Verified construction sites — the COMPLETE map

**In scope (config-bearing):**

| File:line | Verbatim call | Note |
|---|---|---|
| `store.py:1979` | `return SQLiteWikiStore(storage_dir / "wiki.db", wiki_name=wiki_name)` | the factory's own sqlite branch; **never passes `read_only`** |
| `cli.py:421` | `return create_wiki_store(storage, wiki_name=config.wiki_name, backend=config.backend)` | end of `_open_store` (def 394) |
| `cli.py:412` | `return create_wiki_store(` + arango kwargs | arango branch — **do not add a SQLite policy here** |
| `cli.py:441` | `return SourceCollectionManager(storage / "sources", db_path=storage / "wiki.db")` | sqlite branch of `_open_sources` (def 424) |
| `mcp_server.py:130` | `create_wiki_store(storage, wiki_name=config.wiki_name, backend=config.backend)` | sqlite/fallthrough |
| `mcp_server.py:120` | `create_wiki_store(` + arango kwargs | arango — skip |
| `structural/toolkit.py:93` | `create_wiki_store(storage, wiki_name=self._config.wiki_name, backend=self._config.backend)` | sqlite/fallthrough |
| `structural/toolkit.py:84` | `create_wiki_store(` + arango kwargs | arango — skip |
| `sync.py:108` | `return create_wiki_store(storage, wiki_name=config.wiki_name, backend=config.backend)` | end of `_open_plane` (def 90) |
| `federation.py:277` | `return SQLiteWikiStore(storage_dir / "wiki.db", wiki_name=wiki_name, read_only=True)` | guarded by `if backend == "sqlite" and read_only:` at 276 |

**Explicitly OUT of scope (no `WikiProjectConfig` available — they inherit the default):**
`cli.py:541` (`_resolve_read_store`), `cli.py:2800` (`_resolve_write_store`), `cli.py:840`
(`SQLiteWikiStore(gen_dir / "wiki.db", read_only=True)`), `cli.py:443`/`444` (arango/json
source branches), `toolkit.py:124-128/134/145/147/149`, `execution.py:162-164`,
`roblox/ingest.py:136`/`145`, `federation.py:280`, plus every site outside
`knowledge/wiki/`.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
def create_wiki_store(                                        # line 1940
    storage_dir: str | Path,
    wiki_name: str = "",
    backend: str = "sqlite",
    **kwargs: Any,
) -> BaseWikiStore:
    # body 1801-1831; the sqlite branch is:
    #     storage_dir = Path(storage_dir)            # 1801
    #     if backend == "sqlite":                    # 1802
    #         return SQLiteWikiStore(storage_dir / "wiki.db", wiki_name=wiki_name)   # 1834
    # then memory / arangodb / postgres branches, then:
    #     if backend in _EXTRA_BACKENDS:
    #         return _EXTRA_BACKENDS[backend](storage_dir=storage_dir, wiki_name=wiki_name, **kwargs)

# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
def _open_store(root: Path, config: WikiProjectConfig) -> BaseWikiStore:      # line 394
def _open_sources(root: Path, config: WikiProjectConfig,
                  store: Optional[BaseWikiStore] = None) -> SourceCollectionManager:   # line 424
def _require_built(...)                                                       # line 387 (wraps _open_store)

# packages/ai-parrot/src/parrot/knowledge/wiki/sync.py
def _open_plane(root, config):                                                # line 90
    # docstring says it "Mirrors ``cli.py``'s ``_open_store``" — the two ARE
    # duplicated logic and must be changed together.
```

From the other tasks:
```python
SQLitePragmaPolicy(busy_timeout_s=..., performance_pragmas=...)       # TASK-3216
SQLiteWikiStore(..., sqlite_policy=...)                               # TASK-3217
SourceCollectionManager(..., busy_timeout=...)                        # TASK-3221
WikiProjectConfig.sqlite_busy_timeout / .sqlite_performance_pragmas   # TASK-3222
```

### Does NOT Exist

- ~~`create_wiki_store(..., read_only=True)`~~ — **verified: the factory has NO way to
  produce a read-only store.** Its sqlite branch (store.py:1979) never passes `read_only`.
  The only three sites that get one construct `SQLiteWikiStore` directly:
  `federation.py:277`, `cli.py:840`, `roblox/ingest.py:145`. Do not add a `read_only`
  kwarg to the factory — that is a separate change this task does not authorize.
- ~~a `sqlite_policy` kwarg surviving into `_EXTRA_BACKENDS`~~ — spec §7 warns explicitly:
  `create_wiki_store` forwards `**kwargs` to satellite backends at the `_EXTRA_BACKENDS`
  branch. If you leave `sqlite_policy` in `kwargs`, every satellite backend receives an
  unexpected keyword. **Pop it, don't peek at it.**
- ~~`WikiProjectConfig` being available in `toolkit.py`~~ — `LLMWikiToolkit` holds a
  `WikiConfig` (from `models.py`), a DIFFERENT model with no `sqlite_*` fields. That is why
  toolkit.py is out of scope.
- ~~`_open_store` taking a `read_only` parameter~~ — it does not; both `status` and
  `ingest` therefore open WRITABLE planes today. Out of scope here; do not change it.

---

## Implementation Blueprint

### Steps (in order)
1. Add `sqlite_policy_from_config(config)` to `project.py` — *why*: seven call sites need
   the same three-line mapping; one helper means a future third setting is added once, not
   seven times. It belongs in `project.py` because that is where the config model lives.
2. Make `create_wiki_store` **pop** `sqlite_policy` out of `kwargs` before any branch —
   *why*: see the `_EXTRA_BACKENDS` note above; leaving it in `kwargs` breaks every
   satellite backend with an unexpected-keyword `TypeError`.
3. Forward it only inside the `backend == "sqlite"` branch — *why*: AC-1 and spec §7; the
   memory, arangodb and postgres branches have no such concept.
4. Update `cli.py` and `sync.py` together — *why*: `sync.py:_open_plane`'s own docstring
   says it mirrors `cli.py:_open_store`; changing one and not the other is how they drift.
5. In `federation.py:277`, pass a policy carrying ONLY the timeout — *why*: AC-4 and spec
   §2; a foreign, read-only plane gets the bounded wait but must never receive write
   pragmas or performance tuning. `_read` on a read-only store never reaches
   `_apply_pragmas(writable=True)`, so constructing the policy with
   `performance_pragmas=False` is the belt-and-braces half.
6. Prove the value actually lands on a connection — *why*: this whole task is invisible
   unless a test reads `PRAGMA busy_timeout` back off a store built from a config.

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '^def config_path(root: Path) -> Path:' packages/ai-parrot/src/parrot/knowledge/wiki/project.py)
# BEFORE — insert above `def config_path(root: Path) -> Path:` (verified: project.py:635)

def sqlite_policy_from_config(config: "WikiProjectConfig") -> "SQLitePragmaPolicy":
    """Build the SQLite connection policy a config asks for.

    The single mapping from persisted settings to the connection policy;
    every construction site that holds a config uses this rather than
    building a policy inline.

    Args:
        config: The project's wiki config.

    Returns:
        A validated policy carrying the configured timeout and pragma
        opt-in.
    """
    from parrot.knowledge.wiki.store import SQLitePragmaPolicy

    return SQLitePragmaPolicy(
        busy_timeout_s=config.sqlite_busy_timeout,
        performance_pragmas=config.sqlite_performance_pragmas,
    )
```
**Why**: the `store` import is function-local because `store.py` and `project.py` are
mutually reachable; `sources.py` already uses the same lazy-import idiom for
`WIKI_SCHEMA_SQL`. Both bounds were already validated on the config (TASK-3222), so this
can never raise for a config that loaded.

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'storage_dir = Path(storage_dir)' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — insert below `    storage_dir = Path(storage_dir)` (verified: store.py:1977),
#         i.e. BEFORE `    if backend == "sqlite":` (store.py:1978):
    # Pop, never peek: `kwargs` is forwarded verbatim to satellite
    # backends at the _EXTRA_BACKENDS branch, which would reject an
    # unexpected `sqlite_policy` keyword.
    sqlite_policy = kwargs.pop("sqlite_policy", None)
```

```python
# occurrences: 1 (verified: grep -c 'return SQLiteWikiStore(storage_dir / "wiki.db", wiki_name=wiki_name)' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# REPLACE `        return SQLiteWikiStore(storage_dir / "wiki.db", wiki_name=wiki_name)`
#         (verified: store.py:1979) with:
        return SQLiteWikiStore(
            storage_dir / "wiki.db",
            wiki_name=wiki_name,
            sqlite_policy=sqlite_policy,
        )
```
**Why**: `sqlite_policy=None` is exactly what `SQLiteWikiStore.__init__` already defaults
to (TASK-3217), so a caller that passes nothing is unchanged. Popping before the first
branch means every other backend sees the same `kwargs` it sees today.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'return create_wiki_store(storage, wiki_name=config.wiki_name, backend=config.backend)' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py)
# REPLACE the final line of `_open_store` (verified: cli.py:421) with:
    return create_wiki_store(
        storage,
        wiki_name=config.wiki_name,
        backend=config.backend,
        sqlite_policy=sqlite_policy_from_config(config),
    )
```

```python
# occurrences: 1 (verified: grep -c 'return SourceCollectionManager(storage / "sources", db_path=storage / "wiki.db")' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py)
# REPLACE the sqlite branch of `_open_sources` (verified: cli.py:441) with:
        return SourceCollectionManager(
            storage / "sources",
            db_path=storage / "wiki.db",
            busy_timeout=config.sqlite_busy_timeout,
        )
```
**Why**: `_open_store` is the CLI's single store entry point (`_require_built` at cli.py:387
delegates to it), so one edit covers `build`, `ingest`, `status`, `upsert` and the rest.
Import `sqlite_policy_from_config` from `parrot.knowledge.wiki.project` alongside the
existing `WikiProjectConfig` / `load_project_config` imports.

### Remaining call sites (MODIFY)

```python
# FILL IN: apply the identical `sqlite_policy=sqlite_policy_from_config(config)` argument
# to each SQLite/fallthrough `create_wiki_store` below, leaving the ARANGO branch above
# each one untouched — bounded by AC-1 (SQLite only) and spec §7 ("never leak SQLite
# kwargs into memory, ArangoDB, or satellite backend factories"):
#   - mcp_server.py:130        (config var is `config`;        skip the arango call at 120)
#   - structural/toolkit.py:93 (config var is `self._config`;  skip the arango call at 84)
#   - sync.py:108              (config var is `config`;        skip the arango call at 99-106)
# Each target line is unique in its own file; verify with
# `grep -n 'create_wiki_store' <file>` before editing.
```

```python
# occurrences: 1 (verified: grep -c 'read_only=True)' packages/ai-parrot/src/parrot/knowledge/wiki/federation.py)
# REPLACE `        return SQLiteWikiStore(storage_dir / "wiki.db", wiki_name=wiki_name, read_only=True)`
#         (verified: federation.py:277, guarded by `if backend == "sqlite" and read_only:` at 276)
# FILL IN: pass a policy carrying ONLY the busy timeout — a foreign plane must get the
# bounded wait but never write or performance pragmas. Decide where the timeout comes
# from: federation resolves FOREIGN namespaces, so the local project config may not
# apply; defaulting to SQLitePragmaPolicy() (15 s, performance_pragmas=False) is
# acceptable and is bounded by AC-4 and spec §2 ("read-only foreign SQLite stores
# receive busy timeout but never write pragmas or migrate").
```

### `tests/knowledge/wiki/test_sqlite_policy_plumbing.py` (CREATE)

```python
"""FEAT-557 — a configured SQLite policy reaches an actual connection."""
from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.wiki.project import (
    WikiProjectConfig,
    sqlite_policy_from_config,
)
from parrot.knowledge.wiki.store import SQLiteWikiStore, create_wiki_store


class TestPolicyFromConfig:
    def test_maps_both_fields(self) -> None:
        """The helper is the one mapping from config to policy."""
        config = WikiProjectConfig(sqlite_busy_timeout=42.0, sqlite_performance_pragmas=True)
        policy = sqlite_policy_from_config(config)
        assert policy.busy_timeout_s == 42.0
        assert policy.performance_pragmas is True


class TestFactoryForwarding:
    async def test_sqlite_branch_receives_policy(self, tmp_path: Path) -> None:
        """A configured timeout lands on a real connection (AC-5)."""
        policy = sqlite_policy_from_config(WikiProjectConfig(sqlite_busy_timeout=7.0))
        store = create_wiki_store(tmp_path, backend="sqlite", sqlite_policy=policy)
        assert isinstance(store, SQLiteWikiStore)
        async with store._open(writable=True) as conn:
            cur = await conn.execute("PRAGMA busy_timeout")
            assert (await cur.fetchone())[0] == 7_000

    def test_policy_does_not_leak_to_other_backends(self, tmp_path: Path) -> None:
        """`sqlite_policy` is popped before the memory/extra branches (spec §7)."""
        # FILL IN: call create_wiki_store(..., backend="memory", sqlite_policy=...) and
        # assert it constructs without TypeError — bounded by spec §7 and the
        # _EXTRA_BACKENDS forwarding note in the Codebase Contract.

    def test_default_when_no_policy_passed(self, tmp_path: Path) -> None:
        """Omitting the policy still yields the 15 s default (AC-2)."""
        # FILL IN: bounded by AC-2.


class TestCliPlumbing:
    def test_open_store_forwards_configured_timeout(self, tmp_path: Path) -> None:
        """`_open_store` honours .parrot/wiki.json (AC-5)."""
        # FILL IN: build a config with a non-default sqlite_busy_timeout, call
        # cli._open_store(tmp_path, config), and assert the store's policy carries it —
        # bounded by AC-5.

    def test_open_sources_forwards_configured_timeout(self, tmp_path: Path) -> None:
        """`_open_sources` honours the same setting (AC-6)."""
        # FILL IN: bounded by AC-6.
```

### FILL IN checklist
- [ ] `mcp_server.py:130`, `structural/toolkit.py:93`, `sync.py:108` forwarding.
- [ ] `federation.py:277` read-only timeout; bounded by AC-4 / spec §2.
- [ ] `test_policy_does_not_leak_to_other_backends`; bounded by spec §7.
- [ ] `test_default_when_no_policy_passed`; bounded by AC-2.
- [ ] `test_open_store_forwards_configured_timeout`; bounded by AC-5.
- [ ] `test_open_sources_forwards_configured_timeout`; bounded by AC-6.

---

## Acceptance Criteria

- [ ] `create_wiki_store(..., backend="sqlite", sqlite_policy=p)` produces a store using
      `p`; omitting it yields the 15 s default.
- [ ] `create_wiki_store(..., backend="memory"|"arangodb"|"postgres"|<extra>,
      sqlite_policy=p)` does NOT raise and does NOT forward the policy.
- [ ] A `.parrot/wiki.json` with `sqlite_busy_timeout: 30` yields
      `PRAGMA busy_timeout = 30000` on a store opened by `_open_store`.
- [ ] `_open_sources` forwards the same value as `busy_timeout`.
- [ ] `mcp_server.py`, `structural/toolkit.py`, `sync.py` forward it on their SQLite paths;
      their ArangoDB paths are unchanged.
- [ ] `federation.py:277`'s read-only store receives a busy timeout and no write pragmas.
- [ ] The out-of-scope sites listed above are UNCHANGED.
- [ ] No regression: `pytest tests/knowledge/wiki/ -q`
- [ ] Tests pass: `pytest tests/knowledge/wiki/test_sqlite_policy_plumbing.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/`

---

## Test Specification

See the blueprint. The decisive assertion is
`test_sqlite_branch_receives_policy` — it reads the pragma back off a real connection, so
it fails if the value is dropped anywhere along the chain.

---

## Agent Instructions

1. **Read the spec** — §3 Module 3, §7 ("Do not add policy kwargs to all backends
   blindly"), AC-5.
2. **Check dependencies** — TASK-3217, TASK-3221, TASK-3222 all completed.
3. **Verify the Codebase Contract** — re-run
   `grep -rn 'create_wiki_store(\|SQLiteWikiStore(\|SourceCollectionManager(' packages/ai-parrot/src/parrot/knowledge/wiki/`
   and confirm the in-scope table still matches. Update this contract FIRST if it moved.
4. **Implement** from the blueprint; complete every `FILL IN`.
5. **Verify** every acceptance criterion — especially that out-of-scope sites are untouched.
6. **Move this file** to `sdd/tasks/completed/`; update the per-spec index; fill the note.

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
