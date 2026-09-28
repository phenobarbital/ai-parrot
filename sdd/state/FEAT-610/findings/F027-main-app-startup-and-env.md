---
id: F027
query_id: Q025
type: read
intent: How the main app is started (run.py/app.py, navigator Application) and required env
executed_at: 2026-09-28T18:23:00Z
parent_id: null
depth: 0
---
# F027 — run.py → navigator Application(Main); Main.configure mounts QuerySource → BotManager → AuthHandler
## Summary
`run.py` does `app = Application(Main, enable_jinja2=True)` (navigator) and `app.run()`; `Main` (`app.py`) is a `navigator.handlers.types.AppHandler` with `enable_pgpool=True`. In `configure()` the order is: `QuerySource(lazy=False).setup(self.app)`, `BotManager(enable_database_bots=True)`, `setup_pbac(...)` BEFORE `bot_manager.setup(app)`, many handlers, then `AuthHandler().setup(app)`. Importing parrot/navigator triggers navconfig, which loads `settings/settings.py` and `env/<ENV>/.env` (dirs: env/dev, env/local, env/prod…); env/dev/.env defines `AUTH_SECRET_KEY`, `DBHOST/DBNAME/DBUSER`. BotManager flags default from parrot.conf: ENABLE_DATABASE_BOTS=False, ENABLE_CREWS=False, ENABLE_REGISTRY_BOTS=True, ENABLE_SWAGGER=False.
## Citations
- path: `run.py`
  lines: 7-12
  symbol: `-`
  excerpt: |
    from navigator import Application
    from app import Main
    app = Application(Main, enable_jinja2=True)
- path: `app.py`
  lines: 66-73,108-113
  symbol: `Main`
  excerpt: |
    class Main(AppHandler):
        enable_static: bool = True
        enable_pgpool: bool = True
    qry = QuerySource(lazy=False)
    qry.setup(self.app)
    self.bot_manager = BotManager(enable_database_bots=True)
- path: `app.py`
  lines: 334-337
  symbol: `-`
  excerpt: |
    # setup_pbac() MUST be called BEFORE BotManager.setup(app) so that
    # app['abac'] is registered before AgentRegistry.setup(app) reads it.
- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 94-98
  symbol: `ENABLE_*`
  excerpt: |
    ENABLE_SWAGGER = config.getboolean("ENABLE_SWAGGER", fallback=False)
    ENABLE_CREWS = config.getboolean("ENABLE_CREWS", fallback=False)
    ENABLE_DATABASE_BOTS = config.getboolean("ENABLE_DATABASE_BOTS", fallback=False)
    ENABLE_REGISTRY_BOTS = config.getboolean("ENABLE_REGISTRY_BOTS", fallback=True)
- path: `settings/settings.py`
  lines: 47-58
  symbol: `AUTHENTICATION_BACKENDS`
  excerpt: |
    AUTHENTICATION_BACKENDS = (
        'navigator_auth.backends.AzureAuth',
        'navigator_auth.backends.BasicAuth',
        'navigator_auth.backends.NoAuth',
    )
## Implications
- The example can skip navigator `Application`/AppHandler entirely and use plain `web.Application()` + `web.run_app` like examples/forms/form_server.py — the existing precedent for AuthHandler+aiohttp.
- navconfig side effects still apply (import chdirs to repo root and reads settings/ + env/); the example README must list: Redis (`REDIS_URL`), `AUTH_SECRET_KEY`, Postgres DSN (auth.vw_users for BasicAuth, QS datasource, PgUISurfaceStore), LLM key if --live.
- Setting `enable_registry_bots=False` avoids loading every registry/agents-dir agent at startup in the example.
