---
id: F003
query: "BotManager._create_crew_from_definition logic"
type: read
file: packages/ai-parrot/src/parrot/manager/manager.py
lines: 2050-2167
---

Nearly identical to CrewHandler's version (F002). Differences:
- Has fallback to BasicAgent when agent_class not found (line 2076)
- Shared tool resolution is a stub (logs but doesn't actually add tools)
- Has try/except around flow relation setup
- Uses `crew.agents.get(agent_id)` in _get_agents_by_ids (dict lookup)

Both implementations are ~95% duplicated logic. The BotManager version is
slightly more defensive (fallbacks, try/except).
