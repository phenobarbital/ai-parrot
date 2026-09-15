# TASK-3224: CLI checkpoint after build/ingest and WikiStoreBusy soft-skip in upsert

**Feature**: FEAT-557 — wikitoolkit SQLite concurrency hardening
**Spec**: `sdd/specs/wikitoolkit-sqlite-optimizations.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3220, TASK-3223
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. Two operator-facing behaviours:

1. **Checkpoint the long writers.** `build` and `ingest` produce a large WAL; fold it back
   afterwards. `upsert --changed` must NOT checkpoint — it is a short post-commit path and
   WAL autocheckpoint is sufficient (an explicit non-goal in spec §1).
2. **Soft-skip a busy upsert.** `upsert` already treats "another writer holds the lock" as
   a non-error skip at the *file lock* level (cli.py:1642-1650). Now that a SQLite writer
   wait can also expire, `WikiStoreBusy` must get the same non-failing treatment rather
   than a traceback in a git post-commit hook.

> ### ⚠️ Spec correction — verified, read before implementing
> AC-7 says "`build` and `ingest` invoke non-fatal checkpointing **under their existing
> writer lock**". **`ingest` has no writer lock.** Verified: the only three
> `wiki_write_lock(` call sites in `cli.py` are **1394** (`build`), **1641** (`upsert`) and
> **2261** (`_global_registry_lock`). `ingest` (def at **cli.py:3970**) opens a store at
> cli.py:4061 and writes at 4219 / 4295 / 4324 with no mutual exclusion at all.
>
> **Resolution for this task**: checkpoint `build` inside its existing lock, and checkpoint
> `ingest` after its writes complete *without* a lock. **Do NOT add a writer lock to
> `ingest`** — that is a real behaviour change, outside this spec's scope, and it belongs in
> its own ticket. Note it in your Completion Note.

---

## Scope

- Call `SQLiteWikiStore.checkpoint()` after a successful `build`, inside the existing lock.
- Call it after a successful `ingest` (all three apply paths), unlocked — see above.
- Guard both calls so a non-SQLite backend is skipped (`checkpoint` is concrete to
  `SQLiteWikiStore`, not on `BaseWikiStore`).
- Never let a checkpoint failure change the command's exit status.
- Catch `WikiStoreBusy` in `upsert` and turn it into the existing non-failing skip message.
- Do NOT checkpoint in `upsert`.

**NOT in scope**: the `status` sqlite block (TASK-3225); adding a lock to `ingest`;
`checkpoint()` itself (TASK-3220).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | Checkpoint after build/ingest; `WikiStoreBusy` soft-skip in upsert |
| `tests/knowledge/wiki/test_cli_checkpoint.py` | CREATE | Which commands checkpoint, and the busy soft-skip |

---

## Codebase Contract (Anti-Hallucination)

### Verified anchors in `cli.py`

```python
UPSERT_LOCK_WAIT_SECONDS = 3.0                                  # line 109
REGISTRY_LOCK_WAIT_SECONDS = 5.0                                # line 104

def _require_built(...)                                         # line 387
def _open_store(root, config) -> BaseWikiStore:                 # line 394
def _open_sources(root, config, store=None):                    # line 424
def _write_build_stats(output_dir, wiki_name, store_stats,
                       okf_report, graph_stats) -> None:        # lines 1204-1285
def build(...)                                                  # line 1366 (decorators from 1328)
def upsert(...)                                                 # line 1625 (decorators 1616-1624)
def status(...)                                                 # line 1961 (decorators 1957-1960)
def ingest(...)                                                 # line 3970
```

**`build`** — writer lock opens at **cli.py:1394** and the `with` body runs to **1568**:
```python
    base_config = load_project_config(root)                              # 1393
    with wiki_write_lock(config.storage_path(root)) as _acquired:        # 1394
        if not _acquired:                                                # 1395
            click.echo(...)
            raise SystemExit(1)                                          # 1402
        ...
        try:                                                             # 1505
            counts = _run(_pipeline())                                   # 1506
        except Exception as exc:
            ...
            raise                                                        # 1512
        save_project_config(root, base_config)                           # 1513
        ...
        _write_build_stats(                                              # 1536  <- single call site
            output_dir,
            config.wiki_name,
            stats,
            counts.get("okf"),
            counts.get("graph"),
        )                                                                # 1542
        # terminal echoes 1543-1568, still inside the lock
```
`async def _pipeline()` is at **cli.py:1450**, returning `counts` at 1504.

**`upsert`** — lock at **cli.py:1641**, body to **1737**:
```python
    with wiki_write_lock(config.storage_path(root), timeout=UPSERT_LOCK_WAIT_SECONDS) as _acquired:  # 1641
        if not _acquired:                                                # 1642
            if not quiet:
                click.echo(
                    "Another wiki writer is in progress (likely a full "
                    "build) — skipping this upsert; the build will cover "
                    "these files."
                )
            return                                                       # 1650
        ...
        rel_paths = list(paths)                                          # 1656
        if changed:
            rel_paths.extend(_changed_files_from_git(root))              # 1658
        ...
        try:                                                             # 1727
            counts = _run(_pipeline())                                   # 1728
        except Exception as exc:  # surfaced as a clear CLI error
            if config.backend == "arangodb":
                raise click.ClickException(
                    f"Could not connect to ArangoDB for wiki " f"{config.wiki_name!r}: {exc}"
                ) from exc
            raise                                                        # 1734
        if not quiet:
            click.echo(f"Upserted {counts['written']} page(s), " f"removed {counts['removed']}.")  # 1737
```
Note the `except` at 1729 only special-cases arangodb; everything else re-raises at 1734.
**That bare `raise` is what currently turns a busy plane into a traceback.**

**`ingest`** — no lock. Store opened at **cli.py:4060-4062**:
```python
    root, config = _resolve_project(path_)                   # 4060
    store = _open_store(root, config)                        # 4061
    sources = _open_sources(root, config, store=store)       # 4062
```
Three apply drives, all unguarded — `async def _apply_all(...)` is at **cli.py:4173-4187**:
- **cli.py:4219** — `--review`: `_run(_apply_all(applied, wiki_config, header.charter_version))`
- **cli.py:4295** — `--interactive`: `_run(_apply_all(entries, wiki_config, charter.version, acquired_by_uri))`
- **cli.py:4324** — `--auto`: `_run(_apply_all(entries, wiki_config, charter.version, acquired_by_uri))`

Function ends at **cli.py:4335** (`_report_skipped(skipped)`).

### Writer-lock helper — `project.py:64-125`

```python
@contextmanager                                                          # 64
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]:   # 65
```
Advisory: it **yields a bool**, callers decide. `LOCK_FILENAME = "wiki.lock"` (project.py:40),
`_LOCK_POLL_SECONDS = 0.05` (project.py:59), `fcntl` imported guardedly at project.py:28-31
(on a non-POSIX platform it yields `True` unconditionally).

All six repo-wide usages: `cli.py:1394`, `cli.py:1641`, `cli.py:2261`, `tools.py:491`,
`structural/service.py:450`, `jira_sync.py:398`.

### Does NOT Exist

- ~~a writer lock in `ingest`~~ — **confirmed absent.** See the spec-correction box above.
- ~~`BaseWikiStore.checkpoint`~~ — `checkpoint()` is concrete to `SQLiteWikiStore`
  (TASK-3220). `_open_store` returns a `BaseWikiStore`, so you MUST guard with
  `isinstance(store, SQLiteWikiStore)` or `hasattr(store, "checkpoint")` — calling it
  unguarded raises `AttributeError` on the memory/arango/postgres backends.
- ~~per-file skip semantics in `upsert`~~ — there are none; one failure aborts the whole
  upsert (bare `raise` at cli.py:1734). The soft-skip you add is for the WHOLE upsert,
  matching the existing lock-busy message at 1643-1650.
- ~~`_write_build_stats` being called twice~~ — exactly ONE call site, cli.py:1536-1542.

---

## Implementation Blueprint

### Steps (in order)
1. Add a `_checkpoint_if_sqlite(store, label)` helper near `_open_store` — *why*: three
   call sites (build + up to three ingest paths) need the same guard-and-swallow logic, and
   the `isinstance` guard must not be duplicated four times.
2. Swallow every exception in that helper, not just `sqlite3` ones — *why*: AC-7 and spec
   §2 say a checkpoint must "never turn an otherwise successful long write into a CLI
   failure". `checkpoint()` already returns `ok=False` rather than raising (TASK-3220), but
   the helper is the belt-and-braces layer.
3. In `build`, call it after `_write_build_stats` (cli.py:1542) and before the terminal
   echoes — *why*: still inside the lock (which runs to 1568), and after the stats file is
   written so a checkpoint hiccup cannot cost the operator the build report.
4. In `ingest`, call it once after whichever apply path ran, before `_report_skipped` —
   *why*: one call covers all three modes and runs only after the writes are done.
5. In `upsert`, add `except WikiStoreBusy` **before** the existing `except Exception` —
   *why*: Python matches handlers in order, and `WikiStoreBusy` subclasses
   `sqlite3.OperationalError` which subclasses `Exception`; placing it after would make it
   unreachable.
6. Honour `quiet` in the new upsert message — *why*: `upsert --changed --quiet` runs from a
   git post-commit hook; that is exactly where an unexpected line is most unwelcome.
7. Add NO checkpoint to `upsert` — *why*: explicit non-goal in spec §1.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY — helper)

```python
# occurrences: 1 (verified: grep -c '^def _open_sources(' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py)
# BEFORE — insert above `def _open_sources(` (verified: cli.py:424)

