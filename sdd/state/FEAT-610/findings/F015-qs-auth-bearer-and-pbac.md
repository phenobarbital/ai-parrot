---
id: F015
query_id: Q015
type: read
intent: Does the QS slug handler require navigator-auth session/bearer, and how is the token read?
executed_at: 2026-09-28T20:30:00Z
parent_id: null
depth: 0
---
# F015 — QS routes carry no auth decorator; protection comes from the app-wide navigator-auth middleware (Bearer JWT → session), plus optional QS PBAC (enabled in this repo's env)
## Summary
`QueryService.query` has no `@is_authenticated`-style decorator; any authentication is enforced by `navigator_auth.AuthHandler`'s middleware once `AuthHandler().setup(app)` is called: every non-excluded path must present `Authorization: Bearer <jwt>` (also accepted: `auth` query param / `X-Token` header per the token strategies) or a session cookie; the middleware decodes the JWT (`_idp.get_payload` + `decode_token`) and loads/recreates the navigator-session from the payload. Inside QS, `_enforce_pbac` is a no-op unless `app['security']` exists; `QuerySource.setup()` only bootstraps PBAC when `QS_PBAC_ENABLED` is true, and then `slug:execute`, `datasource:use`, `driver:use` are evaluated fail-closed (no session → 404) against YAML policies in `QS_POLICY_PATH`. The ai-parrot `env/.env` sets `QS_PBAC_ENABLED=true` (line 727).
## Citations
- path: `venv:navigator_auth/auth.py`
  lines: 1055-1075
  symbol: `AuthHandler._auth_middleware`
  excerpt: |
    if await self.verify_exceptions(request):
        # Still attempt authentication if a token is present,
    ...
    self.logger.debug(":: AUTH MIDDLEWARE ::")
    try:
        token = await self._idp.get_payload(request)
        _, payload = self._idp.decode_token(code=token)
- path: `venv:navigator_auth/middlewares/strategies.py`
  lines: 105-118
  symbol: `-`
  excerpt: |
    """Extract from Authorization header, auth query, or X-Token header. No validation.
    ...
    if "Authorization" in request.headers:
        scheme, token = request.headers["Authorization"].strip().split(" ", 1)
- path: `venv:querysource/handlers/abstract.py`
  lines: 346-348
  symbol: `AbstractHandler._enforce_pbac`
  excerpt: |
    guardian = request.app.get('security')
    if guardian is None:
        return  # PBAC disabled — fast-path no-op
- path: `venv:querysource/services.py`
  lines: 146-152
  symbol: `QuerySource.setup`
  excerpt: |
    if QS_PBAC_ENABLED:
        _pdp, _evaluator, _guardian = setup_pbac(
            self.app,
            policy_dir=QS_POLICY_PATH,
            cache_ttl=QS_PBAC_CACHE_TTL,
        )
- path: `venv:querysource/conf.py`
  lines: 441-442
  symbol: `QS_PBAC_ENABLED`
  excerpt: |
    QS_PBAC_ENABLED = config.getboolean('QS_PBAC_ENABLED', fallback=False)
    QS_POLICY_PATH = config.get('QS_POLICY_PATH', fallback=str(BASE_DIR / 'policies'))
## Implications
- The browser client just sends `Authorization: Bearer <token>` (token from `POST /api/v1/login`, lanes F020-F022) on every QS fetch; same-origin serving avoids CORS.
- With `QS_PBAC_ENABLED=true` the demo user also needs a policy allowing `slug:execute` on `polestar_graduates_directory` (+ `datasource:use`/`driver:use`) or refreshes return 404; the example should either document/ship a policy dir or set `QS_PBAC_ENABLED=false` for the demo process. Note `app['security']` may also be set by parrot's own `setup_pbac` (app.py imports `parrot.auth.pbac.setup_pbac`) — sharing one guardian is an open question.
