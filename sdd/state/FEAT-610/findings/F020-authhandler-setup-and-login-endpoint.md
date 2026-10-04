---
id: F020
query_id: Q020
type: read
intent: How navigator-auth AuthHandler is constructed/set up and which login routes it registers
executed_at: 2026-09-28T18:23:00Z
parent_id: null
depth: 0
---
# F020 — AuthHandler setup, constructor knobs, and /api/v1/login routes
## Summary
`from navigator_auth import AuthHandler`; `AuthHandler(...).setup(app)` accepts a raw aiohttp `web.Application` or a navigator app. The constructor takes `secure_cookies`, `enable_authdb` (skip the Postgres `authdb` pool) and `backends=[dotted paths]` (overrides the `AUTHENTICATION_BACKENDS` setting, explicitly "for the bundled examples"). `setup()` ALWAYS configures a Redis storage (`REDIS_AUTH_URL`, falls back to `REDIS_URL`) plus a redis-backed `SessionHandler`, and registers GET/POST `/api/v1/login`, `/api/v1/logout`, `/api/v1/auth/token` (refresh), `/api/v1/user/session`. Login picks the backend from the `X-Auth-Method` header (e.g. `BasicAuth`), else tries every backend in order.
## Citations
- path: `venv:navigator_auth/auth.py`
  lines: 87-126
  symbol: `AuthHandler.__init__`
  excerpt: |
    def __init__(self, app_name="auth", secure_cookies=True,
                 enable_authdb=True, backends=None, authz_backends=None, **kwargs)
    ...
    enable_authdb: when False, the PostgreSQL ``authdb`` pool is not configured ...
    backends: explicit list of dotted paths to the authentication
        backends to enable, overriding ``AUTHENTICATION_BACKENDS``.
- path: `venv:navigator_auth/auth.py`
  lines: 638-695
  symbol: `AuthHandler.setup`
  excerpt: |
    redis = RedisStorage(driver="redis", dsn=REDIS_AUTH_URL)
    redis.configure(self.app)
    if self.enable_authdb:
        pool = PostgresStorage(driver="pg", dsn=default_dsn)
    ...
    router.add_route("GET", "/api/v1/login", self.api_login, name="api_login")
    router.add_route("POST", "/api/v1/login", self.api_login, name="api_login_post")
    router.add_route("POST", "/api/v1/auth/token", self.api_refresh_token, ...)
    router.add_route("GET", "/api/v1/user/session", self.get_session, ...)
- path: `venv:navigator_auth/auth.py`
  lines: 337-343
  symbol: `AuthHandler.get_auth_backend`
  excerpt: |
    if method := request.headers.get("X-Auth-Method", None):
        return self.backends[method]
- path: `venv:navigator_auth/conf.py`
  lines: 62-73
  symbol: `EXCLUDE_DEFAULTS`
  excerpt: |
    EXCLUDE_DEFAULTS = ["/static/", "/api/v1/login", "/api/v1/logout", ...]
    _extra_excluded = [... config.get("ROUTES_EXCLUDED", fallback="") ...]
## Implications
- server.py should call `AuthHandler(backends=[...], enable_authdb=<bool>)` explicitly so the example does not depend on repo `settings/settings.py` (which enables AzureAuth+BasicAuth+NoAuth, settings.py:47-58).
- Redis is a hard dependency of AuthHandler (session storage) — the example cannot be Redis-free.
- Public pages (`/`, `/static/...`, client HTML) must be added via `auth.add_exclude_list(path)` or `app["auth_exclude_list"].extend([...])`; `/static/` is excluded by default.
