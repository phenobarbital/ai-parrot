---
id: FEAT-778
title: "Domain Experts: declarative expert bundles (identity + two-tier knowledge + rules + mandatory wiki) bound to SDD flow stages"
slug: domain-experts
type: feature
mode: enrichment
status: review
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-10-30
  summary_oneline: "Domain Experts: declarative expert bundles (persona + two-tier knowledge + rules + mandatory wiki) bound to SDD flow stages"
overall_confidence: medium
base_branch: dev
projects: [ai-parrot, ai-parrot-tools, sdd-tooling, docs]
tags: [domain-experts, knowledge-resolver, prompt-layers, agent-registry, adr, flows, gates, skills]
research_state: sdd/state/FEAT-778/
created: 2026-10-30
updated: 2026-10-30
---

# FEAT-778 — Domain Experts: declarative expert bundles bound to SDD flow stages

> **Mode**: enrichment
> **Confidence**: medium (localization high; scope medium — five phases, five architectural forks, all five resolved in §5)
> **Source**: `file: sdd/proposals/domain-experts.proposal.md` — the brainstorm committed on dev as `2f8d4c397` (2026-10-30), preserved verbatim at `sdd/state/FEAT-778/source.md`
> **Audit**: [`sdd/state/FEAT-778/`](../state/FEAT-778/)

---

## 0. Origin

The original brainstorm (302 lines, Spanish) is preserved verbatim at `sdd/state/FEAT-778/source.md`. Its thesis:

> Se propone introducir en ai-parrot el concepto de **Domain Expert**: un agente declarativo compuesto por una
> identidad (`persona.md`), una knowledge base propia en dos tiers, un conjunto de reglas de gobierno y acceso
> obligatorio al LLM Wiki (OKF) y al bookstore. Un expert es inerte hasta que un stage de un Flow SDD lo nombra
> como lead o support; la delegación siempre la hace el conductor del Flow, nunca otro expert.
>
> El patrón se toma de los *domain experts* de AWS AI-DLC (11 agentes de dominio, knowledge en dos tiers, orden
> de carga determinista, binding a stages) y se adapta a lo que ai-parrot ya tiene: PromptBuilder por capas,
> AgentRegistry/AgentCrew, LLM Wiki OKF, GraphIndex, soporte ADR y gates de sesión AHP. […]
>
> Este documento es un brainstorm para abrir el research; las decisiones quedan abiertas en la sección de preguntas.

The brainstorm proposed: a self-contained bundle (`expert.yaml`, `persona.md`, `knowledge/`, `rules/governance.md`, `adr/`), a pure `KnowledgeResolver → KnowledgeContext` with a deterministic 8-step load order and per-layer budget, an additive rules chain (org → team → project → expert → stage), ADR as consumer and producer, `validate`/`write`/`review` capabilities delegated from `sdd-proposal`/`sdd-spec`, stage YAML with `lead`/`support`/`mode`/`inputs`/`outputs`/`gate`, a scope grid, four dispatch modes (inline / subagent / pipeline / mob), `cve-analyst` as first expert, and five implementation phases.

**Initial signals** (extracted, not interpreted):
- Verbs: *introducir, proponer, sustituir (el loader de KB), delegar, registrar, bind* → additive, feature-shaped.
- Named entities: PromptBuilder `identity` layer, KB loader, LLM Wiki OKF, bookstore, GraphIndex L0/L1/L2, ADR support, AgentRegistry, AgentCrew, AHP gates, OTEL, `sdd-proposal`, `sdd-spec`, `expert.yaml`, `persona.md`, `wikitoolkit`, `spawn_agent`, `cve-analyst`, contracts/legal/trading agents.
- Components / labels: none (file source, no Jira metadata).
- Acceptance criteria provided: no — the source lists invariants (manifest rules) and 12 open questions instead.

---

## 1. Synthesis Summary

