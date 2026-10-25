---
id: FC-006
query_id: [Q024, Q041]
type: read
intent: "AgentRegistry: remote agent registration, kind/protocol field, endpoint resolution (D10 verification)."
executed_at: 2026-10-25T22:44:44Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-006 — AgentRegistry registers LOCAL bots only; no remote-agent entry, no kind/protocol/endpoint field. Remote A2A agents live in ToolManager (RegisteredAgent) and A2AMeshDiscovery

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
