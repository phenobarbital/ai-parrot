# AgentCrew Definition Persistence in BotManager

## Overview

`BotManager` integrates crew definition persistence with its in-memory cache. Redis is the backward-compatible
default. PostgreSQL can be selected as the authoritative definition store; execution-result storage is a separate
subsystem with separate configuration.

## How It Works

### Automatic Persistence

The behavior depends on the configured definition backend:

1. **On Startup** (`on_startup`):
   - The configured store is initialized and active definitions are loaded into memory.
   - PostgreSQL mode may migrate verified Redis sources when migration is enabled and both services are healthy.

2. **When Creating/Updating a Crew** (`add_crew`):
   - Redis mode keeps its historic cache-first, best-effort persistence behavior.
   - PostgreSQL mode persists before publishing the new definition to the cache. A failed write reaches the caller
     and leaves the previous cache and authoritative row unchanged.

3. **When Getting a Crew** (`get_crew`):
   - First checks in-memory cache
   - If not found, loads through the configured definition store
   - Reconstructs the crew and caches it in memory

4. **When Deleting a Crew** (`remove_crew`):
   - Redis mode removes from memory and attempts Redis cleanup best-effort.
   - PostgreSQL mode commits a durable tombstone before evicting the cache. Redis cleanup happens afterward; a
     cleanup failure does not revive the deleted definition.

## Key Format

New Redis writes are tenant-scoped:

- **Crew Definition**: `crew:{tenant}:{name}` — full `CrewDefinition` JSON
- **Crew List**: `crew:{tenant}:list` — set of names for one tenant
- **ID Mapping**: `crew:{tenant}:id:{crew_id}` — maps a tenant/ID to a name
- **Tenant List**: `crew:tenants` — set of known tenants
- **Redis Database**: DB 2 (separate from conversation history on DB 3)

An absent tenant normalizes to `global`. For that tenant, reads also recognize legacy `crew:{name}`, `crew:list`,
and `crew:id:{crew_id}` keys. Migration captures both namespaced and legacy values; differing values are retained as
a conflict rather than cleaned up.

## Usage

### Via REST API

The persistence is **completely transparent**. Just use the crew endpoints normally:

```bash
# Create a crew (automatically saved to Redis)
curl -X PUT http://localhost:5000/api/v1/crew \
  -H "Content-Type: application/json" \
  -d '{
    "name": "research_team",
    "execution_mode": "sequential",
    "agents": [...]
  }'

# Get a crew (loads from Redis if not in memory)
curl http://localhost:5000/api/v1/crew?name=research_team

# Execute a crew
curl -X POST http://localhost:5000/api/v1/crew \
  -H "Content-Type: application/json" \
  -d '{
    "crew_id": "research_team",
    "query": "Research AI trends"
  }'

# Delete a crew (removes from both memory and Redis)
curl -X DELETE http://localhost:5000/api/v1/crew?name=research_team
```

### Programmatically

If you're using BotManager directly in code:

```python
from parrot.manager.manager import BotManager
from parrot.handlers.crew.models import CrewDefinition, AgentDefinition, ExecutionMode

# Initialize manager
bot_manager = BotManager()

# Create crew definition
crew_def = CrewDefinition(
    name="my_crew",
    execution_mode=ExecutionMode.SEQUENTIAL,
    agents=[
        AgentDefinition(
            agent_id="agent1",
            agent_class="BasicAgent",
            name="Agent 1",
            config={"model": "gpt-4"}
        )
    ]
)

# Create and add crew (automatically saved to Redis)
crew = await bot_manager._create_crew_from_definition(crew_def)
await bot_manager.add_crew(crew_def.name, crew, crew_def)

# Get crew (loads from Redis if not in memory)
crew_data = await bot_manager.get_crew("my_crew")
if crew_data:
    crew, crew_def = crew_data
    print(f"Loaded: {crew_def.name}")

# Remove crew (deletes from both memory and Redis)
await bot_manager.remove_crew("my_crew")
```

## Configuration

Definition storage configuration is read from `parrot/conf.py`:

```bash
export CREW_DEFINITION_STORAGE=postgres       # default: redis
export CREW_DEFINITION_PG_DSN='postgres://app:secret@db/parrot'
export CREW_DEFINITION_MIGRATION=false
```

`BotManager(crew_storage_backend=..., crew_migration=...)` overrides the backend and migration flag for one manager;
the DSN remains application configuration. Explicit PostgreSQL mode without a usable DSN stays PostgreSQL mode and
fails closed. It never downgrades writes to Redis.

## Startup Behavior

When the application starts:

1. **Loads Bots** from database (existing behavior)
2. **Loads Crews** from Redis (new behavior)
3. Both are ready for use immediately

Example startup log:

```
INFO :: Bots loaded successfully. Total active bots: 5
INFO Loading 3 crews from Redis...
INFO Loaded crew 'research_team' with 3 agents in sequential mode
INFO Loaded crew 'writing_team' with 2 agents in parallel mode
INFO Loaded crew 'analysis_crew' with 4 agents in flow mode
INFO :: Crews loaded successfully. Total active crews: 3
```

## Benefits

### 1. **Zero Configuration**
- No manual Redis calls needed
- Works out of the box

### 2. **Persistence Across Restarts**
- Crews survive server restarts
- Automatically restored on startup

### 3. **Backend-specific failure behavior**
- Redis-only mode retains best-effort cache-first writes.
- PostgreSQL mode returns storage failures to callers and preserves the last acknowledged cache state.

### 4. **Performance**
- In-memory cache for fast access
- Redis only accessed on cache miss

## Architecture

```
┌─────────────────┐
│   REST API      │
│  CrewHandler    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   BotManager    │
│                 │
│  ┌───────────┐  │
│  │  Memory   │  │ ← Fast in-memory cache
│  │  Cache    │  │
│  └───────────┘  │
│        │        │
│        ▼        │
│  ┌───────────┐  │
│  │CrewRedis  │  │ ← Persistent storage
│  └───────────┘  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Redis DB 2    │
└─────────────────┘
```

## Error Handling

Redis-only mode handles Redis failures with the legacy best-effort policy:

```python
# If Redis is down during startup
WARNING Redis connection failed, skipping crew loading
# → Application starts with empty crew cache

# If Redis fails during save
ERROR Failed to save crew 'my_crew' to Redis: Connection refused
INFO Crew 'my_crew' registered in memory only (Redis persistence failed)
# → Crew works normally but won't survive restart

# If Redis fails during delete
ERROR Failed to delete crew 'my_crew' from Redis: Connection refused
INFO Crew 'my_crew' removed from memory only
# → Crew removed from memory but remains in Redis (manual cleanup needed)
```

PostgreSQL mode is intentionally different. Unavailable authoritative storage maps to HTTP `503`; identity conflicts
map to `409`. Same-name updates are persisted as one upsert and preserve the crew ID and creation time. Rename
updates return `409` before mutation. Deletes commit tombstones before cache eviction; retrying a committed tombstone
is safe.

## Monitoring

Check crew statistics:

```python
stats = bot_manager.get_crew_stats()
print(stats)
```

Returns:

```python
{
    'total_crews': 3,
    'crews_by_mode': {
        'sequential': 1,
        'parallel': 1,
        'flow': 1
    },
    'total_agents': 9,
    'crews': [
        {'name': 'research_team', 'crew_id': 'uuid...', 'mode': 'sequential', 'agent_count': 3},
        {'name': 'writing_team', 'crew_id': 'uuid...', 'mode': 'parallel', 'agent_count': 2},
        {'name': 'analysis_crew', 'crew_id': 'uuid...', 'mode': 'flow', 'agent_count': 4}
    ]
}
```

## Direct Redis Access (Optional)

If you need to access Redis directly for debugging:

```python
# Access the Redis client from BotManager
crew_redis = bot_manager.crew_redis

# Check connection
is_connected = await crew_redis.ping()

# List all crews in Redis
crew_names = await crew_redis.list_crews()

# Get crew metadata
metadata = await crew_redis.get_crew_metadata("my_crew")

# Inspect one source before operator reconciliation
snapshot = await crew_redis.snapshot_crew("my_crew", tenant="global")
```

## Migration

With `CREW_DEFINITION_MIGRATION=true`, PostgreSQL mode runs a guarded Redis migration when both stores are healthy.
The report separates newly `migrated`, `already_present`, tombstone `deleted_sources`, `conflicts`, per-key `failed`
outcomes and `redis_cleanup_failed` outcomes. Conflicting, unreadable, concurrently changed, or cleanup-failed
sources remain in Redis for operator reconciliation; never purge them unconditionally. Tombstones are not
auto-purged because a legacy source could otherwise reappear.

Run a reviewed dry run first with `await manager.crew_storage.migrate_from_redis(dry_run=True)`. Dry runs do not
create schema or mutate data. Migration cleanup requires single-instance Redis; Redis Cluster is rejected. Upgrade
all workers before relying on PostgreSQL acknowledged-write behavior, and do not treat skipped live-service tests as
proof that destructive cleanup is safe.

## Troubleshooting

### Crew not found after restart

Check if Redis is running:

```bash
redis-cli ping
# Should return: PONG
```

Check if crew is in Redis:

```bash
redis-cli -n 2 KEYS "crew:*"
```

### Redis connection errors

Verify Redis configuration in `parrot/conf.py`:

```python
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
```

Test connection:

```python
await bot_manager.crew_redis.ping()
```

## Summary

Crew definitions use tenant-scoped identities in either backend. Redis mode preserves the legacy best-effort policy.
PostgreSQL mode persists before cache publication, fails closed on unavailable authority, uses durable tombstones,
and retains unverified Redis sources for explicit operator reconciliation.