The request is a declarative **expert bundle** plus a **stage binding** layer, and the codebase already holds most of the primitives it names, with four surprises. The skills subsystem (`SkillsDirectoryLoader`, `SkillDefinition`, `SkillView`) is a near-exact precedent for a directory bundle with frontmatter validation, token counting and workspace-over-package shadowing; the `AgentRegistry` already discovers YAML `BotConfig` manifests under `AGENTS_DIR/agents/`; and the ADR decision plane, GraphIndex L2 retrieval and bookstore cards cover the knowledge sources the manifest declares. The surprises: FEAT-321 (approved) already ships file-based identity and **rejected** a sectioned single `persona.md`; the KB path the source wants to replace is a dormant retrieval-only list with no inline-layer equivalent; the AHP gates are typed to the dev-loop by closed Literals; and no deny-list or `spawn_agent` tool exists (the tool is `spawn_sub_agent`, allowlist-only). What is genuinely new is the `ExpertManifest` + `ExpertRegistry`, the `KnowledgeResolver`/`KnowledgeContext`, the governance rules chain, a stage node type compiled into `FlowDefinition`, a generic gate host lifted from `ApprovalGate`, and the blind-contribution protocol. The recommendation is to spec FEAT-778 as phases 1–2 of the source (bundle, resolver, rules, ADR, wiki) with the five forks resolved in §5, and to route phases 3–4 (stages, dispatch modes, scope grid) to a follow-up brainstorm once the resolver exists.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-778/findings/` (50 digests from 69 queries across codebase, git and wiki lanes). 163 citations were probed by `sdd-contract-probe` at HEAD `46f2056c0`: **0 stale, 0 missing** (`sdd/state/FEAT-778/citation_checks.md`).

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/bots/prompts/builder.py` | `PromptBuilder` | 35-362 | name-keyed layer stack; `identity` is ONE replaceable slot (`add`/`replace` by name; `from_system_prompt` already swaps it); `KNOWLEDGE_LAYER` is the slot for a rendered KnowledgeContext | F001, F041 |
| 2 | `packages/ai-parrot/src/parrot/bots/prompts/layers.py` | `PromptLayer` / `LayerPriority` | 22-141 | priority (IDENTITY=10, CUSTOM=80), phase, cacheable, and the FEAT-707 `literal` flag for untrusted authored text | F041, F031 |
| 3 | `packages/ai-parrot/src/parrot/bots/mixins/identity.py` | `IdentityMixin` | 40-260 | approved file-based persona: five per-field `.md` files, pristine builder clone, mtime hot reload; `identity_dir` derived from the class module | F002 |
| 4 | `packages/ai-parrot/src/parrot/bots/prompts/identity.py` | `IdentityFields` / `IDENTITY_FILES` | 27-40 | identity file contract (role, goal, capabilities, backstory, rationale) | F002 |
| 5 | `packages/ai-parrot/src/parrot/registry/registry.py` | `BotConfig` / `PromptConfig` / `AgentKind` | 55-300 | existing declarative agent manifest (tools, toolkits, model, prompt layers, tags, policies, kind) loaded from YAML | F006, F032, F042 |
| 6 | `packages/ai-parrot/src/parrot/registry/registry.py` | `AgentRegistry.load_agent_definition_file` / `register` / `_apply_prompt_config` / `get_bots_by_tag` | 570-1565 | directory-discovered YAML under `AGENTS_DIR/agents/`; duplicates **warn** unless `replace=True`; YAML can add/remove/customize layers; tag index for inert experts | F006 |
| 7 | `packages/ai-parrot/src/parrot/conf.py` | `AGENTS_DIR` | 181-194 | workspace asset root (`{agent}/prompts`, `/kb`, `/skills`, `/templates`, `flows/`) | F005 |
| 8 | `packages/ai-parrot/src/parrot/skills/loader.py` | `SkillsDirectoryLoader` | 26-104 | discovers `{dir}/{name}.md` and `{dir}/{name}/SKILL.md`; warns and skips malformed entries | F007, F029 |
| 9 | `packages/ai-parrot/src/parrot/skills/models.py` | `SkillDefinition` | 68-95 | frontmatter-validated Pydantic with `token_count`, `assets_dir`, `global_only` | F008 |
| 10 | `packages/ai-parrot/src/parrot/skills/tenancy.py` | `SkillView` / `tenant_skills_dir` / `RESERVED_TENANT_NAMES` | 54-248 | tenant-over-global shadowing with `global_only` locks; reserves `kb`, `documents`, `prompts`, `flows` | F008, F034 |
| 11 | `packages/ai-parrot/src/parrot/bots/abstract.py` | `AbstractBot.register_kb` / `configure_kb` / KB activation block | 1189-3945 | priority-sorted KB list, activated per question via `KBSelector`/`should_activate`, `k=5`; no layer order, budget or revision | F003 |
| 12 | `packages/ai-parrot/src/parrot/bots/kb.py` | `KBSelector` | 12-60 | LLM-based KB chooser only; 0 commits in 180 days | F004, F037 |
| 13 | `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py` | `DecisionRecord` / `EvidenceRef` / `ReviewRequest` | 107-303 | ADR record: `source_status` {proposed, accepted, superseded, …} separate from `review_status`; evidence hashed by `source_sha1`; **no tags field** | F009, F043 |
| 14 | `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py` | `DecisionService.why` / `for_symbol` | 276 | LLM-free, `budget_tokens`-bounded ADR reads — the `source: adr` consumer target | F043, F033 |
| 15 | `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/toolkit.py` | `__getattr__` | 1-36 | lazy shim: agent-facing ADR tools ship from `parrot_tools.wiki.decisions` | F010 |
| 16 | `packages/ai-parrot/src/parrot/knowledge/retrieval/__init__.py` | `RetrievalRequest` / `RetrievalBudget` / `ContextBundle` / `SourceDigest` | 1-151 | GraphIndex L2 budgeted, attributable retrieval with digest invalidation — the `source: graphindex, mode: retrieval` target | F011, F044, F035 |
| 17 | `packages/ai-parrot/src/parrot/knowledge/wiki/export.py` | `export_okf_bundle` / `page_frontmatter` | 85-130 | OKF v0.1 bundle shape (frontmatter `type`/`title`/`id`/`tags`); export-only boundary | F045 |
| 18 | `packages/ai-parrot/src/parrot/knowledge/bookstore/models.py` | `BookCard` | 152-180 | DocumentKB-shaped card: `source_sha256`, `toc_digest`, `topics` (filter key), `scope: project\|global` | F027, F012 |
| 19 | `packages/ai-parrot/src/parrot/knowledge/contracts/models.py` | `ContractCard` | 341-457 | `source_sha256` as citation identity, `revision`, `stale_fields` | F012 |
| 20 | `packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py` | `LLMWikiToolkit` / `query` | 48-375 | agent-facing `wiki_*` tools scoped by `wiki_name`; `query(wiki_name, question, file_answer, mode)` has **no tag filter** | F020 |
| 21 | `packages/ai-parrot/src/parrot/models/crew_definition.py` | `AgentDefinition` / `CrewDefinition` / `ExecutionMode` | 22-215 | crew manifest (`extra="forbid"`): agents + `sequential\|parallel\|flow\|loop`; no lead/support, no hub-and-spoke/mob | F013, F014 |
| 22 | `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` | `AgentCrew.from_definition` | 781-800 | `class_resolver` / `tool_resolver` injection seam | F014 |
| 23 | `packages/ai-parrot/src/parrot/flows/dev_flow/definition.py` | `build_dev_flow_definition` / `_dev_loop_node` | 104-160 | `FlowDefinition` of `NodeDefinition(id, type)` + CEL-predicated edges; no stage vocabulary | F015, F036 |
| 24 | `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py` | `ApprovalGate` / `SessionHost.open_gate` / `wait_gate` | 297-1598 | AHP TTL gates, `on_expiry: fail\|approve`, `payload_ref`; `GateKind`/`NodeId` are closed dev-loop Literals | F016 |
| 25 | `packages/ai-parrot/src/parrot/human/models.py` | `HumanInteraction` / `EscalationPolicy` | 31-398 | channel-facing HITL half, separate from dev_loop gates, stable 90 days | F017, F039 |
| 26 | `packages/ai-parrot/src/parrot/tools/spawn.py` | `SpawnSubAgentTool` / `_compute_effective_tools` | 39-190 | the delegation tool; registered name **`spawn_sub_agent`**; allowlist-only; no nesting guard | F018, F047 |
| 27 | `packages/ai-parrot/src/parrot/tools/manager.py` | `ToolManager` | 1945-2029 | PBAC policy denial path — the only existing *deny* mechanism | F019 |
| 28 | `packages/ai-parrot/src/parrot/observability/context.py` | `agent_identity` / `usage_attribution` / `current_seat` / `current_tenant` | 67-162 | ContextVar attribution; inline experts need an explicit `agent_identity()` scope; no tier attribute | F021, F046 |
| 29 | `packages/ai-parrot/src/parrot/clients/base.py` | `_lightweight_model` / `_resolve_invoke_model` | 309-2085 | the only model-tier precedent; file is off-limits per CONTEXT.md | F022 |
| 30 | `packages/ai-parrot/src/parrot/memory/compaction/budget.py` | `resolve_window` / `build_default_budget` | 43-98 | per-model window → `ContextBudget`; base for `KnowledgeContext.budget_tokens` | F026 |
| 31 | `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/legal.ontology.yaml` | legal ontology header | 1-6 | one of four bundled versioned *domain* ontologies (contracts, legal, procedures, field_services) | F023 |
| 32 | `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py` | mermaid codec | 1-10 | structured `Graph` as source of truth, Mermaid as derived view | F024 |
| 33 | `packages/ai-parrot-tools/src/parrot_tools/contracts/agent.py` | `ContractsAgent` | 232-240 | hand-built domain expert with a code-level release gate (`UngatedAnswerRefused`) | F028, F049 |
| 34 | `packages/ai-parrot-tools/src/parrot_tools/legal/librarian/agent.py` | `LegalLibrarianAgent` | 47-70 | second migration candidate; verbatim `system_prompt` opts out of composable layers | F028 |
| 35 | `.claude/agents/sdd-secondopinion.md` | `sdd-secondopinion` | 1-67 | blind, advisory, read-only contribution protocol (CONFIRM/REJECT/ESCALATE) | F025 |
| 36 | `.claude/commands/sdd-spec.md` | sdd-spec command | 1 | no subagent delegation seam today | F030 |

