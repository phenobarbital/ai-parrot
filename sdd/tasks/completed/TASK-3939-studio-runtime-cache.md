# TASK-3939: StudioRuntimeCache and StudioCacheEntry (leases, retirement, reclaimable)

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W2 — Runtime + cache + lifecycle + builder (M7, part 1: StudioRuntimeCache)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2.7 (`StudioRuntimeCache`, base + session entries), §2.7a (retirement, grace, leases, ref-counted versioned
asset directories), §3 Module 7 skeleton. Spec §3 names one module `manager/studio_runtime.py`; to respect
ARCHITECTURE Rule 4 (≤ 500 lines) the cache and the builder get their own modules, re-exported from
`studio_runtime.py` (TASK-3942) so the X7/X8 import path is unchanged.

---

## Scope

- `manager/studio_cache.py`: `StudioCacheEntry` (fields exactly as the §3 M7 skeleton) and `StudioRuntimeCache` with
  `current`, `session`, `install` (returns the replaced entry, now retired), `retire(entry, *, now)`,
  `reclaimable(*, now, grace, session_ttl, idle_ttl)`, `all_entries`, plus asset-dir reference counting per
  `(agent_id, version)` (`acquire_dir`, `release_dir` → True when the last user is gone).
- Pure, synchronous, DB-free; no cleanup calls (the runtime cleans).

**NOT in scope**: Building or cleaning instances (TASK-3940/21); sweep task.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/studio_cache.py` | CREATE | StudioCacheEntry, StudioRuntimeCache |
| `packages/ai-parrot-server/tests/manager/test_studio_cache.py` | CREATE | fake-clock unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
from parrot.bots.abstract import AbstractBot      # type of StudioCacheEntry.bot
```

### Does NOT Exist
- ~~`StudioRuntimeCache`, `StudioCacheEntry`~~ — created here. It is NEVER `BotManager._bots`/`_botdef` (R2, X7).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/manager/studio_cache.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/manager/test_studio_cache.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Parallelism: no dependency (pure bookkeeping over UUID/str keys); creates manager/studio_cache.py imported by TASK-3942
- Cross-feature ordering: none for this new module; FEAT-605 W2.2 starts only after the whole STORAGE W2 runtime
  (TASK-3942/22).
- Rules (§2.7a): sessions past `session_ttl` with 0 leases are reclaimable; base entries idle past `idle_ttl` are
  retired; retired entries are reclaimable when leases == 0 AND `now - retired_at >= grace`; `cleaned` is the
  identity guard (an entry is returned at most once after it is marked cleaned).

### Common constraints (all FEAT-621 tasks)
- Contract verified against `dev` @ `32b1a45d4` (2026-09-30). Earlier FEAT-621 tasks shift line numbers:
  re-run every `grep -c` before editing and fix this file first if an anchor moved.
- Async throughout; the pool is the host's `app["database"]` (asyncdb `pg` pool); no sync driver, no second pool.
- Raw parametrised SQL (`$1…$n`), never value interpolation; schema literal `navigator`.
- Transactions only through `studio_transaction`; statements only through `_exec` (spec §2.5a).
- Pydantic for payloads, frozen dataclasses for records; `self.logger` in views,
  `logging.getLogger("Parrot.AgentStudio.Storage")` in storage/services/runtime.
- ARCHITECTURE Rule 4: functions ≤ 60 lines, cyclomatic complexity ≤ 10, modules ≤ 500 lines.
- **Database rule** (spec §4): integration tests read `TEST_STUDIO_PG_DSN` and `pytest.skip` with a reason when it is
  unset. Point it at a PostgreSQL ≥ 14 database dedicated to this worktree — the fixtures truncate `navigator.ai_*`.
