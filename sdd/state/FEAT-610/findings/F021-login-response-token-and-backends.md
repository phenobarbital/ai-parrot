---
id: F021
query_id: Q020
type: read
intent: Login payload/response shape and which backends need a DB (is there a no-DB option?)
executed_at: 2026-09-28T18:23:00Z
parent_id: null
depth: 0
---
# F021 — BasicAuth needs auth DB; NoAuth is the only storage-less built-in; response carries "token"
## Summary
BasicAuth reads credentials from JSON / form / GET query (`username`/`password` attrs) and validates via `IdentityProvider.get_user`, which queries `app["authdb"]` (Postgres, `AUTH_DB_SCHEMA`=auth, `AUTH_USERS_VIEW`=vw_users) and checks a Django-style `algo$iter$salt$hash` password. The login response is JSON `{"token": <JWT>, **userdata}` (BasicAuth) or `{"token","refresh_token",session,...}` (NoAuth). `NoAuth` (`navigator_auth.backends.NoAuth`) needs no DB: it issues an anonymous Guest JWT on any login call. JWTs are signed with `AUTH_SECRET_KEY` (`JWT_ALGORITHM` default HS256); the middleware decodes Bearer tokens and rebuilds the Redis session if missing.
## Citations
- path: `venv:navigator_auth/backends/basic.py`
  lines: 87-106
  symbol: `BasicAuth.validate_user`
  excerpt: |
    user = await self._idp.get_user(login)
    pwd = user[self.pwd_atrribute]
    if self._idp.check_password(pwd, password, login=login):
        return user
- path: `venv:navigator_auth/backends/idp/__init__.py`
  lines: 146-154
  symbol: `IdentityProvider.get_user`
  excerpt: |
    db = self.app["authdb"]
    async with await db.acquire() as conn:
        search = {self.username_attribute: login}
        user = await self.user_search.get(**search)
- path: `venv:navigator_auth/backends/basic.py`
  lines: 290
  symbol: `BasicAuth.open_session`
  excerpt: |
    return {"token": token, **userdata}
- path: `venv:navigator_auth/backends/noauth.py`
  lines: 20-31,52-75
  symbol: `NoAuth`
  excerpt: |
    class NoAuth(BaseAuthBackend):
        async def check_credentials(self, request):
            return True
    ...
        token, refresh_token, exp, scheme = self._idp.create_token(data=payload, expiration=3600)
        return {"token": token, "refresh_token": refresh_token, ...}
- path: `venv:navigator_auth/conf.py`
  lines: 32-34,333-346
  symbol: `AUTH_DB_SCHEMA / SECRET_KEY`
  excerpt: |
    AUTH_DB_SCHEMA = config.get("AUTH_DB_SCHEMA", fallback="auth")
    AUTH_USERS_VIEW = config.get("AUTH_USERS_VIEW", fallback="vw_users")
    SECRET_KEY = config.get("AUTH_SECRET_KEY")
    AUTH_JWT_ALGORITHM = config.get("JWT_ALGORITHM", fallback="HS256")
## Implications
- Real username/password login in the example requires Postgres with `auth.vw_users` (or `AUTH_USERS_VIEW` override) and hashed passwords — i.e. the standard navigator auth DB.
- A zero-DB demo mode can use `backends=["navigator_auth.backends.NoAuth"], enable_authdb=False` (anonymous Guest token); a "demo user" flow would need a custom BaseAuthBackend/IdentityProvider (the `enable_authdb` docstring alludes to "a custom IdentityProvider" in bundled examples, not found in the installed wheel).
- Client JS: `POST /api/v1/login` with `X-Auth-Method: BasicAuth` (or `NoAuth`) and JSON body; read `data.token`; send `Authorization: Bearer <token>` afterwards.
