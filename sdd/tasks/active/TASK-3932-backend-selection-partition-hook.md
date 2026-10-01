# TASK-3932: Studio storage backend selection (ensure_studio_storage) and the _studio_partition hook

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W1 — Backend selection + partition hook (M4)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3926, TASK-3930
**Assigned-to**: unassigned

---

## Context

Spec §2.2 (`PARROT_STUDIO_STORAGE` auto/database/filesystem; probe), §2.7a (`ensure_studio_storage` memoised behind
an `asyncio.Lock`; `resolve_studio_storage` on_startup wrapper), §2.8 "Partition source", §3 Module 4, X5, X8, X10.

---

## Scope

- `storage/backend.py`: `STUDIO_STORAGE_APP_KEY = "studio_storage"`, `StudioStorage(backend, reason, repos)` with
  `require_for(part)` and a lazily built `services` property (calls `build_studio_services(app, repos)` from
  `storage.services`, imported inside the property — that package arrives in W2), `ensure_studio_storage(app)`,
  `resolve_studio_storage(app)`.
- Resolution matrix: setting × pool present/absent × ledger absent/complete/incomplete/drifted × server 13/14. `auto`:
  absent ⇒ `filesystem` (WARNING once); complete ⇒ `database`; incomplete/drifted/PG<14 ⇒ `unavailable` (ERROR).
  `database`: anything but complete ⇒ `unavailable`. `filesystem`: as today. No pool ⇒ `filesystem` for auto,
  `unavailable` for database.
- `setup_studio_routes`: append `resolve_studio_storage` to `app.on_startup` **once per app** (guard key).
- `StudioBaseView._studio_partition()` (async, returns `StudioPartition.GLOBAL`) and `_studio_storage()`.

**NOT in scope**: Phase-2 required version 8 (TASK-3952); handler use of the storage (W3); the runtime hooks (TASK-3942).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py` | CREATE | StudioStorage, ensure_studio_storage, resolve_studio_storage |
| `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` | MODIFY | register resolve_studio_storage once per app |
| `packages/ai-parrot-server/src/parrot/handlers/studio/_base.py` | MODIFY | _studio_partition and _studio_storage on StudioBaseView |
| `packages/ai-parrot-server/tests/studio/storage/test_backend.py` | CREATE | resolution matrix + partition hook tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
from parrot.handlers.studio.storage.migrate import (read_ledger, LedgerState, list_migrations,
    STUDIO_SCHEMA_REQUIRED)                                                   # TASK-3924/05
from parrot.handlers.studio.storage.repositories import StudioRepositories, build_studio_repositories  # TASK-3930
from parrot.handlers.studio.storage.models import StudioPartition, StudioStorageUnavailable           # TASK-3922
from navconfig import config                                                  # settings source used by parrot.conf
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py
def setup_studio_routes(app: web.Application) -> None:          # line 26 (occurrences: 1)
    app.on_startup.append(reconcile_skills_catalog)             # line 88 (occurrences: 1) ← anchor for the new hook
# packages/ai-parrot-server/src/parrot/handlers/studio/_base.py
class StudioBaseView(BaseView):                                  # line 121
    async def _get_user(self) -> StudioUser:                     # line 164 (occurrences: 1) ← insert before it
```
`app["database"]` is the asyncdb pg pool (`studio/agents.py:63-64` reads it).

### Does NOT Exist
- ~~`ensure_studio_storage`, `StudioStorage`, `_studio_partition`~~ — created here.
- ~~`setup_studio_routes(app, *, prefix=None, view_wrapper=None)`~~ — FEAT-605 W0.2 changes the signature; if it
  merged first, anchor on the new signature and keep the once-per-app guard.
