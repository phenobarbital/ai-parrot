# TASK-5495: User store settings and backend resolver

**Feature**: FEAT-878 — Redis user stores (MongoDB-free local installs)
**Spec**: `sdd/specs/redis-user-stores.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Backend selection" and §3 Module 1. Every user store picks its backend at call time:
per-store switch → `PARROT_USER_STORE` → `redis`. This task creates the `parrot.userstore` package with
that resolver, the validation used at server startup (including the implicit-default guard of §8 Q1),
the crew-result default of §8 Q2, the Redis URL/prefix settings (db 6, §8 Q3) and a per-event-loop
`redis.asyncio` client. Every other FEAT-878 task builds on it.

---

## Scope

- Create `parrot/userstore/settings.py` with `StoreSwitch`, `SWITCHES`, `UserStoreMisconfigured`,
  `resolve_store_backend`, `store_backend_source`, `documentdb_configured`, `implicit_redis_stores`,
  `validate_user_store_settings`, `default_result_storage`, `redis_url`, `key_prefix`,
  `get_user_store_redis`, `close_user_store_redis`.
- Create `parrot/userstore/__init__.py` re-exporting those names.
- Write unit tests (no Redis server needed except the client test, which must not connect).

**NOT in scope**: `RedisDocumentStore` and collection specs (TASK-5496), startup wiring in
`BotManager` (TASK-5508), diagnostics (`checks.py`, TASK-5508), any service change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/userstore/__init__.py` | CREATE | Public re-exports of the settings API |
| `packages/ai-parrot/src/parrot/userstore/settings.py` | CREATE | Switch registry, resolver, validation, Redis client |
| `packages/ai-parrot/tests/userstore/__init__.py` | CREATE | Test package marker (sibling test dirs have one) |
| `packages/ai-parrot/tests/userstore/test_settings.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navconfig import config          # config.get(key, fallback=...) reads os.environ at call time (probed 2026-11-11)
import redis.asyncio as aioredis      # verified: packages/ai-parrot-server/src/parrot/manager/manager.py:1759 (redis 5.2.1)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/conf.py:307-310 — the host/port settings the default URL reuses
REDIS_HOST = config.get("REDIS_HOST", fallback="localhost")   # line 307
REDIS_PORT = config.get("REDIS_PORT", fallback=6379)          # line 308
# Read REDIS_HOST / REDIS_PORT through navconfig at call time — do NOT import parrot.conf (import-time values,
# heavy module).

# packages/ai-parrot/src/parrot/vault_targets.py:235 — the "DocumentDB is configured" rule to mirror
def _default_docdb_factory() -> Optional[Callable[[], Any]]:
    # returns None unless config.get("DOCUMENTDB_HOSTNAME") or config.get("DOCUMENTDB_DBNAME")

# packages/ai-parrot-server/src/parrot/manager/manager.py:1761 — client construction pattern
self.app["redis"] = aioredis.from_url(REDIS_URL, decode_responses=True)
```

### Does NOT Exist
- ~~`parrot.userstore`~~ — created by this task.
- ~~`parrot.storage.userstore`~~ — never put this package under `parrot/storage/` (its `__init__` imports DynamoDB/S3 layers).
- ~~`PARROT_USER_STORE`, `MCP_CONFIGS_STORE`, `TELEGRAM_MCP_STORE`, `INTEGRATIONS_STORE`, `DASHBOARDS_STORE`, `PARROT_USER_STORE_REDIS_URL`, `PARROT_USER_STORE_REDIS_DB`, `PARROT_USER_STORE_REDIS_PREFIX`~~ — no such settings exist yet; this task defines them (call-time reads only, nothing added to `parrot/conf.py`).
- ~~`fakeredis`~~ — not installed.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/userstore/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/userstore/settings.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/userstore/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/userstore/test_settings.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/vault_targets.py#_default_docdb_factory"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Every read goes through `config.get(...)` **at call time** — tests use `monkeypatch.setenv`/`delenv`.
- Values are `str(...).strip().lower()`; empty string counts as unset.
- Never log a Redis URL that may contain a password; log the switch name and backend only.
- Async-only client (`redis.asyncio`); no sync `redis.Redis`.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py:75` — `_postgres_switches()` reads switches the same way today.

---

## Implementation Blueprint

### Steps (in order)
1. Create `settings.py` from the block below and fill the marked bodies — *why*: it is the single source of switch semantics for 13 later tasks.
2. Create `__init__.py` re-exporting the public names — *why*: callers import `from parrot.userstore import resolve_store_backend`.
3. Create the empty `tests/userstore/__init__.py` and `test_settings.py` — *why*: sibling test packages carry `__init__.py`.
4. Run the validation commands and `ruff check` on the new files.

### `packages/ai-parrot/src/parrot/userstore/settings.py` (CREATE)
```python
"""User store backend selection (FEAT-878): per-store switch → PARROT_USER_STORE → redis."""
from __future__ import annotations

