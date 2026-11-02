---
id: FW-004
query_id: Q004
type: wiki_related
intent: "Neighbours of AgentRegistry"
executed_at: 2026-10-30T16:47:12Z
duration_ms: 400
parent_id: null
depth: 0
---

# FW-004 — AgentRegistry neighbourhood: 40 methods incl. `create_agent_definition` (lossless YAML round-trip), `update_agent_tooling`, `register_instance`, capability index; callers are Studio, BotManager, ExecutionPlanToolkit, Roost

## Summary

`wiki_related` lists the registry's `contains` edges: lifecycle (`register`, `register_bot_decorator`, `register_instance`, `register_remote`, `unregister`, `clear_registry`), discovery (`load_modules`, `load_agent_definitions`, `load_agent_definition_file`, `discover_config_agents`, `load_config`), persistence (`create_agent_definition` "lossless YAML", `delete_factory_agent`, `update_agent_tooling` FEAT-593), lookup (`get_instance`, `get_metadata`, `find_by_kind`, `find_capability`, `find_serving`, `get_bots_by_tag`, `list_bots_by_priority`), PBAC (`_collect_and_register_policies`, `register_db_bot_policies`, `evaluator`), Roost (`capability_registry`, `_mirror_roost`). Inbound `calls` come from `ExecutionPlanToolkit._get_agent_registry`, Studio tests (`test_agents_lifecycle`, `test_drafts_d3`), server handler `test_put_registry_remote_kind`, roost directory-lookup tests.

## Citations

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  symbol: `AgentRegistry.create_agent_definition`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.create_agent_definition
  score: 1.00
  excerpt: |
    Save a BotConfig as a lossless YAML agent definition file.

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  symbol: `AgentRegistry.update_agent_tooling`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.update_agent_tooling
  score: 1.00
  excerpt: |
    Rewrite ``agent.toolkits`` / ``agent.mcp_servers`` of the agent's own YAML in place (FEAT-593).

- path: `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py`
  symbol: `ExecutionPlanToolkit._get_agent_registry`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py#ExecutionPlanToolkit._get_agent_registry
  score: 1.00
  excerpt: |
    Return the cached empty ``AgentRegistry``, creating it once.

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  symbol: `AgentRegistry.get_bots_by_tag`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.get_bots_by_tag
  score: 1.00
  excerpt: |
    Get all bots that have a specific tag.

## Notes

Studio (admin UI) and BotManager persist/reload agents through `create_agent_definition`/`load_agent_definition_file`; an expert bundle that is also YAML-round-trippable would inherit the Studio create/edit flow for free. `get_bots_by_tag` is an existing tag index usable for "visible but inert" experts.