### 2.2 Constraints Discovered

- **Single identity slot.** `PromptBuilder` keys layers by name; `identity` is one slot and `configure()` destroys templates, so per-activation persona swaps must clone a pristine builder (the `IdentityMixin` pattern). *Implication*: two inline experts in one turn need a second named layer (e.g. `expert_identity`) at its own priority, or a composition rule. *Evidence*: F001, F041, F002.
- **FEAT-321 already decided the persona shape.** The approved identity capability uses five per-field files and its brainstorm rejected a sectioned single-file persona. *Implication*: the source's four-section `persona.md` contradicts an approved spec (resolved in §5 U1: identity files drive the prompt; `persona.md` is documentation only). *Evidence*: F002, F050.
- **Authored text is literal.** FEAT-707 added `PromptLayer.literal=True` so user-authored layers are never `$`-substituted. *Implication*: persona, rules and knowledge layers must be literal. *Evidence*: F031, F034.
- **Registry is hot and lenient.** 15 commits in 4 days on `registry.py` (FEAT-746/747 review fixes on 2026-10-30); `register()` warns on duplicates instead of failing. *Implication*: keep expert discovery a sibling loader (§5 U3) and branch after the fixes settle; "duplicate experts fail on load" is a local, stricter rule. *Evidence*: F032, F006.
- **No deny-list; wrong tool name.** Tool gating is allowlist-shaped (`allowed_tools` on Agent/MCP/spawn) plus PBAC denial; no `tools_deny`-like field exists, and the delegation tool is registered as `spawn_sub_agent`. *Implication*: the "no expert delegates" invariant must name `spawn_sub_agent` and be enforced as an allowlist or PBAC rule plus a nesting guard. *Evidence*: F018, F019, F047.
- **Two gate stacks, one closed.** `ApprovalGate` (TTL fail-closed/fail-open, `payload_ref`) is typed to the dev-loop by closed `GateKind`/`NodeId` Literals; `parrot/human` is a separate channel-facing HITL stack. *Implication*: §5 U4 lifts the gate into `flows/core`; a third stack must not appear. *Evidence*: F016, F017, F039.
- **Crews have no roles or hub-and-spoke.** `CrewDefinition`/`AgentDefinition` are `extra="forbid"` with no lead/support field and only four execution modes. *Implication*: subagent/mob dispatch is new orchestration (`parallel` + lead integration), not a flag. *Evidence*: F013, F014.
- **ADRs have status but no tags.** `DecisionRecord.source_status`/`review_status` support `filter: {status: [accepted]}`; a domain/tag filter needs wiki tags or links to component pages. Reads are LLM-free and token-budgeted. *Evidence*: F009, F043, F033.
- **Wiki scopes by namespace, bookstore by topics.** `LLMWikiToolkit.query` has no tag parameter; `BookCard.topics` is the only tag-like key. *Implication*: `scope: {tags}` maps to a per-expert wiki namespace (first) or a tag filter in `parrot_tools` (later), and to `topics` on the bookstore. *Evidence*: F020, F027, F012.
- **Clients are off-limits.** `clients/base.py` holds the only tier precedent (`_lightweight_model`) and must not be modified. *Implication*: `tier` projection happens at manifest load (`BotConfig.model`) or in flow seats. *Evidence*: F022, F036.
- **Toolkits live in `parrot_tools`.** Wiki, decisions and graphindex toolkits ship from ai-parrot-tools with core shims. *Implication*: the mandatory wiki/bookstore/graphindex access is a `parrot_tools` dependency of the expert runtime. *Evidence*: F010, F020, F035.
- **KB path is retrieval-shaped and dormant.** Inline always-present layers have no KB equivalent; `bots/kb.py` has no commits in 180 days. *Implication*: the resolver owns inline layers through the prompt stack; folding the KB search path in (§5 U5: yes, in phase 1) raises the blast radius in `abstract.py` with little recent test coverage. *Evidence*: F003, F004, F037.
- **Reserved directory names.** `RESERVED_TENANT_NAMES` already reserves `kb`, `documents`, `prompts`, `flows`; `.parrot/` is only used for `crew_wiki`. *Implication*: `experts/` and `knowledge/` must be added to the reserved set; `AGENTS_DIR` is the root (§5 U2). *Evidence*: F008, F014, F005.
- **Contracts cannot be purely declarative.** `ContractsAgent` routes every answer through a release gate that raises `UngatedAnswerRefused`. *Implication*: the bundle carries persona/knowledge/rules; toolkit and answer-gate stay as code hooks. *Evidence*: F049.
- **Four hand-synced copies.** Dev-flow subagent briefs and SDD commands exist in `_subagent_data` + `.claude` + `.agent` + `.agents`. *Implication*: delegation from `sdd-spec`/`sdd-proposal` must be added to all twins, or generated from one source. *Evidence*: F036, F030.

