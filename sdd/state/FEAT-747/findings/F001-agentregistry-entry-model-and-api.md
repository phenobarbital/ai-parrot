---
id: F001
query_id: Q021, Q022, Q050, Q001
type: read, grep, git_log, wiki_page
intent: "Read the AgentRegistry implementation: entry model (kind, endpoint), register/lookup API, any capability/keyword index."
executed_at: 2026-10-25T23:08:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: FC-001, FC-002, FG-001, FW-001
---

# F001 — AgentRegistry entry model and API

## Summary

**[FC-001] AgentRegistry entry model and API** — `parrot/registry/` holds `registry.py` (1499 lines, `AgentRegistry` + `BotMetadata` + `BotConfig`), `storage.py`, and two sub-packages `capabilities/` (semantic index for tools/datasets, FEAT-070) and `routing/`. `BotMetadata` is a dataclass keyed by name with `factory`, `singleton`, `tags`, `priority`, `dependencies`, `bot_config`, `events_block` — there is no `kind`, no endpoint/URL, no capability list, no locality. Lookup API is by name (`get_bot_instance`, `get_instance`, `has`, `get_metadata`) and by tag (`get_bots_by_tag`); `register()` also feeds PBAC policy collection via `_collect_and_register_policies`.

**[FC-002] Absence: no capability search, locality or remote kind in AgentRegistry** — Pattern `find_capability|capabilit|locality|kind\s*[:=]|remote_agent|RemoteAgent|a2a` (case-insensitive) over `registry/registry.py` and `registry/storage.py`: **zero matches**. A looser probe `remote|endpoint|url|capabilities|tags|categories` on `registry.py` matches only `tags` (lines 63, 247, 532, 574, 591, 613, 766, 1045, 1333, 1396, 1452, 1464-1466). The VERIFY claim holds: AgentRegistry indexes agents by name and tag only; there is no capability id, no category hash, no locality tier and no remote/a2a kind on the entry.

**[FG-001] AgentRegistry history (180 days): PBAC enforcement, AgentStudio YAML round-trip, a `capabilities/` + `routing/` sub-package** — 22 commits since 2026-04-28, all by Jesus Lara / Claude / Javier León. Dominant themes: (1) PBAC enforcement in `AgentRegistry.get_instance` and DB-backed bot policies (FEAT-153, May 2026); (2) AgentStudio management — registry primitives, lossless YAML round-trip, `update_agent_tooling()` atomic rewrite, "normalize factory" (TASK-2509/3656/3657, Aug–Sep 2026); (3) a public agent enumerator and tool catalog fix (Aug 17). The log also reveals two sub-packages the brainstorm does not mention: `registry/capabilities/models.py` (IntentRouterConfig, June 2026) and `registry/routing/` (EmbeddingIntentRouter, StoreRouter, cache, rules). So "capabilities" already exists as a name in the registry — but for intent-routing config, not a capability directory. Last change 2026-09-23; the module is stable, not under active edit.

