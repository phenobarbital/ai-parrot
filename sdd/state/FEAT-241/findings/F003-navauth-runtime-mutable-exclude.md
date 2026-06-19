---
id: F003
query_id: Q009
type: read
intent: How AuthHandler seeds/evaluates/mutates the per-app exclude list
executed_at: 2026-06-16T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F003 — Per-app exclude list is ALREADY runtime-mutable + request-time-evaluated

## Summary

The crux finding. `AuthHandler.setup()` seeds `app["auth_exclude_list"]` as a
**mutable `list`** (not frozen). All exemption checks read it at **request time**
via `request.app.get(AUTH_EXCLUDE_LIST_KEY, ())` + `fnmatch`, in three places:
`verify_exceptions` (basic/jwt auth_middleware), `abac/middleware`, and
`backends/abstract`. `add_exclude_list(path)` appends at runtime. There is **NO
removal method** (grep for `remove_exclude`/`discard` → none). The mutable-list
design landed 2026-04-02 (commit `27b478b`, "new pbac implementation"); the comment
says "avoids global mutation" — i.e. this replaced an earlier frozen/global design.

## Citations

- path: `../navigator-auth/navigator_auth/auth.py`
  lines: 534-537
  symbol: `AuthHandler.setup`
  excerpt: |
    # Seed the per-app exclude list from defaults (avoids global mutation)
    self.app[AUTH_EXCLUDE_LIST_KEY] = list(exclude_list)
    self.app[self.name] = self      # self.name defaults to "auth"

- path: `../navigator-auth/navigator_auth/auth.py`
  lines: 666-677
  symbol: `add_exclude_list` / `verify_exceptions`
  excerpt: |
    def add_exclude_list(self, path: str):
        self.app[AUTH_EXCLUDE_LIST_KEY].append(path)
    async def verify_exceptions(self, request):
        for pattern in request.app.get(AUTH_EXCLUDE_LIST_KEY, ()):
            if fnmatch.fnmatch(request.path, pattern):
                return True

- path: `../navigator-auth/navigator_auth/abac/middleware.py`
  lines: 33-36
  symbol: `abac exclude check`
  excerpt: |
    for pattern in request.app.get(AUTH_EXCLUDE_LIST_KEY, ()):
        if fnmatch.fnmatch(request.path, pattern):
            return await handler(request)

- path: `../navigator-auth/navigator_auth/backends/abstract.py`
  lines: 367
  symbol: `backend exclude check`

## Notes

AuthHandler is registered at `app["auth"]` (constructor `app_name="auth"`, auth.py:69).
A consumer reaches it via `request.app["auth"].add_exclude_list(path)`.
Gap: a `remove_exclude_list(path)` is required for `is_public=False`.
