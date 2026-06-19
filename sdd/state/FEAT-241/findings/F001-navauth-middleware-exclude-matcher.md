---
id: F001
query_id: Q002
type: read
intent: Locate the navigator-auth middleware path-exemption check
executed_at: 2026-06-16T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F001 — Base middleware exclusion matcher (per-middleware frozen tuple)

## Summary

`base_middleware` defines the per-middleware exemption logic. `exclude_routes`
is a **class-level `tuple`** (immutable, set at middleware init). `excluding_routes()`
matches `request.path` against each pattern with `fnmatch.fnmatch` (glob support).
`valid_routes()` short-circuits auth when the path is in the exclude list, is an
OPTIONS request, a SystemRoute (404), or static. This is one of TWO exclusion
mechanisms (the other is the per-app list, F003).

## Citations

- path: `../navigator-auth/navigator_auth/middlewares/abstract.py`
  lines: 13-25
  symbol: `base_middleware`
  excerpt: |
    class base_middleware(ABC):
        anonymous_routes: list = ["/login", "logout", "/static/", ...]
        check_static: bool = True
        exclude_routes: tuple = tuple()
        protected_routes: tuple = tuple()

- path: `../navigator-auth/navigator_auth/middlewares/abstract.py`
  lines: 46-50
  symbol: `excluding_routes`
  excerpt: |
    def excluding_routes(self, request: web.Request):
        for path in self.exclude_routes:
            if fnmatch.fnmatch(request.path, path):
                return True
        return False

- path: `../navigator-auth/navigator_auth/middlewares/abstract.py`
  lines: 57-71
  symbol: `valid_routes`

## Notes

The jwt/token middlewares set `self.exclude_routes` from
`config.get("EXCLUDED_ROUTES", tuple())` at init — this is the "frozen" tuple the
source refers to. It is NOT the right hook for runtime mutation; the per-app list
(F003) is.
