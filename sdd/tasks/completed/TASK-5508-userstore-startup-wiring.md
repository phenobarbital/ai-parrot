# TASK-5508: Server startup wiring — validation, implicit-default guard, diagnostics, cleanup

**Feature**: FEAT-878 — Redis user stores (MongoDB-free local installs)
**Spec**: `sdd/specs/redis-user-stores.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5495
**Assigned-to**: unassigned

---

## Context

Spec §2 "Startup (server)", §3 Module 11, §8 Q1 (resolved: fail closed), AC3, AC13, AC17. When the server
starts it must (1) reject invalid switch values, (2) refuse to start when a DocumentDB installation would
silently default to Redis, (3) warn about risky Redis settings, (4) close the user-store Redis client on
cleanup. The Studio backend must compute its `postgres` switches through the same resolver.

---

## Scope

- Create `parrot/userstore/checks.py` with `run_user_store_diagnostics()` and `install_user_store_hooks(app)`.
- Call `install_user_store_hooks(app)` from `BotManager.setup()` (after `_register_shared_redis()`) and from
  `BotManager.setup_registry_only()` (after `add_studio_runtime_hooks(app)`) — same idempotent helper, mirroring
  how FEAT-621 installs its hooks on both paths.
- `backend._postgres_switches()` → resolver.
- Set an explicit `PARROT_USER_STORE` default in the server test `conftest.py` so `BotManager.setup()` tests
  are not stopped by the guard when a developer env file sets `DOCUMENTDB_HOSTNAME`.
- Tests.

**NOT in scope**: the resolver itself (TASK-5495), crew result default (TASK-5511), the copy CLI (TASK-5509).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/userstore/checks.py` | CREATE | diagnostics + hook installer |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | call `install_user_store_hooks` in `setup()` and `setup_registry_only()` |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py` | MODIFY | `_postgres_switches()` via resolver |
| `packages/ai-parrot-server/tests/conftest.py` | MODIFY | `os.environ.setdefault("PARROT_USER_STORE", "redis")` |
| `packages/ai-parrot-server/tests/unit/test_user_store_startup.py` | CREATE | tests |
| `packages/ai-parrot-server/tests/manager/test_registry_only.py` | MODIFY | hook-count expectation now includes the user-store hook pair |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web                                                     # core dependency
from parrot.userstore import (                                              # TASK-5495
    SWITCHES, UserStoreMisconfigured, close_user_store_redis, get_user_store_redis, redis_url,
    resolve_store_backend, validate_user_store_settings,
)
from redis.exceptions import ResponseError                                  # redis 5.2.1 — CONFIG denied on managed Redis
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/manager/manager.py
def _register_shared_redis(self) -> None:          # line 1740
def setup(                                          # line 2360
    ...
        from .studio_runtime import add_studio_runtime_hooks   # line 2415
        add_studio_runtime_hooks(self.app)                     # line 2417
        self._register_shared_redis()                          # line 2422 (1 occurrence)
def setup_registry_only(self, app: web.Application, *, import_modules: bool = False, load_definitions: bool = False) -> None:  # line 3126
        add_studio_runtime_hooks(app)                          # line 3158 (1 occurrence) — after an idempotency guard on _REGISTRY_ONLY_APP_KEY

# packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py
_STORE_SWITCHES = ("VAULT_STORE", "TOOLKIT_OVERRIDES_STORE", "BYOK_STORE")   # line 67
def _postgres_switches() -> list[str]:                                        # line 75 — today: config.get(key, fallback="documentdb") == "postgres"
def _fail_closed(backend: str, reason: str | None) -> None:                   # uses _postgres_switches()

# packages/ai-parrot-server/tests/conftest.py — `import pytest` occurs 1× (line 11); no `import os` today
```

### Does NOT Exist
- ~~`parrot.userstore.checks`~~ — created by this task.
- ~~A warning-only mode for the implicit-default guard~~ — §8 Q1 resolved: it raises.
- ~~`redis.asyncio.Redis.config_get` returning a string~~ — it returns a dict `{name: value}`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/userstore/checks.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/src/parrot/manager/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/conftest.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/unit/test_user_store_startup.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.setup",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.setup_registry_only",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py#_postgres_switches"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `install_user_store_hooks(app)` is idempotent (app key `"_parrot_user_store_hooks"`): validates first
  (raising `UserStoreMisconfigured` propagates out of `setup()` — fail closed), then appends one `on_startup`
  diagnostics hook and one `on_cleanup` close hook.
