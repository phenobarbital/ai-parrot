---
type: Wiki Summary
title: parrot.bots.factory.tools.finalize
id: mod:parrot.bots.factory.tools.finalize
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Finalize step — write the YAML and reload the registry.
relates_to:
- concept: func:parrot.bots.factory.tools.finalize.finalize_agent_registration
  rel: defines
- concept: func:parrot.bots.factory.tools.finalize.write_agent_yaml
  rel: defines
- concept: mod:parrot.bots.factory.contracts
  rel: references
- concept: mod:parrot.registry
  rel: references
- concept: mod:parrot.registry.registry
  rel: references
- concept: mod:parrot.tools.decorators
  rel: references
---

# `parrot.bots.factory.tools.finalize`

Finalize step — write the YAML and reload the registry.

This is the only tool that mutates the registry on disk. It is invoked at the
very end of the factory flow, **after** the user has approved the
``AgentDefinition`` at the pre-finalize HITL checkpoint.

## Functions

- `async def write_agent_yaml(definition: AgentDefinition, category: str='general') -> Path` — Persist an ``AgentDefinition`` as a YAML file under ``agents/<category>/``.
- `async def finalize_agent_registration(definition: AgentDefinition, category: str='general') -> Dict[str, Any]` — Write the YAML, reload the registry, and return the registration result.
