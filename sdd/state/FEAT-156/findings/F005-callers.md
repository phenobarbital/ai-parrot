---
id: F005
query: "Other AgentCrew instantiation sites"
type: grep
pattern: "AgentCrew("
---

Callers that instantiate AgentCrew directly:
1. parrot/handlers/crew/handler.py:128 — via _create_crew_from_definition
2. parrot/manager/manager.py:2098 — via _create_crew_from_definition
3. parrot/bots/orchestration/hr.py:89 — HRProcessingCrew (hardcoded)
4. parrot/bots/flows/agents/hr.py:111 — flow-based HR crew (hardcoded)

All dynamic (definition-driven) creation goes through the two
_create_crew_from_definition duplicates.
