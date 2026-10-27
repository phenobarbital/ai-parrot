---
id: F004
query_id: Q005, [Q024, Q041]
type: read
intent: "AgentRegistry: remote agent registration, kind/protocol field, endpoint resolution (D10 verification)."
executed_at: 2026-10-25T22:44:44Z
duration_ms: 0
parent_id: null
depth: 2
merged_from: FC-006, FW-006
lane_origin: FC-006-agent-registry-remote-agents, FW-006-agent-registry-local-only
---

# F004 — AgentRegistry registers LOCAL bots only; no remote-agent entry, no kind/protocol/endpoint field. Remote A2A agents live in ToolManager (RegisteredAgent) and A2AMeshDiscovery

## Summary

`AgentRegistry` (core `parrot/registry/registry.py`, 1499 lines) holds `BotMetadata(name, factory, module_path, file_path, singleton, tags, priority, at_startup, dependencies, startup_config, bot_config, events_block)` for bots discovered from modules/YAML and offers `register(name, factory, *, singleton, tags, priority, dependencies, replace, at_startup, startup_config, bot_config)`, `register_instance`, `unregister`, `get_instance`, `load_agent_definitions`, `register_bot_decorator`, PBAC policy collection (`_collect_and_register_policies`, `register_db_bot_policies`) and startup instantiation. A case-insensitive scan of the file for `remote|a2a|RegisteredAgent|endpoint` returned 0 hits. The brainstorm's D10 ("AgentRegistry already registers remote agents and their kind") is therefore NOT true of `AgentRegistry` itself; the remote-agent registry is `ToolManager.register_a2a_agent()` → `RegisteredAgent(url, card)` (FC-004) plus `A2AMeshDiscovery`/`A2AEndpoint` (FC-001). The sibling `parrot/registry/capabilities/` package (FC-007) is an intent-routing capability index, not a remote contract catalog.

## Citations

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 50-72
  symbol: `BotMetadata`
  excerpt: |
    class BotMetadata:
        name: str
        factory: Union[Type[AbstractBot], AgentFactory]
        module_path: str
        file_path: Path
        singleton: bool = False
        tags: Optional[Set[str]] = field(default_factory=set)
        bot_config: Optional[Any] = None
- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 258
  symbol: `AgentRegistry`
  excerpt: |
    class AgentRegistry:
- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 526-540
  symbol: `AgentRegistry.register`
  excerpt: |
    def register(self, name: str, factory: Type[AbstractBot], *, singleton: bool = False,
                 tags: Optional[Iterable[str]] = None, priority: int = 0, dependencies=None,
                 replace: bool = False, at_startup: bool = False, startup_config=None,
                 bot_config: Optional["BotConfig"] = None, **kwargs: Any) -> None:
- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 586-624
  symbol: `register_instance`, `has`, `unregister`
- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 379-463
  symbol: `_collect_and_register_policies`, `register_db_bot_policies`
- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 1324
  symbol: `AgentRegistry.register_bot_decorator`
- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 1471
  symbol: `AgentRegistry.instantiate_startup_agents`
- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 43-46
  symbol: `AgentFactory`

## Notes

Registry package files: registry.py, storage.py, capabilities/{models,registry}.py, routing/{cache,embedding_router,llm_helper,models,ontology_signal,rules,store_router,yaml_loader}.py. Adding a remote-agent kind to `AgentRegistry` is therefore a design change, not a reuse. [cross-lane: type=git_log, intent=registry/ history to see whether a remote-agent entry was ever planned]


<!-- merged from FW-006 -->

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
