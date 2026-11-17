---
id: FC-003
query_id: Q008
type: read
intent: "Read BotManager crew startup load + add_crew/load_crew paths (where rehydration from storage happens)."
executed_at: 2026-11-09T17:19:00Z
duration_ms: 1500
parent_id: null
depth: 0
---

# FC-003 — BotManager crew lifecycle: eager load of ALL tenants at startup, write-through on add/remove, lazy miss-load, sync on list

## Summary

`BotManager.__init__` builds `self.crew_redis = CrewRedis() if self.enable_crews else None` (flag
`ENABLE_CREWS` from config, line 104/230). `on_startup` calls `load_crews()` after `load_bots()`
(3192-3194), which pings Redis and eagerly rehydrates **every crew of every tenant**
(`get_all_crews()` with `tenant=None`) into the in-memory cache `self._crews` keyed `"{tenant}:{name}"`
via `_create_crew_from_definition` → `AgentCrew.from_definition(crew_def, class_resolver=self.get_bot_class,
google_api_key=get_crew_google_api_key())`. `add_crew` caches then write-through `save_crew` (failure
only logged); `get_crew` misses go to `load_crew` then `load_crew_by_id`; `remove_crew` deletes;
`sync_crews` diffs `list_all_crews()` against the cache (called by `CrewHandler.get` before listing).
`update_crew` is memory-only (no persistence). The HTTP `PUT` update path is `get_crew` → `remove_crew`
(Redis delete) → `add_crew` (Redis save), i.e. delete+insert, preserving `crew_id`/`created_at`.
`on_shutdown` closes ChatStorage/ArtifactStore but never closes `crew_redis`.

## Citations

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 227-271
  symbol: `BotManager.__init__`
  excerpt: |
    enable_crews: bool = ENABLE_CREWS,
    ...
    self._crews: Dict[str, Tuple[AgentCrew, CrewDefinition]] = {}
    self.enable_crews: bool = enable_crews
    # Initialize Redis persistence for crews — keyed off instance attr
    self.crew_redis = CrewRedis() if self.enable_crews else None

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 280-287
  symbol: `BotManager._normalize_tenant / _get_crew_key / _split_crew_key`
  excerpt: |
    def _normalize_tenant(tenant): return tenant or "global"
    def _get_crew_key(self, tenant: str, name: str) -> str:
        return f"{tenant}:{name}"

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 3160-3196
  symbol: `BotManager.on_startup`
  excerpt: |
    await self.load_bots(app)
    if self.enable_registry_bots:
        app["bot_config_storage"] = BotConfigStorage()
    # Load crews from Redis
    if self.enable_crews:
        await self.load_crews()

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 3255-3292
  symbol: `BotManager.add_crew`
  excerpt: |
    async def add_crew(self, name: str, crew: AgentCrew, crew_def: CrewDefinition) -> None:
        crew_key = self._get_crew_key(tenant, name)
        if crew_key in self._crews: raise ValueError(f"Crew '{name}' already exists")
        self._crews[crew_key] = (crew, crew_def)
        if self.crew_redis is None: ...; return
        try: await self.crew_redis.save_crew(crew_def)
        except Exception as e: self.logger.error(...)  # memory-only fallback

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 3294-3367
  symbol: `BotManager.get_crew`
  excerpt: |
    async def get_crew(self, identifier: str, as_new: bool = False, tenant: Optional[str] = None)
        -> Optional[Tuple[AgentCrew, CrewDefinition]]:
        # 1. memory by key, then by crew_id
        # 3. If not in memory, try Redis
        crew_def = await self.crew_redis.load_crew(identifier, tenant)
        if not crew_def: crew_def = await self.crew_redis.load_crew_by_id(identifier, tenant)
        base_crew = await self._create_crew_from_definition(crew_def)
        self._crews[cache_key] = (base_crew, crew_def)

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 3383-3429
  symbol: `BotManager.remove_crew`
  excerpt: |
    async def remove_crew(self, identifier: str, tenant: Optional[str] = None) -> bool:
        ... del self._crews[crew_key]
        await self.crew_redis.delete_crew(crew_def.name, crew_def.tenant)

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 3431-3455
  symbol: `BotManager.update_crew`
  excerpt: |
    def update_crew(self, identifier: str, crew: AgentCrew, crew_def: CrewDefinition) -> bool:
        # memory-only: never persists

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 3457-3502
  symbol: `BotManager.load_crews`
  excerpt: |
    if not await self.crew_redis.ping(): ... return
    crew_defs = await self.crew_redis.get_all_crews()
    for crew_def in crew_defs:
        crew = await self._create_crew_from_definition(crew_def)
        self._crews[self._get_crew_key(crew_def.tenant, crew_def.name)] = (crew, crew_def)

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 3504-3555
  symbol: `BotManager.sync_crews`
  excerpt: |
    remote_entries = await self.crew_redis.list_all_crews()
    remote_names = {self._get_crew_key(e["tenant"], e["name"]) for e in remote_entries}
    added = remote_names - local_names; removed = local_names - remote_names
    crew_def = await self.crew_redis.load_crew(name, tenant)

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 3557-3578
  symbol: `BotManager._create_crew_from_definition`
  excerpt: |
    return AgentCrew.from_definition(crew_def, class_resolver=self.get_bot_class,
                                     google_api_key=get_crew_google_api_key())

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/handler.py`
  lines: 325-350
  symbol: `CrewHandler.put (update path)`
  excerpt: |
    existing_crew = await self.bot_manager.get_crew(url_crew_id, tenant=tenant)
    crew_def.crew_id = existing_def.crew_id  # Preserve original ID
    crew_def.created_at = existing_def.created_at
    await self.bot_manager.remove_crew(url_crew_id, tenant=tenant)
    ...
    await self.bot_manager.add_crew(crew_key, crew, crew_def)

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/handler.py`
  lines: 441-445
  symbol: `CrewHandler.get (list)`
  excerpt: |
    # Sync crews from Redis first
    await self.bot_manager.sync_crews()
    crews = self.bot_manager.list_crews(tenant=tenant)

## Notes

- Other `bot_manager.get_crew` consumers (all go through the cache → storage miss path):
  `autonomous/orchestrator.py:1223`, `handlers/crew/saved_execution_service.py:212`,
  `handlers/crew/execution_handler.py:255,683`, `scheduler/manager.py:360`, `handlers/crew/handler.py:245`
  (upload → add_crew). A storage swap behind BotManager is transparent to all of them.
- `sync_crews` assumes the store is shared across workers (multi-worker gunicorn); Postgres satisfies
  this naturally.
- The six storage calls sit behind `if self.crew_redis is None` guards; a dual store needs to preserve
  "memory-only when disabled" semantics.
- Startup ordering: `load_crews()` is the natural place for "init Redis, then Postgres, then optional
  migration" since it already pings before reading.
- Line 2660 `if ENABLE_CREWS:` registers crew routes (not read in detail).
