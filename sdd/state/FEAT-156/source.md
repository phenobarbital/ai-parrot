---
kind: inline
jira_key: null
fetched_at: 2026-05-11T00:00:00Z
summary_oneline: AgentCrew requires a from_definition classmethod to create crews from CrewDefinition
---

AgentCrew requires a method `from_definition` to create/re-create an AgentCrew
from a definition. Currently the creation logic is duplicated in CrewHandler
(HTTP handler) and BotManager, but not as a method in AgentCrew itself.