import asyncio
import logging
import weakref
from dataclasses import dataclass
from typing import Literal

import redis.asyncio as aioredis
from navconfig import config

logger = logging.getLogger("parrot.userstore")

StoreBackend = Literal["redis", "documentdb", "postgres"]
GLOBAL_SWITCH: str = "PARROT_USER_STORE"
DEFAULT_BACKEND: StoreBackend = "redis"
CREW_RESULT_SWITCH: str = "CREW_RESULT_STORAGE"
_GLOBAL_ALLOWED = frozenset({"redis", "documentdb"})
_WITH_POSTGRES = frozenset({"redis", "documentdb", "postgres"})


class UserStoreMisconfigured(RuntimeError):
    """A store switch (or PARROT_USER_STORE) holds a value outside its allowed set,
    or a DocumentDB installation would silently default to Redis."""


@dataclass(frozen=True)
class StoreSwitch:
    """One per-store switch: env key, the collections it governs, its allowed values."""

    name: str
    collections: tuple[str, ...]
    allowed: frozenset[str]


SWITCHES: dict[str, StoreSwitch] = {
    s.name: s
    for s in (
        StoreSwitch("VAULT_STORE", ("user_credentials",), _WITH_POSTGRES),
        StoreSwitch("BYOK_STORE", ("user_llm_keys",), _WITH_POSTGRES),
        StoreSwitch("TOOLKIT_OVERRIDES_STORE", ("user_toolkit_configs",), _WITH_POSTGRES),
        StoreSwitch("MCP_CONFIGS_STORE", ("user_mcp_configs",), _GLOBAL_ALLOWED),
        StoreSwitch("TELEGRAM_MCP_STORE", ("telegram_user_mcp_configs",), _GLOBAL_ALLOWED),
        StoreSwitch("INTEGRATIONS_STORE", ("users_integrations",), _GLOBAL_ALLOWED),
        StoreSwitch("DASHBOARDS_STORE", ("dashboards", "dashboard_tabs"), _GLOBAL_ALLOWED),
    )
}


def _read(key: str) -> str:
    """Normalised call-time value of ``key`` ('' when unset)."""
    return str(config.get(key, fallback="") or "").strip().lower()


def resolve_store_backend(switch: str) -> StoreBackend:
    """Per-store value → PARROT_USER_STORE → "redis".

    Raises:
        KeyError: ``switch`` is not one of SWITCHES.
        UserStoreMisconfigured: the per-store or the global value is not allowed.
    """
    spec = SWITCHES[switch]
    # FILL IN: per-store value first (validate against spec.allowed), then the global value
    #   (validate against _GLOBAL_ALLOWED), else DEFAULT_BACKEND — bounded by spec §2 resolution order / AC2, AC3.
    #   The error message names the switch and the allowed values; it never echoes other config.
    raise NotImplementedError


def store_backend_source(switch: str) -> Literal["switch", "global", "default"]:
    """Which level decided ``resolve_store_backend(switch)``."""
    # FILL IN: "switch" when the per-store value is set, "global" when only PARROT_USER_STORE is set,
    #   else "default" — bounded by spec §3 M1.
    raise NotImplementedError


def documentdb_configured() -> bool:
    """DOCUMENTDB_HOSTNAME or DOCUMENTDB_DBNAME is set (same rule as vault_targets._default_docdb_factory)."""
    return bool(config.get("DOCUMENTDB_HOSTNAME") or config.get("DOCUMENTDB_DBNAME"))


def implicit_redis_stores() -> list[str]:
    """Switch names resolving to redis only by default, plus CREW_RESULT_STORAGE when it and the
    global switch are both unset."""
    # FILL IN: [name for name in SWITCHES if source == "default" and backend == "redis"]
    #   + ["CREW_RESULT_STORAGE"] when _read(CREW_RESULT_SWITCH) == "" and _read(GLOBAL_SWITCH) == "" — bounded by AC17.
    raise NotImplementedError


