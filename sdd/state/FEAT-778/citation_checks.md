# Citation checks — FEAT-778 (sdd-proposal §4d/§5b)

Probe sheet: 163 checks in 4 groups (`probe_group_0..3.json`), run by `sdd-contract-probe` at HEAD 46f2056c0.

| Class | Count | Meaning |
|---|---:|---|
| verified (symbol found, signature matches excerpt) | 98 | def/class located at the cited line |
| verified (file exists / line count ≥ cited) | 11 | includes 3 directory paths (wc error on a dir = exists) |
| not probeable — module constant / attribute / ContextVar | 11 | def/class grep cannot see assignments; verified by the finding's own excerpt, not tagged |
| not probeable — descriptive label used as `symbol` | 42 | probe-sheet artefact (e.g. `commits`, `docstring`, `fields`); the *path* exists in every case except c125 |

## Stale / missing

- **c125** `packages/ai-parrot/src/parrot/skills/` — the probe agent ran the command against a mistyped path (`src/skills/`); the sheet and F034 carry the correct path, which exists. Not a stale citation. **Result: 0 stale, 0 missing — no finding tagged; the §5b re-assembly equals the provisional one.**

## Notable confirmations

- `SpawnSubAgentTool.__init__(..., name: str = "spawn_sub_agent", ...)` (tools/spawn.py:122) — resolves FW-013's unconfirmed tool-name string: the registered name is `spawn_sub_agent`, not `spawn_agent`.
- `AgentRegistry.register(..., replace: bool = False, ...)` (registry.py:570) — duplicate names warn, do not fail.
- `SessionHost.open_gate(*, kind: GateKind, node_id: NodeId, ..., on_expiry: Literal['fail','approve']='fail', questions=...)` (session_state.py:1502-1513).
- `LLMWikiToolkit.query(self, wiki_name, question, file_answer=False, mode='combined')` (parrot_tools/wiki/toolkit.py:373) — no tag filter parameter.
- `DecisionService.why(question, *, include_history=False, limit=10, budget_tokens=3000)` (decisions/service.py:276).
- `AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin, EventEmitterMixin, ToolInterface, VectorInterface, ABC)` (abstract.py:216) — `LocalKBMixin` is the local-KB registration seam.

## Check → finding map

