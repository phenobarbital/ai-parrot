# TASK-3225: wikitoolkit status SQLite diagnostics block

**Feature**: FEAT-557 — wikitoolkit SQLite concurrency hardening
**Spec**: `sdd/specs/wikitoolkit-sqlite-optimizations.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3223
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (the observability third) and AC-5: "Required safe policy is visible".
FEAT-557 changes how every SQLite connection is configured, but none of it is currently
observable — an operator debugging a contended plane has no way to see whether their
`sqlite_busy_timeout` actually took effect, or whether the optional pragmas are on.

This task appends a `sqlite` block to `wikitoolkit status`, in both JSON and human output.
It must be **additive**: the existing payload keys are consumed by other tooling and none
may be removed or renamed.

---

## Scope

- Add an effective-settings reader to `SQLiteWikiStore` that reports what the live
  connection actually has (journal mode, busy timeout ms, synchronous, journal size limit,
  and which optional pragmas are enabled).
- Fold it into `status`'s `payload` under a new `"sqlite"` key.
- Render it in the human output.
- Skip it cleanly for non-SQLite backends.

**NOT in scope**: changing any existing `payload` key; the checkpoint call sites
(TASK-3224); making `status` open a read-only store (see the note below).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | `sqlite_settings()` reader on `SQLiteWikiStore` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | Fold the block into `status` payload + human render |
| `tests/knowledge/wiki/test_cli_status_sqlite.py` | CREATE | JSON block, human render, backward compatibility |

---

## Codebase Contract (Anti-Hallucination)

### Verified anchors — `status` runs cli.py:1961-2082

> The spec's §6 contract says "cli.py:1961-2015". **That end line is wrong**: 2015 is
> mid-`payload`. The function body actually runs to **cli.py:2082**.

```python
def status(...)                                              # line 1961 (decorators 1957-1960)
    ...
    store = _open_store(root, config)                        # 1974   <- writable store; see note
    ...
    sources = _open_sources(root, config, store=store)       # 1984
    read_store = _federate(root, config, store, ns_opt)      # 1985
    stats = _run(read_store.stats())                         # 1986
    namespaces = stats.pop("namespaces", None)               # 1987
    ns_skipped = stats.pop("skipped", None)                  # 1988
    stats.pop("local", None)                                 # 1989
    ...
    payload: dict[str, Any] = {                              # 1997   <- literal starts
        "root": str(root),
        "wiki_name": config.wiki_name,
        "backend": config.backend,
        "storage_dir": str(config.storage_path(root)),
        "env": effective.env,
        "overlay": overlay_label,
        "reachable": reachable,
        "stats": stats,                                      # 2005
        "sources": len(entries),
        "stale_sources": len(stale),
        "languages": {name: s.mode for name, s in all_scanners().items()},
        # FEAT-498: same per-language mode mapping as "languages" above,
        # named for the structural symbol plane specifically — additive,
        # "languages" itself is unchanged for backward compatibility.
        "structural": {name: s.mode for name, s in all_scanners().items()},
    }                                                        # 2013   <- literal ends
    # mutated 2017-2024 (scoped_to branch), 2025-2027 (namespaces)
    payload["roblox_api"] = get_roblox_status()              # 2033
    # JSON emit 2035-2037; human render 2038-2082
```

The `"structural"` key added by FEAT-498 (payload lines 2011-2015) is the **precedent to
follow**: a new key added alongside the old one, with a comment saying the old one is
unchanged for backward compatibility. Do the same.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class SQLiteWikiStore(BaseWikiStore):                        # line 774
    async def stats(self) -> dict[str, Any]:                 # line 1880
    self._policy: SQLitePragmaPolicy                         # TASK-3217
    @asynccontextmanager
    async def _open(self, *, writable: bool) -> AsyncIterator[aiosqlite.Connection]:   # TASK-3217
    async def checkpoint(self, truncate: bool = True) -> dict[str, int | bool]:        # TASK-3220
```

### Does NOT Exist

- ~~`SQLiteWikiStore.sqlite_settings`~~ — this task creates it.
- ~~a `sqlite` key in the `status` payload~~ — verified absent; this task adds it.
- ~~`status` opening a read-only store~~ — it opens a **writable** one at cli.py:1974
  (`_open_store` has no `read_only` parameter). That is pre-existing and **out of scope**;
  do not change it here. It does mean the settings you read back are the write-path
  settings, which is what AC-5 wants to show.
