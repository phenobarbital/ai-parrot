---
id: F006
query_id: Q025
type: read
intent: "Read AgentRegistry: discovery by directory, YAML definition loading, duplicate-name handling."
executed_at: 2026-10-30T16:42:58Z
duration_ms: 1500
parent_id: null
depth: 0
merged_from: [FC-006-agentregistry-yaml-definitions, FW-003-agentregistry-api, FW-004-agentregistry-neighbours]
---

# F006 — AgentRegistry: `BotConfig` Pydantic manifest, `agents.yaml` + `AGENTS_DIR/agents/**/*.yaml` definitions, duplicate names warn (not fail) unless `replace=True`

## Summary

*[FC-006-agentregistry-yaml-definitions]* `registry.py` (1710 lines). `BotConfig` (lines 256-300) is the existing declarative agent manifest: name, class_name/module, enabled, origin repo|factory, config, tools/toolkits/mcp_servers, model, system_prompt, `prompt: PromptConfig` (preset/remove/add/customize layers), vector_store, tags, priority, policies (PBAC), kind local|remote, contract_categories, roost. `load_agent_definitions()` rglobs `AGENTS_DIR/agents/*.yaml` and `load_agent_definition_file()` needs an `agent:` top key; per-file errors are logged and skipped. `register()`/`register_instance()` on an existing name log a warning and keep the old one unless `replace=True` — the source's "duplicate names fail on load" would be a stricter rule. `create_agent_definition()` writes `{name}.yaml` losslessly; `update_agent_tooling` refuses non-editable paths.

*[FW-003-agentregistry-api]* `AgentRegistry` (registry.py:L302-1710) scans `agents_dir` (default `BASE_DIR/agents`) plus `extra_agent_dirs`, imports modules (`load_modules`), and loads YAML definitions (`load_agent_definitions` :1003, `load_agent_definition_file` :1025-1119) into `BotConfig` (:256) → `BotMetadata` (:68, with `kind: AgentKind`). `register_remote` (:1522) registers non-local kinds that never instantiate. `PromptConfig` (:243-253: `preset`, `remove`, `add`, `customize`) is applied by `_apply_prompt_config` (:841-901) — YAML can already remove/add/customize prompt layers, including inline `PromptLayer` dicts. The registry also carries a capability index (`capability_registry`, `find_capability`, `_mirror_roost` FEAT-747) and PBAC policy registration.

*[FW-004-agentregistry-neighbours]* `wiki_related` lists the registry's `contains` edges: lifecycle (`register`, `register_bot_decorator`, `register_instance`, `register_remote`, `unregister`, `clear_registry`), discovery (`load_modules`, `load_agent_definitions`, `load_agent_definition_file`, `discover_config_agents`, `load_config`), persistence (`create_agent_definition` "lossless YAML", `delete_factory_agent`, `update_agent_tooling` FEAT-593), lookup (`get_instance`, `get_metadata`, `find_by_kind`, `find_capability`, `find_serving`, `get_bots_by_tag`, `list_bots_by_priority`), PBAC (`_collect_and_register_policies`, `register_db_bot_policies`, `evaluator`), Roost (`capability_registry`, `_mirror_roost`). Inbound `calls` come from `ExecutionPlanToolkit._get_agent_registry`, Studio tests (`test_agents_lifecycle`, `test_drafts_d3`), server handler `test_put_registry_remote_kind`, roost directory-lookup tests.