### 2.3 Recent History (Relevant)

| Area | Window | Activity | Signal | Evidence |
|------|--------|----------|--------|----------|
| `registry/` | 2026-10-26 → 10-30 | 15 commits: `AgentKind{LOCAL,A2A,SQUAWK}`, `register_remote`, `find_by_kind`, same-day review fixes | **collision hotspot**; design against post-FEAT-746 registry | F032 |
| `skills/` | 2026-10-19 → 10-28 | 15 commits: FEAT-707 per-tenant shadowing, `literal` layers, request-local turn skill | freshest bundle + shadowing precedent | F034 |
| `bots/prompts/` | 90 days | 15 commits: `literal` flag, `TOOLLESS_DATA_GROUNDING_LAYER`, output-language layer; identity layer untouched | layer machinery stable and extensible | F031 |
| `knowledge/wiki/decisions/` | 90 days | 15 commits: FEAT-578 hardening, LLM-free reads, FEAT-760 prefixed aliases (2026-10-27) | ADR plane mature | F033 |
| `knowledge/retrieval/` | since 2026-08-20 | FEAT-435 L2 built in one day; one pin seam since | stable | F035 |
| `flows/dev_flow/` | last 2026-09-19 | per-run model seats; personas shipped as `_subagent_data/*.md` in 4 copies | seats = existing tier→model mechanism | F036 |
| `knowledge/bookstore/` | 2026-09-06 → 10-01 | re-index identity hotfixes, atomic-swap reindex | card identity solved | F038 |
| `bots/kb.py` | 180 days | **0 commits** | dormant, low coverage | F037 |
| `human/` | 90 days | **0 commits** | stable HITL stack | F039 |
| `sdd/` | 180 days | source committed as `2f8d4c397`; no other expert/persona doc | no duplicate to fold | F040, F050 |

