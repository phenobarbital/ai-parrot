---
type: Wiki Summary
title: parrot.bots.factory.tools.introspection
id: mod:parrot.bots.factory.tools.introspection
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Introspection helpers — the catalog the builders show to their LLM.
relates_to:
- concept: func:parrot.bots.factory.tools.introspection.list_available_toolkits
  rel: defines
- concept: func:parrot.bots.factory.tools.introspection.list_available_tools
  rel: defines
- concept: func:parrot.bots.factory.tools.introspection.list_registered_agents
  rel: defines
- concept: func:parrot.bots.factory.tools.introspection.load_agent_definition
  rel: defines
- concept: mod:parrot.registry
  rel: references
- concept: mod:parrot.tools
  rel: references
- concept: mod:parrot.tools.decorators
  rel: references
- concept: mod:parrot.tools.registry
  rel: references
---

# `parrot.bots.factory.tools.introspection`

Introspection helpers — the catalog the builders show to their LLM.

Every helper has a plain async function (callable from builder code) and a
``@tool``-decorated wrapper of the same name suffix for LLM invocation.

## Functions

- `async def list_available_toolkits() -> List[Dict[str, str]]` — Return the registered toolkit catalog: name + class docstring summary.
- `async def list_available_tools() -> List[Dict[str, str]]` — Return the catalog of standalone ``@tool`` functions discovered.
- `async def list_registered_agents() -> List[Dict[str, Any]]` — List agents currently known to ``AgentRegistry`` (YAML + decorator).
- `async def load_agent_definition(name: str) -> Optional[Dict[str, Any]]` — Return the ``BotConfig`` of a registered agent as a dict (for cloning).