- ~~`PARROT_STUDIO_STORAGE`~~ config key — new.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/_base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/storage/test_backend.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py#setup_studio_routes",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/_base.py#StudioBaseView"
  ]
}
```

---

## Implementation Notes

- Parallelism: maps read_ledger/LedgerState from TASK-3926 (storage/migrate.py) to a backend and builds StudioRepositories from TASK-3930 (storage/repositories.py); first FEAT-621 writer of studio/__init__.py and studio/_base.py (TASK-3944 follows on _base.py)
- Cross-feature ordering: X16 — `studio/_base.py` and `studio/__init__.py` also carry small FEAT-605 edits (W0.2,
  W1.1, W2.1): serialise, whichever merges first; rebase onto the other. FEAT-605 W2.1 overrides `_studio_partition`
  and needs STORAGE W0+W1 (this task included) merged. FEAT-605 W0.2's per-prefix idempotency must keep
  `resolve_studio_storage` appended at most once per app (X10).
- `reason` is logged, never returned to clients. The probe is read-only (three statements, one connection).
- `services` is a lazy property so this W1 task does not import W2 code; it is exercised from TASK-3944 on.

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

### Steps (in order)
1. Write `backend.py`; 2. hook it in `setup_studio_routes`; 3. add the two `_base.py` methods; 4. tests.

### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py` (CREATE)
```python
"""Studio storage backend selection (spec §2.2, §2.7a)."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from aiohttp import web

from .models import StudioPartition, StudioStorageUnavailable
from .repositories import StudioRepositories, build_studio_repositories

logger = logging.getLogger("Parrot.AgentStudio.Storage")
STUDIO_STORAGE_APP_KEY = "studio_storage"
_LOCK_KEY = "_astudio_storage_lock"


@dataclass
class StudioStorage:
    backend: Literal["database", "filesystem", "unavailable"]
    reason: str | None = None
    repos: StudioRepositories | None = None
    app: Any = field(default=None, repr=False)
    _services: Any = field(default=None, repr=False)

    def require_for(self, part: StudioPartition) -> None:
        if self.backend == "unavailable" or (self.backend != "database" and part.tenant is not None):
            raise StudioStorageUnavailable(self.reason or self.backend)

    @property
    def services(self) -> Any:
        if self.backend != "database":
            return None
        if self._services is None:
            from .services import build_studio_services   # W2 (TASK-3933); lazy by design
            self._services = build_studio_services(self.app, self.repos)
        return self._services


async def ensure_studio_storage(app: web.Application) -> StudioStorage:
    """Idempotent, lock-guarded, memoised on app[STUDIO_STORAGE_APP_KEY]; runs the §2.2 probe once."""
    # FILL IN: setdefault an asyncio.Lock under _LOCK_KEY; return memoised; else read setting
    #   (config.get("PARROT_STUDIO_STORAGE", fallback="auto")), probe via read_ledger on app.get("database"),
    #   map with _resolve(...) — bounded by test_backend_resolution_matrix.
    raise NotImplementedError


async def resolve_studio_storage(app: web.Application) -> None:
    await ensure_studio_storage(app)
```

### `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    app.on_startup.append(reconcile_skills_catalog)' __init__.py)
# AFTER — insert below `    app.on_startup.append(reconcile_skills_catalog)` (verified: __init__.py:88)
    from .storage.backend import resolve_studio_storage

    if not app.get("_astudio_storage_hook_installed"):
        app["_astudio_storage_hook_installed"] = True
        app.on_startup.append(resolve_studio_storage)
```

### `packages/ai-parrot-server/src/parrot/handlers/studio/_base.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def _get_user(self) -> StudioUser:' _base.py)
# BEFORE — insert above `    async def _get_user(self) -> StudioUser:` (verified: _base.py:164)
    async def _studio_partition(self) -> "StudioPartition":
        """Storage partition for this request: GLOBAL here; FEAT-605 v0.2 W2.1 overrides it (X5)."""
        from .storage.models import StudioPartition
        return StudioPartition.GLOBAL

    def _studio_storage(self) -> "StudioStorage":
        return self.request.app["studio_storage"]
```

### `packages/ai-parrot-server/tests/studio/storage/test_backend.py` (CREATE)
```python
"""FEAT-621 M4 — backend matrix (§2.2) and partition hook."""
# FILL IN: test_backend_resolution_matrix — parametrise setting × pool × ledger state × server version using a
#   LedgerState stub returned by a patched read_ledger (pure mapping) plus one real-PG case per outcome when the
#   DSN is set; test_ensure_is_memoised_and_locked (two concurrent calls probe once);
#   test_require_for_tenant_on_filesystem_raises; test_hook_registered_once (setup_studio_routes twice →
#   resolve_studio_storage appears once in app.on_startup); test_studio_partition_default_global (request built
#   with make_mocked_request + NAV_SESSION).
```

### FILL IN checklist
- [ ] `ensure_studio_storage` + `_resolve` mapping.
- [ ] five tests.

---

## Acceptance Criteria

- [ ] Resolution matrix per §2.2; a partly migrated or drifted DB resolves `unavailable`, never `filesystem` (`test_backend_resolution_matrix`, AC2).
- [ ] `ensure_studio_storage` probes once per app, under a lock; `resolve_studio_storage` registered once per app.
- [ ] A tenant partition on `filesystem` raises `StudioStorageUnavailable` (→ 503 `studio_storage_unavailable` in W3).
- [ ] `_studio_partition()` returns `StudioPartition.GLOBAL` (X5).
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/storage/test_backend.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_backend_resolution_matrix` | §2.2, AC2 |
| `test_ensure_is_memoised_and_locked` | §2.7a |
| `test_require_for_tenant_on_filesystem_raises` | §2.2 |
| `test_hook_registered_once` | X10 |
| `test_studio_partition_default_global` | X5 |

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
   `feat(agentstudio-db-storage): TASK-3932 — Studio storage backend selection (ensure_studio_storage) and the _studio_partition hook`.
8. Close with `scripts/sdd/close_task.sh TASK-3932 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, deviations, issues.

**Deviations from spec**: none | describe if any