- Diagnostics never raise and run only when some switch resolves to `redis`. Never log a password:
  redact the URL (`scheme://host:port/db`).
- Warnings: unreachable (PING), `maxmemory-policy` starting with `allkeys-`, persistence off (`appendonly == "no"` and `save == ""`).
- The conftest default is safe: `redis` is also the built-in default, so it only changes `store_backend_source()`
  from "default" to "global" — which is exactly what disarms the guard. Guard tests `delenv` it.

---

## Implementation Blueprint

### Steps (in order)
1. Create `checks.py` — *why*: core owns the checks; server only installs them.
2. Call the installer from both BotManager setup paths — *why*: hosts using `setup_registry_only()` also serve user stores.
3. Switch `_postgres_switches()` to the resolver — *why*: `PARROT_USER_STORE` must not hide a per-store `postgres`.
4. Add the conftest default; write tests.

### `packages/ai-parrot/src/parrot/userstore/checks.py` (CREATE)
```python
"""FEAT-878 startup checks: switch validation (fail closed) and Redis durability diagnostics (warn only)."""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

from redis.exceptions import ResponseError

from .settings import (
    SWITCHES, close_user_store_redis, get_user_store_redis, redis_url, resolve_store_backend,
    validate_user_store_settings,
)

_HOOKS_KEY = "_parrot_user_store_hooks"


def _safe_url() -> str:
    """redis_url() without credentials."""
    parts = urlsplit(redis_url())
    return f"{parts.scheme}://{parts.hostname}:{parts.port or 6379}{parts.path}"


async def run_user_store_diagnostics(logger: logging.Logger | None = None) -> list[str]:
    """Never raises. Returns the warning lines it logged (ping, eviction policy, persistence).
    Skipped entirely when no switch resolves to redis."""
    log = logger or logging.getLogger("parrot.userstore")
    warnings: list[str] = []
    # FILL IN: resolve SWITCHES (any exception → return []); return [] when "redis" not used;
    #   PING (warn + return on failure); CONFIG GET maxmemory-policy / appendonly / save, each in try/except
    #   ResponseError (log.debug and skip); append + log.warning each finding — bounded by spec §2 Startup / AC13.
    return warnings


def install_user_store_hooks(app: Any) -> None:
    """Idempotent: validate switches (raises UserStoreMisconfigured), then add diagnostics + cleanup hooks."""
    if app.get(_HOOKS_KEY):
        return
    validate_user_store_settings()
    app[_HOOKS_KEY] = True

    async def _diagnostics(_app: Any) -> None:
        await run_user_store_diagnostics()

    async def _close(_app: Any) -> None:
        await close_user_store_redis()

    app.on_startup.append(_diagnostics)
    app.on_cleanup.append(_close)
```

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'self._register_shared_redis()' packages/ai-parrot-server/src/parrot/manager/manager.py)
# AFTER `self._register_shared_redis()` (verified: manager.py:2422) insert:
        # FEAT-878: validate user-store switches (fail closed) + Redis diagnostics/cleanup hooks.
        from parrot.userstore.checks import install_user_store_hooks

        install_user_store_hooks(self.app)
# occurrences: 1 (verified: grep -c 'add_studio_runtime_hooks(app)' .../manager.py)
# AFTER `add_studio_runtime_hooks(app)` (verified: manager.py:3158, inside setup_registry_only) insert:
        from parrot.userstore.checks import install_user_store_hooks

        install_user_store_hooks(app)
```

### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _postgres_switches() -> list[str]:' .../studio/storage/backend.py)
# REPLACE the body of _postgres_switches (line 75) with:
    """The phase-2 store switches currently resolving to ``postgres`` (FEAT-878 resolver)."""
    from parrot.userstore import resolve_store_backend

    return [key for key in _STORE_SWITCHES if resolve_store_backend(key) == "postgres"]
```

### `packages/ai-parrot-server/tests/conftest.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'import pytest' packages/ai-parrot-server/tests/conftest.py)
# AFTER `import pytest` (verified: conftest.py:11) insert:
import os

