---
id: F004
query_id: Q004
type: read
intent: Does is_authenticated respect the exclude list / allow_anonymous?
executed_at: 2026-06-16T00:00:00Z
duration_ms: 0
parent_id: F003
depth: 1
---

# F004 — Handler-level `is_authenticated` ignores the exclude list (second auth layer)

## Summary

Decisive constraint. `is_authenticated` is a **handler-level decorator** that checks
ONLY `request.get("authenticated", False)`; if false it tries every auth backend and
raises `HTTPUnauthorized` when none succeed. It does NOT consult
`auth_exclude_list`, `allow_anonymous`, or `request.match_info`. So exempting a path
in the per-app exclude list (F003) prevents the *middleware* from 401-ing, but a
handler still wrapped in `is_authenticated` will independently 401 an anonymous
caller. `allow_anonymous` is a separate decorator that sets `request.allow_anonymous
= True` (which `verify_exceptions` honors, auth.py:702) — but it does NOT influence
`is_authenticated`.

## Citations

- path: `../navigator-auth/navigator_auth/decorators.py`
  lines: 144-176
  symbol: `is_authenticated`
  excerpt: |
    async def _wrap(*args, **kwargs):
        request = args[-1]
        if request.get("authenticated", False):
            return await handler(*args, **kwargs)
        else:
            auth = get_auth(app)
            for _, backend in auth.backends.items():
                userdata = await backend.authenticate(request)
                if userdata: break
            if userdata: return await handler(...)
            else: raise web.HTTPUnauthorized(reason="Access Denied")

- path: `../navigator-auth/navigator_auth/decorators.py`
  lines: 42-72
  symbol: `allow_anonymous`
  excerpt: |
    def allow_anonymous(handler):
        # sets request.allow_anonymous = True; honored by verify_exceptions
        setattr(request, "allow_anonymous", True)

## Notes

Implication: making a formdesigner route public requires action at BOTH layers —
the middleware exclude list AND the per-handler decorator. The current `_wrap_auth`
(F005) unconditionally applies `is_authenticated`, so it is the hard blocker.
