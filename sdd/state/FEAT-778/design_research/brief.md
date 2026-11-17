<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
The request is a declarative **expert bundle** plus a **stage binding** layer, and the codebase already holds most of the primitives it names, with four surprises. The skills subsystem (`SkillsDirectoryLoader`, `SkillDefinition`, `SkillView`) is a near-exact precedent for a directory bundle with frontmatter validation, token counting and workspace-over-package shadowing; the `AgentRegistry` already discovers YAML `BotConfig` manifests under `AGENTS_DIR/agents/`; and the ADR decision plane, GraphIndex L2 retrieval and bookstore cards cover the knowledge sources the manifest declares. The surprises: FEAT-321 (approved) already ships file-based identity and **rejected** a sectioned single `persona.md`; the KB path the source wants to replace is a dormant retrieval-only list with no inline-layer equivalent; the AHP gates are typed to the dev-loop by closed Literals; and no deny-list or `spawn_agent` tool exists (the tool is `spawn_sub_agent`, allowlist-only). What is genuinely new is the `ExpertManifest` + `ExpertRegistry`, the `KnowledgeResolver`/`KnowledgeContext`, the governance rules chain, a stage node type compiled into `FlowDefinition`, a generic gate host lifted from `ApprovalGate`, and the blind-contribution protocol. The recommendation is to spec FEAT-778 as phases 1–2 of the source (bundle, resolver, rules, ADR, wiki) with the five forks resolved in §5, and to route phases 3–4 (stages, dispatch modes, scope grid) to a follow-up brainstorm once the resolver exists.

---

Original request (verbatim excerpt):
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

### Constraints and goals
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

### Recommended option / probable scope


### Verified code anchors (paths only — open them yourself)
packages/ai-parrot/src/parrot/bots/prompts/builder.py
packages/ai-parrot/src/parrot/bots/prompts/layers.py
packages/ai-parrot/src/parrot/bots/mixins/identity.py
packages/ai-parrot/src/parrot/bots/prompts/identity.py
packages/ai-parrot/src/parrot/registry/registry.py
packages/ai-parrot/src/parrot/conf.py
packages/ai-parrot/src/parrot/skills/loader.py
packages/ai-parrot/src/parrot/skills/models.py
packages/ai-parrot/src/parrot/skills/tenancy.py
packages/ai-parrot/src/parrot/bots/abstract.py
packages/ai-parrot/src/parrot/bots/kb.py
packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py
packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py
packages/ai-parrot/src/parrot/knowledge/wiki/decisions/toolkit.py
packages/ai-parrot/src/parrot/knowledge/retrieval/__init__.py
packages/ai-parrot/src/parrot/knowledge/wiki/export.py
packages/ai-parrot/src/parrot/knowledge/bookstore/models.py
packages/ai-parrot/src/parrot/knowledge/contracts/models.py
packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py
packages/ai-parrot/src/parrot/models/crew_definition.py
packages/ai-parrot/src/parrot/bots/flows/crew/crew.py
packages/ai-parrot/src/parrot/flows/dev_flow/definition.py
packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
packages/ai-parrot/src/parrot/human/models.py
packages/ai-parrot/src/parrot/tools/spawn.py
packages/ai-parrot/src/parrot/tools/manager.py
packages/ai-parrot/src/parrot/observability/context.py
packages/ai-parrot/src/parrot/clients/base.py
packages/ai-parrot/src/parrot/memory/compaction/budget.py
packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/legal.ontology.yaml
packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py
packages/ai-parrot-tools/src/parrot_tools/contracts/agent.py
packages/ai-parrot-tools/src/parrot_tools/legal/librarian/agent.py
.claude/agents/sdd-secondopinion.md
.claude/commands/sdd-spec.md

### Questions still open in the exploration document
- [ ] **Per-layer budget policy** — fixed quota per layer, proportional to `tier`, or derived from the active model; how `trimmed` is reported. *Default: derive from `build_default_budget(model)`, fixed fractions per layer, `trimmed` surfaced in the stage gate payload.* — *Owner*: spec. *Blocks claims*: C17.
- [ ] **Wiki minimum scope validation** — fail on load vs warn when an expert has no documents in its namespace. *Default: warn on load, fail at activation when the stage names it as lead.* — *Owner*: spec. *Blocks claims*: C10, C21.
- [ ] **ADR inline cap and filter key** — how many accepted ADRs inline before retrieval; filter by `links` to component pages vs new wiki tags. *Default: `budget_tokens` on `DecisionService`; `links`-based filter.* — *Owner*: spec. *Blocks claims*: C7.
- [ ] **Promoted rules persistence and audit** — where `team.md`/`project.md` promotions are stored and who approved them. *Default: a reviewed ADR-like record with `review_history`, reusing the decisions plane.* — *Owner*: spec.
- [ ] **Contributions storage** — workspace files vs memory backend with the turn (affects per-turn compaction). *Default: workspace files referenced by `payload_ref`.* — *Owner*: spec (phase 3).
- [ ] **Scope grid declaration and `tier` → seat/OTEL** — YAML grid compiled with the flow vs policy in code; where `tier` → model lives (navconfig vs flow manifest) and how it reaches telemetry. *Default: one `FlowDefinition` per scope; `tier` → per-run seat; `current_seat="<stage>.<expert>"`.* — *Owner*: follow-up brainstorm (phase 4). *Blocks claims*: C16.
- [ ] **Expert memory and migration order** — does an expert own memory between activations ("Memory Focus") or read workspace memory only; which agent migrates first (contracts keeps its code gate). *Default: workspace memory only in v1; `ContractsAgent` first, with code hooks.* — *Owner*: spec (phase 5). *Blocks claims*: C18.

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