- **Request/session rule** (spec §4, ARCHITECTURE R6): handler tests use `aiohttp_client` with the real session
  middleware or `make_mocked_request(..., app=app)` + `request["NAV_SESSION"] = SessionData(...)`; never a `Mock`
  with a hand-set `.session`. Each new assertion is mutation-checked (revert the guarded line ⇒ RED).
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src` as needed;
  never `uv sync` inside a worktree.

---

## Implementation Blueprint

> Write each block to its declared path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name or file path the blueprint fixes (they come from spec §2.4/§2.5/§3 skeletons).

### `packages/ai-parrot-server/src/parrot/manager/studio_cache.py` (CREATE)
```python
"""Studio runtime cache (spec §2.7/§2.7a). Private to StudioAgentRuntime; never BotManager._bots."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID


@dataclass
class StudioCacheEntry:
    qualified: str
    session_id: str | None
    agent_id: UUID
    version: int
    bot: "AbstractBot"
    asset_dir: Path | None
    leases: int = 0
    expires_at: float | None = None
    last_used: float = 0.0
    retired_at: float | None = None
    cleaned: bool = False


class StudioRuntimeCache:
    def __init__(self) -> None:
        self._base: dict[str, StudioCacheEntry] = {}
        self._sessions: dict[tuple[str, str], StudioCacheEntry] = {}
        self._retired: list[StudioCacheEntry] = []
        self._dir_refs: dict[tuple[UUID, int], int] = {}
    # FILL IN: current, session, install, retire, reclaimable, all_entries, acquire_dir, release_dir —
    #   bounded by the §2.7a rules in Implementation Notes.
```

### `packages/ai-parrot-server/tests/manager/test_studio_cache.py` (CREATE)
```python
"""FEAT-621 M7 — cache bookkeeping with a fake clock (AC14)."""
# FILL IN: test_install_retires_previous; test_session_expiry_requires_no_lease; test_retired_needs_grace_and_no_lease;
#   test_dir_refcount_across_base_and_session; test_three_versions_each_reclaimable_once.
```

---

## Acceptance Criteria

- [ ] Install retires the previous entry; reclaimable obeys session TTL, idle TTL, grace and leases (AC14 groundwork).
- [ ] Asset dirs are reference-counted per `(agent_id, version)` across base and session entries.
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/manager/test_studio_cache.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_install_retires_previous` | §2.7a |
| `test_session_expiry_requires_no_lease` | §2.7a |
| `test_retired_needs_grace_and_no_lease` | §2.7a |
| `test_dir_refcount_across_base_and_session` | §2.7a |
| `test_three_versions_each_reclaimable_once` | AC14 groundwork |

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-db-storage --feature-id FEAT-621`).
2. Read the spec sections cited in Context; check every `Depends-on` task is `"done"` in
   `sdd/tasks/index/agentstudio-db-storage.json`.
3. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
4. Set this task `"in-progress"` in the index (with `started_at`) and commit only the index.
5. Implement exactly the files listed, starting from the Blueprint; no refactors outside scope.
6. `ruff check --fix` the touched Python files; run the Validation Commands.
7. Commit code only (never `git add .`/`-A`):
   `feat(agentstudio-db-storage): TASK-3939 — StudioRuntimeCache and StudioCacheEntry (leases, retirement, reclaimable)`.
8. Close with `scripts/sdd/close_task.sh TASK-3939 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (sonnet)
**Date**: 2026-10-01
**Notes**: manager/studio_cache.py: StudioCacheEntry + StudioRuntimeCache (current/session/install/retire/reclaimable/all_entries, acquire_dir/release_dir ref-counting per (agent_id, version)). Pure and synchronous. Added mark_cleaned(entry) (identity guard: leaves every structure, never returned again) and a private _unlink; install retires the replaced entry at entry.last_used. Session expiry = leases 0 AND (now>=expires_at or now-last_used>=session_ttl); idle base entries with 0 leases are retired inside reclaimable(). 8 tests pass; 10 mutations RED (the one survivor, the redundant cleaned filter, got its own test).

**Deviations from spec**: none
