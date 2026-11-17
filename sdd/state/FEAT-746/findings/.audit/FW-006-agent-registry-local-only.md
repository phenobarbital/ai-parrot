---
id: FW-006
query_id: Q005
type: wiki_page
intent: "Orient: AgentRegistry and how remote agents are registered with a kind (a2a)."
executed_at: 2026-10-25T22:44:49Z
duration_ms: 0
parent_id: null
depth: 2
---

# FW-006 — AgentRegistry registers LOCAL bots (classes/YAML BotConfig); it has no remote-agent entry or protocol kind — remote discovery lives in A2AMeshDiscovery

## Summary

`parrot.registry.AgentRegistry` (and the `register_agent` decorator = `register_bot_decorator`) manages locally instantiable bots: `BotMetadata(name, factory, module_path, file_path, singleton, tags, priority, at_startup, bot_config)` and `BotConfig(name, class_name, module, tools, toolkits, mcp_servers, model, system_prompt, vector_store, policies)`. The only outward-pointing field is `mcp_servers` (list of MCPServerConfig dicts applied via `setup_mcp_servers`). There is no `kind`/`protocol`/`endpoint` for a remote agent, so brainstorm D10 ("AgentRegistry already registers remote agents and their kind (A2A or this protocol)") is NOT backed by the wiki; the remote registry that exists is `A2AMeshDiscovery` (FW-001) with `RegisteredAgent` from `a2a/models.py`. AgentRegistry does integrate PBAC: `setup(app)` grabs the navigator-auth PDP evaluator and `_collect_and_register_policies` loads per-bot `PolicyRuleConfig`s.

## Citations

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  symbol: `AgentRegistry`
  wiki_page_id: file:packages/ai-parrot/src/parrot/registry/registry.py
  excerpt: |
    class AgentRegistry: register(name, factory) / register_instance / unregister / get_instance(name, request) /
        load_agent_definitions(dir) / create_agent_definition / update_agent_tooling / register_bot_decorator / list_agents
        def setup(self, app): self._evaluator = getattr(app.get("abac"), "_evaluator", None)
- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  symbol: `BotConfig`
  excerpt: |
    class BotConfig(BaseModel): name, class_name, module, enabled, origin: Literal["repo","factory"], config,
        tools: Optional[ToolConfig], toolkits: List[str|ToolkitSpec], mcp_servers: List[Dict], model, system_prompt, prompt,
        vector_store, tags, singleton, at_startup, startup_config, priority, policies: Optional[List[PolicyRuleConfig]]
- path: `packages/ai-parrot/src/parrot/registry/__init__.py`
  symbol: `register_agent`
  wiki_page_id: file:packages/ai-parrot/src/parrot/registry/__init__.py (score 1.00)
  excerpt: |
    agent_registry = AgentRegistry(agents_dir=AGENTS_DIR, extra_agent_dirs=[PLUGINS_DIR / "agents"])
    register_agent = agent_registry.register_bot_decorator
- path: `packages/ai-parrot/src/parrot/a2a/models.py`
  symbol: `RegisteredAgent`
  excerpt: |
    class RegisteredAgent: Definition about a Registered Agent.   # used by A2AMeshDiscovery, not AgentRegistry

## Notes

- Design implication: either extend `BotConfig`/`AgentRegistry` with a remote kind, or make the RemoteToolkit resolve endpoints from `A2AMeshDiscovery`-style config (YAML with ${ENV} substitution already exists there).
- [cross-lane: type=grep, intent=grep "RegisteredAgent" definition fields in a2a/models.py (name, url, card, tags, status?) to see whether a protocol/kind field can be added]
