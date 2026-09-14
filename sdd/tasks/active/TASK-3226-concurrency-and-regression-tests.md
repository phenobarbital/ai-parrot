# TASK-3226: Multiprocess contention test and read-path SQL evidence

**Feature**: FEAT-557 — wikitoolkit SQLite concurrency hardening
**Spec**: `sdd/specs/wikitoolkit-sqlite-optimizations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3219, TASK-3220, TASK-3221, TASK-3224, TASK-3225
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 and §4. Every prior task carries its own focused tests. This task adds the
two things none of them can prove alone:

1. **The read-path SQL trace** — hard evidence for AC-4 that a read on a migrated plane
   issues zero write statements. Asserting it per-method is the only way to know the
   `_connect` → `_read` sweep (TASK-3219) actually removed the writes rather than moving
   them.
2. **The multiprocess contention test** — two real OS processes writing one WAL file,
   proving AC-3 end to end: every write either completes within the timeout or reports a
   typed `WikiStoreBusy`, and a raw `database is locked` never escapes.

It also registers the `slow` marker, which does not exist yet.

---

## Scope

- Register a `slow` pytest marker.
- Add the read-path SQL trace test covering `get_page`, `search_fts`, `symbols_for`,
  `stats`, `dump_pages` and `page_hashes`.
- Add the `slow`-marked multiprocess contention test.
- Add the checkpoint-call-site integration assertion (build/ingest yes, `upsert --changed` no).
- Run the existing wiki suite unchanged as the regression gate.
- Save evidence to `artifacts/logs/`.

**NOT in scope**: changing any production code — if a test fails, the fix belongs in the
task that owns that file. Changing any existing test's expectations.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `pytest.ini` | MODIFY | Register the `slow` marker |
| `tests/knowledge/wiki/test_store_concurrency.py` | MODIFY | Read-path trace + multiprocess contention |
| `tests/knowledge/wiki/test_cli_checkpoint.py` | MODIFY | Checkpoint call-site integration assertions |
| `artifacts/logs/feat-557-concurrency.log` | CREATE | Evidence of the runs |

---

## Codebase Contract (Anti-Hallucination)

### Test infrastructure — VERIFIED, and it is not what the spec says

> **Spec correction.** Spec §3 M5 names
> `packages/ai-parrot/tests/knowledge/wiki/test_store_concurrency.py`. That is the WRONG
> tree. Verified: `packages/ai-parrot/tests/knowledge/wiki/` holds 18 CLI/MCP/Jira/installer
> files and **no store tests at all**. The store's real suite is the 70-entry
> `tests/knowledge/wiki/`, which contains `test_store.py` (664 lines), `test_sources.py`,
> `test_federation.py`, `test_project_lock.py`, `test_store_migration_v2.py`. All FEAT-557
> tests live in `tests/knowledge/wiki/`.

**`pytest.ini` at the repo root is the governing config** (a `pytest.ini` always wins over
`[tool.pytest.ini_options]` in any `pyproject.toml`). Verified contents:

```ini
# pytest.ini
[pytest]
asyncio_mode = auto
markers =
    integration: Integration tests with external APIs (Telegram, Massive, etc)
    live: Live integration tests that require external services (claude CLI, Redis, real LLM API). Skipped when prerequisites are missing.
    real_llm: Real LLM integration tests (require PARROT_TEST_REAL_LLM=1 env var)
filterwarnings =
    ignore::DeprecationWarning
```

Consequences you must rely on:
- `asyncio_mode = auto` → `async def test_...` needs **no** `@pytest.mark.asyncio`.
- There is **no `slow` marker** — you must add it (step 1).
- `--strict-markers` is NOT active here, so an unregistered marker only warns. Register it
  anyway: the repo registers every marker it uses, and the root `pyproject.toml` DOES set
  `--strict-config`/`--strict-markers` for its own `testpaths`.

Existing store-test patterns to follow — `tests/knowledge/wiki/test_store.py:55-85`:
```python
@pytest.fixture(params=["sqlite", "memory", pytest.param("postgres", marks=needs_pg)])
async def store(tmp_path: Path, request: pytest.FixtureRequest) -> BaseWikiStore:
    """Fresh store of each backend, rooted at tmp_path."""
    ...
        yield create_wiki_store(tmp_path, wiki_name="test-wiki", backend=request.param)
