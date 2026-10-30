---
id: FG-002
query_id: Q061
type: git_log
intent: "Recent activity on the registry (YAML definitions, remote kind)."
executed_at: 2026-10-30T16:41:30Z
duration_ms: 350
parent_id: null
depth: 0
---

# FG-002 — registry/: very active (15 commits in the last 4 days); AgentKind + remote entries just landed (FEAT-746/747)

## Summary

15 commits between 2026-10-26 and 2026-10-30 (all Jesus), i.e. the registry is under active change right now. Two feature streams: FEAT-746/747 inter-agent protocol (TASK-4750 added `AgentKind{LOCAL,A2A,SQUAWK}`, `BotMetadata.kind/endpoint/contract_categories`, `BotConfig.kind` with a `_kind_requirements` validator, `register_remote()`, `find_by_kind()`, YAML definitions of remote kind) and FEAT-?? inline-a2ui-component-routing (TASK-4757/4758/4759). Three review-fix commits on 2026-10-30 (PBAC before remote refusal, Roost capabilities, PUT fails loudly). Implication: any `ExpertManifest` discovery hook must be designed against the post-FEAT-746 registry (kind-aware entries, YAML-loaded BotConfig), and a parallel feature is still landing fixes there.

## Citations

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: n/a
  symbol: `AgentKind`, `BotMetadata`, `BotConfig._kind_requirements`, `AgentRegistry.register_remote`, `AgentRegistry.find_by_kind`
  excerpt: |
    0001fabb4 2026-10-26 Jesus feat(inter-agent-protocol): TASK-4750 — registry remote agent kind
    +class AgentKind(str, Enum): LOCAL = "local"; A2A = "a2a"; SQUAWK = "squawk"
    +    kind: AgentKind = AgentKind.LOCAL
    +    endpoint: Optional[str] = None
    +    contract_categories: List[str] = Field(default_factory=list)
    +    @model_validator(mode="after")
    +    def _kind_requirements(self) -> "BotConfig": ... class_name/module required for local; endpoint for remote
    +            if config.kind != AgentKind.LOCAL: self.register_remote(config)   # inside YAML loading
    +    def find_by_kind(self, kind: AgentKind) -> List[BotMetadata]:
    (files: registry/__init__.py, registry/registry.py, tests/registry/test_remote_kind.py)

- path: `packages/ai-parrot/src/parrot/registry/`
  lines: n/a
  symbol: commits
  excerpt: |
    a30ca3319 2026-10-30 fix(inter-agent-protocol): remote entries advertise Roost capabilities; PUT fails loudly
    f94a4a879 2026-10-30 fix(inter-agent-protocol): PBAC before the remote refusal; no endpoint leak
    defa729a4 2026-10-30 fix(inter-agent-protocol): FEAT-746 review follow-ups
    fced3204c/acb8475a5/125d87b3b 2026-10-27 feat(inline-a2ui-component-routing): TASK-4758/4759/4757
    634bb2e6c 2026-10-26 feat(local-inter-agent): TASK-4716 (CapabilityRegistry annotation fixes follow)

## Notes

- `BotConfig` is a Pydantic model already loaded from YAML agent definitions; it is the natural base/sibling for an `expert.yaml` manifest (a new `kind` or a separate model).
- Collision risk: FEAT-746/747 are still receiving review fixes on `registry.py` (2026-10-30) — an expert-discovery change should branch after they settle.
- [cross-lane: type=read, intent=read registry.py load_agent_definition_file / load_agents_from_dir to see how a directory of YAML definitions is discovered and whether duplicate names fail]
