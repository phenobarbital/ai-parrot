# TASK-3518 Research: Verify Real navigator-session Redis and Fixture Authentication

**Feature**: FEAT-581 — Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Module**: M4 (spike gate, per spec §8 "Implementation Spike Gates": "Validate
session payload/cookie wire round-trip using the installed lockfile
environment — owner: M4; blocks M4 implementation packet.")
**Acceptance criteria addressed**: AC4, AC17
**Date**: 2026-09-19

---

## 0. Baseline and Provenance

| Item | Value |
|---|---|
| Worktree HEAD at spike time | `d0b0859e9` |
| Host | Linux 7.0.0-30-generic x86_64, shared workspace `.venv` interpreter (Python 3.12), invoked read-only |
| `navigator-session` installed | **1.0.1** (`importlib`/`__version__` read directly, `navigator_session/version.py:9`) |
| `navigator-session` declared floor | `>=1.0.1` — `packages/ai-parrot/pyproject.toml:110` and root `pyproject.toml:176`. Installed == floor, no drift. |
| `redis` (Python client) | `5.2.1` |
| `redis-server` binary | **not installed** in this shared `.venv`/host (`which redis-server` → not found) |
| Disposable Redis used instead | `redis:7-alpine` Docker image, already cached locally (`docker images`) |

Source anchors re-verified byte-for-byte against the task's Codebase Contract:

- `packages/ai-parrot-server/src/parrot/manager/manager.py` — sha256
  `4a02c5feb76658ddd89a63649ae28bd13f1cdd39e9feeab51343048851c80844` — **matches
  the task's Codebase Contract exactly**, unmodified by this task.
- `docker/integrations/server.py` — sha256
  `c580501988bc7a82b8ba884bb8f1ded9542083f7e86cf5c0bb9a71e983ebc302` — **matches**.

Additional installed-package anchors read/hashed for this spike (none part of
this task's file scope; none modified):

| File | sha256 |
|---|---|
| `navigator_session/__init__.py` | `ed1bb1d396697e2ddd47acb26b47ceeefe967cd0d26c7b6f22eee70c3db8b61c` |
| `navigator_session/conf.py` | `3def2ab2e926b797175cf737870169852585e71088a597de150f098480849e8c` |
| `navigator_session/session.py` | `086f938ec990aa3ba4e8dec60983604130a4ad7a6d82afacc070e27a680798a2` |
| `navigator_session/storages/abstract.py` | `8b660508aea3b28400e8360379ec06ce39569ce1a2c7d9c251f726e98c1f9291` |
| `navigator_session/storages/redis.py` | `4b04a12f6bb35f61a182115e22b0ecb22e9fd565edf3f517e4f14e70e323b375` |
| `navigator_session/storages/cookie.py` | `5482f35426ad2a50e1328403a04db2d2eeacee5a78c1b75ea7939cd0d7c825c8` |
| `navconfig/kardex.py` | `43f1781bff96e1a7b65af79a25baca6a50e597e6c6e9650011bce76f5a84001d` |
| `navconfig/project.py` | `004c6cc61d49e886b8b8df9685b7a8896dff542f9c5eb24de9749b00d2e242dc` |
| `packages/ai-parrot-server/tests/test_tools_list_route.py` | `b25f2cac7a1e620eb46715aa88d5276e7d88250419dc03e23bf649758d86d5c6` |

**Method.** Two spike scripts, both run under the shared `.venv` interpreter,
real (unmocked) `navigator_session` 1.0.1, real (unmocked, unmodified)
`BotManager` from `parrot.manager.manager`, and a real disposable Redis
container — **never** the operator's shared `docker-redis-1` (port 6379,
still running, `dbsize` untouched, confirmed below). Disposable
driver scripts and raw logs are **not part of this task's file scope** and
were written under `/tmp` (ephemeral per-invocation sandbox storage), not
committed; their exact contents and outputs are reproduced verbatim/sanitized
below rather than referenced by path, since `/tmp` does not persist across
tool invocations in this harness.

- **Spike 1** (`unittest.mock.patch.object(..., "SESSION_URL", ...)` +
  hand-rolled dict "request") — run first to establish mechanics, then
  **discarded as the frozen contract** once §2 of the spec was re-read
  closely: it violates the spec's explicit "not an arbitrary `SESSION_URL`
  constructor argument" and "No monkeypatch, synthetic request object ...
  is permitted in the target process" constraints. Its results are kept in
  §4 only as a secondary cross-check (both approaches agree on outcomes),
  not as the selected contract.
- **Spike 2** (env-var-only fixture isolation, real `aiohttp.web.Request`
  objects throughout, real `BotManager.get_user_bot()`) — this is the
  **spec-compliant** experiment and the one this report's contract is based
  on (§3).

Private Redis argv used both times (identical container, different name per
run to avoid a stale-name collision):

```bash
docker run -d --rm --name spike-redis-3518 -p 16399:6379 redis:7-alpine
# ... experiment ...
docker stop spike-redis-3518   # --rm auto-removes on stop; no manual `docker rm`
```

Clean shutdown verified — `docker ps -a --filter name=spike-redis` returns
empty after each `docker stop`. The operator's `docker-redis-1` (port 6379)
was **never contacted**: every experiment's Redis client points at
`127.0.0.1:16399` (Spike 1: via a patched module attribute; Spike 2: via
`REDIS_PORT=16399` in a `SITE_ROOT`-isolated env), and `docker ps` before/
after every run confirms `docker-redis-1` stayed `Up`, untouched, with no
`FLUSHDB`/`FLUSHALL`/key inspection issued against it at any point.

---

## 1. Q1 — Installed navigator-session API, version/source, cookie round-trip with disposable Redis

**Verdict: PASS.**

### 1.1 Version/source anchors (read, not assumed)

```
navigator_session.__version__ == "1.0.1"          # version.py:9
navigator_session.__file__ == ".../site-packages/navigator_session/__init__.py"
```

Module map (all read in full):

- `navigator_session/__init__.py` — `new_session()`/`get_session()` free
  functions (§1.3 below).
- `navigator_session/conf.py` — all config constants, computed **once** at
  import time from `navconfig.config.get(...)` (§2).
- `navigator_session/session.py` — `SessionHandler` (only supports
  `storage="redis"`; any other value raises `NotImplementedError` —
  `session.py:16-21`).
- `navigator_session/storages/abstract.py` — `AbstractStorage`: cookie
  name is `self.__name__ = SESSION_COOKIE_SECURE` (`abstract.py:66`) — i.e.
  the **cookie name** is drawn from the `SESSION_COOKIE_SECURE` config key
  (fallback value `"csrf_secure"`), not a literal `"session_id"`/app name.
  Confirmed live: the real `Set-Cookie` header name was `csrf_secure` in
  both spikes.
- `navigator_session/storages/redis.py` — `RedisStorage` (the only
  storage `SessionHandler` can build); imports `SESSION_URL` **by value**
  from `..conf` at module import time (`redis.py:7-14`) — a copy, not a
  live reference (relevant to §2).
- `navigator_session/storages/cookie.py` — `CookieStorage`: **confirmed
  unfinished**, see §5.

### 1.2 Cookie round-trip with disposable Redis — verified end-to-end

Spike 2 (spec-compliant), against `redis://127.0.0.1:16399/0`
(disposable container), using a real `aiohttp` app with
`SessionHandler(storage="redis", use_cookies=True, secure=False).setup(app)`
and a real `aiohttp.test_utils.TestClient`:

```
POST /e2e/bootstrap-login          -> 200 {"session_id": "2755fa3201874ef68972206af886169e"}
                                       (Set-Cookie: csrf_secure=... issued by the
                                        session_middleware after the handler returns,
                                        because new_session() marks the session
                                        is_changed=True and the middleware calls
                                        storage.save_session(request, response, session))
GET  /e2e/protected/bot  (with the real cookie from above)
                                    -> 200 {"bot": null, "user_id": "e2e-test-user-3518"}
                                       (user_id recovered via Redis GET "session:<id>",
                                        decoded, matches what was frozen at login)
```

This is a genuine round trip: `new_session()` → Redis `SET session:<id>` +
`SET user:<identity>` → cookie issued → next HTTP request → cookie parsed →
Redis `GET session:<id>` → session reconstructed with the original
`user_id`. **PASS**, first required question.

---

## 2. Q — REDIS_HOST/REDIS_PORT/SESSION_DB import ordering and fixture config-root settings

**Verdict: PASS, with a concrete, load-bearing gotcha the spec text does not
fully cover — recorded here because it will silently break M4 otherwise.**

### 2.1 The three constants are computed once, at first import — confirmed

`navigator_session/conf.py:36-39`:

```python
REDIS_HOST = config.get("REDIS_HOST", fallback="localhost")
REDIS_PORT = config.get("REDIS_PORT", fallback=6379)
REDIS_SESSION_DB = config.get("SESSION_DB", fallback=0)
SESSION_URL = f"{SESSION_BACKEND}://{REDIS_HOST}:{REDIS_PORT}/{REDIS_SESSION_DB}"
```

These are plain module-level names, evaluated exactly once when
`navigator_session.conf` is first imported (transitively, on
`import navigator_session`). Changing `os.environ` **after** that import has
**no effect** — confirmed empirically (`import navigator_session.conf`,
then mutate `os.environ`, then re-read `SESSION_URL` unchanged). Matches the
spec's own instruction: "Set REDIS_HOST, REDIS_PORT, SESSION_DB **before**
importing navigator-session."

Also: `navigator_session/storages/redis.py:7-14` does
`from ..conf import (SESSION_URL, ...)` — a **name binding**, i.e. a
snapshot copy at `storages.redis` import time. Patching
`navigator_session.conf.SESSION_URL` **after** `storages.redis` has already
been imported does **not** change what `RedisStorage.on_startup()` actually
uses — only `navigator_session.storages.redis.SESSION_URL` (the copy) does.
This is why Spike 1 patched `ns_redis_mod.SESSION_URL`, not `ns_conf.SESSION_URL`
— and why the spec is right to forbid relying on that pattern for the real
target process; it is fragile to import order and does not match "the URL is
computed from those variables."

### 2.2 The gotcha: this repo's checked-in `env/.env` wins over `os.environ`, regardless of import order

Setting `os.environ["REDIS_HOST"]`/`["REDIS_PORT"]` **before** importing
`navigator_session` is **necessary but not sufficient** in this repository,
because `navconfig`'s `Kardex.get()` checks its own `_mapping_` dict
(populated by parsing the discovered `env/.env` file) **before** falling
back to `os.environ`:

```python
# navconfig/kardex.py:509-514
if key in self._mapping_:
    return self._mapping_[key]
# get ENV value
if key in os.environ:
    ...
```

`_mapping_` is populated once, at `Kardex` construction, from
`self._env_loader.load_environment()` (`kardex.py:319`) — i.e. from the
project's `env/.env` file, **loaded with `override=False`** by
`python-dotenv` internally but that flag only governs whether `load_dotenv`
overwrites `os.environ`; it does **not** change the fact that `Kardex.get()`
checks its own `_mapping_` dict first, unconditionally, ahead of
`os.environ`, for any key present in the file.

**Verified empirically, in this exact repository**:

```
$ grep -n '^REDIS_HOST\|^REDIS_PORT' env/.env
107:REDIS_HOST=nav-api.dev.local
108:REDIS_PORT=6379
# (no SESSION_DB key in env/.env)

$ python3 -c "
import os
os.environ['REDIS_HOST']='testhost123'; os.environ['REDIS_PORT']='55999'
os.environ['SESSION_DB']='5'   # not in env/.env
import navigator_session.conf as c
print(c.REDIS_HOST, c.REDIS_PORT, c.REDIS_SESSION_DB, c.SESSION_URL)
"
nav-api.dev.local 6379 5 redis://nav-api.dev.local:6379/5
```

`REDIS_HOST`/`REDIS_PORT` (present in `env/.env`) **silently ignored** the
just-set `os.environ` values and resolved to the operator's
`nav-api.dev.local:6379`; `SESSION_DB` (absent from `env/.env`) correctly
fell through to the `os.environ` value. Setting the three env vars alone,
as the spec's prose literally says, **is not sufficient in this repo** —
it will silently point the "isolated" fixture Redis client at the operator's
configured host unless the config root itself is isolated too.

### 2.3 The fix: isolate `SITE_ROOT` (not just the three Redis vars)

`navconfig.project.project_root()` does **not** use `cwd` to find the
project root — with no `SITE_ROOT` env var set, and running inside a
virtualenv (the normal case here), it resolves via
`site_root = Path(sys.prefix).resolve().parent` (`navconfig/project.py:138-139`)
— i.e. **the parent directory of the active `.venv`**, which is this repo
root, **regardless of the target subprocess's `cwd`**. This means a target
subprocess cannot dodge the operator's `env/.env` just by being spawned
from a different working directory while sharing this `.venv`.

Setting `SITE_ROOT` (and having a project-shaped `env/` subdirectory
under it, even an empty one — `Kardex` raises `FileExistsError` if
`SITE_ROOT/env/` is entirely absent) **before** any `navconfig`/
`navigator_session` import makes the plain env vars work exactly as the
spec assumes. Verified, minimal reproduction:

```
$ mkdir -p /tmp/fixture_root/env
$ python3 -c "
import os
os.environ['SITE_ROOT']='/tmp/fixture_root'
os.environ['REDIS_HOST']='127.0.0.1'; os.environ['REDIS_PORT']='16399'; os.environ['SESSION_DB']='3'
import navconfig; print(navconfig.SITE_ROOT, navconfig.BASE_DIR)
import navigator_session.conf as c
print(c.REDIS_HOST, c.REDIS_PORT, c.REDIS_SESSION_DB, c.SESSION_URL)
"
/tmp/fixture_root /tmp/fixture_root
127.0.0.1 16399 3 redis://127.0.0.1:16399/3
```

Spike 2 used exactly this recipe (`SITE_ROOT=/tmp/.../fixture_root` with a
bare `env/` subdirectory, `REDIS_HOST=127.0.0.1`, `REDIS_PORT=16399`,
`SESSION_DB=0`, all set before any `navconfig`/`navigator_session`/`parrot`
import) and `navigator_session.conf.SESSION_URL` resolved to
`redis://127.0.0.1:16399/0` — the disposable container, never the operator's
Redis — with **no monkeypatch of any kind**.

---

## 3. Q — Synthetic user payload, protected fixture checks, real BotManager route, anonymous/invalid-cookie denial

**Verdict: PASS for anonymous denial and the cookie round trip; PASS with an
important, concrete caveat for "protected route works with this identity";
BLOCKED-adjacent finding for invalid-cookie denial (denial itself works only
if the caller wraps `get_session()` — unwrapped, it is a 500, not a 401).**

### 3.1 Frozen synthetic user payload (for M4/M5 fixtures to reuse verbatim)

```python
synthetic_user = {"user_id": "e2e-test-user-3518", "email": "e2e-3518@test.local"}
identity = "e2e-test-user-3518"   # used as navigator_session's SESSION_KEY ('id') value
```

### 3.2 Real BotManager route selected: `BotManager.get_user_bot()`

Per the task's Codebase Contract, the frozen real target is
`parrot.manager.manager.BotManager` (constructed per the contract's exact
minimal-profile signature: `enable_database_bots=False, enable_crews=False,
enable_registry_bots=False, enable_swagger_api=False`). Its
`get_user_bot(request, chatbot_id)` (`manager.py:1090-1141`) is the concrete
method that consumes `navigator_session`:

```python
try:
    session = request.session or await get_session(request)
except AttributeError:
    session = await get_session(request)
if session is None:
    return None
user_id = session.get("user_id")
if not user_id:
    return None
...
bot_model = await self._fetch_user_bot_model(user_id, cid)
```

`_fetch_user_bot_model` (DB lookup, `manager.py:1060+`) is **explicitly
stubbed** in this spike (instance-level replacement returning `None` and
recording its call args) — this is a disclosed scope boundary, not a hidden
monkeypatch of anything session/auth-related: DB access is out of this
task's Scope, and the task's own Codebase Contract requires the minimal
profile to have discovery/database disabled. The `request` object itself is
a **real** `aiohttp.web.Request`, obtained by hitting a real HTTP route
through `aiohttp.test_utils.TestClient` — no hand-rolled dict/fake object is
used anywhere in Spike 2 (the spec's "No monkeypatch, synthetic request
object ... is permitted in the target process" constraint is honored).

### 3.3 Anonymous denial — PASS

```
GET /e2e/protected/bot   (no cookie at all)
-> BotManager.get_user_bot() -> session is None -> returns None
-> route handler falls back to get_session(request, ignore_cookie=False) -> None
-> 401 {"anonymous": true}
```

Confirms **AC4**'s "anonymous protected requests fail."

### 3.4 A real, load-bearing gap: `get_user_bot()`'s own `get_session()` call never reads the cookie

`get_user_bot()` calls the free function `get_session(request)` with **no**
`ignore_cookie` argument — and `get_session()`'s default is
`ignore_cookie=True` (`navigator_session/__init__.py:55-59`). Verified
directly: after a real login (`bootstrap-login`) that issued a real,
valid `csrf_secure` cookie, a **second, separate** `aiohttp.web.Request` for
`GET /e2e/protected/bot` carries that cookie correctly (this repo's
`aiohttp.test_utils.TestClient` cookie jar persists it across requests, and
a route-local `get_session(request, ignore_cookie=False)` call in the same
handler *does* recover `user_id="e2e-test-user-3518"` from Redis via that
cookie) — but `BotManager.get_user_bot()`'s own internal
`get_session(request)` call, with the default `ignore_cookie=True`, **never
attempted to read the cookie at all** and resolved to `session=None` purely
because no `request[SESSION_ID]`/`request[SESSION_KEY]` had been
pre-populated on that fresh Request object by anything upstream. Confirmed
by the recorded side channel: `fetch_calls_after_valid_cookie == []` — the
DB lookup was never reached, `get_user_bot()` returned `None` even though a
perfectly valid session cookie was present and independently verified to
resolve correctly one line later in the same handler.

**Implication for M4 (not resolved here — a design constraint to carry
forward, not a fix applied by this research task):** cookie-based session
auth alone cannot make `get_user_bot()` return a non-`None` result as the
method is coded today. A protected E2E fixture route must itself call
`get_session(request, ignore_cookie=False)` (or otherwise populate
`request[SESSION_KEY]`/`request[SESSION_ID]` from the resolved identity)
**before** delegating to `get_user_bot()`, mirroring how a real
JWT/PBAC-authenticated request would already carry that identity on
`request` by the time `get_user_bot()` runs in production. This is exactly
why the spec frames this as "the protected fixture endpoint validates this
session; **the test then calls** a real BotManager API route" (two
sequential steps) rather than assuming the BotManager route resolves the
cookie by itself.

### 3.5 Invalid-cookie denial — must be explicitly wrapped, or it is a 500, not a 401

Two independent, concrete reproductions:

- **Wrapped (Spike 1's route)**: `get_session(request, ignore_cookie=False)`
  called inside a `try/except RuntimeError` → cleanly mapped to
  `401 {"error": "Error Loading user Session: Parsing Error: Invalid JSON
  data: ..."}`.
- **Unwrapped (Spike 2's route)**: the same call, without a surrounding
  `try/except`, propagates a `RuntimeError` out of the handler → aiohttp's
  default error path → **HTTP 500**, plain-text body (`text/plain`), not a
  clean JSON denial.

Root cause, read directly: `AbstractStorage.load_cookie()`
(`storages/abstract.py:161-167`) calls `self._decoder(cookie)` — a
`datamodel.parsers.json.json_decoder` call — on the raw cookie string with
**no exception handling of its own**; a malformed/tampered cookie value
raises `datamodel.exceptions.ParserError`, which propagates up through
`RedisStorage.load_session()` (uncaught there too) into the free function
`get_session()`, which wraps it as `RuntimeError(f"Error Loading user
Session: {err!s}")` and **re-raises** (`navigator_session/__init__.py:93-98`,
the `if new is True: return await storage.new_session(...)` branch only
applies when the caller explicitly opted into `new=True`).

**Contract for M4**: "invalid cookie is denied" (AC4/spec §2) is true **only
if** the fixture/route code wraps `get_session(..., ignore_cookie=False)` in
`try/except RuntimeError` and maps that to a `401`. This is not automatic —
the library's own behavior on a bad cookie is an unhandled exception, not a
graceful `None`. M4's fixture route (and, per §3.4, any code path that
pre-populates identity before calling `get_user_bot()`) must include this
try/except explicitly.

---

## 4. Cross-check (Spike 1, monkeypatch-based, kept only as corroboration)

Run against the same disposable Redis, using `unittest.mock.patch.object`
on `navigator_session.storages.redis.SESSION_URL` and a `dict`-based fake
request for the `BotManager.get_user_bot()` half of the experiment (this
approach is **not** the frozen contract — see §0 — but its outcomes are
consistent with Spike 2 and are kept here only as independent corroboration
of §1.2 and §3.3):

```json
{
  "anonymous_no_cookie_status": 401,
  "login_status": 200,
  "whoami_with_valid_cookie_status": 200,
  "whoami_with_valid_cookie_body": {"user_id": "e2e-test-user-3518"},
  "whoami_with_invalid_cookie_status": 401,
  "get_user_bot_anonymous": null,
  "get_user_bot_authenticated_identity_present": null,
  "get_user_bot_fetch_calls": [["e2e-test-user-3518", "chatbot-x"]]
}
```

Note the last line: when Spike 1 **pre-populated** `request['id']` (the
`SESSION_KEY` value) directly on the fake request object — bypassing the
cookie entirely, simulating an upstream identity middleware — `_fetch_user_bot_model`
**was** called with the correct `user_id`. This corroborates §3.4's
diagnosis from the opposite direction: `get_user_bot()` works correctly once
identity is already on `request`; it is specifically the cookie-to-request
hop that its own `get_session()` call skips by default.

---

## 5. Q — CookieStorage unfinished → BLOCKED, downstream gated

**Verdict: BLOCKED (as expected/required — not a research failure).**
`navigator_session.storages.cookie.CookieStorage` is unimplemented at two
independent levels:

1. **Broken import.** `storages/cookie.py:9-12` does
   `from navigator_session.conf import (SESSION_NAME, SECRET_KEY)` —
   `SECRET_KEY` is **not defined anywhere in `navigator_session/conf.py`**
   (confirmed by reading the full 46-line file; `grep -rn SECRET_KEY` in
   the installed package only finds it inside `cookie.py` itself).
   Reproduced directly:
   ```
   >>> import navigator_session.storages.cookie
   ImportError: cannot import name 'SECRET_KEY' from 'navigator_session.conf'
   ```
   Any code path that imports `navigator_session.storages.cookie` — even
   indirectly — fails immediately, before any of its methods could run.
2. **Stub methods.** Even setting the import error aside, every
   `CookieStorage` method body is a bare `pass` (`new_session`,
   `load_session`, `get_session`, `save_session` — `cookie.py:58-90`); the
   module's own docstring is `"""TODO: Encrypted JSON Cookie Storage."""`.

This matches the spec's own resolved decision verbatim: "Session backend:
private Redis, because installed cookie storage is incomplete" (spec §8).
`SessionHandler(storage=...)` only accepts `"redis"` in this installed
version anyway (`session.py:16-21`, anything else raises
`NotImplementedError`), so there is no live code path to a cookie-only,
service-free session backend today. **This BLOCKED status is final for this
task**: M4 must build against `RedisStorage` only; a cookie-storage
alternative is not a fallback option until `navigator-session` ships a
fixed `CookieStorage` upstream — not something this task, or M4, can
implement by patching the installed dependency.

---

## 6. Selected Contract (frozen, for M4 to build against)

1. **Fixture Redis isolation recipe (verified, minimal)**: before any
   `navconfig`/`navigator_session`/`parrot` import in the target process,
   set `SITE_ROOT=<isolated dir with an env/ subdir>`, `REDIS_HOST`,
   `REDIS_PORT`, `SESSION_DB`. Setting the three Redis vars alone is
   **not** sufficient in this repository — `env/.env`'s checked-in
   `REDIS_HOST=nav-api.dev.local`/`REDIS_PORT=6379` silently wins via
   `Kardex._mapping_` precedence over `os.environ` (kardex.py:509-514)
   unless `SITE_ROOT` is also isolated. Never monkeypatch
   `navigator_session(.conf/.storages.redis).SESSION_URL` directly — it is
   fragile to which submodule already imported the stale copy, and the
   spec explicitly forbids it for the real target process.
2. `SessionHandler(storage=...)` only accepts `"redis"` in this installed
   version — any other value raises `NotImplementedError`
   (`session.py:16-21`); there is no live "service-free" alternative today
   (see item 7 / §5).
3. **Cookie name** is whatever `SESSION_COOKIE_SECURE` resolves to
   (default `"csrf_secure"`) — not an app-chosen name; fixtures/tests that
   assert on `Set-Cookie` must use `navigator_session.conf.SESSION_COOKIE_SECURE`,
   not a literal.
4. `SessionHandler(storage="redis", use_cookies=True, ...)` — `use_cookies`
   defaults to `False` and must be passed explicitly, or no cookie is ever
   set regardless of the storage backend.
5. **`BotManager.get_user_bot()` never reads the session cookie on its
   own** (`get_session(request)` default `ignore_cookie=True`). M4's
   protected-route fixture must call `get_session(request,
   ignore_cookie=False)` itself first and ensure the resolved identity is
   visible to `get_user_bot()` (e.g. by re-populating
   `request[SESSION_KEY]`/`request[SESSION_ID]`) before delegating —
   matching the spec's own two-step framing ("validates this session; the
   test then calls a real BotManager API route").
6. **Invalid-cookie denial requires an explicit `try/except RuntimeError`**
   around any `get_session(..., ignore_cookie=False)` call — the library
   raises on a malformed/tampered cookie rather than returning `None`;
   without the wrapper, the result is an HTTP 500, not the spec-required
   denial.
7. `CookieStorage` is BLOCKED (broken import + stub methods) — build only
   against `RedisStorage`; do not attempt a service-free session path.
8. Frozen synthetic payload for reuse: `{"user_id": "e2e-test-user-3518",
   "email": "e2e-3518@test.local"}`, identity key value
   `"e2e-test-user-3518"`.
9. The harness must never issue `FLUSHDB`/`FLUSHALL`/key-scan against the
   operator's shared Redis — verified compatible with the recipe in item 1,
   since the isolated `SITE_ROOT` + explicit `REDIS_HOST`/`REDIS_PORT`
   point exclusively at a disposable, private instance.

## 7. Rejected Assumptions

- Rejected: that setting `REDIS_HOST`/`REDIS_PORT`/`SESSION_DB` via
  `os.environ` before import is sufficient by itself, as the spec's prose
  literally reads — verified false in this repo; `env/.env`'s checked-in
  values win via `Kardex._mapping_` precedence unless `SITE_ROOT` is also
  isolated.
- Rejected: that `navconfig` resolves its project root from the process's
  `cwd` — verified it instead resolves via `Path(sys.prefix).resolve().parent`
  (the active virtualenv's parent) when no `SITE_ROOT` is set, independent
  of the target subprocess's working directory.
- Rejected: that a valid session cookie is sufficient for
  `BotManager.get_user_bot()` to resolve an authenticated user — verified
  false; its own `get_session()` call defaults to `ignore_cookie=True` and
  never inspects the cookie unless the caller pre-populates
  `request[SESSION_KEY]`/`request[SESSION_ID]`.
- Rejected: that an invalid/tampered session cookie is denied gracefully
  by `navigator_session` itself — verified it raises an unhandled
  `RuntimeError` (wrapping a JSON parse error) that the caller must
  explicitly catch to produce a clean denial.
- Rejected: that `CookieStorage` is merely incomplete but importable —
  verified it fails to import at all (`SECRET_KEY` undefined in
  `navigator_session.conf`), on top of every method being a `pass` stub.

## 8. BLOCKED Items

- `CookieStorage`/service-free session storage: **BLOCKED**, confirmed
  final for this installed `navigator-session` version (§5). Any future
  task that needs a cookie-only, Redis-free session backend is gated on an
  upstream fix to `navigator-session`, not on work this repository can do
  itself.

No other required question in this task's Scope was blocked — the
disposable-Redis, real-`BotManager`, real-request round trip is fully
reproducible end-to-end today.

## 9. Acceptance Criteria Mapping

- **AC4** ("Minimal BotManager uses real isolated Redis sessions; required
  missing service is BLOCKED and anonymous protected requests fail."):
  supported — §1.2/§2.3 demonstrate a real isolated Redis session round
  trip (never the operator's shared instance); §3.3 demonstrates anonymous
  denial; §5 demonstrates the "required missing service" (cookie storage)
  correctly reports BLOCKED rather than silently degrading. The
  `redis-server` binary itself was absent on this host (§0) — the M4
  adapter's own "missing redis-server blocks required authenticated
  scenarios" behavior (spec §2 line 263-264) was not separately exercised
  here (no adapter exists yet to test); this spike used a disposable
  Docker container as the available substitute, consistent with "record
  ... private Redis argv and clean shutdown" in this task's Scope.
- **AC17** (focused tests, ruff/black clean, no `clients/base.py`
  modification): this task modified no runtime Python — its only file is
  this research document; the required validation command (§10) passes
  unmodified.

## 10. Validation Commands Run

```bash
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src \
  python3 -m pytest packages/ai-parrot-server/tests/test_tools_list_route.py -q
```

Result: `4 passed, 8 warnings in 4.24s` — existing test file, unmodified by
this task, confirming the spike's real-`BotManager`/real-Redis experiments
above did not regress this route's existing coverage. (Note en route: this
file's own `test_tools_list_get_route_reachable` monkeypatches
`navigator_auth.decorators.get_session` — a **different** package
(`navigator_auth`, not `navigator_session`) used by `@user_session()`
-decorated routes like `ToolList`. That is a separate authentication
mechanism from the `navigator_session`-based one this research verifies;
`BotManager.get_user_bot()` — this task's frozen "real BotManager route"
per the Codebase Contract — uses `navigator_session`, not `navigator_auth`.
Recorded here so M4 does not conflate the two when picking its "selected
real API route.")

## 11. Artifacts

Raw script sources and outputs are reproduced verbatim/sanitized inline in
§1-§4 above (this repo's ephemeral `/tmp` sandboxing does not persist
scratch files across tool invocations, so no `artifacts/logs/` path is
referenced — nothing was silently dropped; every command and its full,
unedited output is embedded in this report). Docker container names used
(all stopped/auto-removed via `--rm`, none left running):
`spike-redis-3518`, `spike-redis-3518b` .. `spike-redis-3518f`.
