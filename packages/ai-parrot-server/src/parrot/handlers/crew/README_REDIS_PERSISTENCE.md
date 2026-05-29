# Redis Persistence for AgentsCrew

This module provides async-based Redis persistence for AgentsCrew definitions, allowing crews to be stored, retrieved, and managed across sessions.

## Overview

The `CrewRedis` class enables you to:
- Save crew definitions to Redis with key format `crew:{name}`
- Load crew definitions by name or crew_id
- List all available crews
- Update crew metadata
- Delete crews
- Manage multiple crews efficiently

## Installation

The Redis persistence layer requires the `redis` package with async support:

```bash
pip install redis
```

## Configuration

Redis configuration is managed through `parrot/conf.py`:

```python
REDIS_HOST = 'localhost'  # Default
REDIS_PORT = 6379         # Default
REDIS_DB = 2              # CrewRedis uses DB 2 by default
```

## Basic Usage

### Initialize CrewRedis

```python
from parrot.handlers.crew.redis_persistence import CrewRedis

# Use default configuration
crew_redis = CrewRedis()

# Or specify custom Redis URL
crew_redis = CrewRedis(redis_url="redis://localhost:6379/2")

# Check connection
is_connected = await crew_redis.ping()
```

### Save a Crew Definition

```python
from parrot.handlers.crew.models import CrewDefinition, AgentDefinition, ExecutionMode

# Create a crew definition
crew_def = CrewDefinition(
    name="blog_writing_team",
    description="A crew for researching and writing blog posts",
    execution_mode=ExecutionMode.SEQUENTIAL,
    agents=[
        AgentDefinition(
            agent_id="researcher",
            agent_class="BasicAgent",
            name="Content Researcher",
            config={"model": "gpt-4", "temperature": 0.7},
            tools=["web_search", "summarize"],
            system_prompt="You are an expert researcher."
        ),
        AgentDefinition(
            agent_id="writer",
            agent_class="BasicAgent",
            name="Blog Writer",
            config={"model": "gpt-4", "temperature": 0.9},
            tools=["write", "format_markdown"],
            system_prompt="You are a creative blog writer."
        )
    ],
    shared_tools=["calculator"],
    metadata={"version": "1.0", "author": "content_team"}
)

# Save to Redis (key: crew:blog_writing_team)
success = await crew_redis.save_crew(crew_def)
```

### Load a Crew Definition

```python
# Load by name (key: crew:blog_writing_team)
crew = await crew_redis.load_crew("blog_writing_team")

if crew:
    print(f"Loaded crew: {crew.name}")
    print(f"Agents: {len(crew.agents)}")
    print(f"Execution mode: {crew.execution_mode}")

# Load by crew_id
crew = await crew_redis.load_crew_by_id("some-uuid-here")
```

### List All Crews

```python
# Get list of crew names
crew_names = await crew_redis.list_crews()
print(f"Available crews: {crew_names}")

# Get all crew definitions
all_crews = await crew_redis.get_all_crews()
for crew in all_crews:
    print(f"{crew.name}: {crew.description}")
```

### Check Crew Existence

```python
exists = await crew_redis.crew_exists("blog_writing_team")
if exists:
    print("Crew exists in Redis")
```

### Update Crew Metadata

```python
# Update metadata without loading full definition
success = await crew_redis.update_crew_metadata(
    "blog_writing_team",
    {
        "status": "active",
        "runs": 10,
        "last_run": "2025-12-12T10:00:00"
    }
)
```

### Get Crew Metadata

```python
# Get metadata without loading full crew definition
metadata = await crew_redis.get_crew_metadata("blog_writing_team")
if metadata:
    print(f"Crew ID: {metadata['crew_id']}")
    print(f"Agent count: {metadata['agent_count']}")
    print(f"Created at: {metadata['created_at']}")
```

### Delete a Crew

```python
# Delete crew from Redis
success = await crew_redis.delete_crew("blog_writing_team")
```

### Clean Up

```python
# Close Redis connection when done
await crew_redis.close()
```

## Key Format

The CrewRedis class uses the following key formats in Redis:

- **Crew Definition**: `crew:{name}` - Stores the full CrewDefinition as JSON
- **Crew List**: `crew:list` - Set of all crew names
- **ID Mapping**: `crew:id:{crew_id}` - Maps crew_id to crew name for lookup by ID

## Advanced Usage

### Flow-Based Crews