def validate_user_store_settings() -> dict[str, StoreBackend]:
    """Resolve every switch; raise UserStoreMisconfigured on the first invalid value, or when
    documentdb_configured() and implicit_redis_stores() is non-empty. Returns {switch: backend}."""
    # FILL IN: resolve all SWITCHES (first error propagates); then the guard. The guard message lists
    #   the stores and both fixes, verbatim keys: "PARROT_USER_STORE=documentdb" (keep MongoDB) and
    #   "PARROT_USER_STORE=redis" (move; run `python -m parrot.userstore.copy` first) — bounded by spec §2 Startup / AC17.
    raise NotImplementedError


def default_result_storage() -> Literal["redis", "documentdb"]:
    """Crew/flow result backend when CREW_RESULT_STORAGE is unset: PARROT_USER_STORE, else "redis"."""
    # FILL IN: validate the global value against _GLOBAL_ALLOWED (UserStoreMisconfigured otherwise) — bounded by AC18.
    raise NotImplementedError
```
**Why this shape**: the switch table and allowed sets come verbatim from spec §2 Data Models; `postgres`
is allowed only on the three FEAT-621 switches. Reads are call-time so tests can flip env vars. The guard
lives in `validate_user_store_settings()` (not in the resolver) so ordinary calls never fail on the default.

### `packages/ai-parrot/src/parrot/userstore/settings.py` (CREATE, continued — Redis client)
```python
def redis_url() -> str:
    """PARROT_USER_STORE_REDIS_URL, else redis://{REDIS_HOST}:{REDIS_PORT}/{PARROT_USER_STORE_REDIS_DB} (db 6)."""
    explicit = str(config.get("PARROT_USER_STORE_REDIS_URL", fallback="") or "").strip()
    if explicit:
        return explicit
    host = config.get("REDIS_HOST", fallback="localhost")
    port = config.get("REDIS_PORT", fallback=6379)
    db = config.get("PARROT_USER_STORE_REDIS_DB", fallback=6)
    return f"redis://{host}:{port}/{db}"


def key_prefix() -> str:
    """PARROT_USER_STORE_REDIS_PREFIX, default "parrot:us" (no trailing colon)."""
    return str(config.get("PARROT_USER_STORE_REDIS_PREFIX", fallback="parrot:us") or "parrot:us").rstrip(":")


_CLIENTS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, aioredis.Redis]" = weakref.WeakKeyDictionary()


def get_user_store_redis() -> aioredis.Redis:
    """One lazily created client per running event loop (decode_responses=True)."""
    # FILL IN: key the cache by asyncio.get_running_loop(); create with aioredis.from_url(redis_url(),
    #   decode_responses=True) — from_url does not connect, so this stays cheap — bounded by spec §7 "Event loops".
    raise NotImplementedError


async def close_user_store_redis() -> None:
    """Close and forget the current loop's client; no-op when none was created."""
    # FILL IN: pop the current loop's client and `await client.aclose()` (redis>=5) — bounded by spec §2.
    raise NotImplementedError
```
**Why**: db 6 is the §8 Q3 decision; Cluster users override the URL. A client is bound to the loop that
first used it, so the cache is per loop.

### `packages/ai-parrot/src/parrot/userstore/__init__.py` (CREATE)
```python
"""FEAT-878 user stores: backend selection and Redis primitives. See wiki/stores/user-stores.md."""
from .settings import (
    DEFAULT_BACKEND,
    GLOBAL_SWITCH,
    SWITCHES,
    StoreBackend,
    StoreSwitch,
    UserStoreMisconfigured,
    close_user_store_redis,
    default_result_storage,
    documentdb_configured,
    get_user_store_redis,
    implicit_redis_stores,
    key_prefix,
    redis_url,
    resolve_store_backend,
    store_backend_source,
    validate_user_store_settings,
)