def _checkpoint_if_sqlite(store: BaseWikiStore, label: str) -> None:
    """Fold the WAL back after a long writer; never fail the command.

    ``checkpoint()`` is concrete to :class:`SQLiteWikiStore` — the
    memory, ArangoDB and Postgres backends have no such method — so the
    call is guarded. A checkpoint is maintenance: a failure is logged
    and swallowed, never surfaced as a non-zero exit (AC-7).

    Args:
        store: The store the long writer just used.
        label: Command name, for the debug line.
    """
    if not isinstance(store, SQLiteWikiStore):
        return
    try:
        report = _run(store.checkpoint())
    except Exception:  # noqa: BLE001 - maintenance must never fail the command
        logger.debug("%s: WAL checkpoint failed", label, exc_info=True)
        return
    logger.debug("%s: WAL checkpoint %s", label, report)
```
**Why this shape**: the `isinstance` guard is mandatory — `_open_store` is typed
`-> BaseWikiStore` and genuinely returns arango/memory/postgres stores in this CLI.
`except Exception` is deliberate and is the one place in this feature where a blanket catch
is correct: AC-7 makes "never fail the build" the stronger requirement. Import
`SQLiteWikiStore` alongside the existing `create_wiki_store` import, and confirm the
module-level `logger` and the `_run(...)` async bridge already used at cli.py:1506/1728.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY — build)

```python
# occurrences: 1 (verified: grep -c '            counts.get("graph"),' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py)
# AFTER — insert below the closing `        )` of the `_write_build_stats(` call
#         (verified: cli.py:1536-1542; the line `            counts.get("graph"),` is
#         at 1541 and the closing paren at 1542). Still INSIDE the writer lock, whose
#         body runs to cli.py:1568.
        _checkpoint_if_sqlite(store, "build")
