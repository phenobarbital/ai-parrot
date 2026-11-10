---
id: FC-001
query_id: Q006
type: read
intent: "Read CrewRedis in full: key layout, tenant handling, legacy keys, _strip_unknown_keys, connection setup."
executed_at: 2026-11-09T17:16:00Z
duration_ms: 900
parent_id: null
depth: 0
---

# FC-001 — CrewRedis: full public API, key layout, tenant/legacy semantics, connection setup

## Summary

`CrewRedis` (704 lines, `handlers/crew/redis_persistence.py`) is a plain class (no base class / interface)
with its own `redis.asyncio.Redis` client built in `__init__` from `REDIS_HOST`/`REDIS_PORT` and a
hard-coded `db=2` (URL `redis://{REDIS_HOST}:{REDIS_PORT}/2` unless `redis_url` is passed). Tenant is
taken from `crew.tenant`, normalized `None → "global"`. Every write method swallows exceptions and returns
`False`/`None`/`[]` (never raises). The public surface a Postgres sibling must mirror is: `save_crew`,
`load_crew`, `load_crew_by_id`, `delete_crew`, `list_crews`, `list_all_crews`, `crew_exists`,
`get_all_crews`, `get_crew_metadata`, `update_crew_metadata`, `ping`, `close`, `clear_all_crews`.
`_deserialize_crew` runs `_strip_unknown_keys` (root + agents/tool_nodes/flow_relations) before
`CrewDefinition(**crew_dict)` so legacy documents stay loadable under `extra="forbid"`. Lines 590+ are a
`test_crew_redis()` demo using `print` (not a pytest test).

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`
  lines: 7-51
  symbol: `CrewRedis.__init__`
  excerpt: |
    from redis.asyncio import Redis
    from .models import CrewDefinition
    from ...conf import REDIS_URL
    class CrewRedis:
        def __init__(self, redis_url: str = None, key_prefix: str = "crew", db: int = 2):
            if redis_url is None:
                from ...conf import REDIS_HOST, REDIS_PORT
                redis_url = f"redis://{REDIS_HOST}:{REDIS_PORT}/{db}"
            self.redis = Redis.from_url(self.redis_url, decode_responses=True, encoding="utf-8",
                socket_connect_timeout=5, socket_timeout=5, retry_on_timeout=True)

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`
  lines: 53-98
  symbol: `CrewRedis._get_key / _get_list_key / _get_tenants_key / _get_legacy_* / _get_id_mapping_key`
  excerpt: |
    def _normalize_tenant(tenant): return tenant or "global"
    _get_key(name, tenant)            -> f"{prefix}:{tenant}:{name}"      # JSON string
    _get_list_key(tenant)             -> f"{prefix}:{tenant}:list"        # SET of names
    _get_tenants_key()                -> f"{prefix}:tenants"              # SET of tenants
    _get_legacy_key(name)             -> f"{prefix}:{name}"               # pre-tenant layout
    _get_legacy_list_key()            -> f"{prefix}:list"
    _get_legacy_id_mapping_key(id)    -> f"{prefix}:id:{crew_id}"
    _get_id_mapping_key(id, tenant)   -> f"{prefix}:{tenant}:id:{crew_id}"  # STRING -> name

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`
  lines: 100-123
  symbol: `CrewRedis._serialize_crew`
  excerpt: |
    crew_dict = crew.model_dump(mode='json')
    ...
    return json.dumps(crew_dict, ensure_ascii=False, separators=(',', ':'))

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`
  lines: 125-178
  symbol: `CrewRedis._strip_unknown_keys`
  excerpt: |
    from .models import AgentDefinition, FlowRelation, ToolNodeDefinition
    cleaned = _prune(crew_dict, CrewDefinition, "")
    for field, model in (("agents", AgentDefinition), ("tool_nodes", ToolNodeDefinition),
                         ("flow_relations", FlowRelation)):
        ...
    if dropped: self.logger.warning("Ignoring unknown key(s) %s in stored crew %r; ...", dropped, crew_id)

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`
  lines: 180-218
  symbol: `CrewRedis._deserialize_crew`
  excerpt: |
    crew_dict = json.loads(data)
    # created_at/updated_at ISO -> datetime
    crew_dict = self._strip_unknown_keys(crew_dict, crew_dict.get('crew_id', '<unknown>'))
    return CrewDefinition(**crew_dict)

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`
  lines: 220-260
  symbol: `CrewRedis.save_crew`
  excerpt: |
    async def save_crew(self, crew: CrewDefinition) -> bool:
        crew.updated_at = datetime.utcnow()
        tenant = self._normalize_tenant(crew.tenant)
        await self.redis.set(self._get_key(crew.name, tenant), serialized)
        await self.redis.sadd(self._get_list_key(tenant), crew.name)
        await self.redis.sadd(self._get_tenants_key(), tenant)
        await self.redis.set(self._get_id_mapping_key(crew.crew_id, tenant), crew.name)
        return True   # except Exception: log + return False

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`
  lines: 262-326
  symbol: `CrewRedis.load_crew / load_crew_by_id`
  excerpt: |
    async def load_crew(self, name: str, tenant: Optional[str] = None) -> Optional[CrewDefinition]:
        data = await self.redis.get(key)
        if data is None and tenant == "global": data = await self.redis.get(legacy_key)
    async def load_crew_by_id(self, crew_id: str, tenant: Optional[str] = None) -> Optional[CrewDefinition]:
        name = await self.redis.get(id_key)   # legacy fallback only for "global"
        return await self.load_crew(name, tenant)

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`
  lines: 328-375
  symbol: `CrewRedis.delete_crew`
  excerpt: |
    async def delete_crew(self, name: str, tenant: Optional[str] = None) -> bool:
        crew = await self.load_crew(name, tenant)
        result = await self.redis.delete(key); await self.redis.srem(list_key, name)
        # global: also deletes legacy key + legacy list member + legacy id mapping
        if await self.redis.scard(self._get_list_key(tenant)) == 0:
            await self.redis.srem(self._get_tenants_key(), tenant)

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`
  lines: 377-477
  symbol: `CrewRedis.list_crews / list_all_crews / crew_exists / get_all_crews`
  excerpt: |
    async def list_crews(self, tenant=None) -> List[str]           # sorted names (+legacy for global)
    async def list_all_crews(self) -> List[Dict[str, str]]          # [{"tenant":..., "name":...}]
    async def crew_exists(self, name, tenant=None) -> bool
    async def get_all_crews(self, tenant=None) -> List[CrewDefinition]  # tenant=None => ALL tenants

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`
  lines: 479-587
  symbol: `CrewRedis.get_crew_metadata / update_crew_metadata / ping / close / clear_all_crews`
  excerpt: |
    async def get_crew_metadata(self, name, tenant=None) -> Optional[Dict[str, Any]]
        # crew_id, tenant, name, description, execution_mode, agent_count, created_at, updated_at, metadata
    async def update_crew_metadata(self, name, metadata, tenant=None) -> bool   # load + merge + save_crew
    async def ping(self) -> bool
    async def close(self)
    async def clear_all_crews(self) -> int

## Notes

- Natural key in Redis is `(tenant, name)`; `crew_id` is only a secondary index (`crew:{tenant}:id:{crew_id}`).
  A Postgres table therefore needs `UNIQUE (tenant, name)` plus a `crew_id` lookup (unique per tenant).
- Redis writes are 4 separate commands (no MULTI/pipeline) — partial writes are possible today.
- `save_crew` mutates `crew.updated_at` in place; `created_at` comes from the model default.
- `CrewDefinition` is imported via `handlers/crew/models.py` (`from .models import CrewDefinition`), not
  directly from `parrot.models.crew_definition` — see FC-004.
- Legacy (pre-tenant) keys exist only for the `global` tenant; a migration must read them too
  (`list_all_crews` already folds legacy names into `global`).
- No abstract interface exists → a Postgres store has no contract to implement; "init both" requires
  either a new protocol/ABC or a composite wrapper exposing the same method names.