```
Test classes already in that file: `TestHelpers` (102), `TestPagesCrud` (122),
`TestSearchFts` (183), `TestVectorSearch` (220), `TestEdgesAndNeighbors` (243),
`TestReplaceSourceSlice` (283), `TestLintQueries` (347), `TestRebuildFromTree` (372),
`TestReadOnlyFallback` (418), `TestExplicitReadOnlyMode` (613),
`TestReadOnlyConcurrencySafety` (710), `TestSymbolPlane` (741).

`tests/knowledge/wiki/conftest.py` (13 KB) defines `pytest_configure` registering an
`arangodb` marker (lines 27-39) and an autouse `isolated_parrot_home` (41-57) — a
per-directory precedent for registering a marker, if you prefer that to `pytest.ini`.

### Reader/writer method inventory — for the trace test

**15 readers** (must issue no write): `symbols_for`, `find_symbols`, `search_symbols_fts`,
`page_hashes`, `get_page`, `list_pages`, `search_fts`, `search_vector`, `neighbors`,
`dump_pages`, `dump_edges`, `stats`, `orphan_sources`, `broken_edges`, `missing_bodies`.

**6 writers**: `upsert_pages`, `add_edges`, `replace_source_slice`, `delete_page`,
`upsert_embedding`, `upsert_symbols`.

### How to trace SQL — verified mechanism

`aiosqlite.Connection` proxies the stdlib connection. `sqlite3.Connection.set_trace_callback(fn)`
fires `fn(statement: str)` for every statement. Reach the underlying connection through the
aiosqlite wrapper (it exposes `._conn`) or install the callback via `conn._execute(...)`.

**FILL IN**: confirm the exact attribute on the installed `aiosqlite` version before
relying on `._conn`; if it differs, wrap `conn.execute` instead. Bounded by: the test must
observe EVERY statement, not just the ones the test itself issues.

### Does NOT Exist

- ~~a `slow` marker~~ — verified absent from `pytest.ini` and from both `pyproject.toml`
  files. Step 1 adds it.
- ~~`test_store_concurrency.py` in `packages/ai-parrot/tests/`~~ — and it must not be
  created there. See the spec-correction box.
- ~~`pytest-xdist` being configured~~ — do not assume `-n auto` is available.
- ~~a writer lock in `ingest`~~ — see TASK-3224; the contention test must not assume one.

> **`pytest` hang gotcha (repo-wide, pre-existing).** The suite can finish its summary and
> then never exit. Wrap long runs:
> `timeout -s KILL 600 pytest tests/knowledge/wiki/ -q`

---

## Implementation Blueprint

### Steps (in order)
1. Register the `slow` marker in `pytest.ini` — *why*: the multiprocess test is slow by
   construction and must be deselectable with `-m "not slow"`; an unregistered marker is a
   warning today and a hard error under the root `pyproject.toml`'s `--strict-markers`.
2. Write the read-path trace test first — *why*: it is the direct evidence for AC-4, the
   feature's central claim, and it fails loudly if TASK-3219 missed a call site.
3. Drive the contention test with `multiprocessing.Event`, not `sleep` — *why*: spec §4
   names the fixture, and a sleep-coordinated test is flaky under CI load, which is exactly
   when a concurrency test must be trustworthy.
4. Use a SHORT `busy_timeout_s` in the contention test — *why*: the assertion is "typed
   busy, never raw lock error"; waiting the full 15 s default to observe it makes the suite
   painful for no added signal.
5. Assert the error TYPE and its attributes, never a message substring — *why*: spec §7.
6. Run the full wiki suite last and save the output — *why*: CLAUDE.md requires evidence in
   `artifacts/logs/`, and this task is the feature's verification gate.

### `pytest.ini` (MODIFY)

```ini
# occurrences: 1 (verified: grep -c 'real_llm: Real LLM integration tests' pytest.ini)
# AFTER — insert below the `real_llm: ...` line in the `markers =` block:
    slow: Long-running tests (multiprocess contention, large fixtures). Deselect with -m "not slow".
```
**Why**: one four-space-indented continuation line, matching the three markers already
there. Do not restructure the block.

### `tests/knowledge/wiki/test_store_concurrency.py` (MODIFY — read-path trace)

```python
# AFTER — append to the file created by TASK-3217 / extended by TASK-3218 / TASK-3220.

_WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "DROP", "REPLACE",
                   "COMMIT", "BEGIN")


def _is_write(statement: str) -> bool:
    """Whether a traced SQL statement mutates or opens a transaction."""
    return statement.strip().upper().startswith(_WRITE_PREFIXES)


class TestReadPathIssuesNoWrites:
    """AC-4: pure reads on a migrated plane take no writer lock."""

    @pytest.mark.parametrize(
        "call",
        [
            lambda s: s.get_page("intro"),
            lambda s: s.search_fts("neural"),
            lambda s: s.stats(),
            lambda s: s.dump_pages(),
            lambda s: s.page_hashes(["intro"]),
            lambda s: s.symbols_for("a.py"),
        ],
    )
    async def test_reader_issues_no_write_statement(self, store, call) -> None:
        """Trace every statement a reader issues and assert none writes."""
        # FILL IN: install a trace callback that appends to a list, invoke `call(store)`,
        # and assert `[s for s in traced if _is_write(s)] == []`. See the "How to trace
        # SQL" note in the Codebase Contract for reaching the stdlib connection —
        # bounded by AC-4. The plane must already be MIGRATED before tracing starts,
        # otherwise first-use schema replay legitimately writes.

    async def test_read_only_ladder_sets_timeout_but_no_write_pragma(self, tmp_path) -> None:
        """AC-4: mode=ro / immutable rungs get the busy timeout only."""
        # FILL IN: bounded by AC-4 and spec §7 ("read-only mode=ro and immutable
        # fallbacks may receive busy timeout and read-safe performance settings only").
```

### `tests/knowledge/wiki/test_store_concurrency.py` (MODIFY — contention)

```python
# AFTER — append below the class above.

def _peer_writer(db_path: str, ready, release, result) -> None:
    """Child process: hold an immediate writer transaction, then release.

    Runs in a SEPARATE process so the contention is real OS-level SQLite
    locking, not asyncio task interleaving in one process.
    """
    # FILL IN: open stdlib sqlite3 on `db_path`, run BEGIN IMMEDIATE, set `ready`,
    # wait on `release`, then COMMIT and close. Put the whole body in try/except and
    # report through `result` so a child crash surfaces as a test failure rather than
    # a hang — bounded by spec §4 ("two independently opened processes, coordinated
    # by multiprocessing.Event, to hold an immediate writer lock deterministically").


@pytest.mark.slow
class TestMultiprocessContention:
    """AC-3 end to end: typed busy or success, never `database is locked`."""

    async def test_peer_writer_yields_typed_busy_never_raw_lock_error(self, tmp_path) -> None:
        """A held peer writer produces WikiStoreBusy, not a raw OperationalError."""
        # FILL IN: spawn `_peer_writer` via multiprocessing, wait for `ready`, then
        # attempt a write through a store built with SQLitePragmaPolicy(busy_timeout_s=1.0)
        # and assert it raises WikiStoreBusy carrying db_path/operation/waited_seconds.
        # Assert on the TYPE, never on a message substring (spec §7). ALWAYS set
        # `release` and join the child in a `finally` so a failure cannot hang the
        # suite — bounded by AC-3.

    async def test_write_completes_when_peer_releases_within_timeout(self, tmp_path) -> None:
        """A writer that releases in time lets the waiter through — no error."""
        # FILL IN: release the peer well inside the busy timeout and assert the write
        # SUCCEEDS. This is the other half of AC-3 ("all writes either complete within
        # timeout or report typed busy") and is what proves the busy handler is
        # actually installed rather than the timeout merely being recorded.

    async def test_source_manager_and_store_contend_safely(self, tmp_path) -> None:
        """The sync SourceCollectionManager and async store share one WAL safely."""
        # FILL IN: drive a SourceCollectionManager write against the same wiki.db while
        # the store holds a writer, and assert the same typed-busy-or-success property
        # — bounded by AC-6 and spec §4's "peer remember/source write against one WAL
        # file".
```

### `tests/knowledge/wiki/test_cli_checkpoint.py` (MODIFY)

```python
# FILL IN: add one integration test asserting the checkpoint call-site policy as a
# whole — build checkpoints, ingest checkpoints, `upsert --changed` does NOT — in a
# single test so the three-way contract is visible in one place. Bounded by AC-7 and
# spec §1's non-goal ("No checkpoint after `upsert --changed`"). TASK-3224 created
# this file with the per-command tests; this is the combined assertion.
```

### Evidence

```bash
# Run from the repo root, with the venv active.
mkdir -p artifacts/logs
source .venv/bin/activate

