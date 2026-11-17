---
id: FW-002
query_id: Q002
type: wiki_page
intent: "Read the CrewRedis page for its API outline (save/load/list/delete/id map)."
executed_at: 2026-11-09T17:13:10Z
duration_ms: 400
parent_id: FW-001
depth: 1
---

# FW-002 — CrewRedis API: 14 public async methods, tenant-scoped keys with a "global" legacy fallback

## Summary

`CrewRedis(redis_url=None, key_prefix="crew", db=2)` builds `redis://{REDIS_HOST}:{REDIS_PORT}/{db}` when no URL
is given. Public surface: `save_crew`, `load_crew(name, tenant)`, `load_crew_by_id(crew_id, tenant)`,
`delete_crew`, `list_crews(tenant)`, `list_all_crews()`, `crew_exists`, `get_all_crews(tenant)`,
`get_crew_metadata`, `update_crew_metadata`, `ping`, `close`, `clear_all_crews`. A `None` tenant normalizes to
`"global"`, and only the `global` tenant also reads legacy un-tenanted keys (`crew:{name}`, `crew:list`,
`crew:id:{crew_id}`). The `crew_id`→name lookup is a separate key. Errors are swallowed: `save_crew` returns
`False`, `load_crew` returns `None`, `list_crews` returns `[]`. `_deserialize_crew` runs `_strip_unknown_keys`
(root + agents / tool_nodes / flow_relations) so already-stored crews stay loadable under `extra="forbid"`.
`save_crew` sets `crew.updated_at = datetime.utcnow()` before writing.

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`
  lines: 20-24
  symbol: `CrewRedis.__init__`
  excerpt: |
    def __init__(self, redis_url: str = None, key_prefix: str = "crew",
                 db: int = 2  # Use DB 2 for crew persistence
- path: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`
  lines: 54-98
  symbol: `CrewRedis._normalize_tenant`
  excerpt: |
    return tenant or "global"
    _get_key -> f"{prefix}:{tenant}:{name}";  _get_list_key -> f"{prefix}:{tenant}:list"
    _get_tenants_key -> f"{prefix}:tenants";  _get_id_mapping_key -> f"{prefix}:{tenant}:id:{crew_id}"
    legacy: f"{prefix}:{name}", f"{prefix}:list", f"{prefix}:id:{crew_id}"
- path: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`
  lines: 125-178
  symbol: `CrewRedis._strip_unknown_keys`
  excerpt: |
    CrewDefinition, AgentDefinition, ToolNodeDefinition and FlowRelation are all extra="forbid",
    so a single obsolete key anywhere in a stored document makes the whole crew unloadable.
- path: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`
  lines: 180-218
  symbol: `CrewRedis._deserialize_crew`
  excerpt: |
    crew_dict = self._strip_unknown_keys(crew_dict, crew_dict.get('crew_id', '<unknown>'))
    return CrewDefinition(**crew_dict)
- path: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`
  lines: 220-260
  symbol: `CrewRedis.save_crew`
  excerpt: |
    crew.updated_at = datetime.utcnow()
    tenant = self._normalize_tenant(crew.tenant)
    await self.redis.set(key, serialized); sadd(list_key, crew.name); sadd(tenants_key, tenant)
    await self.redis.set(id_key, crew.name) ... except Exception: return False
- path: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`
  lines: 262-326
  symbol: `CrewRedis.load_crew`
  excerpt: |
    data = await self.redis.get(key)
    if data is None and tenant == "global": data = await self.redis.get(legacy_key)
- path: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`
  lines: 397-419
  symbol: `CrewRedis.list_all_crews`
  excerpt: |
    tenants = smembers(tenants_key); legacy list adds "global"; returns [{"tenant":..., "name":...}]
- path: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`
  lines: 479-545
  symbol: `CrewRedis.update_crew_metadata`
  excerpt: |
    get_crew_metadata / update_crew_metadata — metadata without loading/modifying agents (body not in wiki excerpt)

## Notes

`list_all_crews()` + `load_crew(name, tenant)` already give a full enumeration path that a Redis→Postgres
migration can iterate. Identity is (tenant, name) with a secondary (tenant, crew_id) index — a Postgres table
needs both as unique keys. Wiki page `updated_at` is 2026-08-22, so its excerpt may lag the file; line numbers
above come from a grep on the current checkout.
[cross-lane: type=read, intent=confirm get_crew_metadata/update_crew_metadata/get_all_crews bodies (truncated in wiki) — Q006]