- ~~`read_store` being the local store~~ — `read_store = _federate(...)` at cli.py:1989 may
  be a **federated** store spanning namespaces. Read the SQLite settings from the LOCAL
  `store` (cli.py:1974), not from `read_store`.

### SQLite pragmas to report — return values, verified

| Pragma | Returns |
|---|---|
| `PRAGMA journal_mode` | text, e.g. `wal` |
| `PRAGMA busy_timeout` | integer **milliseconds** |
| `PRAGMA synchronous` | **integer** `0`/`1`/`2` (OFF/NORMAL/FULL) — *not* the word `NORMAL` |
| `PRAGMA journal_size_limit` | integer bytes (`-1` = no limit) |

`PRAGMA synchronous` returning `1` for NORMAL is the classic trap here — the spec's AC-5
says "`synchronous=NORMAL`" but SQLite reports the integer.

---

## Implementation Blueprint

### Steps (in order)
1. Put the reader on the store, not in the CLI — *why*: the CLI holds a `BaseWikiStore` and
   should not know SQLite pragma names; keeping the SQL beside `_apply_pragmas` means the
   applied set and the reported set cannot drift.
2. Open with `writable=False` for the read-back — *why*: `status` is a read command; it must
   not take a writer reservation just to render diagnostics (AC-4).
3. Map `synchronous` from its integer to a name — *why*: see the trap above; AC-5 asks for
   the setting to be *visible*, and `2` is not legible to an operator.
4. Report which optional pragmas are enabled, from `self._policy.performance_pragmas` —
   *why*: AC-5 requires distinguishing the always-on safe set from the opt-in set.
5. Add `payload["sqlite"]` after the literal closes, near the `roblox_api` line — *why*:
   mutating after construction is the pattern already used at cli.py:2014-2033, and it
   keeps the guard (`if isinstance(store, SQLiteWikiStore)`) out of the dict literal.
6. Add NOTHING to and remove NOTHING from the existing keys — *why*: AC-8 says
   "backward-compatible"; other tooling parses this JSON.

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '    async def checkpoint(self, truncate: bool = True)' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — insert below the END of `checkpoint()` (added by TASK-3220).

    async def sqlite_settings(self) -> dict[str, Any]:
        """Report the SQLite settings a live connection actually has.

        Read back from the connection rather than echoed from the policy,
        so what the operator sees is what SQLite is really doing (AC-5).

        Returns:
            ``journal_mode``, ``busy_timeout_ms``, ``synchronous``,
            ``journal_size_limit`` and ``performance_pragmas``.
        """
        _SYNCHRONOUS_NAMES = {0: "OFF", 1: "NORMAL", 2: "FULL", 3: "EXTRA"}
        async with self._open(writable=False) as conn:
            async def _one(pragma: str) -> Any:
                async with conn.execute(f"PRAGMA {pragma}") as cur:
                    row = await cur.fetchone()
                return row[0] if row else None

            synchronous = await _one("synchronous")
            return {
                "journal_mode": await _one("journal_mode"),
                "busy_timeout_ms": await _one("busy_timeout"),
                # PRAGMA synchronous returns an INTEGER (0/1/2), not a name.
                "synchronous": _SYNCHRONOUS_NAMES.get(int(synchronous), str(synchronous)),
                "journal_size_limit": await _one("journal_size_limit"),
                "performance_pragmas": self._policy.performance_pragmas,
            }
```
**Why this shape**: `writable=False` keeps `status` a pure read (AC-4). Reading the values
back rather than echoing `self._policy` is the point — it catches the case where a pragma
silently failed to apply, which is exactly what an operator runs `status` to find out. The
`_SYNCHRONOUS_NAMES` map exists because AC-5 asks to *see* `NORMAL`, and SQLite says `1`.
**FILL IN**: decide whether opening with `writable=False` still reports the
`journal_size_limit` the write path sets — if a read-only open reports `-1`, note it in the
docstring rather than silently showing a misleading value; bounded by AC-5.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'payload\["roblox_api"\] = get_roblox_status()' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py)
# BEFORE — insert above `    payload["roblox_api"] = get_roblox_status()` (verified: cli.py:2033)
    # FEAT-557: effective SQLite connection policy. Additive — every key
    # already in `payload` is unchanged. Read from the LOCAL store, not
    # from `read_store`, which may be a federated span.
    if isinstance(store, SQLiteWikiStore):
        payload["sqlite"] = _run(store.sqlite_settings())
```