## Citations

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 243-253
  symbol: `PromptConfig`
  excerpt: |
    class PromptConfig(BaseModel):
        preset: str = "default"
        remove: List[str]; add: List[Union[str, Dict[str, Any]]]; customize: Dict[str, Dict[str, Any]]

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 256-300
  symbol: `BotConfig`
  excerpt: |
    class BotConfig(BaseModel):
        name: str; class_name: Optional[str]; module: Optional[str]; enabled: bool = True
        origin: Literal["repo", "factory"] = "repo"
        tools: Optional[ToolConfig]; toolkits: List[Union[str, ToolkitSpec]]; mcp_servers: ...
        model: Optional[ModelConfig]; system_prompt: ...; prompt: Optional[PromptConfig]
        tags: Optional[Set[str]]; priority: int = 0; policies: Optional[List["PolicyRuleConfig"]]
        kind: AgentKind = AgentKind.LOCAL; endpoint: Optional[str]; contract_categories: List[str]

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 570-592
  symbol: `AgentRegistry.register`
  excerpt: |
    self.logger.warning(f"Bot {name} already registered, use replace=True to overwrite")

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 1003-1060
  symbol: `AgentRegistry.load_agent_definitions / load_agent_definition_file`
  excerpt: |
    if not definitions_dir: definitions_dir = AGENTS_DIR.joinpath("agents")
    for yaml_file in definitions_dir.rglob("*.yaml"): ... self.load_agent_definition_file(yaml_file)
    agent_def = content.get("agent")   # file must have an 'agent:' section

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 1121-1159
  symbol: `AgentRegistry.create_agent_definition`
  excerpt: |
    filename = f"{config.name.lower()}.yaml"

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 55-68
  symbol: `AgentKind / BotMetadata`
  excerpt: |
    class AgentKind(str, Enum): ...
    class BotMetadata: ... "information about agents found during discovery"

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 302-1710
  symbol: `AgentRegistry`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry
  score: 1.00
  excerpt: |
    def __init__(self, agents_dir: Optional[Path] = None, *, extra_agent_dirs: Optional[Iterable[Path]] = None):
        self.agents_dir = agents_dir or BASE_DIR / "agents"
        self._registered_agents: Dict[str, BotMetadata] = {}
        self._discovery_paths: List[Path] = []

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 841-901
  symbol: `AgentRegistry._apply_prompt_config`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry._apply_prompt_config
  score: 1.00
  excerpt: |
    def _apply_prompt_config(bot: AbstractBot, prompt_config: PromptConfig) -> None:
        builder = bot._prompt_builder
        if builder is None and has_prompt_mutations:
            builder = get_preset(prompt_config.preset or "default")
        for layer_name in prompt_config.remove: builder.remove(layer_name)
        for item in prompt_config.add:  # str -> get_domain_layer(item); dict -> inline PromptLayer

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 1025-1119
  symbol: `AgentRegistry.load_agent_definition_file`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.load_agent_definition_file
  score: 1.00
  excerpt: |
    def load_agent_definition_file(self, yaml_file: Path) -> bool:
        content = yaml.safe_load(yaml_file.read_text())
        agent_def = content.get("agent")
        if "model" in content: bot_config_data["model"] = ModelConfig(**content["model"])
        if "tools" in content: bot_config_data["tools"] = ToolConfig(**content["tools"])

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 243-285
  symbol: `PromptConfig` / `BotConfig`
  excerpt: |
    class PromptConfig(BaseModel):        # :243
        preset: str = "default"
        remove: List[str]; add: List[Union[str, Dict]]; customize: Dict[str, Dict]
    class BotConfig(BaseModel):           # :256
        kind: AgentKind = AgentKind.LOCAL  # :285

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

*[FC-006-agentregistry-yaml-definitions]* An `ExpertManifest` could either extend `BotConfig` (new `kind`) or sit beside it with its own loader; `PromptConfig.add/customize` already lets YAML inject custom layers.

*[FW-003-agentregistry-api]* The registry is already a *directory-discovered, YAML-validated* manifest loader with a `kind` discriminator — the source's "expert.yaml discovered by presence and validated with Pydantic" maps onto adding an `AgentKind`/manifest variant (or a sibling `ExpertRegistry` feeding it) rather than a new registry. The YAML `prompt:` block is the existing hook for persona-as-layer.

*[FW-004-agentregistry-neighbours]* Studio (admin UI) and BotManager persist/reload agents through `create_agent_definition`/`load_agent_definition_file`; an expert bundle that is also YAML-round-trippable would inherit the Studio create/edit flow for free. `get_bots_by_tag` is an existing tag index usable for "visible but inert" experts.
