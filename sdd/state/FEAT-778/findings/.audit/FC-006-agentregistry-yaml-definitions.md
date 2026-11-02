---
id: FC-006
query_id: Q025
type: read
intent: "Read AgentRegistry: discovery by directory, YAML definition loading, duplicate-name handling."
executed_at: 2026-10-30T16:42:58Z
duration_ms: 1500
parent_id: null
depth: 0
---

# FC-006 — AgentRegistry: `BotConfig` Pydantic manifest, `agents.yaml` + `AGENTS_DIR/agents/**/*.yaml` definitions, duplicate names warn (not fail) unless `replace=True`

## Summary

`registry.py` (1710 lines). `BotConfig` (lines 256-300) is the existing declarative agent manifest: name, class_name/module, enabled, origin repo|factory, config, tools/toolkits/mcp_servers, model, system_prompt, `prompt: PromptConfig` (preset/remove/add/customize layers), vector_store, tags, priority, policies (PBAC), kind local|remote, contract_categories, roost. `load_agent_definitions()` rglobs `AGENTS_DIR/agents/*.yaml` and `load_agent_definition_file()` needs an `agent:` top key; per-file errors are logged and skipped. `register()`/`register_instance()` on an existing name log a warning and keep the old one unless `replace=True` — the source's "duplicate names fail on load" would be a stricter rule. `create_agent_definition()` writes `{name}.yaml` losslessly; `update_agent_tooling` refuses non-editable paths.

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

## Notes

An `ExpertManifest` could either extend `BotConfig` (new `kind`) or sit beside it with its own loader; `PromptConfig.add/customize` already lets YAML inject custom layers.