**[FW-001] AgentRegistry registers agents by decorator/YAML; NO capability index, NO locality ranking, NO remote-agent kind** — `parrot.registry` exports a global `agent_registry = AgentRegistry(agents_dir=AGENTS_DIR, extra_agent_dirs=[PLUGINS_DIR/'agents'])` and `register_agent = agent_registry.register_bot_decorator`. The registry (`registry/registry.py`, class at l.258) is keyed by **name**; a `BotMetadata` entry (l.50) carries `name, factory, module_path, file_path, singleton, tags, priority, at_startup, dependencies, startup_config, bot_config, events_block`. The decorator (l.1324) accepts `name, priority, dependencies, singleton, at_startup, startup_config, tags`. Lookup API is `register / register_instance (l.586) / has / unregister / get_metadata / get_instance (l.659, async, PBAC-guarded via agent_guard.enforce_agent_access) / get_bot_instance / list_agents (l.1421) / list_agent_names / list_bots_by_priority / get_bots_by_tag (l.1450)`. The only discovery-by-attribute is `get_bots_by_tag`. The API outline contains **no** `find_capability`, no capability ids/hashes, no `kind` (local/remote/a2a) field, no endpoint field, no locality/cost ranking — the brainstorm's VERIFY claim 'AgentRegistry does not index capabilities or rank by locality' is CONFIRMED; its D10 claim that the registry 'already registers remote agents and their kind' is NOT supported by the core registry (remote discovery lives in `parrot.a2a.mesh`, see FW-009). PBAC is wired in: `evaluator()`, `setup(app)`, `_collect_and_register_policies`, `register_db_bot_policies`.


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

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 1450-1452
  symbol: `AgentRegistry.get_bots_by_tag`
  excerpt: |
    def get_bots_by_tag(self, tag: str) -> List[BotMetadata]:
        return [metadata for metadata in self._registered_agents.values() if tag in metadata.tags]

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 1459-1469
  symbol: `AgentRegistry.get_registration_info`
  excerpt: |
    "by_tags": {
        tag: [name for name, metadata in self._registered_agents.items() if tag in metadata.tags]
        for tag in set().union(*(metadata.tags for metadata in self._registered_agents.values()))

- sha: `0c4f5ebb5d` date: 2026-05-07 author: Jesus Lara — feat(botmanager-pbac-permissions): TASK-1054 — AgentRegistry.get_instance enforcement — files: `packages/ai-parrot/src/parrot/registry/registry.py`

- sha: `fc304d5267` date: 2026-05-07 author: Jesus Lara — feat(botmanager-pbac-permissions): TASK-1051 — AgentRegistry.register_db_bot_policies — files: `registry/registry.py`

- sha: `546c277917` date: 2026-05-15 author: Jesus Lara — feat(lifecycle-events-system): TASK-1196 — BotManager YAML events loader — files: `registry/registry.py`

- sha: `04cd4a47bd` date: 2026-06-05 author: Jesus Lara — feat(intent-router): TASK-1485 — extend IntentRouterConfig with output-mode fields — files: `registry/capabilities/models.py`

- sha: `9b9c16db7d` date: 2026-06-05 author: Jesus Lara — feat(intent-router): TASK-1484 — EmbeddingIntentRouter engine — files: `registry/routing/embedding_router.py`

- sha: `cb81523d7b` date: 2026-07-27 author: Jesus — TASK-1931 — StoreRouter & AbstractBot decoupling via MultiSearch protocol — files: `registry/routing/store_router.py`

- sha: `b9735c6f59` date: 2026-08-17 author: Claude — feat(registry): add a public agent enumerator; fix the tool catalog — files: `registry/registry.py`

- sha: `6571889ebb` date: 2026-08-27 author: Jesus Lara — feat(agentstudio-management): TASK-2509 — Registry primitives + lossless YAML round-trip — files: `registry/registry.py`

- sha: `f638ba6fad` date: 2026-09-23 author: Jesus — TASK-3657 — AgentRegistry.update_agent_tooling() in-place atomic YAML rewrite — files: `registry/registry.py`

- sha: `2c65632c39` date: 2026-09-23 author: Jesus — fix: resolve pre-existing F841/F811 in registry.py — files: `registry/registry.py`

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  symbol: `AgentRegistry`
  excerpt: |
    (file identified by all registry commits; holds get_instance PBAC enforcement,
     register_db_bot_policies, update_agent_tooling, public agent enumerator)

- path: `packages/ai-parrot/src/parrot/registry/capabilities/models.py`
  symbol: `IntentRouterConfig`
  excerpt: |
    (identified by 04cd4a47bd; "capabilities" here = intent-router config, not a capability directory)

- path: `packages/ai-parrot/src/parrot/registry/routing/embedding_router.py`
  symbol: `EmbeddingIntentRouter`

- path: `packages/ai-parrot/src/parrot/registry/routing/store_router.py`
  symbol: `StoreRouter`

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

[FC-001] Q020 tree: `registry/{__init__,registry,storage}.py`, `registry/capabilities/{models,registry}.py`, `registry/routing/*`. The brainstorm's premise that AgentRegistry 'knows remote agents and their kind' is NOT borne out in core — remote/A2A agents live in `ToolManager._registered_agents` (see FC-014) and in the Matrix crew registry (FC-008). Capability search by keyword/cap-id and ranking by locality are absent (FC-002). See FC-019 for the `capabilities/` sub-package which is a *tool/dataset* semantic index, not an agent directory.

[FC-002] `capabilit` DOES match inside `registry/capabilities/` (excluded from this probe) — that sub-package is the FEAT-070 `CapabilityRegistry` for datasets/tools (FC-019), a natural seed for `find_capability` but it does not index agents today.

[FG-001] - The name collision matters for the spec: `registry.capabilities` is already taken by intent-routing models; a capability *directory* needs a distinct name or must extend these models deliberately.
- PBAC already gates `AgentRegistry.get_instance` (TASK-1054) — a natural anchor for the "inter-agent communication grant".
- [cross-lane: type=read, intent=read registry/capabilities/models.py and registry/registry.py get_instance to see what PBAC enforcement and 'capabilities' currently mean]
- [cross-lane: type=wiki_query, intent=EmbeddingIntentRouter / IntentRouterMixin — could be the harness-side 'find who answers' without an LLM]

[FW-001] ABSENCE: no `find_capability`, `capability`, `locality`, `kind`, `endpoint` symbol in the registry API outline (wiki) — grep lane should re-confirm (`[cross-lane: type=grep, intent=confirm absence of capability/kind/endpoint fields in registry/registry.py and registry/storage.py]`). `wiki_related` shows consumers: `bots/flows/result_agent.py`, `manager/studio_runtime.py`, `handlers/agents/data.py`, `bots/factory/tools/{finalize,introspection}.py`, `cli/loaders.py` — any entry-model extension must stay backward-compatible with these. Registry imports `..auth.agent_guard.enforce_agent_access` and `..tools.spec.{ToolkitSpec, AgentMCPServerSpec, normalize_tooling}` (per-agent tooling declarations exist — a natural slot for a 'contract' advertisement).