```python
from parrot.handlers.crew.models import FlowRelation

crew_def = CrewDefinition(
    name="research_synthesis_team",
    description="Parallel research with synthesis",
    execution_mode=ExecutionMode.FLOW,
    agents=[
        AgentDefinition(
            agent_id="coordinator",
            name="Research Coordinator",
            # ... config
        ),
        AgentDefinition(
            agent_id="tech_researcher",
            name="Tech Researcher",
            # ... config
        ),
        AgentDefinition(
            agent_id="synthesizer",
            name="Synthesizer",
            # ... config
        )
    ],
    flow_relations=[
        # Coordinator runs first, then researchers in parallel
        FlowRelation(
            source="coordinator",
            target=["tech_researcher", "market_researcher"]
        ),
        # Synthesizer runs after both researchers complete
        FlowRelation(
            source=["tech_researcher", "market_researcher"],
            target="synthesizer"
        )
    ]
)

await crew_redis.save_crew(crew_def)
```

### Bulk Operations

```python
# Get all crews
all_crews = await crew_redis.get_all_crews()

# Filter by execution mode
sequential_crews = [
    crew for crew in all_crews
    if crew.execution_mode == ExecutionMode.SEQUENTIAL
]

# Clear all crews (use with caution!)
deleted_count = await crew_redis.clear_all_crews()
print(f"Deleted {deleted_count} crews")
```

## Integration with BotManager

The CrewRedis class can be integrated with the existing BotManager for persistent storage:

```python
class BotManager:
    def __init__(self):
        self._crews = {}  # In-memory cache
        self.crew_redis = CrewRedis()  # Persistent storage

    async def create_crew(self, crew_def: CrewDefinition):
        # Create crew instance
        crew = AgentCrew(name=crew_def.name, agents=agents)

        # Cache in memory
        self._crews[crew_def.crew_id] = (crew, crew_def)

        # Persist to Redis
        await self.crew_redis.save_crew(crew_def)

    async def get_crew(self, crew_id: str):
        # Check memory cache first
        if crew_id in self._crews:
            return self._crews[crew_id]

        # Load from Redis
        crew_def = await self.crew_redis.load_crew_by_id(crew_id)
        if crew_def:
            # Reconstruct crew from definition
            crew = self._create_crew_from_definition(crew_def)
            self._crews[crew_id] = (crew, crew_def)
            return (crew, crew_def)

        return None
```

## Error Handling

The CrewRedis class includes comprehensive error handling and logging:

```python
try:
    crew = await crew_redis.load_crew("nonexistent_crew")
    if crew is None:
        print("Crew not found")
except Exception as e:
    print(f"Error loading crew: {e}")
```

All methods return appropriate values:
- `save_crew()`: Returns `True` on success, `False` on failure
- `load_crew()`: Returns `CrewDefinition` if found, `None` otherwise
- `delete_crew()`: Returns `True` if deleted, `False` if not found
- `list_crews()`: Returns empty list on error

## Performance Considerations

1. **Connection Pooling**: The Redis client automatically manages connection pooling
2. **Serialization**: Uses JSON for efficient serialization/deserialization
3. **Caching**: Consider implementing an in-memory cache layer for frequently accessed crews
4. **Batch Operations**: Use `get_all_crews()` for bulk loading instead of multiple individual loads

## Testing

Run the built-in test suite:

```bash
# Test the persistence layer
python parrot/handlers/crew/redis_persistence.py

# Run the comprehensive examples
python examples/crew/redis_persistence_example.py
```

## Database Selection

By default, CrewRedis uses Redis database 2 to avoid conflicts with other Redis-based storage:

- **DB 0**: General purpose (default)
- **DB 1**: Configuration cache
- **DB 2**: Crew persistence (CrewRedis)
- **DB 3**: Conversation history
- **DB 4**: Services

## Troubleshooting

### Redis Connection Failed

```python
if not await crew_redis.ping():
    print("Check Redis server is running: redis-cli ping")
```

### Serialization Errors

Ensure all crew data types are JSON-serializable. The module automatically handles datetime serialization.

### Key Conflicts

If using custom key prefixes, ensure they don't conflict with existing Redis keys:

```python
crew_redis = CrewRedis(key_prefix="myapp_crew")
```

## Example Scripts

See `/examples/crew/redis_persistence_example.py` for comprehensive examples including:
- Basic persistence
- Flow-based crews
- Metadata updates
- Bulk operations

## API Reference

### CrewRedis Class

#### Methods

- `__init__(redis_url=None, key_prefix="crew", db=2)`
- `save_crew(crew: CrewDefinition) -> bool`
- `load_crew(name: str) -> Optional[CrewDefinition]`
- `load_crew_by_id(crew_id: str) -> Optional[CrewDefinition]`
- `delete_crew(name: str) -> bool`
- `list_crews() -> List[str]`
- `crew_exists(name: str) -> bool`
- `get_all_crews() -> List[CrewDefinition]`
- `get_crew_metadata(name: str) -> Optional[Dict[str, Any]]`
- `update_crew_metadata(name: str, metadata: Dict[str, Any]) -> bool`
- `ping() -> bool`
- `close() -> None`
- `clear_all_crews() -> int`

## License

This module is part of the ai-parrot project and follows the same MIT license.
