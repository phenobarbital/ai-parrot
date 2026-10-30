---
id: FC-014
query_id: Q033
type: read
intent: "R1: read PermissionContext / UserSession — channel, user_id, tenant fields."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-014 — PermissionContext = UserSession(user_id, tenant_id, roles, metadata) + request_id + channel + trace_context + extra; build_principal_context() helper

## Summary

`parrot/auth/permission.py` (252 lines). Frozen dataclass `UserSession(user_id: str, tenant_id: str, roles: frozenset[str], metadata: dict)`; `PermissionContext(session, request_id=None, channel: Optional[str]=None, trace_context=None, extra: dict)` with `user_id`/`tenant_id`/`roles` properties. `build_principal_context(principal, channel, tenant_id=None, roles=None)` defaults `tenant_id` to the principal ('no tenant_id resolution exists yet'). No `principal_id`/`nav_user_id` distinct from `user_id`.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/permission.py`
  lines: 21-49
  symbol: `UserSession`
  excerpt: |
    class UserSession:
        user_id: str
        tenant_id: str
        roles: frozenset[str]
        metadata: dict[str, Any]
- path: `packages/ai-parrot/src/parrot/auth/permission.py`
  lines: 81-126
  symbol: `PermissionContext`
  excerpt: |
    class PermissionContext:
        session: UserSession
        request_id: Optional[str] = None
        channel: Optional[str] = None
        trace_context: Optional[TraceContext] = None
        extra: dict[str, Any]
- path: `packages/ai-parrot/src/parrot/auth/permission.py`
  lines: 166-205
  symbol: `build_principal_context`
  excerpt: |
    def build_principal_context(principal: str, *, channel: str, tenant_id: Optional[str] = None, roles=None) -> PermissionContext:
        tenant_id=tenant_id or principal

## Notes

`channel` field exists (TASK-749). Whether `user_id` is the platform principal depends on the channel: Telegram puts the raw telegram_id (FC-056, wrapper.py:1284-1292); web puts the session user_id (FC-048).
