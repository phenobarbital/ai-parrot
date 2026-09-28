---
id: F023
query_id: Q022
type: read
intent: How ai-parrot-server exposes agents over HTTP and how A2UI output appears in responses
executed_at: 2026-09-28T18:23:00Z
parent_id: null
depth: 0
---
# F023 — BotManager.setup routes; AgentTalk returns a2ui_envelope; ui_surfaces plane is Postgres-backed
## Summary
`from parrot.manager import BotManager`; `BotManager(enable_database_bots=False, enable_crews=False, enable_registry_bots=True, enable_swagger_api=False)` (defaults from parrot.conf). `setup(app)` registers on_startup (`load_bots` → AgentRegistry pipeline), publishes a lazy `app["redis"]` from `REDIS_URL` (unless already set), `app["bot_manager"]`, a FEAT-598 data-plane guard hook, and routes incl. `POST /api/v1/agents/chat/{agent_id}` (AgentTalk), `/api/v1/agents/{agent_id}/a2ui[...]` (A2UIHandler), and the persistent surfaces lane `/api/v1/ui/surfaces[/{surface_id}[/refresh|/share]]`. AgentTalk (`@is_authenticated()`) returns, when `output_mode == a2ui`, JSON `{input, output, output_mode:"a2ui", a2ui_envelope, artifact_id, metadata}`. `UISurfacesHandler` lazily builds `PgUISurfaceStore()` on `parrot.conf.default_dsn` — surface URLs need Postgres.
## Citations
- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 193-199
  symbol: `BotManager.__init__`
  excerpt: |
    def __init__(self, enable_database_bots: bool = ENABLE_DATABASE_BOTS,
                 enable_crews: bool = ENABLE_CREWS,
                 enable_registry_bots: bool = ENABLE_REGISTRY_BOTS,
                 enable_swagger_api: bool = ENABLE_SWAGGER) -> None:
- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 2283-2338
  symbol: `BotManager.setup`
  excerpt: |
    self._register_shared_redis()
    self.app["bot_manager"] = self
    self.app.on_startup.append(self._setup_dataplane_guard)
    router.add_view("/api/v1/agents/chat/{agent_id}", AgentTalk)
    router.add_view("/api/v1/agents/{agent_id}/a2ui", A2UIHandler)
    router.add_view("/api/v1/ui/surfaces/{surface_id}", UISurfacesHandler)
    router.add_view("/api/v1/ui/surfaces/{surface_id}/refresh", UISurfacesHandler)
- path: `packages/ai-parrot-server/src/parrot/handlers/agent.py`
  lines: 2800-2822
  symbol: `AgentTalk`
  excerpt: |
    if getattr(response, "output_mode", None) == OutputMode.A2UI:
        return self.json_response({
            "output_mode": OutputMode.A2UI.value,
            "a2ui_envelope": getattr(response, "a2ui_envelope", None),
            "artifact_id": getattr(response, "artifact_id", None),
            "metadata": a2ui_metadata})
- path: `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py`
  lines: 330-336
  symbol: `UISurfacesHandler.store`
  excerpt: |
    store = self.request.app.get("ui_surfaces_store")
    if store is None:
        store = PgUISurfaceStore()
- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 738-742,1179-1181
  symbol: `BotManager.add_bot / add_agent`
  excerpt: |
    def add_bot(self, bot): self._bots[bot.name] = bot
    def add_agent(self, agent): self._bots[str(agent.chatbot_id)] = agent
## Implications
- Minimal wiring: `bm = BotManager(enable_database_bots=False, enable_crews=False, enable_registry_bots=False); bm.setup(app)` then `bm.add_agent(agent)` from an on_startup hook after `await agent.configure()` (whether get_bot auto-configures a manually added bot is UNVERIFIED).
- If the example serves "the surface URL" via `/api/v1/ui/surfaces/{id}`, it needs Postgres (default_dsn) — or server.py can serve its own surface JSON route instead.
- BotManager already provides `app["redis"]` which navigator-auth refresh-token rotation reuses (app.py comment + manager.py:2285-2289).