- c0 [symbol] `packages/ai-parrot/src/parrot/bots/prompts/builder.py` :: `__init__` → F001
- c1 [symbol] `packages/ai-parrot/src/parrot/bots/prompts/builder.py` :: `default` → F001
- c2 [symbol] `packages/ai-parrot/src/parrot/bots/prompts/builder.py` :: `from_system_prompt` → F001
- c3 [symbol] `packages/ai-parrot/src/parrot/bots/prompts/builder.py` :: `replace` → F001
- c4 [symbol] `packages/ai-parrot/src/parrot/bots/prompts/builder.py` :: `build` → F001
- c5 [symbol] `packages/ai-parrot/src/parrot/bots/mixins/identity.py` :: `IdentityMixin` → F002
- c6 [symbol] `packages/ai-parrot/src/parrot/bots/mixins/identity.py` :: `__init__` → F002
- c7 [symbol] `packages/ai-parrot/src/parrot/bots/mixins/identity.py` :: `_resolve_identity_dir` → F002
- c8 [symbol] `packages/ai-parrot/src/parrot/bots/mixins/identity.py` :: `_reload_identity` → F002
- c9 [symbol] `packages/ai-parrot/src/parrot/bots/prompts/identity.py` :: `IdentityFields` → F002
- c10 [symbol] `sdd/specs/promptbuilder-identity-capability.spec.md` :: `CAPABILITIES_LAYER` → F002
- c11 [symbol] `packages/ai-parrot/src/parrot/bots/abstract.py` :: `register_kb` → F003
- c12 [symbol] `packages/ai-parrot/src/parrot/bots/abstract.py` :: `configure_kb` → F003
- c13 [symbol] `packages/ai-parrot/src/parrot/bots/abstract.py` :: `AbstractBot` → F003
- c14 [symbol] `packages/ai-parrot/src/parrot/bots/stores/local.py` :: `registration` → F003
- c15 [symbol] `packages/ai-parrot/src/parrot/stores/kb/abstract.py` :: `AbstractKnowledgeBase` → F003
- c16 [symbol] `packages/ai-parrot/src/parrot/bots/kb.py` :: `KBSelector` → F004
- c17 [symbol] `packages/ai-parrot/src/parrot/conf.py` :: `AGENTS_DIR` → F005
- c18 [symbol] `packages/ai-parrot/src/parrot/bots/agent.py` :: `Agent` → F005, F019
- c19 [symbol] `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` :: `skill_paths` → F005
- c20 [symbol] `packages/ai-parrot/src/parrot/bots/flows/flow/loader.py` :: `loader` → F005
- c21 [symbol] `packages/ai-parrot/src/parrot/bots/stores/local.py` :: `dir` → F005
- c22 [symbol] `packages/ai-parrot/src/parrot/registry/registry.py` :: `PromptConfig` → F006
- c23 [symbol] `packages/ai-parrot/src/parrot/registry/registry.py` :: `BotConfig` → F006
- c24 [symbol] `packages/ai-parrot/src/parrot/registry/registry.py` :: `register` → F006
- c25 [symbol] `packages/ai-parrot/src/parrot/registry/registry.py` :: `load_agent_definition_file` → F006
- c26 [symbol] `packages/ai-parrot/src/parrot/registry/registry.py` :: `create_agent_definition` → F006
- c27 [symbol] `packages/ai-parrot/src/parrot/registry/registry.py` :: `BotMetadata` → F006
- c28 [symbol] `packages/ai-parrot/src/parrot/registry/registry.py` :: `AgentRegistry` → F006
- c29 [symbol] `packages/ai-parrot/src/parrot/registry/registry.py` :: `_apply_prompt_config` → F006
- c30 [symbol] `packages/ai-parrot/src/parrot/registry/registry.py` :: `load_agent_definition_file` → F006
- c31 [symbol] `packages/ai-parrot/src/parrot/registry/registry.py` :: `update_agent_tooling` → F006
- c32 [symbol] `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` :: `_get_agent_registry` → F006
- c33 [symbol] `packages/ai-parrot/src/parrot/registry/registry.py` :: `get_bots_by_tag` → F006
- c34 [symbol] `packages/ai-parrot/src/parrot/skills/loader.py` :: `SkillsDirectoryLoader` → F007
- c35 [symbol] `packages/ai-parrot/src/parrot/skills/loader.py` :: `load_into` → F007
- c36 [symbol] `packages/ai-parrot/src/parrot/skills/models.py` :: `SkillDefinition` → F008
- c37 [symbol] `packages/ai-parrot/src/parrot/skills/models.py` :: `SkillVersion` → F008
- c38 [symbol] `packages/ai-parrot/src/parrot/skills/models.py` :: `Skill` → F008
- c39 [symbol] `packages/ai-parrot/src/parrot/skills/tenancy.py` :: `tenant_skills_dir` → F008
- c40 [symbol] `packages/ai-parrot/src/parrot/skills/tenancy.py` :: `SkillView` → F008
- c41 [symbol] `packages/ai-parrot/src/parrot/skills/tenancy.py` :: `bind_skill_tenant` → F008
- c42 [symbol] `packages/ai-parrot/src/parrot/skills/parsers.py` :: `parse_skill_file` → F008
- c43 [symbol] `sdd/proposals/per-tenant-skills.brainstorm.md` :: `skills` → F008
- c44 [symbol] `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py` :: `DecisionRecord` → F009, F043
- c45 [symbol] `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py` :: `EvidenceRef` → F009
- c46 [symbol] `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py` :: `GenerationInfo` → F009
- c47 [symbol] `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py` :: `ReviewRequest` → F009
- c48 [symbol] `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/toolkit.py` :: `__getattr__` → F010
- c49 [symbol] `packages/ai-parrot/src/parrot/knowledge/retrieval/__init__.py` :: `docstring` → F011
- c50 [file] `packages/ai-parrot/src/parrot/knowledge/retrieval/__init__.py` → F011
- c51 [symbol] `packages/ai-parrot/src/parrot/knowledge/bookstore/models.py` :: `BookCard` → F012, F027
- c52 [symbol] `packages/ai-parrot/src/parrot/knowledge/contracts/models.py` :: `source_sha256` → F012
- c53 [symbol] `packages/ai-parrot/src/parrot/knowledge/contracts/models.py` :: `identity` → F012
- c54 [symbol] `packages/ai-parrot/src/parrot/knowledge/retrieval/digest.py` :: `derive_digest` → F012
- c55 [symbol] `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` :: `hashing` → F012
- c56 [symbol] `packages/ai-parrot/src/parrot/knowledge/contracts/models.py` :: `ContractCard` → F012
- c57 [symbol] `packages/ai-parrot/src/parrot/models/crew_definition.py` :: `AgentDefinition` → F013
- c58 [symbol] `packages/ai-parrot/src/parrot/models/crew_definition.py` :: `CrewDefinition` → F013
- c59 [symbol] `packages/ai-parrot/src/parrot/bots/flows/crew/nodes.py` :: `CrewAgentNode` → F013
- c60 [symbol] `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` :: `from_definition` → F014
- c61 [symbol] `packages/ai-parrot/src/parrot/models/crew_definition.py` :: `ExecutionMode` → F014
- c62 [symbol] `packages/ai-parrot-server/src/parrot/manager/manager.py` :: `_create_crew_from_definition` → F014
- c63 [symbol] `packages/ai-parrot/src/parrot/flows/dev_flow/definition.py` :: `docstring` → F015
- c64 [symbol] `packages/ai-parrot/src/parrot/flows/dev_flow/definition.py` :: `_dev_loop_node` → F015
- c65 [symbol] `packages/ai-parrot/src/parrot/flows/dev_flow/definition.py` :: `build_dev_flow_definition` → F015
- c66 [symbol] `packages/ai-parrot/src/parrot/flows/dev_loop/definition.py` :: `CLOSE` → F015
- c67 [symbol] `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py` :: `ApprovalGate` → F016
- c68 [symbol] `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py` :: `kinds` → F016
- c69 [symbol] `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py` :: `GateExpired` → F016
- c70 [symbol] `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py` :: `wait_gate` → F016
- c71 [symbol] `sdd/specs/agent-host-protocol-session-state.spec.md` :: `SessionHost` → F016
- c72 [symbol] `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py` :: `open_gate` → F016
- c73 [symbol] `packages/ai-parrot/src/parrot/human/models.py` :: `ConsensusMode` → F017
- c74 [symbol] `packages/ai-parrot/src/parrot/human/models.py` :: `EscalationPolicy` → F017
- c75 [symbol] `packages/ai-parrot/src/parrot/human/models.py` :: `HumanInteraction` → F017
- c76 [symbol] `packages/ai-parrot/src/parrot/tools/spawn.py` :: `SpawnSubAgentInput` → F018
- c77 [symbol] `packages/ai-parrot/src/parrot/tools/spawn.py` :: `__init__` → F018
- c78 [symbol] `packages/ai-parrot/src/parrot/tools/spawn.py` :: `_compute_effective_tools` → F018
- c79 [symbol] `packages/ai-parrot/src/parrot/memory/compaction/policies.py` :: `mention` → F018
- c80 [symbol] `packages/ai-parrot/src/parrot/tools/manager.py` :: `ToolManager` → F019
- c81 [symbol] `packages/ai-parrot/src/parrot/tools/host_hooks.py` :: `allowed_tools` → F019
- c82 [symbol] `packages/ai-parrot/src/parrot/tools/mcp_mixin.py` :: `allowed_tools` → F019
- c83 [symbol] `packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py` :: `LLMWikiToolkit` → F020
- c84 [symbol] `packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py` :: `__init__` → F020
- c85 [symbol] `packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py` :: `_search_for` → F020
- c86 [symbol] `packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py` :: `query` → F020
- c87 [symbol] `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` :: `WikiToolBundle` → F020
- c88 [symbol] `packages/ai-parrot/src/parrot/observability/context.py` :: `current_tenant` → F021
- c89 [symbol] `packages/ai-parrot/src/parrot/observability/context.py` :: `invocation_context` → F021
- c90 [symbol] `packages/ai-parrot/src/parrot/observability/context.py` :: `usage_attribution` → F021
- c91 [symbol] `packages/ai-parrot/src/parrot/clients/base.py` :: `_lightweight_model` → F022
- c92 [symbol] `packages/ai-parrot/src/parrot/clients/base.py` :: `_resolve_invoke_model` → F022
- c93 [symbol] `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/legal.ontology.yaml` :: `header` → F023
- c94 [symbol] `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/contracts.ontology.yaml` :: `ontology` → F023
- c95 [symbol] `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/procedures.ontology.yaml` :: `ontology` → F023
- c96 [symbol] `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/field_services.ontology.yaml` :: `ontology` → F023
- c97 [symbol] `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py` :: `docstring` → F024
- c98 [symbol] `packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py` :: `models` → F024
- c99 [symbol] `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid_c4.py` :: `mermaid` → F024
- c100 [symbol] `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/mermaiddiagram.py` :: `component` → F024
- c101 [symbol] `.claude/agents/sdd-secondopinion.md` :: `frontmatter` → F025
- c102 [symbol] `.claude/agents/sdd-secondopinion.md` :: `rules` → F025
- c103 [symbol] `packages/ai-parrot/src/parrot/memory/compaction/budget.py` :: `resolve_window` → F026
- c104 [symbol] `packages/ai-parrot/src/parrot/memory/compaction/budget.py` :: `compaction_disabled_by_env` → F026
- c105 [symbol] `packages/ai-parrot/src/parrot/memory/compaction/budget.py` :: `apply_commit` → F026
- c106 [symbol] `packages/ai-parrot/src/parrot/knowledge/bookstore/models.py` :: `fields` → F027
- c107 [symbol] `packages/ai-parrot/src/parrot/knowledge/bookstore/models.py` :: `RelateSummary` → F027
- c108 [symbol] `packages/ai-parrot-tools/src/parrot_tools/contracts/agent.py` :: `ContractsAgent` → F028, F049
- c109 [symbol] `packages/ai-parrot-tools/src/parrot_tools/contracts/agent.py` :: `ContractsAgentProducer` → F028
- c110 [symbol] `packages/ai-parrot-tools/src/parrot_tools/contracts/toolkit.py` :: `ContractsToolkit` → F028
- c111 [symbol] `packages/ai-parrot-tools/src/parrot_tools/legal/librarian/agent.py` :: `LegalLibrarianAgent` → F028
- c112 [symbol] `tests/unit/test_skills_directory_loader.py` :: `fixture` → F029
- c113 [symbol] `tests/unit/test_skills_directory_loader.py` :: `test_discover_nonexistent_path` → F029
- c114 [symbol] `.claude/commands/sdd-spec.md` :: `command` → F030
- c115 [symbol] `.claude/commands/sdd-proposal.md` :: `command` → F030
- c116 [symbol] `packages/ai-parrot/src/parrot/bots/prompts/layers.py` :: `PromptLayer` → F031
- c117 [symbol] `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py` :: `TOOLLESS_DATA_GROUNDING_LAYER` → F031
- c118 [symbol] `packages/ai-parrot/src/parrot/bots/prompts/` :: `commits` → F031
- c119 [symbol] `packages/ai-parrot/src/parrot/registry/registry.py` :: `AgentKind` → F032
- c120 [symbol] `packages/ai-parrot/src/parrot/registry/` :: `commits` → F032
- c121 [symbol] `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py` :: `_normalize_prefix` → F033
- c122 [symbol] `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/` :: `commits` → F033
- c123 [symbol] `packages/ai-parrot/src/parrot/skills/mixin.py` :: `SkillRegistryMixin` → F034
- c124 [symbol] `packages/ai-parrot/src/parrot/skills/tenancy.py` :: `views` → F034
- c125 [symbol] `packages/ai-parrot/src/parrot/skills/` :: `commits` → F034
- c126 [symbol] `packages/ai-parrot/src/parrot/knowledge/retrieval/` :: `DirectSymbolPolicy` → F035
- c127 [symbol] `packages/ai-parrot/src/parrot/knowledge/retrieval/pin.py` :: `capability` → F035
- c128 [symbol] `packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_data/sdd-ideation.md` :: `brief` → F036
- c129 [symbol] `packages/ai-parrot/src/parrot/flows/dev_flow/` :: `commits` → F036
- c130 [file] `packages/ai-parrot/src/parrot/bots/kb.py` → F037
- c131 [file] `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` → F038
- c132 [symbol] `packages/ai-parrot/src/parrot/knowledge/bookstore/` :: `commits` → F038
- c133 [symbol] `packages/ai-parrot/src/parrot/human/` :: `package` → F039
- c134 [file] `sdd/proposals/domain-experts.proposal.md` → F040
- c135 [file] `sdd/specs/per-tenant-skills.spec.md` → F040
- c136 [file] `sdd/specs/adr-prefixed-aliases.spec.md` → F040
- c137 [symbol] `sdd/specs/` :: `hits` → F040
- c138 [symbol] `packages/ai-parrot/src/parrot/bots/prompts/builder.py` :: `PromptBuilder` → F041
- c139 [symbol] `packages/ai-parrot/src/parrot/bots/prompts/layers.py` :: `LayerPriority` → F041
- c140 [symbol] `packages/ai-parrot/src/parrot/bots/prompts/layers.py` :: `IDENTITY_LAYER` → F041
- c141 [symbol] `packages/ai-parrot/tests/test_agent_definitions.py` :: `test_bot_config_fields` → F042
- c142 [symbol] `packages/ai-parrot/tests/fixtures/agents/marketing.yaml` :: `system_prompt` → F042
- c143 [symbol] `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py` :: `DecisionConfig` → F043
- c144 [symbol] `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py` :: `why` → F043
- c145 [file] `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/` → F043
- c146 [symbol] `packages/ai-parrot/src/parrot/knowledge/retrieval/__init__.py` :: `SourceDigest` → F044
- c147 [file] `sdd/specs/graphindex-retriever.spec.md` → F044
- c148 [symbol] `packages/ai-parrot/src/parrot/knowledge/wiki/export.py` :: `export_okf_bundle` → F045
- c149 [symbol] `packages/ai-parrot/src/parrot/knowledge/wiki/export.py` :: `page_frontmatter` → F045
- c150 [symbol] `packages/ai-parrot/src/parrot/observability/context.py` :: `agent_identity` → F046
- c151 [file] `sdd/tasks/index/spawn-ephemeral-subagent-tool.json` → F047
- c152 [symbol] `packages/ai-parrot/src/parrot/tools/spawn.py` :: `SpawnSubAgentTool` → F047
- c153 [symbol] `sdd/specs/long-term-memory.spec.md` :: `LongTermMemoryMixin` → F048
- c154 [symbol] `packages/ai-parrot/src/parrot/memory/unified/manager.py` :: `__init__` → F048
- c155 [symbol] `packages/ai-parrot-tools/src/parrot_tools/legal/boe/sync.py` :: `sync_boe` → F049
- c156 [file] `packages/ai-parrot-tools/src/parrot_tools/legal/librarian/` → F049
- c157 [symbol] `sdd/proposals/claude_legal-wiki-design.md` :: `skeleton` → F049
- c158 [symbol] `sdd/proposals/promptbuilder-identity-capability.brainstorm.md` :: `brainstorm` → F050
- c159 [symbol] `sdd/tasks/completed/TASK-1900-secondopinion-subagent-brief.md` :: `brief` → F050
- c160 [symbol] `sdd/specs/hitl-escalation-tier.spec.md` :: `tier` → F050
- c161 [symbol] `sdd/specs/sdd-spec-changes.spec.md` :: `frontmatter` → F050
- c162 [file] `.agent/rules/` → F050
