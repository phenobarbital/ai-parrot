---
id: FW-003
query_id: Q003
type: wiki_page
intent: "AgentRegistry API outline: discovery, YAML definitions, kinds"
executed_at: 2026-10-30T16:47:12Z
duration_ms: 400
parent_id: null
depth: 0
---

# FW-003 — AgentRegistry discovers by directory import + YAML `agent:` definitions, keeps `BotMetadata` with `kind` (LOCAL/remote), and already mutates PromptBuilder layers from YAML (`PromptConfig`)

## Summary

`AgentRegistry` (registry.py:L302-1710) scans `agents_dir` (default `BASE_DIR/agents`) plus `extra_agent_dirs`, imports modules (`load_modules`), and loads YAML definitions (`load_agent_definitions` :1003, `load_agent_definition_file` :1025-1119) into `BotConfig` (:256) → `BotMetadata` (:68, with `kind: AgentKind`). `register_remote` (:1522) registers non-local kinds that never instantiate. `PromptConfig` (:243-253: `preset`, `remove`, `add`, `customize`) is applied by `_apply_prompt_config` (:841-901) — YAML can already remove/add/customize prompt layers, including inline `PromptLayer` dicts. The registry also carries a capability index (`capability_registry`, `find_capability`, `_mirror_roost` FEAT-747) and PBAC policy registration.

## Citations

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

## Notes

The registry is already a *directory-discovered, YAML-validated* manifest loader with a `kind` discriminator — the source's "expert.yaml discovered by presence and validated with Pydantic" maps onto adding an `AgentKind`/manifest variant (or a sibling `ExpertRegistry` feeding it) rather than a new registry. The YAML `prompt:` block is the existing hook for persona-as-layer.
