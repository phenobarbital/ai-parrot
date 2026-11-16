# TASK-5707: Replay-safe review order, exact review scope, ceiling warning and CLI errors

**Feature**: FEAT-892 — Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: S (1–2h)
**Depends-on**: TASK-5706, TASK-5678
**Assigned-to**: claude (sdd-fix)
**Discovered-from**: `issue:5fb1a338c719`

## Context

Feature review of FEAT-892, minor findings bundle (`issue:5fb1a338c719`). This task takes the four findings that live
in `backends/sqlite.py` and `dynamics/cli.py`:

- **(a)** `list_reviews` orders by `recorded_at`, a wall clock. A clock step can reorder commits made by different
  processes; `rowid` follows commit order.
- **(b)** `apply_review` checks that the episode exists with `namespace.build_filter()`, which drops unset dimensions.
  A ref whose namespace has no `user_id` therefore admits an episode owned by a user, and the state lands under a ref
  key that differs from the episode's own. The store already requires an exact match; the backend, a public API, does
  not.
- **(c)** `search_similar` scores only the newest `vector_ceiling` candidates but logs nothing when it truncates (D7
  requires a warning).
- **(g)** `dynamics/cli.py::_execute` converts only `TypeError` and `ValueError`; any other failure prints a traceback.

## Scope

- (a) `ORDER BY rowid ASC` in `list_reviews`.
- (b) Exact match on all seven scope dimensions in `apply_review`.
- (c) A warning when the scoped candidate set exceeds the ceiling.
- (g) `_execute` reports every `Exception` as a `click.ClickException`.
- Tests for the four changes.

**NOT in scope:** findings (d) Redis write atomicity, (e) `HybridBM25Strategy.invalidate`, (f) feedback timestamps,
(h) deprecation warnings, (i) unshielded completion and (j) private attribute reads. Their files are being edited by
TASK-5703 and TASK-5704 or are outside the files this issue names; they move to a follow-up ledger issue. No change to
the review digest, to `vector_status` or to the CLI command set.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py` | MODIFY | (a) order, (b) exact scope, (c) warning |
| `packages/ai-parrot/src/parrot/memory/dynamics/cli.py` | MODIFY | (g) error conversion |
| `packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py` | MODIFY | Tests for (a), (b), (c) |
| `packages/ai-parrot/tests/memory/agent_memory/test_operations.py` | MODIFY | Test for (g) |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

- `from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend`
- `from parrot.memory.dynamics.cli import register_memory_commands`
- `import click` and `from click.testing import CliRunner`

### Existing Signatures to Use

- `reviews(dedupe_key TEXT PRIMARY KEY, …)` is a rowid table (no `WITHOUT ROWID`), and review rows are never deleted,
  so `rowid` increases with every commit made under `BEGIN IMMEDIATE` (`backends/sqlite.py:65`).
- `_FILTERABLE_COLUMNS` lists the seven scope columns, which are also the `MemoryNamespace` field names
  (`backends/sqlite.py:35`).
- `EpisodicMemoryStore._episode_matches_namespace` compares the same seven fields (`episodic/store.py`).
- `search_similar` (after TASK-5706) reads `episode_id, embedding, embedding_dim` with `LIMIT self._vector_ceiling`.
- `logger = logging.getLogger(__name__)` at module level (`backends/sqlite.py:29`).
- `_execute(settings, operation)` wraps `asyncio.run(_invoke(...))` (`dynamics/cli.py:34`); `export-reviews` raises a
  `click.ClickException` from inside the operation.

### Does NOT Exist

- A sequence column on `reviews`; no schema change is needed and `_SCHEMA_VERSION` stays 3.
- A logger on `dynamics/cli.py`; the CLI reports through `click.ClickException`.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/memory/dynamics/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/memory/agent_memory/test_operations.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py#SQLiteEpisodeBackend.list_reviews",
    "sym:packages/ai-parrot/src/parrot/memory/dynamics/cli.py#register_memory_commands"
  ]
}
```

## Implementation Notes

### Key Constraints

- (b) An episode outside the exact scope answers `ignored` / `memory ref is unavailable`, the same receipt as a missing
  episode, so the backend never reveals that the id exists elsewhere.
- (c) One extra candidate row is read to detect truncation; the result set and `vector_status` do not change.
- (g) `click.ClickException` passes through unchanged; `KeyboardInterrupt` and other `BaseException`s are not caught.

## Implementation Blueprint

### Steps (in order)

