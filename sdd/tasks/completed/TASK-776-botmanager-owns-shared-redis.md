# TASK-776: BotManager Owns Shared `app['redis']` + JiraOAuthManager Self-Discovery

**Feature**: FEAT-107 — Jira OAuth 2.0 (3LO)
**Spec**: `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (4-6h)
**Depends-on**: TASK-775
**Assigned-to**: unassigned

---

## Context

After TASK-775 shipped, the aiohttp `Application` still has no owner for a
shared `app['redis']` client. navigator-auth reads it (`auth.py:282`,
`middlewares/django.py:54`) and FEAT-108's `VaultTokenSync` consumes it via
`TelegramAgentWrapper._init_post_auth_providers()`, but **no package in the
`navigator*` stack publishes it**:

- `navigator_session` creates its own private `aioredis.ConnectionPool` in
  `storages/redis.py:40-46` and never exposes it.
- `navigator_auth` and `navigator` core only consume `app['redis']`; they
  expect the bootstrap to wire it.

Today the only way to satisfy the contract is to add Redis wiring to
`app.py`, which pollutes the bootstrap with infrastructure responsibilities.
We want a cleaner pattern:

1. **`BotManager.setup(app)`** — the first ai-parrot component configured —
   publishes `app['redis']` using the existing `REDIS_URL` constant from
   `parrot.conf:253`. `VaultTokenSync` and navigator-auth's refresh-token
   rotation both pick it up automatically.
2. **`JiraOAuthManager.__init__(..., app=...)`** — when the manager is
   constructed with a reference to the aiohttp app, it reuses
   `app['redis']` if present and only falls back to building its own Redis
   client from `redis_url` when the app does not provide one. This removes
   the redundant Redis pool FEAT-107 currently creates alongside
   navigator-session's.
3. **`JiraOAuthManager.setup()` is parameterless** — the app is already
   stored on `self._app` during `__init__`, so the caller does not pass it
   twice. Bootstrap in `app.py` becomes a single fluent line.

The net effect: one shared Redis client per app, owned by BotManager, and
every consumer gets it for free. `app.py` stays clean.

---

## Scope

### 1. `BotManager.setup(app)` publishes `app['redis']`

- File: `packages/ai-parrot/src/parrot/manager/manager.py:703`.
- Add synchronous Redis client creation right after `self.app = app` is
  set:
  ```python
  if 'redis' not in self.app:
      import redis.asyncio as aioredis
      from ..conf import REDIS_URL
      self.app['redis'] = aioredis.from_url(REDIS_URL, decode_responses=True)
      self._redis_owned = True
  else:
      self._redis_owned = False
  ```
  `redis.asyncio.from_url()` is lazy — no connection is opened until the
  first command, so calling it synchronously in `setup()` is safe.
- **Idempotence**: if a prior component already set `app['redis']`, do not
  overwrite — respect external ownership and set `self._redis_owned = False`.
- **Cleanup**: register an `on_cleanup` handler so BotManager closes the
  client **only when it owns it**:
  ```python
  async def _cleanup_redis(app):
      if self._redis_owned:
          client = app.pop('redis', None)
          if client is not None:
              close = getattr(client, 'aclose', None) or client.close
              result = close()
              if hasattr(result, '__await__'):
                  await result
  app.on_cleanup.append(_cleanup_redis)
  ```
- Log one line at setup: `"BotManager: registered shared Redis client at
  app['redis'] (owned=<bool>, url=<...>)"`.

### 2. `JiraOAuthManager.__init__` accepts `app`

- File: `packages/ai-parrot/src/parrot/auth/jira_oauth.py:97`.
- Add `app: Optional["web.Application"] = None` kwarg-only (placed before
  `redis_url` for ergonomics, but all new kwargs stay after the `*,`).
- Update the validation: the manager needs **one of** `app` (with
  `app['redis']` set), `redis_client`, or `redis_url`.
  ```python
  if (
      app is None
      and redis_client is None
      and not redis_url
  ):
      raise ValueError(
          "JiraOAuthManager requires one of: app (with app['redis']), "
          "redis_client, or redis_url"
      )
  ```