__all__ = [
    "DEFAULT_BACKEND", "GLOBAL_SWITCH", "SWITCHES", "StoreBackend", "StoreSwitch", "UserStoreMisconfigured",
    "close_user_store_redis", "default_result_storage", "documentdb_configured", "get_user_store_redis",
    "implicit_redis_stores", "key_prefix", "redis_url", "resolve_store_backend", "store_backend_source",
    "validate_user_store_settings",
]
```
**Why**: TASK-5496 extends this file with the Redis document store exports.

### FILL IN checklist
- [ ] `resolve_store_backend` — precedence + validation; bounded by AC2/AC3
- [ ] `store_backend_source` — three levels; bounded by §3 M1
- [ ] `implicit_redis_stores` — includes CREW_RESULT_STORAGE rule; bounded by AC17
- [ ] `validate_user_store_settings` — invalid values + guard message; bounded by AC17
- [ ] `default_result_storage` — global or redis; bounded by AC18
- [ ] `get_user_store_redis` / `close_user_store_redis` — per-loop cache; bounded by §7

---

## Acceptance Criteria

- [ ] No switch and no global → `resolve_store_backend(x) == "redis"` for all 7 switches (spec AC1 foundation)
- [ ] Per-store beats global beats default, both directions (AC2)
- [ ] Invalid values raise `UserStoreMisconfigured`; `postgres` only on VAULT/BYOK/TOOLKIT_OVERRIDES (AC3)
- [ ] Guard raises with `DOCUMENTDB_HOSTNAME` set and no switches; cleared by `PARROT_USER_STORE=redis|documentdb`; absent without DocumentDB vars (AC17)
- [ ] `default_result_storage()` → `redis` by default, `documentdb` with the global switch (AC18)
- [ ] `ruff check` clean on the new files

---

## Validation Commands
- `pytest packages/ai-parrot/tests/userstore/test_settings.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/userstore/test_settings.py
import asyncio
import pytest

from parrot.userstore import (
    SWITCHES, UserStoreMisconfigured, default_result_storage, implicit_redis_stores, redis_url,
    resolve_store_backend, store_backend_source, validate_user_store_settings,
)

ALL_KEYS = [*SWITCHES, "PARROT_USER_STORE", "CREW_RESULT_STORAGE", "DOCUMENTDB_HOSTNAME", "DOCUMENTDB_DBNAME",
            "PARROT_USER_STORE_REDIS_URL", "PARROT_USER_STORE_REDIS_DB"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ALL_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_resolve_default_is_redis():
    assert {resolve_store_backend(s) for s in SWITCHES} == {"redis"}


def test_resolve_precedence(monkeypatch):
    monkeypatch.setenv("PARROT_USER_STORE", "documentdb")
    monkeypatch.setenv("VAULT_STORE", "redis")
    assert resolve_store_backend("VAULT_STORE") == "redis"
    assert store_backend_source("VAULT_STORE") == "switch"
    assert resolve_store_backend("BYOK_STORE") == "documentdb"
    assert store_backend_source("BYOK_STORE") == "global"


def test_resolve_invalid_value_raises(monkeypatch): ...      # VAULT_STORE=mongo; PARROT_USER_STORE=postgres
def test_postgres_only_where_allowed(monkeypatch): ...       # MCP_CONFIGS_STORE=postgres raises; VAULT_STORE=postgres ok
def test_guard_implicit_redis_with_documentdb(monkeypatch): ...  # DOCUMENTDB_HOSTNAME=localhost → raises; message names both fixes
def test_guard_cleared_by_explicit_switch(monkeypatch): ...  # PARROT_USER_STORE=redis → validate returns dict
def test_guard_absent_without_documentdb_config(): ...       # validate returns all "redis"
def test_default_result_storage_follows_global(monkeypatch): ...
def test_redis_url_default_db6(monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "h"); monkeypatch.setenv("REDIS_PORT", "1234")
    assert redis_url() == "redis://h:1234/6"


async def test_client_per_event_loop(): ...  # same loop → same object; close → next call returns a new client; never connects
```

---

## Agent Instructions

1. **Work in the feature worktree** — `parrot sdd worktree ensure --slug redis-user-stores --feature-id FEAT-878`
2. **Read the spec** (§2 Backend selection, §3 M1, §8 resolved questions)
3. **Check dependencies** in `sdd/tasks/index/redis-user-stores.json` (none for this task)
4. **Verify the Codebase Contract** before writing code
5. **Update status** → `"in-progress"` (set `started_at`), commit only the index file
6. **Implement** from the blueprint, complete every `# FILL IN:`
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — only the files listed above
9. **Close the task** — `parrot sdd task close TASK-5495 redis-user-stores verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