1. `sqlite.py` (a): replace the `ORDER BY` — because wall-clock order is not commit order.
2. `sqlite.py` (b): build the episode predicate from all seven columns — because `build_filter()` drops unset ones.
3. `sqlite.py` (c): read `vector_ceiling + 1` candidates, warn and drop the extra row.
4. `cli.py` (g): widen the conversion.
5. Tests, then the Validation Commands.

### `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py` (MODIFY)

```python
# REPLACES `"ORDER BY recorded_at ASC, dedupe_key ASC"` (verified: sqlite.py:681)
# occurrences: 1 (verified: grep -c 'ORDER BY recorded_at ASC, dedupe_key ASC' sqlite.py)
"ORDER BY rowid ASC"

# REPLACES `scope_filter = namespace.build_filter()` and the loop that reads it (verified: sqlite.py:329)
# occurrences: 1
for field in _FILTERABLE_COLUMNS:
    value = getattr(namespace, field)
    # FILL IN: `IS NULL` for None, `= ?` otherwise — bounded by Key Constraints (b)
```

**Why**: both changes make the backend enforce what the store already assumes.

### `packages/ai-parrot/src/parrot/memory/dynamics/cli.py` (MODIFY)

```python
# REPLACES `except (TypeError, ValueError) as exc:` and its body (verified: cli.py:41)
# occurrences: 1 (verified: grep -c 'except (TypeError, ValueError) as exc:' cli.py)
except click.ClickException:
    raise
except (TypeError, ValueError) as exc:
    raise click.ClickException(str(exc)) from exc
except Exception as exc:  # noqa: BLE001 - a command reports its failure, it does not print a traceback
    raise click.ClickException(f"{type(exc).__name__}: {exc}") from exc
```

**Why**: an operator needs the failure and its type, not a traceback.

### FILL IN checklist

- [ ] (b) predicate loop — bounded by Key Constraints (b).
- [ ] (c) warning text names the candidate limit and the scope filter keys, never values.

## Acceptance Criteria

- [ ] Reviews are listed in commit order even when `recorded_at` goes backwards.
- [ ] `apply_review` answers `ignored` for an episode that matches only the non-null dimensions of the ref namespace.
- [ ] A search over more candidates than the ceiling logs one warning and returns the same rows as before.
- [ ] A failing memory command exits non-zero with `Error: <Type>: <message>` and no traceback.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py packages/ai-parrot/tests/memory/agent_memory/test_operations.py packages/ai-parrot/tests/memory/dynamics/test_export.py -q`

## Test Specification

- `test_list_reviews_follows_commit_order_when_clock_steps_back`: (a).
- `test_apply_review_requires_exact_episode_scope`: (b).
- `test_measured_ceiling_reports_degradation`: extended with the warning assertion, (c).
- `test_memory_cli_reports_unexpected_failures_without_traceback`: (g).

## Agent Instructions

1. Verify the Codebase Contract against the source before editing.
2. Touch only the files listed above.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit code with `fix(agent-memory-mixin): TASK-5707 — Replay-safe review order, exact review scope, ceiling warning and CLI errors`,
   then close the task with `scripts/sdd/close_task.sh`.

## Completion Note

- Task: TASK-5707
- Feature: agent-memory-mixin
- Implementation SHA: d64b2eac04
- Closed at (UTC): 2026-11-16T10:04:28+00:00
- Resolves: findings (a), (b), (c) and (g) of `issue:5fb1a338c719`
- Validation: `test_sqlite_backend.py`, `test_operations.py` and `test_export.py` pass (29 tests) in a clean tree of
  the commit. Each new assertion fails on the previous code: the order test lists `second, third, first`, the scope
  test gets `applied`, the ceiling test sees no warning and the CLI test gets a raw exception.
- (b) is consistent with TASK-5703, which keeps review identity on the exact namespace and leaves cross-scope review out
  of scope. Only `EpisodicMemoryStore` calls `apply_review`, and it already required the exact match.
- (c) reads one row beyond the ceiling to detect truncation; that row is dropped before scoring.
- (g) keeps the plain message for `TypeError` / `ValueError` and lets a `click.ClickException` through unchanged.
- Not done here: findings (d) Redis write atomicity, (e) `HybridBM25Strategy.invalidate`, (f) feedback timestamps,
  (h) deprecation warnings, (i) unshielded completion and (j) private attribute reads. When this task was filed the
  files of (d), (e), (f) and (j) were being edited by TASK-5703 and TASK-5704; both have landed since. The six findings
  are re-filed as one ledger issue with their real files, so `issue:5fb1a338c719` can close on the four fixed here.
- `started_at` was written together with this note; no separate start commit was made.
- Implemented by Claude through `/sdd-fix`, by hand (no coder seat).
