---
id: F002
query_id: Q001
type: read
intent: How navigator-auth declares the exclude list seed + app key
executed_at: 2026-06-16T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F002 — Exclude-list configuration (`auth_exclude_list` app key)

## Summary

`conf.py` defines the per-app exclude-list app key and its default seed. There is
NO `frozenset` literal anywhere in `navigator_auth` (grep returned zero). The seed
is a plain `list`; extra patterns come from the `ROUTES_EXCLUDED` env var.

## Citations

- path: `../navigator-auth/navigator_auth/conf.py`
  lines: 44-58
  symbol: `AUTH_EXCLUDE_LIST_KEY`
  excerpt: |
    AUTH_EXCLUDE_LIST_KEY = "auth_exclude_list"
    EXCLUDE_DEFAULTS: list[str] = [
        "/static/", "/api/v1/login", "/api/v1/logout",
        "/api/v1/forgot-password", "/api/v1/reset-password",
    ]
    _extra_excluded = [e.strip() for e in config.get("ROUTES_EXCLUDED", fallback="").split(",")]
    exclude_list = EXCLUDE_DEFAULTS + [e for e in _extra_excluded if e]

## Notes

`grep -rniE 'frozenset' navigator_auth` → no matches. The source's "frozenset"
premise does not match the current code; see F003 for the mutable-list refactor.