---

## 3. Probable Scope  *(mode = enrichment)*

The source's design, adjusted by the findings and by the five decisions in §5.

### What's New

- **`ExpertManifest` + bundle loader (`ExpertRegistry`)** — Pydantic manifest for `expert.yaml`; discovery by presence under `AGENTS_DIR/experts/<slug>/` with `tenants/<t>/experts/` shadowing (same rules as `SkillView`, `global_only` locks); strict invariants: `name == dir`, duplicates fail, `knowledge` must include `source: wiki`, the allowlist must exclude `spawn_sub_agent`, `tier` never names a model. Registers a configured agent into `AgentRegistry` (sibling, not a new `AgentKind`). *Evidence*: F007, F008, F006, F042, F047.
- **`KnowledgeResolver → KnowledgeContext`** — pure, deterministic, serializable; `(expert, stage, workspace) → ordered, budgeted layers`: rules → Tier-1 shared → Tier-1 expert → Tier-2 shared → Tier-2 expert → accepted ADRs → stage inputs → retrieval handles (wiki/bookstore/graphindex, and — per U5 — the existing KB list as a `mode: retrieval` source). Inline layers render into `KNOWLEDGE_LAYER` as `literal=True`; each layer carries `source`, `revision` (sha256), `tokens`; trim order Tier-1 methodology before Tier-2, never rules or identity. Budget derived via `build_default_budget`/`resolve_window`. *Evidence*: F001, F026, F043, F044, F008, F003.
- **Governance rules chain** — additive `ALWAYS`/`NEVER` layers org → team → project → expert → stage, count/dedupe/verify in tests; promotion of discovered rules only through a human gate. No precedent exists (`memory/unified` has namespaces and weights, not rule files). *Evidence*: F048, F050.
- **Persona activation** — identity files (`identity/{role,goal,capabilities,backstory,rationale}.md`, per U1) loaded through `IdentityMixin` with an explicit `identity_dir`; `persona.md` kept as human-readable documentation; activation wraps the call in `agent_identity(expert)` + `usage_attribution(run, "<stage>.<expert>")`. *Evidence*: F002, F021, F046.
- **Generic gate host** (per U4) — `ApprovalGate` semantics (`on_expiry fail|approve`, TTL, `payload_ref`) lifted into `flows/core` with an open `GateKind`; dev_loop becomes a consumer; `approve_or_request_changes` is the first stage gate kind. *Evidence*: F016.
- **Stage node type + compiler** (phase 3–4, follow-up spec) — a `NODE_REGISTRY` node whose config carries `lead`/`support`/`mode`/`inputs`/`outputs{schema}`/`gate`, compiled into a `FlowDefinition`; the scope grid is CEL-conditioned edges or one definition per scope; hub-and-spoke and mob are `parallel` + lead integration. *Evidence*: F015, F014, F013.
- **Blind-contribution protocol** — `contributions/<slug>.md` identity-marked artifacts, mutually blind supports, lead integration, gate that requires every expected contribution; codifies the `sdd-secondopinion` brief and CLAUDE.md's second-opinion rules. *Evidence*: F025, F030.

### What Changes

- **`packages/ai-parrot/src/parrot/registry/registry.py`::`AgentRegistry`** — accept registrations from `ExpertRegistry`; tag index (`get_bots_by_tag`) for visible-but-inert experts. *Evidence*: F006, F032.
- **`packages/ai-parrot/src/parrot/bots/mixins/identity.py`::`IdentityMixin`** — explicit `identity_dir` from a bundle (today derived from the class module); expose the pristine-clone swap for per-activation personas. *Evidence*: F002.
- **`packages/ai-parrot/src/parrot/bots/prompts/layers.py`::`LayerPriority`** — a named `expert_identity`/`rules` layer at its own priority if stacking over the conductor identity is needed for inline mode. *Evidence*: F041, F031.
- **`packages/ai-parrot/src/parrot/bots/abstract.py`::KB activation block** (per U5) — the `knowledge_bases` list becomes a retrieval source consumed through the resolver; `register_kb`/`KBSelector` are kept as the implementation of that source. *Evidence*: F003, F004.
- **`packages/ai-parrot/src/parrot/skills/tenancy.py`::`RESERVED_TENANT_NAMES`** — add `experts`, `knowledge`. *Evidence*: F008.
- **`packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`::`AgentCrew.from_definition`** — `class_resolver`/`tool_resolver` that resolve an expert name to its configured agent. *Evidence*: F014.
- **`packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py`::`ApprovalGate`/`GateKind`/`NodeId`** — becomes a consumer of the lifted generic host. *Evidence*: F016.
- **`packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py`::`LLMWikiToolkit.query`** — per-expert namespace binding first; tag/topics filter later. *Evidence*: F020.
- **`.claude/commands/sdd-spec.md`** (+ `.agent/workflows`, `.agents/skills` twins) — new delegation section for `validate`/`write`/`review`. *Evidence*: F030, F036.

