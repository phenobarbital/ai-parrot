# TASK-775: JiraOAuthManager Lifecycle & setup(app) — FEAT-107 Hotfix

**Feature**: FEAT-107 — Jira OAuth 2.0 (3LO)
**Spec**: `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (4-6h)
**Depends-on**: TASK-751, TASK-752
**Assigned-to**: unassigned

---

## Context

FEAT-107 shipped with `JiraOAuthManager` requiring the caller to pre-build a
Redis client and pass it in, and with the callback route mounted by a free
function (`setup_jira_oauth_routes(app)`) invoked from an unrelated module
(`autonomous/orchestrator.py:272-281`). This forced every application bootstrap
to wire three separate things (create Redis client, instantiate manager,
mount route) and leaked the orchestrator's responsibility into the auth
module.

The manager already manages `aiohttp.ClientSession` lifecycle internally
(`jira_oauth.py:111-136`: accepts one externally or owns a lazy-created one,
tracks `_http_owned` for cleanup). Extending the same self-ownership pattern
to Redis — and adding a `setup(app)` convenience method in the spirit of
`BotManager.setup(app)` / `AgentSchedulerManager.setup(app)` — makes the
caller's bootstrap a single line and removes duplicated knowledge from the
orchestrator.

The user explicitly wants the Telegram-specific `setup_combined_auth_routes`
(FEAT-108) **kept separate**. `parrot.auth` must not import from
`parrot.integrations.telegram` — the coupling stays one-directional.

---

## Scope

### 1. `JiraOAuthManager.__init__` — accept `redis_url`

- Add `redis_url: Optional[str] = None` as kwarg-only (after `redis_client`).
- Make `redis_client` also kwarg-only via a `*,` separator — current signature
  is all-positional.
- Raise `ValueError` in `__init__` if both `redis_url` and `redis_client`
  are missing (we need one or the other).
- Track `_redis_url`, `_redis_owned` (True when we built the client from URL).

### 2. Lifecycle hooks — `_on_startup` / `_on_cleanup`

- `_on_startup(app)` — create Redis client from `redis_url` if `redis_client`
  was not passed. Use `redis.asyncio.from_url(self._redis_url,
  decode_responses=True)`. Call `await self.redis.ping()` to fail fast on
  misconfiguration.
- `_on_cleanup(app)` — close the Redis client if we own it
  (`self._redis_owned`), and close the aiohttp session if we own it
  (`self._http_owned`). Prefer `await self.redis.aclose()` (redis-py ≥ 5);
  fall back to `await self.redis.close()` + `await self.redis.wait_closed()`
  if needed.

### 3. `setup(app)` convenience method

- **Idempotent**: track `self._setup_done` so duplicate calls are safe
  no-ops. This is important because the orchestrator may also invoke it
  defensively.
- Registers `app['jira_oauth_manager'] = self` (only if not already set
  to a different instance — raise `RuntimeError` if overwriting).
- Mounts `GET /api/auth/jira/callback` via the existing
  `setup_jira_oauth_routes(app)` helper (the helper itself does not change
  in this task — still lives in `parrot.auth.routes`).
- Appends `self._on_startup` / `self._on_cleanup` to `app.on_startup` /
  `app.on_cleanup`.
- **Does NOT** touch the FEAT-108 combined callback. Callers who need the
  Telegram combined flow invoke `setup_combined_auth_routes(app)` themselves.

### 4. Refactor `orchestrator.setup_routes()`

Current block (`orchestrator.py:269-281`) manually mounts both
`setup_jira_oauth_routes` and `setup_combined_auth_routes`. Simplify to:

```python
manager = app.get('jira_oauth_manager')
if manager is not None:
    # Idempotent — safe even if the bootstrap already called setup(app).
    manager.setup(app)
    # FEAT-108 combined callback is an integration concern.
    from ..integrations.telegram.combined_callback import (
        setup_combined_auth_routes,
    )
    setup_combined_auth_routes(app)
