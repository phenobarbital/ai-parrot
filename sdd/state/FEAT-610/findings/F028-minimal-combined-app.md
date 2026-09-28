---
id: F028
query_id: Q025
type: read
intent: Minimal app that mounts QuerySource + AuthHandler + BotManager together without breaking
executed_at: 2026-09-28T18:23:00Z
parent_id: F027
depth: 1
---
# F028 — Minimal combined wiring: order, shared Redis, exclusions, and infra floor
## Summary
Only `app.py` mounts all three together; its order (QuerySource → [PBAC] → BotManager.setup → AuthHandler.setup) is the proven one. BotManager publishes a lazy `app["redis"]` (`redis.asyncio.from_url(REDIS_URL)`) idempotently, which navigator-auth's `/api/v1/auth/token` refresh reads from `request.app.get("redis")`. AuthHandler's middleware protects every route not in `app["auth_exclude_list"]`, so the index page and any public route must be excluded explicitly; `/static/` and `/api/v1/login` are excluded by default. Infra floor: Redis always (auth sessions); Postgres whenever BasicAuth, QuerySource DB-backed slugs, or `/api/v1/ui/surfaces` are used.
## Citations
- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 1606-1631
  symbol: `BotManager._register_shared_redis`
  excerpt: |
    existing = self.app.get("redis")
    if existing is not None:
        self._redis_owned = False
        return
    self.app["redis"] = aioredis.from_url(REDIS_URL, decode_responses=True)
- path: `venv:navigator_auth/auth.py`
  lines: 396-412
  symbol: `AuthHandler.api_refresh_token`
  excerpt: |
    redis = request.app.get("redis")
    if not redis:
        raise web.HTTPInternalServerError(reason="Redis configuration missing")
- path: `venv:navigator_auth/auth.py`
  lines: 1046-1075
  symbol: `AuthHandler._auth_middleware`
  excerpt: |
    if await self.verify_exceptions(request):
        ...best-effort token decode...
        return await handler(request)
    token = await self._idp.get_payload(request)
    _, payload = self._idp.decode_token(code=token)
- path: `venv:navigator_auth/auth.py`
  lines: 839
  symbol: `AuthHandler.add_exclude_list`
  excerpt: |
    def add_exclude_list(self, path: str) -> None:
## Implications
- Sketch: `app = web.Application(); QuerySource(lazy=False).setup(app); bm = BotManager(enable_database_bots=False, enable_registry_bots=False); bm.setup(app); auth = AuthHandler(backends=[...], enable_authdb=...); auth.setup(app); auth.add_exclude_list("/")` + on_startup: configure agent, `bm.add_agent(agent)`.
- PBAC (`setup_pbac`) is optional; without it AgentTalk is allowed (`agent.py` post docstring: "If PBAC is not configured, access is allowed").
- Whether `QuerySource.setup` works on a plain `web.Application` (vs navigator BaseApplication) is lane B's call; querysource/services.py:131-135 accepts both `BaseApplication` and `WebApp`.
