---
id: F029
query_id: Q043
type: read
intent: "Server-side session identity resolution"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-029]
---

# F029 — resolve_user_id: Identity.id is the only field every navigator-auth backend sets; coerced to str

## Summary

`parrot.auth.session_identity.resolve_user_id(request, session)` resolves the authenticated user's id backend-independently: `request.user`/`request["user"]` → `Identity.id` (int PK for DB users, string for token/external identities), then `AUTH_USERID_ATTRIBUTE` in the session, then nested under `AUTH_SESSION_OBJECT`. Returns `str` or None (fail-open to None).

## Citations

- path: `packages/ai-parrot/src/parrot/auth/session_identity.py`
  lines: 11-17, 35, 90-133
  symbol: `module docstring / _IDENTITY_ID_ATTRS / resolve_user_id`
  excerpt: |
    The one field EVERY backend populates is ``Identity.id`` ... an ``int`` primary key for DB-backed users, a string for token/external identities
    _IDENTITY_ID_ATTRS = ("id", "user_id", "userid", "object_id", "upn", "username")
    def resolve_user_id(request: Any, session: Any = None) -> str | None:

## Notes

Whatever endpoint S-4 adds for CLI login/token exchange gets the Navigator user_id through this helper (S-1 `WebPrincipalResolver` presumably uses it).