```

This removes the import of `setup_jira_oauth_routes` from the orchestrator.
Callers whose bootstrap already calls `manager.setup(app)` get the
FEAT-108 combined callback mounted automatically via the orchestrator
path when it runs.

### 5. Tests

- `tests/unit/test_jira_oauth_manager.py`:
  - Existing `JiraOAuthManager(client_id=..., client_secret=..., ...,
    redis_client=...)` fixture is positional — update to kwarg-only.
  - Add `test_init_with_redis_url_creates_client_on_startup`.
  - Add `test_init_without_redis_url_or_client_raises`.
  - Add `test_on_cleanup_closes_owned_redis_and_leaves_external_alone`.

- `tests/unit/test_oauth_callback_routes.py`:
  - Existing tests register routes manually via `setup_jira_oauth_routes(app)`.
    Add one that exercises the full `manager.setup(app)` path and verifies
    the route is mounted, the manager is stored, and signals are appended.
  - Add `test_setup_is_idempotent` — call `setup(app)` twice, ensure no
    duplicate routes / duplicate signal handlers.

### 6. Spec updates — `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md`

- Codebase Contract: update `JiraOAuthManager.__init__` signature, add
  `setup(app)`, `_on_startup`, `_on_cleanup` entries.
- Integration Points: row for "App wiring" should read
  `manager.setup(app)` instead of manually mounting the route.
- Add a "Resolved by TASK-775" entry in the revision history.

**NOT in scope**:
- Changing `setup_jira_oauth_routes` itself — it keeps working standalone
  for any caller that prefers it.
- Adding `setup_combined_auth_routes` to the manager — that import stays
  on the Telegram side per architectural decision.
- Changing callback HTML or the `/api/auth/jira/callback` URL.
- Adding new scopes or Jira API functionality.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/jira_oauth.py` | MODIFY | Add `redis_url` kwarg, `_on_startup`, `_on_cleanup`, `setup(app)`, idempotence flag |
| `packages/ai-parrot/src/parrot/autonomous/orchestrator.py` | MODIFY | Replace manual `setup_jira_oauth_routes` call with `manager.setup(app)` |
| `packages/ai-parrot/tests/unit/test_jira_oauth_manager.py` | MODIFY | Adjust fixture to kwarg-only; add lifecycle tests |
| `packages/ai-parrot/tests/unit/test_oauth_callback_routes.py` | MODIFY | Add `setup(app)` end-to-end + idempotence tests |
| `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md` | MODIFY | Update contract, integration points, revision history |

---

## Codebase Contract (Anti-Hallucination)

### Verified locations

- `JiraOAuthManager.__init__` — `jira_oauth.py:97-113`
- aiohttp session lifecycle pattern (precedent for Redis) —
  `jira_oauth.py:111-112` (`_http_owned`) + `jira_oauth.py:129-136`
  (lazy `_get_session`)
- `setup_jira_oauth_routes` — `parrot/auth/routes.py:139-157`
- Orchestrator block to refactor — `autonomous/orchestrator.py:269-281`
- Existing manager test fixture — `tests/unit/test_jira_oauth_manager.py:108`
- Existing callback route tests — `tests/unit/test_oauth_callback_routes.py`
- Setup-pattern precedents — `BotManager.setup(app)`
  (`parrot/manager/manager.py:703`), `AgentSchedulerManager.setup(app=...)`

### Verified imports

```python
# Already imported in jira_oauth.py:
import aiohttp
from typing import Any, Dict, List, Optional, Tuple

# New imports needed:
from aiohttp import web  # type hint for setup(app: web.Application)
import redis.asyncio as aioredis  # lazy — only when building from redis_url
```

### Does NOT exist (do NOT reference)

- ~~`JiraOAuthManager.setup`~~ — method to be created in this task
- ~~`JiraOAuthManager._on_startup` / `._on_cleanup` / `._setup_done`~~ —
  to be created in this task
- ~~`parrot.auth.jira_oauth` importing from `parrot.integrations.telegram`~~ —
  forbidden direction, keep auth module free of Telegram dependencies

---

## Implementation Notes

### Signature after this task

```python
class JiraOAuthManager:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        *,
        redis_url: Optional[str] = None,
        redis_client: Any = None,
        scopes: Optional[List[str]] = None,
        http_session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        if not redis_url and redis_client is None:
            raise ValueError(
                "JiraOAuthManager requires redis_url or redis_client"
            )
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._redis_url = redis_url
        self.redis = redis_client
        self._redis_owned = redis_client is None
        self.scopes = list(scopes) if scopes else list(DEFAULT_SCOPES)
        self._http = http_session
        self._http_owned = http_session is None
        self._setup_done = False
        self.logger = logger

    def setup(self, app: "web.Application") -> None:
        if self._setup_done:
            return
        existing = app.get("jira_oauth_manager")
        if existing is not None and existing is not self:
            raise RuntimeError(
                "app['jira_oauth_manager'] is already set to a different "
                "JiraOAuthManager instance."
            )
        app["jira_oauth_manager"] = self
        app.on_startup.append(self._on_startup)
        app.on_cleanup.append(self._on_cleanup)
        from .routes import setup_jira_oauth_routes
        setup_jira_oauth_routes(app)
        self._setup_done = True

    async def _on_startup(self, app: "web.Application") -> None:
        if self.redis is None and self._redis_url:
            import redis.asyncio as aioredis
            self.redis = aioredis.from_url(
                self._redis_url, decode_responses=True,
            )
            self._redis_owned = True
        if self.redis is not None:
            await self.redis.ping()

    async def _on_cleanup(self, app: "web.Application") -> None:
        if self._redis_owned and self.redis is not None:
            close = getattr(self.redis, "aclose", None) or self.redis.close
            result = close()
            if hasattr(result, "__await__"):
                await result
            self.redis = None
        if self._http_owned and self._http is not None and not self._http.closed:
            await self._http.close()
            self._http = None
```