```
**Why**: inside the lock means no peer writer can be mid-transaction, which is when
`TRUNCATE` has the best chance of succeeding. After `_write_build_stats` means the operator
keeps their report regardless. **FILL IN**: confirm the local variable holding the store in
`build`'s scope is named `store` — check the `_open_store` / `_require_built` call inside
`build` (between cli.py:1403 and 1450) and use whatever name is actually bound there.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY — ingest)

```python
# FILL IN: add ONE `_checkpoint_if_sqlite(store, "ingest")` call in `ingest` (def at
# cli.py:3970) that runs after whichever apply path executed — the three drives are at
# cli.py:4219 (--review), 4295 (--interactive) and 4324 (--auto) — and before
# `_report_skipped(skipped)` at cli.py:4335. Prefer a single call near the end of the
# function over three copies. Bounded by AC-7 and by the spec-correction box above:
# do NOT wrap `ingest` in a writer lock. The store variable is bound at cli.py:4061.
```
**Why**: `ingest` writes through three mutually exclusive flag paths but always converges
on the function tail, so one call at the end covers every mode without duplicating the
guard.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY — upsert soft-skip)

```python
# occurrences: 2 (verified: grep -c 'except Exception as exc:  # surfaced as a clear CLI error' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py)
# FILL IN: disambiguate — this handler text appears in BOTH `build` (cli.py:1507) and
# `upsert` (cli.py:1729). Target the `upsert` one by quoting its surrounding context:
#
#         try:
#             counts = _run(_pipeline())
#         except Exception as exc:  # surfaced as a clear CLI error
#             if config.backend == "arangodb":
#
# ...and insert a new handler BEFORE it (order matters — WikiStoreBusy subclasses
# sqlite3.OperationalError subclasses Exception, so a later handler is unreachable):
#
#         except WikiStoreBusy:
#             if not quiet:
#                 click.echo(
#                     "The wiki plane is busy (a build or another agent holds "
#                     "the SQLite writer lock) — skipping this upsert; the "
#                     "next build will cover these files."
#                 )
#             return
#
# Bounded by AC-8 and by the existing lock-busy skip at cli.py:1643-1650, whose wording
# and `quiet` handling this mirrors. Do NOT add a checkpoint here (spec §1 non-goal).
```
**Why**: `upsert --changed --quiet` is wired into a git post-commit hook, so a busy plane
must produce a calm skip and exit 0, exactly as a busy *file* lock already does. Returning
(not raising) is what keeps the hook green.

### `tests/knowledge/wiki/test_cli_checkpoint.py` (CREATE)

```python
"""FEAT-557 — which CLI commands checkpoint, and busy soft-skip in upsert."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.store import WikiStoreBusy


class TestCheckpointCallSites:
    def test_build_checkpoints(self, tmp_path: Path) -> None:
        """A successful build folds the WAL back (AC-7)."""
        # FILL IN: run the `build` command against a temp project with
        # `_checkpoint_if_sqlite` patched, assert it was called once with "build" —
        # bounded by AC-7. Follow the CliRunner setup already used in
        # tests/knowledge/wiki/test_cli.py.

    def test_ingest_checkpoints(self, tmp_path: Path) -> None:
        """A successful ingest folds the WAL back (AC-7)."""
        # FILL IN: bounded by AC-7.

    def test_upsert_does_not_checkpoint(self, tmp_path: Path) -> None:
        """`upsert --changed` must NOT checkpoint (spec §1 non-goal)."""
        # FILL IN: bounded by spec §1 ("No checkpoint after `upsert --changed`").

    def test_checkpoint_failure_does_not_fail_build(self, tmp_path: Path) -> None:
        """A raising checkpoint still leaves exit code 0 (AC-7)."""
        # FILL IN: patch store.checkpoint to raise, assert result.exit_code == 0 —
        # bounded by AC-7 ("never turns an otherwise successful long write into a
        # CLI failure").

    def test_non_sqlite_backend_is_skipped(self, tmp_path: Path) -> None:
        """A memory/arango store has no checkpoint(); the guard handles it."""
        # FILL IN: bounded by the isinstance guard in the Codebase Contract.


class TestUpsertBusySoftSkip:
    def test_busy_upsert_is_not_an_error(self, tmp_path: Path) -> None:
        """WikiStoreBusy yields exit 0 and an actionable message (AC-8)."""
        # FILL IN: patch the upsert pipeline to raise WikiStoreBusy, assert
        # exit_code == 0 and the skip message is echoed — bounded by AC-8.

    def test_busy_upsert_is_silent_when_quiet(self, tmp_path: Path) -> None:
        """`--quiet` keeps the git hook's output clean."""
        # FILL IN: bounded by the existing `quiet` handling at cli.py:1643-1650.
