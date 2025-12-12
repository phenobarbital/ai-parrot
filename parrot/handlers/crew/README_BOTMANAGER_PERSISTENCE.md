# AgentsCrew Redis Persistence - Integrated into BotManager

## Overview

Redis persistence for AgentsCrew has been **fully integrated into BotManager**. Crews are automatically saved to and loaded from Redis, making persistence completely transparent to users of the API.

## How It Works

### Automatic Persistence

The BotManager now handles all Redis persistence automatically:

1. **On Startup** (`on_startup`):
   - All crews are loaded from Redis into memory
   - Similar to how bots are loaded from the database

2. **When Creating/Updating a Crew** (`add_crew`):
   - Crew is added to in-memory cache
   - Automatically saved to Redis (key: `crew:{name}`)
   - If Redis fails, crew remains in memory with a warning

3. **When Getting a Crew** (`get_crew`):
   - First checks in-memory cache
   - If not found, loads from Redis
   - Reconstructs the crew and caches it in memory

4. **When Deleting a Crew** (`remove_crew`):
   - Removes from in-memory cache
   - Automatically deletes from Redis
   - If Redis fails, crew is still removed from memory

## Key Format

Crews are stored in Redis with the following key structure:

- **Crew Definition**: `crew:{name}` - Full CrewDefinition as JSON
- **Crew List**: `crew:list` - Set of all crew names
- **ID Mapping**: `crew:id:{crew_id}` - Maps crew_id to crew name
- **Redis Database**: DB 2 (separate from conversation history on DB 3)

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

Redis configuration is in `parrot/conf.py`:

```python
REDIS_HOST = 'localhost'  # Default
REDIS_PORT = 6379         # Default
REDIS_DB = 2              # CrewRedis uses DB 2
```

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

### 3. **Graceful Degradation**
- If Redis is unavailable, crews still work in-memory
- Warnings logged for Redis failures

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

The system handles Redis failures gracefully:

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

# Clear all crews (caution!)
deleted_count = await crew_redis.clear_all_crews()
```

## Migration

If you have crews in the old standalone CrewRedis system, they're automatically accessible via BotManager's `get_crew()` method, which will load them from Redis on first access.

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

Redis persistence for crews is now **fully automatic**:

✅ Crews are saved to Redis when created
✅ Crews are loaded from Redis on startup
✅ Crews are loaded from Redis on first access
✅ Crews are deleted from Redis when removed
✅ All transparent to API users
✅ Graceful fallback if Redis is unavailable

No manual Redis operations needed - just use the CrewHandler API!