### Bootstrap before vs. after

```python
# BEFORE
jira_redis = aioredis.from_url("redis://...", decode_responses=True)
self.app["jira_oauth_manager"] = JiraOAuthManager(
    client_id=..., client_secret=..., redirect_uri=...,
    redis_client=jira_redis,
)
setup_jira_oauth_routes(self.app)           # mount callback
# User also has to manage jira_redis lifecycle themselves.

# AFTER
JiraOAuthManager(
    client_id=config.get("JIRA_CLIENT_ID"),
    client_secret=config.get("JIRA_CLIENT_SECRET"),
    redirect_uri=config.get("JIRA_REDIRECT_URI"),
    redis_url=config.get("JIRA_OAUTH_REDIS_URL",
                         fallback="redis://localhost:6379/4"),
).setup(self.app)
# Redis pool + route + signals wired in one call; cleanup automatic.
```

### Redis cleanup compatibility

The `getattr(self.redis, "aclose", None) or self.redis.close` pattern covers:
- redis-py ≥ 5.0 (has `aclose`)
- redis-py 4.x async (still has `close` returning a coroutine)
- Mocked redis clients in tests (both patterns should work)

The `if hasattr(result, "__await__"):` check handles the rare case of a
mock that returns a non-coroutine from `close()`.

---

## Acceptance Criteria

- [ ] `JiraOAuthManager.__init__` accepts `redis_url: Optional[str] = None`
      kwarg-only and raises `ValueError` when neither `redis_url` nor
      `redis_client` is provided.
- [ ] `JiraOAuthManager.setup(app)` exists, is idempotent, registers the
      manager on `app['jira_oauth_manager']`, appends `on_startup` /
      `on_cleanup` signal handlers, and mounts
      `GET /api/auth/jira/callback` via `setup_jira_oauth_routes(app)`.
- [ ] Calling `setup(app)` twice does not register duplicate routes or
      duplicate signal handlers.
- [ ] Setting `app['jira_oauth_manager']` to a **different** instance and
      then calling `setup(app)` raises `RuntimeError`.
- [ ] `_on_startup` creates a Redis client from `redis_url` when no client
      was passed; `_on_cleanup` closes it only when we own it.
- [ ] `_on_cleanup` closes the owned aiohttp session (existing behavior
      preserved).
- [ ] `orchestrator.setup_routes()` no longer imports
      `setup_jira_oauth_routes` directly — it calls `manager.setup(app)`
      when the manager is present.
- [ ] `setup_combined_auth_routes` (FEAT-108) continues to live in
      `parrot.integrations.telegram.combined_callback` and is **not**
      imported from `parrot.auth`.
- [ ] `parrot.auth.jira_oauth` has **zero** imports from
      `parrot.integrations.*` (verified via `grep`).
- [ ] All existing tests pass:
      `pytest packages/ai-parrot/tests/unit/test_jira_oauth_manager.py
      packages/ai-parrot/tests/unit/test_oauth_callback_routes.py
      packages/ai-parrot/tests/unit/test_wrapper_combined_auth.py -v`
- [ ] New tests cover: `redis_url`-only init, missing-both raises,
      `setup()` idempotence, cleanup-ownership.
- [ ] Spec FEAT-107 revision history bumped with TASK-775 note.

---

## Test Specification (sketch)

```python
# tests/unit/test_jira_oauth_manager.py — new cases

def test_init_requires_redis_url_or_client():
    with pytest.raises(ValueError, match="redis_url or redis_client"):
        JiraOAuthManager(
            client_id="x", client_secret="y", redirect_uri="https://h/cb",
        )


@pytest.mark.asyncio
async def test_on_startup_builds_redis_from_url(monkeypatch):
    built = {}
    class FakeRedis:
        async def ping(self): built["pinged"] = True
        async def aclose(self): built["closed"] = True
    def fake_from_url(url, **kw):
        built["url"] = url; return FakeRedis()
    monkeypatch.setattr(
        "redis.asyncio.from_url", fake_from_url, raising=False,
    )
    mgr = JiraOAuthManager(
        client_id="x", client_secret="y", redirect_uri="https://h/cb",
        redis_url="redis://localhost:6379/4",
    )
    await mgr._on_startup(app=None)
    assert built["url"] == "redis://localhost:6379/4"
    assert built["pinged"] is True
    await mgr._on_cleanup(app=None)
    assert built["closed"] is True


@pytest.mark.asyncio
async def test_on_cleanup_leaves_external_redis_alone(mock_redis):
    mgr = JiraOAuthManager(
        client_id="x", client_secret="y", redirect_uri="https://h/cb",
        redis_client=mock_redis,
    )
    await mgr._on_cleanup(app=None)
    mock_redis.aclose.assert_not_called()  # we did not own it
```