### What's Untouched (Non-Goals)

- `packages/ai-parrot/src/parrot/clients/base.py` — tier projection never lands here. *Evidence*: F022.
- `parrot/human` models and channels — reused by the generic gate host, not redesigned. *Evidence*: F017, F039.
- GraphIndex L2 internals and bookstore ingestion — consumed through `RetrievalRequest`/`BookCard`. *Evidence*: F044, F027.
- OTEL plumbing — scopes added, no new ContextVars (a `tier` attribute is optional). *Evidence*: F021.
- CVE feed ingestion beyond onboarding to the bookstore, admin UI for experts, multi-team/workshop mode, concrete tier→provider mapping (navconfig policy) — out of scope per the source.

### Patterns to Follow

- Composite bundle discovery + frontmatter validation + `token_count` + `assets_dir` (skills). *Evidence*: F007, F008.
- `SkillView` tenant-over-global shadowing with `global_only` locks for Tier 2 over Tier 1. *Evidence*: F008, F034.
- `IdentityMixin` pristine clone + mtime hot reload for persona swaps. *Evidence*: F002.
- `PromptLayer(literal=True)` for every authored/untrusted layer. *Evidence*: F031.
- `FlowDefinition` nodes by type from `NODE_REGISTRY` + CEL-conditioned edges. *Evidence*: F015.
- `ApprovalGate.on_expiry fail|approve` with `payload_ref` pointing at contributions. *Evidence*: F016.
- `DecisionService.why/for_symbol(budget_tokens=…)`; produced ADRs follow `origin="inferred"` + `review_status` gate. *Evidence*: F043, F009.
- `RetrievalRequest`/`RetrievalBudget → ContextBundle`; `SourceDigest` invalidation. *Evidence*: F044.
- `BookCard.source_sha256` + `topics` + `scope: project|global` as the DocumentKB contract. *Evidence*: F027, F012.
- `sdd-secondopinion` neutral brief for blind review. *Evidence*: F025.
- Agent-facing toolkits in `parrot_tools`, shims in core. *Evidence*: F010.

### Integration Risks

- **Registry churn** — FEAT-746/747 fixes still landing; mitigation: sibling `ExpertRegistry`, branch after they settle. *Evidence*: F032.
- **Identity contract** — a second persona format would conflict with FEAT-321; mitigation (U1): identity files drive the prompt, `persona.md` is documentation. *Evidence*: F002, F050.
- **Gate lift** — lifting `ApprovalGate` touches a 1,600-line dev-loop session state with a REST surface; mitigation: adapter-first, dev_loop keeps its Literals as a narrowing of the generic kind. *Evidence*: F016.
- **Invariant not enforced** — no deny-list; mitigation: allowlist/PBAC rule naming `spawn_sub_agent` + nesting guard in `SpawnSubAgentTool`. *Evidence*: F018, F019.
- **Wiki scoping** — `scope: {tags}` cannot be honoured today; mitigation: per-expert wiki namespace first. *Evidence*: F020, F045.
- **Vocabulary collisions** — *domain* (ontology domains) and *tier* (HITL escalation tiers); mitigation: avoid `domain` in module names, consider `judgement`/`model_class` for the manifest field. *Evidence*: F023, F050.
- **KB fold-in (U5)** — `abstract.py` KB block has no recent tests; mitigation: pin current behaviour with tests before routing it through the resolver. *Evidence*: F003, F037.
- **Contracts migration** — the release gate is code; mitigation: bundle + code hooks. *Evidence*: F049, F028.
- **Command twins** — four hand-synced copies; mitigation: protocol in one shared data file. *Evidence*: F036, F030.
- **Scope breadth** — five phases in one feature; mitigation: FEAT-778 = phases 1–2; phases 3–4 in a follow-up spec.

### Revised phases (from the source's five)