# 1. The feature's own tests, including the slow tier.
timeout -s KILL 900 pytest tests/knowledge/wiki/test_store_concurrency.py \
    tests/knowledge/wiki/test_sources_concurrency.py \
    tests/knowledge/wiki/test_sqlite_policy.py \
    tests/knowledge/wiki/test_project_sqlite_config.py \
    tests/knowledge/wiki/test_sqlite_policy_plumbing.py \
    tests/knowledge/wiki/test_cli_checkpoint.py \
    tests/knowledge/wiki/test_cli_status_sqlite.py \
    -v 2>&1 | tee artifacts/logs/feat-557-concurrency.log

# 2. The full wiki suite, unchanged, as the regression gate (AC-9).
timeout -s KILL 900 pytest tests/knowledge/wiki/ -q 2>&1 \
    | tee -a artifacts/logs/feat-557-concurrency.log

# 3. Lint the touched files.
ruff check packages/ai-parrot/src/parrot/knowledge/wiki/ tests/knowledge/wiki/ 2>&1 \
    | tee -a artifacts/logs/feat-557-concurrency.log

# 4. Confirm the slow tier is deselectable.
timeout -s KILL 900 pytest tests/knowledge/wiki/ -q -m "not slow" 2>&1 \
    | tee -a artifacts/logs/feat-557-concurrency.log
```

### FILL IN checklist
- [ ] `test_reader_issues_no_write_statement` — the trace mechanism; bounded by AC-4.
- [ ] `test_read_only_ladder_sets_timeout_but_no_write_pragma`; bounded by AC-4.
- [ ] `_peer_writer` child body; bounded by spec §4.
- [ ] `test_peer_writer_yields_typed_busy_never_raw_lock_error`; bounded by AC-3.
- [ ] `test_write_completes_when_peer_releases_within_timeout`; bounded by AC-3.
- [ ] `test_source_manager_and_store_contend_safely`; bounded by AC-6.
- [ ] Combined checkpoint call-site test; bounded by AC-7.

---

## Acceptance Criteria

- [ ] `slow` is a registered marker; `pytest -m "not slow"` deselects the contention class.
- [ ] Every one of the six traced read methods issues zero write statements on a migrated
      plane.
- [ ] The multiprocess test proves: held peer writer → `WikiStoreBusy` with all three
      attributes; released in time → the write succeeds.
- [ ] A raw `sqlite3.OperationalError: database is locked` never escapes a store or
      source-manager write.
- [ ] `build` and `ingest` checkpoint; `upsert --changed` does not.
- [ ] Full suite green: `timeout -s KILL 900 pytest tests/knowledge/wiki/ -q`
- [ ] No existing test's expectations were changed.
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/ tests/knowledge/wiki/`
- [ ] Evidence saved to `artifacts/logs/feat-557-concurrency.log`.

---

## Test Specification

The blueprint above IS the specification. The two load-bearing tests are
`test_reader_issues_no_write_statement` (AC-4) and
`test_peer_writer_yields_typed_busy_never_raw_lock_error` (AC-3) — if either cannot be made
to pass, the problem is in the production code, and the fix belongs to whichever task owns
that file, not here.

---

## Agent Instructions

1. **Read the spec** — §4 (the full test specification), §3 Module 5, AC-3/4/9. Read the
   spec-correction box above: the spec's test directory is wrong.
2. **Check dependencies** — TASK-3219, 3220, 3221, 3224, 3225 all completed. This is the
   last task in the feature.
3. **Verify the Codebase Contract** — confirm `pytest.ini` still lacks a `slow` marker and
   that `tests/knowledge/wiki/test_store.py` is still the store's suite.
4. **Implement** from the blueprint; complete every `FILL IN`.
5. **Verify** every acceptance criterion and save the evidence.
6. **Move this file** to `sdd/tasks/completed/`; update the per-spec index; fill the note.

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: test modules live in `tests/knowledge/wiki/`, not
`packages/ai-parrot/tests/knowledge/wiki/` as spec §3 M5 states — the latter tree contains
no store tests.