```python
# tests/unit/test_oauth_callback_routes.py — new cases

def test_manager_setup_mounts_route_and_signals(mock_redis):
    app = web.Application()
    mgr = JiraOAuthManager(
        client_id="x", client_secret="y", redirect_uri="https://h/cb",
        redis_client=mock_redis,
    )
    mgr.setup(app)
    assert app["jira_oauth_manager"] is mgr
    assert any(
        r.resource.canonical == "/api/auth/jira/callback"
        for r in app.router.routes()
    )
    assert mgr._on_startup in app.on_startup
    assert mgr._on_cleanup in app.on_cleanup


def test_setup_is_idempotent(mock_redis):
    app = web.Application()
    mgr = JiraOAuthManager(
        client_id="x", client_secret="y", redirect_uri="https://h/cb",
        redis_client=mock_redis,
    )
    mgr.setup(app)
    mgr.setup(app)  # no-op
    routes = [
        r for r in app.router.routes()
        if r.resource.canonical == "/api/auth/jira/callback"
    ]
    assert len(routes) == 1
    assert app.on_startup.count(mgr._on_startup) == 1
    assert app.on_cleanup.count(mgr._on_cleanup) == 1


def test_setup_rejects_conflicting_existing_manager(mock_redis):
    app = web.Application()
    other = object()
    app["jira_oauth_manager"] = other
    mgr = JiraOAuthManager(
        client_id="x", client_secret="y", redirect_uri="https://h/cb",
        redis_client=mock_redis,
    )
    with pytest.raises(RuntimeError, match="already set"):
        mgr.setup(app)
```

---

## Output

When complete, the agent must:
1. Move this file to `sdd/tasks/completed/`
2. Update `sdd/tasks/.index.json` status to `done`
3. Add a brief completion note below

### Completion Note

**Completed**: 2026-04-19

Implementation (commit `c39e3cc0`):

- `JiraOAuthManager.__init__` now accepts `redis_url` and `redis_client`
  as kwarg-only; raises `ValueError` if neither is supplied. Tracks
  `_redis_url` and `_redis_owned` to scope cleanup responsibility.
- Added idempotent `setup(app)` that stores the manager on
  `app['jira_oauth_manager']`, appends `_on_startup` / `_on_cleanup` to
  the aiohttp signals, and mounts the callback via
  `setup_jira_oauth_routes(app)`. Raises `RuntimeError` if the app
  already holds a different manager instance. `_setup_done` guards
  duplicate calls from both the bootstrap and the orchestrator.
- `_on_startup` lazily builds the Redis client from `redis_url`
  (`redis.asyncio.from_url(..., decode_responses=True)`) and calls
  `ping()` to fail fast. `_on_cleanup` closes the owned Redis (tries
  `aclose()` first, falls back to `close()`) and the owned aiohttp
  session.
- `orchestrator.setup_routes()` now delegates to `manager.setup(app)`
  when the manager is present and no longer imports
  `setup_jira_oauth_routes` directly. The FEAT-108 combined callback
  continues to be mounted from `parrot.integrations.telegram` — the
  auth module stays free of integration imports (verified via grep).
- Tests: added `TestInitialization` and `TestLifecycleHooks` to
  `tests/unit/test_jira_oauth_manager.py`; added `setup(app)` mount,
  idempotence, and conflict-rejection cases to
  `tests/unit/test_oauth_callback_routes.py`. The route-count helper
  filters to `method == 'GET'` because aiohttp's `add_get` also adds a
  matching HEAD route by default.
- Spec `FEAT-107` updated: new `__init__` signature + `setup`/lifecycle
  methods in the public interfaces section, integration-points row
  rewritten, revision history bumped to v0.2.

**Test results**: `pytest packages/ai-parrot/tests/unit/test_jira_oauth_manager.py
packages/ai-parrot/tests/unit/test_oauth_callback_routes.py
packages/ai-parrot/tests/unit/test_wrapper_combined_auth.py -v` → 58
passed.