# FEAT-878: an explicit global user-store switch keeps the implicit-default startup guard (DOCUMENTDB_HOSTNAME in a
# developer env file) out of BotManager.setup() tests. "redis" is also the built-in default, so no code path changes.
os.environ.setdefault("PARROT_USER_STORE", "redis")
```

### FILL IN checklist
- [ ] `run_user_store_diagnostics` body
- [ ] tests for guard, diagnostics, installer idempotency, `_postgres_switches`

---

## Acceptance Criteria

- [ ] Invalid switch → `BotManager.setup()` raises `UserStoreMisconfigured` (AC3)
- [ ] `DOCUMENTDB_HOSTNAME` set + no switches → raises, message lists stores (+ `CREW_RESULT_STORAGE`) and both fixes (AC17)
- [ ] Diagnostics warn on `allkeys-*`, on persistence off; `CONFIG` errors skipped; never raise (AC13); no password in logs (AC14)
- [ ] `PARROT_USER_STORE=documentdb` + `VAULT_STORE=postgres` → `_postgres_switches() == ["VAULT_STORE"]`
- [ ] Existing manager/studio suites still pass
- [ ] `ruff check` clean

---

## Validation Commands
- `pytest packages/ai-parrot-server/tests/unit/test_user_store_startup.py -q`
- `pytest packages/ai-parrot-server/tests/studio/storage/test_store_registration.py -q`
- `pytest packages/ai-parrot-server/tests/manager/test_registry_only.py -q`
- `pytest packages/ai-parrot-server/tests/manager/test_studio_runtime.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/unit/test_user_store_startup.py
import pytest
from aiohttp import web

from parrot.userstore import UserStoreMisconfigured
from parrot.userstore.checks import install_user_store_hooks, run_user_store_diagnostics


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for key in ("PARROT_USER_STORE", "CREW_RESULT_STORAGE", "DOCUMENTDB_HOSTNAME", "DOCUMENTDB_DBNAME",
                "VAULT_STORE", "BYOK_STORE", "TOOLKIT_OVERRIDES_STORE", "MCP_CONFIGS_STORE",
                "TELEGRAM_MCP_STORE", "INTEGRATIONS_STORE", "DASHBOARDS_STORE"):
        monkeypatch.delenv(key, raising=False)


def test_startup_rejects_invalid_switch(monkeypatch):
    monkeypatch.setenv("VAULT_STORE", "mongo")
    with pytest.raises(UserStoreMisconfigured):
        install_user_store_hooks(web.Application())


def test_guard_implicit_redis_with_documentdb(monkeypatch): ...   # message contains "PARROT_USER_STORE=documentdb" and "=redis"
def test_installer_idempotent(): ...                               # two calls → one startup + one cleanup hook
async def test_diagnostics_warnings(monkeypatch): ...              # fake client: ping ok, allkeys-lru, appendonly no, save "" → 2 warnings
async def test_diagnostics_config_denied_skipped(monkeypatch): ... # config_get raises ResponseError → no exception
def test_studio_postgres_switches_resolver(monkeypatch): ...
```

---

## Agent Instructions

1. **Work in the feature worktree** — `parrot sdd worktree ensure --slug redis-user-stores --feature-id FEAT-878`
2. **Read the spec** (§2 Startup, §3 M11, §8 Q1, AC3/AC13/AC17)
3. **Check dependencies** — TASK-5495 must be `done`
4. **Verify the Codebase Contract** (re-run each `grep -c`)
5. **Update status** → `"in-progress"`, commit only the index file
6. **Implement** from the blueprint, complete every `# FILL IN:`
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
8. **Commit the code** — only the files listed above
9. **Close the task** — `parrot sdd task close TASK-5508 redis-user-stores verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note


- Task: TASK-5508
- Feature: redis-user-stores
- Implementation SHA: fb0444a101d5d9fd1cfe124e3f50014240efcd28
- Closed at (UTC): 2026-11-11T00:56:25+00:00
- Fix commits: fb0444a101d5d9fd1cfe124e3f50014240efcd28

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 1 |
| seat_summary | Seat: gpt-5.6-terra/gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol (attempt 3) · Attempts: 3 · Duration: 759s · Tokens: n/a. Feedback: coder-feedback:8a7d759e64c2b859d6293ea1 (existing-test-not-updated) |
