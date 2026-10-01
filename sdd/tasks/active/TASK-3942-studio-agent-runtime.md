# TASK-3942: StudioAgentRuntime: revalidating lookup, single flight, leases, sweep, lifecycle hooks

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W2 — Runtime + cache + lifecycle + builder (M7, part 4: StudioAgentRuntime + lifecycle hooks)
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3932, TASK-3939, TASK-3940, TASK-3941
**Assigned-to**: unassigned

---

## Context

Spec §2.6 (read-through revalidation on every lookup; single-flight rebuild; retire, never clean immediately),
§2.7 (`get`, `get_session`, `use` with a lease, `reload`, `evict`), §2.7a (hooks table: `add_studio_runtime_hooks`,
`install_studio_runtime` awaiting `ensure_studio_storage` first, `start`, `sweep(now=None)`, `shutdown`), X7, X8.
Not delegation-eligible: locking, leases and cleanup ordering need the thinking model.

---

## Scope

- `manager/studio_runtime.py`: `StudioAgentRuntime(manager, repos, builder, *, revalidate_ttl=0.0, session_ttl=3600.0,
  idle_ttl=3600.0, retire_grace=300.0, sweep_interval=60.0)` with `get`, `get_session`, `use` (async context manager,
  lease), `reload` (forced rebuild → `ReloadResult`, `name` = bare name), `evict` (retire), `start`, `sweep`,
  `shutdown`; per-key `asyncio.Lock` single flight; one WARNING per `(agent_id, version)` on a refused build.
- Module functions `add_studio_runtime_hooks(app)` (once per app, guard `"_astudio_runtime_hooks_installed"`),
  `install_studio_runtime(app)` (awaits `ensure_studio_storage` FIRST; database ⇒ build runtime, set
  `app["bot_manager"].studio`, `await runtime.start()`), `shutdown_studio_runtime(app)`.
- Settings `STUDIO_RUNTIME_DIR` (via `studio_runtime_dir()` from `services/_common.py`, TASK-3933), `STUDIO_REVALIDATE_TTL_SECONDS`, `STUDIO_SESSION_TTL_SECONDS`,
  `STUDIO_IDLE_TTL_SECONDS`, `STUDIO_RETIRE_GRACE_SECONDS`, `STUDIO_SWEEP_INTERVAL_SECONDS`.
- Re-export `StudioRuntimeCache`, `StudioCacheEntry`, `StudioAgentBuilder` from this module.

**NOT in scope**: BotManager wiring (`studio` attribute, `get_studio_bot`, GLOBAL fallback, `setup()` call — TASK-3943).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/studio_runtime.py` | CREATE | StudioAgentRuntime + lifecycle hooks + re-exports |
| `packages/ai-parrot-server/tests/manager/test_studio_runtime.py` | CREATE | real-PG runtime and lifecycle tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
from parrot.manager.studio_cache import StudioCacheEntry, StudioRuntimeCache       # TASK-3939
from parrot.manager.studio_builder import StudioAgentBuilder                       # TASK-3940
from parrot.manager.manager import cleanup_bot_instance, ReloadResult, AgentReloadError   # TASK-3941 ; manager.py:163,:153
from parrot.handlers.studio.storage.backend import ensure_studio_storage            # TASK-3932
from parrot.handlers.studio.storage.models import StudioAgentKey, StudioPartition, StudioStorageUnavailable  # TASK-3922
from parrot.auth.agent_guard import enforce_agent_access                            # agent_guard.py:172 (evaluator None ⇒ allow)
```