```

### FILL IN checklist
- [ ] `build` — confirm the store variable's real name before inserting the call.
- [ ] `ingest` — single `_checkpoint_if_sqlite` call before `_report_skipped`; no lock.
- [ ] `upsert` — `except WikiStoreBusy` inserted BEFORE the existing `except Exception`,
      disambiguated from the identical handler in `build`.
- [ ] All seven test bodies above.

---

## Acceptance Criteria

- [ ] A successful `build` calls `checkpoint()` once, inside its existing writer lock.
- [ ] A successful `ingest` calls `checkpoint()` once, in all three apply modes.
- [ ] `upsert --changed` never calls `checkpoint()`.
- [ ] A checkpoint that fails or raises leaves the command's exit code unchanged.
- [ ] A non-SQLite backend is skipped without `AttributeError`.
- [ ] `WikiStoreBusy` during `upsert` exits 0 with a skip message; `--quiet` suppresses it.
- [ ] `ingest` is NOT given a writer lock by this task.
- [ ] No regression: `pytest tests/knowledge/wiki/test_cli.py tests/knowledge/wiki/test_ingest.py -q`
- [ ] Tests pass: `pytest tests/knowledge/wiki/test_cli_checkpoint.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`

---

## Test Specification

See the blueprint. `tests/knowledge/wiki/test_cli.py` (69.8K) has the established
`CliRunner` + temp-project setup — copy its fixture pattern rather than inventing one.

---

## Agent Instructions

1. **Read the spec** — §3 Module 4, AC-7, AC-8. **Read the spec-correction box at the top
   of this file first** — the spec is wrong about `ingest` having a writer lock.
2. **Check dependencies** — TASK-3220 (`checkpoint()`) and TASK-3223 (plumbing) completed.
3. **Verify the Codebase Contract** — re-confirm with
   `grep -n 'wiki_write_lock(' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
   that there are still exactly three sites (1394, 1641, 2261) and none in `ingest`.
   If `ingest` has gained a lock since, STOP and report — the spec-correction box no
   longer applies and the design decision changes.
