---
id: FW-001
query_id: Q001
type: wiki_page
intent: "Orient: AgentRegistry — how agents are registered (decorator), what remote-agent kinds exist, whether capabilities are indexed."
executed_at: 2026-10-25T22:46:00Z
duration_ms: 900
parent_id: null
depth: 0
---

# FW-001 — AgentRegistry registers agents by decorator/YAML; NO capability index, NO locality ranking, NO remote-agent kind

## Summary

`parrot.registry` exports a global `agent_registry = AgentRegistry(agents_dir=AGENTS_DIR, extra_agent_dirs=[PLUGINS_DIR/'agents'])` and `register_agent = agent_registry.register_bot_decorator`. The registry (`registry/registry.py`, class at l.258) is keyed by **name**; a `BotMetadata` entry (l.50) carries `name, factory, module_path, file_path, singleton, tags, priority, at_startup, dependencies, startup_config, bot_config, events_block`. The decorator (l.1324) accepts `name, priority, dependencies, singleton, at_startup, startup_config, tags`. Lookup API is `register / register_instance (l.586) / has / unregister / get_metadata / get_instance (l.659, async, PBAC-guarded via agent_guard.enforce_agent_access) / get_bot_instance / list_agents (l.1421) / list_agent_names / list_bots_by_priority / get_bots_by_tag (l.1450)`. The only discovery-by-attribute is `get_bots_by_tag`. The API outline contains **no** `find_capability`, no capability ids/hashes, no `kind` (local/remote/a2a) field, no endpoint field, no locality/cost ranking — the brainstorm's VERIFY claim 'AgentRegistry does not index capabilities or rank by locality' is CONFIRMED; its D10 claim that the registry 'already registers remote agents and their kind' is NOT supported by the core registry (remote discovery lives in `parrot.a2a.mesh`, see FW-009). PBAC is wired in: `evaluator()`, `setup(app)`, `_collect_and_register_policies`, `register_db_bot_policies`.

## Citations

- path: `packages/ai-parrot/src/parrot/registry/__init__.py`
  lines: 1-22
  symbol: `agent_registry / register_agent`
  wiki_page_id: file:packages/ai-parrot/src/parrot/registry/__init__.py (score=1.00)
  excerpt: |
    agent_registry = AgentRegistry(agents_dir=AGENTS_DIR, extra_agent_dirs=[PLUGINS_DIR / "agents"])
    register_agent = agent_registry.register_bot_decorator
- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 50-72
  symbol: `BotMetadata`
  wiki_page_id: file:packages/ai-parrot/src/parrot/registry/registry.py
  excerpt: |
    name: str
    factory: Union[Type[AbstractBot], AgentFactory]
    singleton: bool = False
    tags: Optional[Set[str]] = field(default_factory=set)
    priority: int = 0
    dependencies: List[str] = field(default_factory=list)
    bot_config: Optional[Any] = None
    events_block: Optional[Dict[str, Any]] = None
- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 258
  symbol: `AgentRegistry`
  excerpt: |
    class AgentRegistry:  # Central registry for managing Bot/Agent discovery and registration
- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 586
  symbol: `AgentRegistry.register_instance`
- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 659
  symbol: `AgentRegistry.get_instance`
  excerpt: |
    async def get_instance(self, name, request)  # PBAC-guarded (enforce_agent_access)
- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 1324-1334
  symbol: `AgentRegistry.register_bot_decorator`
  excerpt: |
    def register_bot_decorator(self, *, name=None, priority=0, dependencies=None,
        singleton=False, at_startup=False, startup_config=None, tags=None, **kwargs)
- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 1421
  symbol: `AgentRegistry.list_agents`
- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 1450
  symbol: `AgentRegistry.get_bots_by_tag`
  excerpt: |
    def get_bots_by_tag(self, tag: str) -> List[BotMetadata]

## Notes

ABSENCE: no `find_capability`, `capability`, `locality`, `kind`, `endpoint` symbol in the registry API outline (wiki) — grep lane should re-confirm (`[cross-lane: type=grep, intent=confirm absence of capability/kind/endpoint fields in registry/registry.py and registry/storage.py]`). `wiki_related` shows consumers: `bots/flows/result_agent.py`, `manager/studio_runtime.py`, `handlers/agents/data.py`, `bots/factory/tools/{finalize,introspection}.py`, `cli/loaders.py` — any entry-model extension must stay backward-compatible with these. Registry imports `..auth.agent_guard.enforce_agent_access` and `..tools.spec.{ToolkitSpec, AgentMCPServerSpec, normalize_tooling}` (per-agent tooling declarations exist — a natural slot for a 'contract' advertisement).
