---
id: F002
query: "CrewHandler._create_crew_from_definition logic"
type: read
file: packages/ai-parrot/src/parrot/handlers/crew/handler.py
lines: 76-177
---

`_create_crew_from_definition(self, crew_def: CrewDefinition) -> AgentCrew`:
1. Iterates crew_def.agents, resolves class via `self.bot_manager.get_bot_class()`
2. Collects tools from agent_def.tools (just names, not resolved)
3. Creates agent: `agent_class(name=..., tools=tools, **agent_def.config)`
4. Sets system_prompt if present
5. Creates `AgentCrew(name=..., agents=agents, max_parallel_tasks=...)`
6. Adds shared tools via `self.bot_manager.get_tool(tool_name)`
7. Sets up flow relations if execution_mode == FLOW

Helper `_get_agents_by_ids(crew, agent_ids)` at line 160 — iterates
`crew.agents` matching by name.

Key dependency: requires a `bot_manager` instance for class and tool resolution.
