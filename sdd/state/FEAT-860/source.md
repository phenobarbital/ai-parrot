---
kind: inline
jira_key: null
fetched_at: 2026-11-09T17:11:28Z
summary_oneline: Postgres CrewDefinition storage (navigator.crew_definitions) alongside Redis, with migration=True to move existing crews from Redis to Postgres
---

postgres-crew-storage -- vamos a definir un Postgres Crew Definition Storage para el
CrewDefinition de Redis a Postgres, con este nuevo storage se inicializan los dos (redis y
luego postgres) y un flag "migration=True" permite "mover" desde redis a postgres los Crew
existentes, una tabla `navigator.crew_definitions` en postgres de donde se pueden re-hidratar
los crew tal como se realiza desde Redis.

<!-- Session context (prior turns of the same conversation, 2026-11-09):
- CrewDefinition JSON is persisted in Redis by CrewRedis
  (packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py), keys
  crew:{tenant}:{name}, crew:{tenant}:list, crew:tenants, crew:{tenant}:id:{crew_id}.
- BotManager.add_crew() saves via self.crew_redis.save_crew(); load_crew / load_crew_by_id rehydrate.
- CrewHandler (/api/v1/crew) exposes GET / PUT / DELETE, no PATCH.
- Postgres today only stores crew EXECUTIONS (PostgresResultStorage, table crew_executions,
  FEAT-307 agentcrew-saved-crews); no Postgres table for crew definitions exists.
-->