```python
# FILL IN: render the block in the human output (cli.py:2038-2082), following the
# formatting of the sections already there. Emit nothing when the "sqlite" key is
# absent. Bounded by AC-8 ("backward-compatible SQLite diagnostics block") — the
# JSON path must keep working unchanged when `--json` is passed (emit at
# cli.py:2035-2037).
```
**Why**: guarding on `isinstance` keeps arango/memory/postgres planes free of a meaningless
block, and inserting before `roblox_api` matches the existing post-literal mutation style
(cli.py:2014-2033). `_run` is the same async bridge used at cli.py:1986.

### `tests/knowledge/wiki/test_cli_status_sqlite.py` (CREATE)

```python
"""FEAT-557 — `wikitoolkit status` SQLite diagnostics block."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner


class TestSqliteSettings:
    async def test_reports_effective_policy(self, tmp_path: Path) -> None:
        """The reader reflects what the connection really has (AC-5)."""
        # FILL IN: build a store with a non-default busy timeout, call
        # `await store.sqlite_settings()`, assert busy_timeout_ms matches and
        # synchronous renders as a NAME not an integer — bounded by AC-5.

    async def test_read_is_not_a_write(self, tmp_path: Path) -> None:
        """Reading the settings takes no writer lock (AC-4)."""
        # FILL IN: bounded by AC-4.


class TestStatusPayload:
    def test_json_contains_sqlite_block(self, tmp_path: Path) -> None:
        """`status --json` grows a `sqlite` key (AC-8)."""
        # FILL IN: run `status --json` via CliRunner (copy the setup from
        # tests/knowledge/wiki/test_cli.py), parse stdout, assert
        # payload["sqlite"]["busy_timeout_ms"] == 15000 — bounded by AC-8.

    def test_existing_keys_are_unchanged(self, tmp_path: Path) -> None:
        """No prior payload field is removed or renamed (AC-8)."""
        # FILL IN: assert every one of root, wiki_name, backend, storage_dir, env,
        # overlay, reachable, stats, sources, stale_sources, languages, structural,
        # roblox_api is still present — bounded by AC-8. This is the regression
        # guard that matters most; other tooling parses this payload.

    def test_human_output_renders_the_block(self, tmp_path: Path) -> None:
        """The non-JSON render shows the settings."""
        # FILL IN: bounded by AC-8.

    def test_non_sqlite_backend_has_no_block(self, tmp_path: Path) -> None:
        """A memory/arango plane emits no `sqlite` key."""
        # FILL IN: bounded by the isinstance guard.
```

### FILL IN checklist
- [ ] `sqlite_settings` — confirm `journal_size_limit` is meaningful on a `writable=False`
      open; bounded by AC-5.
- [ ] Human render in `status` (cli.py:2038-2082); bounded by AC-8.
- [ ] Five test bodies above — `test_existing_keys_are_unchanged` is the critical one.

---

## Acceptance Criteria

- [ ] `SQLiteWikiStore.sqlite_settings()` returns `journal_mode`, `busy_timeout_ms`,
      `synchronous`, `journal_size_limit`, `performance_pragmas`.
- [ ] `synchronous` renders as a name (`NORMAL`), not the raw integer.
- [ ] `status --json` includes a `sqlite` object; every pre-existing key is still present
      and unrenamed.
- [ ] Human output renders the block; a non-SQLite backend renders nothing extra.
- [ ] Reading the settings issues no write statement.
- [ ] No regression: `pytest tests/knowledge/wiki/test_cli.py -q`
- [ ] Tests pass: `pytest tests/knowledge/wiki/test_cli_status_sqlite.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/cli.py packages/ai-parrot/src/parrot/knowledge/wiki/store.py`

---

## Test Specification

See the blueprint. `test_existing_keys_are_unchanged` is the backward-compatibility gate
AC-8 asks for — write it first.

---

## Agent Instructions

1. **Read the spec** — §3 Module 4, AC-5, AC-8. Note the spec's §6 line range for `status`
   is wrong (it says 1961-2015; the function ends at 2082).
2. **Check dependencies** — TASK-3223 completed. TASK-3220 is not strictly required but
   `sqlite_settings` is inserted after `checkpoint()`; if TASK-3220 has not landed, insert
   after `stats()` (store.py:1880) instead.
3. **Verify the Codebase Contract** — confirm the `payload` literal still starts at
   cli.py:1997 and `payload["roblox_api"]` is still at 2033.
4. **Implement** from the blueprint; complete every `FILL IN`.
5. **Verify** every acceptance criterion.
6. **Move this file** to `sdd/tasks/completed/`; update the per-spec index; fill the note.

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