4. **Implement** from the blueprint; complete every `FILL IN`.
5. **Verify** every acceptance criterion.
6. **Record the `ingest` lock gap** in your Completion Note as a follow-up candidate.
7. **Move this file** to `sdd/tasks/completed/`; update the per-spec index; fill the note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-14
**Notes**: Added `_checkpoint_if_sqlite(store, label)` before `_open_sources`, guarded by
`isinstance(store, SQLiteWikiStore)` and swallowing any exception. `build` checkpoints
(SQLite backend only) inside its existing writer lock, right after `_write_build_stats`
— since `store` is local to the nested `_pipeline()` closure, a fresh `_open_store(root,
config)` handle is opened for the checkpoint call (cheap: the schema/migration probe on
it is a read-first no-op since the plane is already current). `ingest` checkpoints once
per apply-writing branch (`--review`, `--interactive`, `--auto` — NOT `--dry-run`, which
writes nothing), using the `store` variable already bound in `ingest`'s outer scope, with
no writer lock added (confirmed exactly 3 `wiki_write_lock(` sites remain: 1404/1651/2271,
none in `ingest`). `upsert` gets an `except WikiStoreBusy` handler inserted BEFORE the
existing `except Exception`, mirroring the file-lock-busy message/`quiet` handling exactly.
All 8 new tests pass (2 unit tests for the helper's own swallow/guard behavior + 4
call-site tests + 2 busy-soft-skip tests). Regression (`test_cli.py` + `test_ingest.py`):
133 passed. Full `tests/knowledge/wiki/` suite: 1684 passed, 11 skipped (unrelated), 1
pre-existing failure (noted since TASK-3217). `ruff check` clean on both touched files
(pre-existing, unrelated `Optional` F821 in `cli.py:_open_sources`'s signature, verified
identical on `dev`, left untouched).

**Deviations from spec**: `ingest` has no writer lock, so its checkpoint runs unlocked —
see the spec-correction box. AC-7's "under their existing writer lock" holds for `build`
only. Additionally, the blueprint's `build` snippet assumed a `store` variable directly
in scope at the insertion point; `store` is actually local to `_pipeline()`, so a fresh
`_open_store(root, config)` call was used instead (SQLite-only, guarded by
`config.backend == "sqlite"` to avoid an unnecessary ArangoDB reconnect). The blueprint's
"one call near the end" preference for `ingest` was not achievable without a control-flow
change: `--review`/`--interactive`/`--auto` each `return` from their own branch rather
than converging on a single tail, so one call was placed in each of the three branches
instead of one shared call site — noted as a follow-up candidate for a future refactor
that unifies the three apply paths' tails, but out of this task's scope.

**Follow-up candidate (not actioned, per the spec-correction box)**: `ingest` still has
no writer lock at all — two concurrent `ingest` invocations (or an `ingest` racing a
`build`) can interleave writes with no mutual exclusion. This is a pre-existing gap,
unrelated to FEAT-557, and adding one is an explicit non-goal of this task; it deserves
its own ticket.