1. **Bundle + resolver + persona** — `ExpertManifest`, `ExpertRegistry` under `AGENTS_DIR/experts/`, `KnowledgeResolver`/`KnowledgeContext` (inline + retrieval incl. the KB list), identity files via `IdentityMixin`, reserved names, deterministic tests without LLM.
2. **Rules, ADR, wiki** — additive rules chain, `source: adr` via `DecisionService` (status filter), ADR production as `origin=inferred` + review gate, mandatory `LLMWikiToolkit`/`BookstoreToolkit` with per-expert namespace, digest contract on cards.
3. **Delegation from sdd-proposal / sdd-spec** — capabilities, contributions protocol, gate requiring contributions, command twins. *(follow-up spec)*
4. **Stages, dispatch, scope grid, generic gate host** — stage node type, compiler, lifted `ApprovalGate`, subagent/pipeline/mob over `AgentCrew`. *(follow-up brainstorm → spec)*
5. **First experts** — `cve-analyst` (security-patch scope), then `mvp`/`poc` grid with Domain Design (`Graph` + Mermaid codec), then `ContractsAgent`/`LegalLibrarianAgent` migration with code hooks retained.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `PromptBuilder` keys layers by name; `identity` is one replaceable slot and `from_system_prompt` already swaps it | F001, F041 | high | direct read 35-362; probe confirmed `add`/`replace`/`build`/`from_system_prompt` |
| C2 | An approved file-based identity contract exists (IdentityMixin, five files, hot reload) and rejected a sectioned single `persona.md` | F002, F050 | high | code read + spec/brainstorm; symbols probed |
| C3 | The skills subsystem is the closest architectural twin of the expert bundle | F007, F008, F029, F034 | high | direct reads of loader/models/tenancy/parsers |
| C4 | `AgentRegistry` already loads directory-discovered YAML `BotConfig` with a kind discriminator and mutates layers from YAML; duplicates warn | F006, F042 | high | registry read + fixture test; `register(replace=False)` probed |
| C5 | `AGENTS_DIR/{agent}/…` is the asset convention; no `experts/` or `.parrot/` root exists (crew_wiki aside) | F005, F014 | high | grep over conf.py and callers |
| C6 | KB path is a priority-sorted per-question retrieval list with no order/budget/revision; `kb.py` is only `KBSelector`, dormant 180 days | F003, F004, F037 | high | read + grep + git log |
| C7 | A complete ADR plane exists with status/review lifecycle, hashed evidence, LLM-free budgeted reads, no tags | F009, F043, F033, F010 | high | models read + wiki page + git log; `why(…, budget_tokens)` probed |
| C8 | GraphIndex L2 exposes `RetrievalRequest/RetrievalBudget → ContextBundle` and `SourceDigest`; stable since 2026-08-20 | F011, F044, F035 | high | package init + wiki page + git log |
| C9 | Digests already exist on `BookCard`/`ContractCard`; no generic "invalidate summary on digest change" on `BookCard` | F012, F027, F038 | medium | models read; `library.py`/`catalog.py` not read |
| C10 | `LLMWikiToolkit` scopes by `wiki_name`, no tag filter | F020 | high | toolkit read; `query` signature probed |
| C11 | Crews have no lead/support role and four modes; `from_definition` exposes resolver seams | F013, F014 | high | models + crew.py read |
| C12 | Declarative flows are `FlowDefinition` + CEL edges with no stage vocabulary; a stage is a new node type | F015, F036 | high | definition.py read; `NodeDefinition.config` shape not read |
| C13 | AHP gates exist as dev_loop `ApprovalGate` with closed Literals; `parrot/human` is separate and stable | F016, F017, F039 | high | read + spec + git log; `open_gate` signature probed |
| C14 | Delegation tool is `SpawnSubAgentTool` named `spawn_sub_agent`, allowlist-only, no nesting guard; no deny-list anywhere | F018, F019, F047 | high | spawn.py read + repo-wide grep; probe shows `name="spawn_sub_agent"` |
| C15 | OTEL attribution is ContextVar-based; inline experts need `agent_identity()`; no tier attribute | F021, F046 | high | context.py read |
| C16 | Only `_lightweight_model` as tier precedent; `clients/base.py` off-limits; flows use per-run seats | F022, F036 | medium | base.py grep; seats seen in commit messages only |
| C17 | No org/team/project rules chain exists; nearest primitives are `ContextAssembler` weights and `ContextBudget` | F048, F026 | medium | evidence of absence from wiki + spec; no repo-wide grep for rule files |
| C18 | Hand-built domain agents exist for contracts (code gate) and legal (verbatim prompt); no trading agent | F028, F049, F023 | high | grep + wiki page; classes probed |
| C19 | `sdd-spec` has no delegation seam; `sdd-proposal` and `sdd-secondopinion` are the precedents | F030, F025 | high | grep of command file + agent brief read |
| C20 | No other SDD document covers domain experts; the source is committed on dev (`2f8d4c397`) | F040, F050 | high | filtered git log + wiki query; commit verified |
| C21 | Authored Tier-1 OKF files can be served as a file-backed wiki namespace rather than a new loader | F045 | low | inferred from `OKF_TYPE_TO_CATEGORY`; `file_store` backend not located |
| C22 | The registry is a collision hotspot right now | F032 | high | 15 commits in 4 days incl. same-day fixes |

Distribution: **18** high, **3** medium, **1** low. Overall **medium**: localization is high, but the scope spans five phases and C21 (bundled OKF knowledge as a wiki namespace) is load-bearing for phase 2 and still low.

---

## 5. Open Questions

### Resolved (during proposal phase, 2026-10-30)

- [x] **U1 — Persona contract: FEAT-321 identity files vs AI-DLC four-section `persona.md`?** — *Resolved*: **Both** — identity/ five files feed the prompt layer; `persona.md` is kept as human-readable documentation only. *Resolves claims*: C2.
- [x] **U2 — Where do expert bundles live?** — *Resolved*: **`AGENTS_DIR/experts/<slug>`** — workspace bundles beside agents; Tier 2 via `tenants/<t>/experts` shadowing, same rules as skills (`global_only` locks). *Resolves claims*: C3, C5.
- [x] **U3 — Registry integration?** — *Resolved*: **Sibling `ExpertManifest` + `ExpertRegistry`** — own Pydantic manifest and loader that registers a configured agent into `AgentRegistry`; decoupled from the FEAT-746/747 churn; strict duplicate rule stays local. *Resolves claims*: C4, C22.
- [x] **U4 — Stage gates: widen dev_loop Literals, lift `ApprovalGate`, or build on `parrot/human`?** — *Resolved*: **Lift `ApprovalGate` into `flows/core`** — generic gate host with open `GateKind`; dev_loop becomes a consumer. *Resolves claims*: C13.
- [x] **U5 — Phase-1 blast radius: does the resolver replace the KB path?** — *Resolved*: **Replace in phase 1** — the KB path becomes a `mode: retrieval` source of the resolver now; the higher blast radius in `abstract.py` is accepted (pin current KB behaviour with tests first). *Resolves claims*: C6.

