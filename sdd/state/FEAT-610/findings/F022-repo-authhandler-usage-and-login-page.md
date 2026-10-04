---
id: F022
query_id: Q020
type: grep
intent: Existing repo usage of AuthHandler and an in-repo login page storing the JWT in localStorage
executed_at: 2026-09-28T18:23:00Z
parent_id: null
depth: 0
---
# F022 — Repo usage: app.py, examples/forms/form_server.py, and the admin_login_page localStorage pattern
## Summary
Root `app.py` builds `AuthHandler()` and `auth.setup(self.app)` LAST in `Main.configure()` (after QuerySource and BotManager), then adds exclusions via `auth.add_exclude_list(...)`. `examples/forms/form_server.py` (tracked) is the closest precedent: plain `web.Application()`, `AuthHandler().setup(app)`, `app["auth_exclude_list"].extend(["/admin","/",...])`, and a login page `parrot.autonomous.admin.admin_login_page` that POSTs `/api/v1/login` with `X-Auth-Method: BasicAuth` and stores `ai_parrot_token` / `ai_parrot_session` in localStorage. Other users: examples/autonomous/quickstart.py and examples/advisors/voice.py (both untracked/gitignored).
## Citations
- path: `app.py`
  lines: 294-305
  symbol: `Main.configure`
  excerpt: |
    auth = AuthHandler()
    auth.setup(self.app)  # configure this Auth system into App.
    auth.add_exclude_list('/api/docs*')
    auth.add_exclude_list('/api/v1/artifacts/public/*')
- path: `examples/forms/form_server.py`
  lines: 49-70
  symbol: `create_app`
  excerpt: |
    app = web.Application()
    app.router.add_get("/admin", admin_login_page)
    auth = AuthHandler()
    auth.setup(app)
    app["auth_exclude_list"].extend([
        "/admin", "/", "/gallery", "/forms/*",
    ])
- path: `packages/ai-parrot-server/src/parrot/autonomous/admin.py`
  lines: 251-336
  symbol: `admin_login_page`
  excerpt: |
    localStorage.setItem('ai_parrot_token', data.token);
    localStorage.setItem('ai_parrot_session', JSON.stringify(data));
    const resp = await fetch('/api/v1/login', { method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-Auth-Method': 'BasicAuth'},
        body: JSON.stringify({ username, password }) });
## Implications
- Reuse the `ai_parrot_token` localStorage key and the `X-Auth-Method: BasicAuth` login call convention in the static client for consistency.
- `admin_login_page` could even be mounted directly as the example's login page (it is an aiohttp handler in ai-parrot-server).