### Does NOT Exist
- ~~`BotManager.studio`~~, ~~`get_studio_bot`~~ — TASK-3943.
- ~~`BotManager.setup_registry_only`~~ — FEAT-605 W0.2; it calls `add_studio_runtime_hooks` in FEAT-605 W2.2.
- ~~`LISTEN/NOTIFY`~~ — not used (§2.6).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/manager/studio_runtime.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/manager/test_studio_runtime.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/agent_guard.py#enforce_agent_access"
  ]
}
```

---

## Implementation Notes

- Parallelism: composes StudioRuntimeCache (TASK-3939, manager/studio_cache.py), StudioAgentBuilder (TASK-3940, manager/studio_builder.py), cleanup_bot_instance (TASK-3941, manager.py) and ensure_studio_storage + repos (TASK-3932, storage/backend.py); creates manager/studio_runtime.py
- Cross-feature ordering: X16 — FEAT-605 W2.2 (`setup_registry_only` calling `add_studio_runtime_hooks`) starts only
  after this task and TASK-3943 merge. TOOLKITS Wave 4 (M3b + M5) needs STORAGE W2 runtime identity
  (`_studio_key`, `_tooling_ref`).
- Circular import: `manager.py` (TASK-3943) imports this module lazily inside `setup()`; this module imports
  `cleanup_bot_instance` from `manager.py` at module level — keep it that way round.
- Revalidation statement is `repos.agents.get_version(part, name)`; a different `agent_id` with the same name is
  always a rebuild. Session lookups (`new=True` test chat) build a FRESH instance from the current snapshot, never a
  clone.
- Shutdown runs in `on_cleanup` before the host closes the pool; instance cleanup needs no DB.

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

### `packages/ai-parrot-server/src/parrot/manager/studio_runtime.py` (CREATE)
```python
"""Studio agent runtime (spec §2.6/§2.7/§2.7a). Instances live only in StudioRuntimeCache."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger("Parrot.AgentStudio.Storage")
_HOOKS_KEY = "_astudio_runtime_hooks_installed"


class StudioAgentRuntime:
    def __init__(self, manager, repos, builder, *, revalidate_ttl: float = 0.0, session_ttl: float = 3600.0,
                 idle_ttl: float = 3600.0, retire_grace: float = 300.0, sweep_interval: float = 60.0) -> None:
        self._cache = StudioRuntimeCache()
        self._locks: dict[str, asyncio.Lock] = {}
        # FILL IN: store the rest; _sweep_task = None

    async def get(self, key: StudioAgentKey):
        """§2.6 steps 1–4: get_version → retire on missing/disabled → reuse on same (agent_id, version) → single-flight rebuild."""
        raise NotImplementedError

    @asynccontextmanager
    async def use(self, key: StudioAgentKey, *, session_id: str | None = None, request=None):
        # FILL IN: lookup (session or base), enforce_agent_access before any build, leases += 1 / -= 1 in finally.
        raise NotImplementedError
        yield
    # FILL IN: get_session, reload, evict, start, sweep(now=None) -> int, shutdown.


def add_studio_runtime_hooks(app) -> None:
    if app.get(_HOOKS_KEY):
        return
    app[_HOOKS_KEY] = True
    app.on_startup.append(install_studio_runtime)
    app.on_cleanup.append(shutdown_studio_runtime)


async def install_studio_runtime(app) -> None:
    storage = await ensure_studio_storage(app)          # FIRST, whatever the hook order (X8)
    # FILL IN: database ⇒ build runtime from settings + storage.repos + builder; app["bot_manager"].studio = runtime;
    #   await runtime.start(); else leave studio None.


async def shutdown_studio_runtime(app) -> None:
    # FILL IN: runtime = getattr(app.get("bot_manager"), "studio", None); await runtime.shutdown() when present.
    ...
```

### `packages/ai-parrot-server/tests/manager/test_studio_runtime.py` (CREATE)
```python
"""FEAT-621 M7 runtime on real Postgres (AC5, AC10, AC11, AC14)."""
# FILL IN: test_cross_pod_revalidation (two runtimes, one DB); test_single_flight_rebuild (20 concurrent get →
#   builder once); test_snapshot_during_edit (50 builds vs concurrent writes; _studio_version matches its data);
#   test_builder_constructor_settings_cross_runtime (PATCH on runtime A, rebuild on runtime B);
#   test_memory_partitioned_by_agent_id (acme/sales vs beta/sales; delete+recreate empty history);
#   test_session_expiry; test_three_versions_cleanup_once (mutation: reuse name guard ⇒ RED);
#   test_inflight_survives_replacement; test_shutdown_cleans_all; test_lifecycle_registry_only_mount
#   (add_studio_runtime_hooks BEFORE setup_studio_routes, no BotManager.setup()).
```

---

## Acceptance Criteria

- [ ] Two runtimes on one DB see each other's writes on the next lookup; builds never mix versions (`test_cross_pod_revalidation`, `test_snapshot_during_edit`, AC5).
- [ ] Constructor settings follow create → PATCH → rebuild on another runtime (AC10); memory key per `agent_id` (AC11).
- [ ] Lifecycle: either hook order works; sessions expire; three versions and shutdown clean each instance exactly once; an in-flight lease survives replacement with its directory (AC14).
- [ ] Single-flight rebuild (`test_single_flight_rebuild`).
- [ ] Regression: `pytest packages/ai-parrot-server/tests/manager/test_studio_cache.py -q` (from TASK-3939) still green.
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/manager/test_studio_runtime.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_cross_pod_revalidation` | AC5 |
| `test_single_flight_rebuild` | §2.6 |
| `test_snapshot_during_edit` | AC5 |
| `test_builder_constructor_settings_cross_runtime` | AC10 |
| `test_memory_partitioned_by_agent_id` | AC11 |
| `test_session_expiry` | AC14 |
| `test_three_versions_cleanup_once` | AC14 |
| `test_inflight_survives_replacement` | AC14 |
| `test_shutdown_cleans_all` | AC14 |
| `test_lifecycle_registry_only_mount` | AC14, X8 |

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
   `feat(agentstudio-db-storage): TASK-3942 — StudioAgentRuntime: revalidating lookup, single flight, leases, sweep, lifecycle hooks`.
8. Close with `scripts/sdd/close_task.sh TASK-3942 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, deviations, issues.

**Deviations from spec**: none | describe if any
