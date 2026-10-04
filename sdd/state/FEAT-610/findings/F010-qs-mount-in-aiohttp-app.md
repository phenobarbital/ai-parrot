---
id: F010
query_id: Q010
type: read
intent: How ai-parrot mounts QuerySource into an aiohttp app today
executed_at: 2026-09-28T20:30:00Z
parent_id: null
depth: 0
---
# F010 — QuerySource is mounted with `QuerySource(lazy=False).setup(app)`; no parrot-side helper exists
## Summary
The only in-repo mounting of the QuerySource *service* is the root `app.py` (navigator `AppHandler`), which does `qry = QuerySource(lazy=False); qry.setup(self.app)` right before `BotManager.setup()`. There is no parrot/ai-parrot-server helper wrapping it; `QuerySource` is a `Singleton` from `querysource.services` whose `setup()` accepts either a navigator `BaseApplication` or a plain `aiohttp.web.Application` (`navigator.types.WebApp` resolves to `aiohttp.web_app.Application`), registers ~60 routes, and appends `qs_start`/`qs_stop` to on_startup/on_shutdown. So a self-contained example can mount it on a bare `web.Application()` in two lines.
## Citations
- path: `app.py`
  lines: 7, 108-113
  symbol: `Main.configure`
  excerpt: |
    from querysource.services import QuerySource
    ...
    # Loading QUerySource
    qry = QuerySource(lazy=False)
    qry.setup(self.app)
    # Chatbot System
    self.bot_manager = BotManager(enable_database_bots=True)
- path: `venv:querysource/services.py`
  lines: 65, 131-140
  symbol: `QuerySource.setup`
  excerpt: |
    class QuerySource(metaclass=Singleton):
    ...
    def setup(self, app: web.Application) -> web.Application:
        if isinstance(app, BaseApplication):  # migrate to BaseApplication (on types)
            self.app = app.get_app()
        elif isinstance(app, WebApp):
            self.app = app  # register the app into the Extension
        # register the Connection Object:
        self.connection.setup(app=app)
- path: `venv:querysource/services.py`
  lines: 402-408
  symbol: `QuerySource.setup`
  excerpt: |
    ### Startup Event for QuerySource:
    self.app.on_startup.append(
        self.qs_start
    )
    self.app.on_shutdown.append(
        self.qs_stop
    )
## Implications
- `examples/a2ui/server.py` can do `app = web.Application(); QuerySource(lazy=False).setup(app)` — no navigator `Application`/`AppHandler` needed (precedent for bare aiohttp + AuthHandler: `examples/forms/form_server.py`, see F015).
- `QuerySource` is a process-wide Singleton; construct it once. Importing `querysource` imports `navconfig`, which loads `env/.env` + `settings/` of the ai-parrot checkout.