- Store `self._app = app` so `setup()` can reuse it.
- Resolution order for `self.redis` (runs in `_on_startup`, NOT `__init__`,
  so the app's Redis is allowed to be created later):
  1. If `redis_client` was passed → use it. `_redis_owned = False`.
  2. Elif `self._app` is not None AND `self._app.get('redis')` is not
     None → use it. `_redis_owned = False`.
  3. Elif `self._redis_url` is set → build with `aioredis.from_url(...)`.
     `_redis_owned = True`.
  4. Else → raise `RuntimeError` at startup (should not happen — caught by
     `__init__` validation).
- **In `__init__`**, only validate; do **not** try `self._app.get('redis')`
  — BotManager may not have published it yet if the manager is
  instantiated before `BotManager.setup(app)`. Resolution happens on
  startup signal.

### 3. `JiraOAuthManager.setup()` — no args

- File: same.
- Current signature: `def setup(self, app: web.Application) -> None`.
- New signature: `def setup(self) -> None`.
- Behavior: uses `self._app` (set in `__init__`). Raises `RuntimeError`
  with a clear message if `self._app is None` — "Pass `app=` to the
  constructor or use `redis_url` and mount routes manually".
- Keep the idempotence flag (`self._setup_done`) and the
  "refuses-to-overwrite-different-instance" check from TASK-775.

### 4. Update `orchestrator.setup_routes()`

- File: `packages/ai-parrot/src/parrot/autonomous/orchestrator.py:272`.
- Current:
  ```python
  if 'jira_oauth_manager' in app:
      app['jira_oauth_manager'].setup(app)
      ...
  ```
- New:
  ```python
  manager = app.get('jira_oauth_manager')
  if manager is not None:
      manager.setup()
      ...
  ```

### 5. Simplify `app.py`

- File: `app.py` at the repo root.
- Current (lines 91-98):
  ```python
  jira_oauth_manager = JiraOAuthManager(
      client_id=JIRA_CLIENT_ID,
      client_secret=JIRA_CLIENT_SECRET,
      redirect_uri=JIRA_REDIRECT_URI,
      redis_url=JIRA_OAUTH_REDIS_URL,
  )
  jira_oauth_manager.setup(self.app)
  setup_combined_auth_routes(self.app)
  ```
- New:
  ```python
  JiraOAuthManager(
      client_id=JIRA_CLIENT_ID,
      client_secret=JIRA_CLIENT_SECRET,
      redirect_uri=JIRA_REDIRECT_URI,
      app=self.app,
  ).setup()
  setup_combined_auth_routes(self.app)
  ```
- **Important ordering**: `BotManager.setup(self.app)` (line 88) publishes
  `app['redis']` before the JiraOAuthManager is constructed. Keep that
  order.
- `JIRA_OAUTH_REDIS_URL` constant in `conf.py:564` can stay (useful for
  deployments that want a dedicated Redis for OAuth state) but is now
  **optional** — the default path reuses `app['redis']` from BotManager.

### 6. Tests

- `tests/unit/test_jira_oauth_manager.py`:
  - Update fixture — replace `redis_client=mock_redis` with
    `app=fake_app_with_redis()` where natural.
  - Add `test_init_with_app_resolves_redis_from_app_on_startup`.
  - Add `test_init_without_app_redis_or_url_raises`.
  - Add `test_app_redis_takes_precedence_over_redis_url`.
  - Adjust any `manager.setup(app)` calls to `manager.setup()`.

- `tests/unit/test_oauth_callback_routes.py`:
  - Same signature migration.
  - Add `test_setup_without_app_raises_runtime_error` — construct manager
    with only `redis_client=...` and call `.setup()` to verify it fails
    with a useful message.

- `tests/unit/test_bot_manager_redis.py` (NEW):
  - `test_setup_publishes_redis_when_absent`.
  - `test_setup_preserves_existing_redis_and_marks_not_owned`.
  - `test_cleanup_closes_redis_only_when_owned`.

- Verify existing FEAT-108 wrapper tests still pass —
  `tests/unit/test_wrapper_combined_auth.py` uses `_make_app(redis=...)`
  directly, so nothing to change there.

### 7. Spec updates — `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md`

- §6 Codebase Contract: update `JiraOAuthManager.__init__` signature
  (add `app`), update `setup()` signature (no args).
- §6 Integration Points: add row — `BotManager.setup(app)` →
  `app['redis']` — consumed by `JiraOAuthManager` and `VaultTokenSync`.
- §7 Known Risks: add note that shared Redis ownership lives in
  BotManager; document the "first-setter-wins" idempotence contract.
- Revision history: bump to 0.3 with TASK-776 reference.

**NOT in scope**:
- Changing `BotManager.__init__` — Redis setup lives in `setup()` only.
- Creating a separate `AppServices` / `RedisService` helper class —
  per user direction, keep the responsibility inside `BotManager`.
- Touching navigator-auth / navigator-session / navigator core — the
  expectation of `app['redis']` being externally provided is preserved;
  BotManager just becomes the external provider.
- Adding `app['authdb']` creation — navigator-auth already publishes it.
- Migrating `JIRA_OAUTH_REDIS_URL` usage out of the codebase — it stays
  as an opt-out for deployments that want isolated OAuth state.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/manager/manager.py` | MODIFY | `BotManager.setup(app)` publishes `app['redis']` + cleanup hook |
| `packages/ai-parrot/src/parrot/auth/jira_oauth.py` | MODIFY | `__init__` accepts `app=`; `setup()` becomes parameterless; Redis resolution order updated |
| `packages/ai-parrot/src/parrot/autonomous/orchestrator.py` | MODIFY | Call `manager.setup()` (no args) in `setup_routes()` |
| `app.py` | MODIFY | Simplify Jira bootstrap to one fluent line using `app=self.app` |
| `packages/ai-parrot/tests/unit/test_jira_oauth_manager.py` | MODIFY | Switch fixtures to `app=`; new tests for `app`-based init |
| `packages/ai-parrot/tests/unit/test_oauth_callback_routes.py` | MODIFY | Update `setup()` calls to no args; test RuntimeError path |
| `packages/ai-parrot/tests/unit/test_bot_manager_redis.py` | CREATE | Coverage for the BotManager Redis ownership contract |
| `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md` | MODIFY | Update §6 / §7; bump revision history |

---

## Codebase Contract (Anti-Hallucination)

### Verified locations
- `BotManager.setup(app)` — `packages/ai-parrot/src/parrot/manager/manager.py:703-718`
- `REDIS_URL` — `packages/ai-parrot/src/parrot/conf.py:253`
- `JiraOAuthManager.__init__` (post-TASK-775) —
  `packages/ai-parrot/src/parrot/auth/jira_oauth.py:97-125` (already accepts
  `redis_url` / `redis_client` kwargs-only)
- `JiraOAuthManager.setup(app)` (post-TASK-775) — same file, accepts `app`
  positionally today
- `orchestrator.setup_routes()` post-TASK-775 —
  `packages/ai-parrot/src/parrot/autonomous/orchestrator.py:269-281`
- Bootstrap —
  `app.py:91-98`
- navigator-auth reads `app['redis']` — confirmed at
  `.venv/lib/python3.11/site-packages/navigator_auth/auth.py:282`

### Verified imports
```python
# BotManager new imports:
import redis.asyncio as aioredis
from ..conf import REDIS_URL

# JiraOAuthManager — aiohttp.web imported lazily for type hint only:
if TYPE_CHECKING:
    from aiohttp import web
```

### Does NOT exist (do NOT reference)
- ~~`BotManager._redis_owned`~~ — created in this task
- ~~`JiraOAuthManager._app`~~ — created in this task
- ~~`app.py` imports `redis.asyncio`~~ — intentionally kept out to keep
  bootstrap clean
- ~~A `RedisService` helper class~~ — explicitly out of scope

---

## Acceptance Criteria

- [ ] `BotManager.setup(app)` publishes `app['redis']` (via
      `aioredis.from_url(REDIS_URL, decode_responses=True)`) when the key
      is not already set.
- [ ] `BotManager.setup(app)` does **not** overwrite a pre-existing
      `app['redis']` value and records that it does not own it.
- [ ] `BotManager` registers an `on_cleanup` handler that closes the Redis
      client only when it owns it (`self._redis_owned`).
- [ ] `JiraOAuthManager.__init__` accepts `app: Optional[web.Application]`
      kwarg-only. Raises `ValueError` when none of `app`, `redis_client`,
      or `redis_url` provide a way to get a Redis client.
- [ ] In `_on_startup`, the manager uses `app['redis']` when `self._app`
      has it, otherwise falls back to its own `redis_url`.
- [ ] `JiraOAuthManager.setup()` is parameterless; calling it without
      having passed `app=` to `__init__` raises `RuntimeError`.
- [ ] `orchestrator.setup_routes()` calls `manager.setup()` (no args).
- [ ] `app.py` bootstrap compiles to a single fluent
      `JiraOAuthManager(..., app=self.app).setup()` call.
- [ ] Startup of the full stack (dev-like env) shows neither
      `app['jira_oauth_manager'] is not set` nor
      `app['authdb']/app['database'] or app['redis'] is not set`.
- [ ] All existing FEAT-107 + FEAT-108 tests pass:
      `pytest packages/ai-parrot/tests/unit/test_jira_oauth_manager.py
      packages/ai-parrot/tests/unit/test_oauth_callback_routes.py
      packages/ai-parrot/tests/unit/test_wrapper_combined_auth.py -v`
- [ ] New tests for the BotManager Redis ownership contract pass.
- [ ] Spec FEAT-107 revision history updated to 0.3.

---

## Test Specification (sketch)

```python
# tests/unit/test_jira_oauth_manager.py — new cases

def test_init_requires_one_of_app_redis_client_or_url():
    with pytest.raises(ValueError, match="one of: app"):
        JiraOAuthManager(
            client_id="x", client_secret="y", redirect_uri="https://h/cb",
        )


@pytest.mark.asyncio
async def test_app_redis_resolved_on_startup(mock_redis):
    app = {"redis": mock_redis}  # dict acts as app.get / app[...]
    mgr = JiraOAuthManager(
        client_id="x", client_secret="y", redirect_uri="https://h/cb",
        app=app,
    )
    await mgr._on_startup(app)
    assert mgr.redis is mock_redis
    assert mgr._redis_owned is False


@pytest.mark.asyncio
async def test_app_redis_takes_precedence_over_redis_url(mock_redis, monkeypatch):
    built = []
    monkeypatch.setattr(
        "redis.asyncio.from_url",
        lambda *a, **kw: built.append(a) or mock_redis,
    )
    app = {"redis": mock_redis}
    mgr = JiraOAuthManager(
        client_id="x", client_secret="y", redirect_uri="https://h/cb",
        app=app, redis_url="redis://should-not-be-used/0",
    )
    await mgr._on_startup(app)
    assert mgr.redis is mock_redis
    assert built == []  # from_url was never called


def test_setup_without_app_raises():
    mgr = JiraOAuthManager(
        client_id="x", client_secret="y", redirect_uri="https://h/cb",
        redis_url="redis://localhost:6379/4",
    )
    with pytest.raises(RuntimeError, match="Pass `app=`"):
        mgr.setup()
```

```python
# tests/unit/test_bot_manager_redis.py — NEW

@pytest.mark.asyncio
async def test_setup_publishes_redis_when_absent(app_factory):
    app = app_factory()
    assert "redis" not in app
    mgr = BotManager()
    mgr.setup(app)
    assert "redis" in app
    assert mgr._redis_owned is True


@pytest.mark.asyncio
async def test_setup_preserves_existing_redis_and_marks_not_owned(
    app_factory, mock_redis,
):
    app = app_factory()
    app["redis"] = mock_redis
    mgr = BotManager()
    mgr.setup(app)
    assert app["redis"] is mock_redis  # untouched
    assert mgr._redis_owned is False


@pytest.mark.asyncio
async def test_cleanup_closes_redis_only_when_owned(app_factory):
    app = app_factory()
    mgr = BotManager()
    mgr.setup(app)
    client = app["redis"]
    # Simulate app.on_cleanup firing
    for handler in app.on_cleanup:
        await handler(app)
    assert "redis" not in app  # popped
```

---

## Implementation Notes

### Ownership discipline

The `_redis_owned` flag is the single source of truth for "do I close this
in on_cleanup?". External providers (tests, other bootstraps, future
injections) stay in control of their own client's lifecycle.

### BotManager is the natural first-owner

`app.py` always calls `BotManager.setup(self.app)` as the first ai-parrot
step after framework-level setup (QuerySource, BackgroundQueue). Making
BotManager responsible for `app['redis']` means every downstream ai-parrot
component (schedulers, handlers, integrations, toolkits) can rely on it
without extra wiring.

If a consumer really wants a different Redis client, they assign
`app['redis']` **before** calling `BotManager.setup(self.app)`. The
idempotence check keeps that path working.

### Why resolve Redis in `_on_startup`, not `__init__`

`JiraOAuthManager(..., app=self.app)` may be constructed in
`Main.configure()` at a moment when `app['redis']` already exists (we call
`BotManager.setup()` first), but we still defer lookup to startup so:
1. The ordering constraint is explicit — the startup signal is the
   guaranteed "all services are wired" moment.
2. Any component that happens to publish `app['redis']` in an
   `on_startup` signal (not synchronously in `setup()`) is still honored.
3. `ping()` — already added in TASK-775 — remains the single liveness
   check for the connection.

### Keep `redis_url` as an escape hatch

Deployments that want the OAuth state in a dedicated Redis (separate from
the shared `app['redis']`) simply pass `redis_url=...` without `app=`. The
ownership resolver ignores `app` if `redis_client` or `redis_url` are more
specific.

---

## Output

When complete, the agent must:
1. Move this file to `sdd/tasks/completed/`
2. Update `sdd/tasks/.index.json` status to `done`
3. Add a brief completion note below

### Completion Note

Implemented on `dev` (commit `3705fcdb`):

- `BotManager.setup(app)` (`parrot/manager/manager.py:703-...`) now calls
  a new `_register_shared_redis()` helper that publishes
  `app['redis']` via `redis.asyncio.from_url(REDIS_URL, decode_responses=True)`
  when the key is absent. If another component already set it,
  BotManager keeps it untouched and marks `_redis_owned = False`.
  `_cleanup_shared_redis` is registered as an `on_cleanup` handler and
  closes the client only when `_redis_owned`.
- `JiraOAuthManager.__init__` gained a kwarg-only `app=`. The "need
  one of" validation now accepts `app`, `redis_client`, or
  `redis_url`. `_on_startup` resolves `self.redis` in priority order
  (explicit client > `app['redis']` > `redis_url` fallback) and
  raises `RuntimeError` if no source is available.
- `JiraOAuthManager.setup()` is parameterless — uses `self._app`
  stored at construction. Calling it without having passed `app=`
  raises `RuntimeError` with a pointer to the two recovery paths.
- `orchestrator.setup_routes()` invokes `manager.setup()` without
  arguments.
- `app.py` bootstrap simplified to `JiraOAuthManager(client_id=...,
  client_secret=..., redirect_uri=..., app=self.app).setup()` — the
  `JIRA_OAUTH_REDIS_URL` import is gone; the shared app-level client
  is enough.
- Tests:
  - `test_jira_oauth_manager.py`: added
    `test_accepts_app_without_redis_url_or_client`,
    `test_on_startup_resolves_redis_from_app`,
    `test_on_startup_app_redis_takes_precedence_over_url`,
    `test_on_startup_falls_back_to_redis_url_when_app_has_no_redis`,
    `test_on_startup_raises_when_no_redis_source`. Renamed
    `test_requires_redis_url_or_client` → the new
    `test_requires_app_redis_client_or_url`.
  - `test_oauth_callback_routes.py`: existing
    `test_manager_setup_*` cases migrated to the new
    `app=` constructor + parameterless `setup()`. Added
    `test_setup_without_app_raises`.
  - `test_bot_manager_redis.py` (new): covers the ownership contract
    (publish-when-absent, preserve-when-present, close-only-when-owned,
    idempotent-when-popped). Uses `importorskip` so it skips cleanly
    on envs where BotManager's import chain is broken by the
    pre-existing `notify` / `navconfig` / `navigator.background`
    version drift (same issue kills `test_botmanager_flags.py`).
- Spec FEAT-107 bumped to 0.3 with two new Integration Points rows
  and a full TASK-776 revision entry.

**Verification**: 250 passed + 1 module-skipped (env issue, NOT from
TASK-776). `app.py` imports cleanly. `JiraOAuthManager.__init__`
signature now reads `(self, client_id, client_secret, redirect_uri,
*, app=None, redis_url=None, redis_client=None, scopes=None,
http_session=None)` and `JiraOAuthManager.setup` is `(self) -> None`.

**Pre-existing env issue (out of scope)**: The installed `notify`
package expects `navconfig.DEBUG` and `navconfig.logging.logger`, and
additionally imports `navigator.background` (missing). Affects
`tests/test_botmanager_flags.py` identically. Should be fixed
separately — not a regression from this task.
