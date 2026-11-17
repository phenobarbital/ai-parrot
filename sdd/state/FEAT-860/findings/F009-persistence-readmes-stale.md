---
id: F009
query_id: Q015
type: read
intent: "Read the persistence READMEs that a new backend would have to update."
executed_at: 2026-11-09T17:30:30Z
duration_ms: 700
parent_id: null
depth: 0
merged_from: [FC-010]
---

# F009 — The two crew persistence READMEs are Redis-only and STALE (pre-tenant key format `crew:{name}`)

## Summary

`handlers/crew/README_REDIS_PERSISTENCE.md` (366 lines) and `README_BOTMANAGER_PERSISTENCE.md` (303 lines)
document CrewRedis as the only backend. Both describe the pre-tenant key layout (`crew:{name}`,
`crew:list`, `crew:id:{crew_id}`) — the code (FC-001) actually writes `crew:{tenant}:{name}`,
`crew:{tenant}:list`, `crew:tenants`, `crew:{tenant}:id:{crew_id}` and only READS the legacy keys for the
`global` tenant. The BotManager README has a "Migration" section that only talks about the old standalone
CrewRedis (lazy load on first access) and a "Startup Behavior" section; both would need a Postgres section.
Docs state "DB 2 for crews (separate from conversation history on DB 3)".

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/README_REDIS_PERSISTENCE.md`
  lines: 8, 30, 44
  symbol: `Overview / Configuration`
  excerpt: |
    - Save crew definitions to Redis with key format `crew:{name}`
    REDIS_DB = 2              # CrewRedis uses DB 2 by default
    crew_redis = CrewRedis(redis_url="redis://localhost:6379/2")

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/README_REDIS_PERSISTENCE.md`
  lines: 161-167
  symbol: `## Key Format`
  excerpt: |
    - **Crew Definition**: `crew:{name}` - Stores the full CrewDefinition as JSON
    - **Crew List**: `crew:list` - Set of all crew names
    - **ID Mapping**: `crew:id:{crew_id}` - Maps crew_id to crew name for lookup by ID

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/README_BOTMANAGER_PERSISTENCE.md`
  lines: 32-39
  symbol: `## Key Format`
  excerpt: |
    - **Crew Definition**: `crew:{name}` - Full CrewDefinition as JSON
    - **ID Mapping**: `crew:id:{crew_id}` - Maps crew_id to crew name
    - **Redis Database**: DB 2 (separate from conversation history on DB 3)

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/README_BOTMANAGER_PERSISTENCE.md`
  lines: 256-258
  symbol: `## Migration`
  excerpt: |
    If you have crews in the old standalone CrewRedis system, they're automatically accessible via
    BotManager's `get_crew()` method, which will load them from Redis on first access.

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/README_BOTMANAGER_PERSISTENCE.md`
  lines: 187-204
  symbol: `## Error Handling`
  excerpt: |
    # If Redis is down during startup → Application starts with empty crew cache
    # If Redis fails during save → Crew works normally but won't survive restart
    # If Redis fails during delete → Crew removed from memory but remains in Redis (manual cleanup needed)

## Notes

- A docs task is warranted: fix the stale key format AND add the Postgres backend + migration flag.
- `[cross-lane: type=wiki_query, intent=check whether a wiki/techwiki page documents crew persistence and would need updating]`
