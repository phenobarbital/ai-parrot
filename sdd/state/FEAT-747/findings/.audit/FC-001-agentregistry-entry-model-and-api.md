---
id: FC-001
query_id: Q021
type: read
intent: "Read the AgentRegistry implementation: entry model (kind, endpoint), register/lookup API, any capability/keyword index."
executed_at: 2026-10-26T00:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-001 — AgentRegistry entry model and API

## Summary

`parrot/registry/` holds `registry.py` (1499 lines, `AgentRegistry` + `BotMetadata` + `BotConfig`), `storage.py`, and two sub-packages `capabilities/` (semantic index for tools/datasets, FEAT-070) and `routing/`. `BotMetadata` is a dataclass keyed by name with `factory`, `singleton`, `tags`, `priority`, `dependencies`, `bot_config`, `events_block` — there is no `kind`, no endpoint/URL, no capability list, no locality. Lookup API is by name (`get_bot_instance`, `get_instance`, `has`, `get_metadata`) and by tag (`get_bots_by_tag`); `register()` also feeds PBAC policy collection via `_collect_and_register_policies`.

## Citations

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 50-71
  symbol: `BotMetadata`
  excerpt: |
    name: str
    factory: Union[Type[AbstractBot], AgentFactory]
    module_path: str
    file_path: Path
    singleton: bool = False
    tags: Optional[Set[str]] = field(default_factory=set)
    priority: int = 0
    at_startup: bool = False
    dependencies: List[str] = field(default_factory=list)
    bot_config: Optional[Any] = None  # Optional[BotConfig]

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 258-330
  symbol: `AgentRegistry.__init__`
  excerpt: |
    self._registered_agents: Dict[str, BotMetadata] = {}
    # PBAC: app and evaluator references (set via setup())
    self._app: Any = None
    self._evaluator: Any = None

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 526-584
  symbol: `AgentRegistry.register`
  excerpt: |
    def register(self, name: str, factory: Type[AbstractBot], *, singleton=False, tags=None,
                 priority=0, dependencies=None, replace=False, at_startup=False,
                 startup_config=None, bot_config=None, **kwargs) -> None:
        ...
        self._registered_agents[name] = metadata
        # PBAC: collect and register policy rules for this agent
        self._collect_and_register_policies(name, factory, bot_config)

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 519-524
  symbol: `AgentRegistry.get_bot_instance`
  excerpt: |
    def get_bot_instance(self, name: str) -> Optional[AbstractBot]:

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 1324-1420
  symbol: `AgentRegistry.register_bot_decorator`
  excerpt: |
    def register_bot_decorator(self, name=..., *, tags=None, ...)

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 1421-1452
  symbol: `AgentRegistry.list_agents / get_bots_by_tag`
  excerpt: |
    def list_agents(self) -> List[BotMetadata]:
    def list_agent_names(self) -> List[str]:
    def get_bots_by_tag(self, tag: str) -> List[BotMetadata]:
        return [metadata for metadata in self._registered_agents.values() if tag in metadata.tags]


## Notes

Q020 tree: `registry/{__init__,registry,storage}.py`, `registry/capabilities/{models,registry}.py`, `registry/routing/*`. The brainstorm's premise that AgentRegistry 'knows remote agents and their kind' is NOT borne out in core — remote/A2A agents live in `ToolManager._registered_agents` (see FC-014) and in the Matrix crew registry (FC-008). Capability search by keyword/cap-id and ranking by locality are absent (FC-002). See FC-019 for the `capabilities/` sub-package which is a *tool/dataset* semantic index, not an agent directory.