### Unresolved (defer to spec / implementation)

From the source's own list, not blocking the next command; suggested defaults in italics.

- [ ] **Per-layer budget policy** — fixed quota per layer, proportional to `tier`, or derived from the active model; how `trimmed` is reported. *Default: derive from `build_default_budget(model)`, fixed fractions per layer, `trimmed` surfaced in the stage gate payload.* — *Owner*: spec. *Blocks claims*: C17.
- [ ] **Wiki minimum scope validation** — fail on load vs warn when an expert has no documents in its namespace. *Default: warn on load, fail at activation when the stage names it as lead.* — *Owner*: spec. *Blocks claims*: C10, C21.
- [ ] **ADR inline cap and filter key** — how many accepted ADRs inline before retrieval; filter by `links` to component pages vs new wiki tags. *Default: `budget_tokens` on `DecisionService`; `links`-based filter.* — *Owner*: spec. *Blocks claims*: C7.
- [ ] **Promoted rules persistence and audit** — where `team.md`/`project.md` promotions are stored and who approved them. *Default: a reviewed ADR-like record with `review_history`, reusing the decisions plane.* — *Owner*: spec.
- [ ] **Contributions storage** — workspace files vs memory backend with the turn (affects per-turn compaction). *Default: workspace files referenced by `payload_ref`.* — *Owner*: spec (phase 3).
- [ ] **Scope grid declaration and `tier` → seat/OTEL** — YAML grid compiled with the flow vs policy in code; where `tier` → model lives (navconfig vs flow manifest) and how it reaches telemetry. *Default: one `FlowDefinition` per scope; `tier` → per-run seat; `current_seat="<stage>.<expert>"`.* — *Owner*: follow-up brainstorm (phase 4). *Blocks claims*: C16.
- [ ] **Expert memory and migration order** — does an expert own memory between activations ("Memory Focus") or read workspace memory only; which agent migrates first (contracts keeps its code gate). *Default: workspace memory only in v1; `ContractsAgent` first, with code hooks.* — *Owner*: spec (phase 5). *Blocks claims*: C18.

> Seven deferred items exceed the template's five-item caution. They are spec-level details with defaults, not research gaps; phases 3–4 own three of them and go to their own brainstorm.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-778`** — *Rationale*: localization is high-confidence and the five architectural forks were decisions, not research gaps; all five are now resolved. Spec FEAT-778 as **phases 1–2** of §3 (manifest + `ExpertRegistry` + `KnowledgeResolver` with the KB fold-in + identity files + rules chain + ADR/wiki sources + reserved names), carrying the §5 defaults as resolved questions.

### Alternatives

- **`/sdd-brainstorm` for phases 3–4** (stages, dispatch modes, scope grid, generic gate host) — recommended as a *follow-up* once the resolver exists; it has its own forks (lift mechanics for `ApprovalGate`, hub-and-spoke vs mob over `AgentCrew`).
- **`/sdd-task FEAT-778`** — not suitable; the scope is multi-module and multi-package.
- **Manual review** — only if the FEAT-746/747 registry fixes are still landing when the spec is cut; re-check `git log -- packages/ai-parrot/src/parrot/registry/` first.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-778/state.json` |
| Source (raw, verbatim brainstorm) | `sdd/state/FEAT-778/source.md` |
| Research plan (58 queries, 3 lanes) | `sdd/state/FEAT-778/research_plan.json` |
| Findings (50 canonical digests) | `sdd/state/FEAT-778/findings/F001-*.md` … `F050-*.md` |
| Lane originals (59, archived) | `sdd/state/FEAT-778/findings/.audit/FC-*.md`, `FG-*.md`, `FW-*.md` |
| Citation probes (163 checks, 4 groups) | `sdd/state/FEAT-778/probe_sheet.json`, `probe_group_{0..3}.json`, `citations_raw.json`, `citation_checks.md` |
| Synthesis (JSON, with Q&A answers) | `sdd/state/FEAT-778/synthesis.json` |

**Budget consumed** (profile `default`, parallel lanes codebase / git / wiki):
- Files read: 29 / 40
- Grep calls: 18 / 25
- Git calls: 10 / 10
- Wiki calls: 28 (free)
- Wall time: 568s across lanes (longest lane 568s vs 255s lane allowance — the parent did not enforce the lane cut-off; all lanes completed with 0 skipped queries)
- Merge: 59 lane findings → 50 canonical (9 merged by shared `(path, symbol)`)
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (additive verbs, greenfield bundle; no negation in source).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` (FEAT-708 parallel lanes + citation probes) |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (with Claude Fable 5.1) |
| Original brainstorm | Jesus Lara, 2026-10-30 (`2f8d4c397`), preserved at `sdd/state/FEAT-778/source.md` |
