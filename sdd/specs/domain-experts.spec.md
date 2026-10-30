---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-tools, sdd-tooling, docs]
tags: [domain-experts, knowledge-resolver, prompt-layers, agent-registry, adr, flows, gates, skills]
---

# Feature Specification: Domain Experts — declarative expert bundles, KnowledgeResolver and governance rules (phases 1–2)

**Feature ID**: FEAT-778
**Date**: 2026-10-30
**Author**: Jesus Lara (with Claude Fable 5.1)
**Status**: approved
**Target version**: 1.3.0

> **Source**: proposal `sdd/proposals/domain-experts.proposal.md` (FEAT-778, status `accepted`, research state
> `sdd/state/FEAT-778/`). This spec covers the proposal's **phases 1–2** only: the expert bundle, its registry, the
> `KnowledgeResolver` (with the KB fold-in decided in U5), identity files, the governance rules chain, and the ADR /
> wiki / bookstore / GraphIndex knowledge sources. Phases 3–4 (stage binding, dispatch modes, scope grid, the generic
> gate host lifted from `ApprovalGate` — U4) and phase 5 (first experts, migrations) are **out of scope** and get their
> own brainstorm once the resolver exists.

---

## 1. Motivation & Business Requirements

### Problem Statement

ai-parrot already has every primitive a *domain expert* needs — a layered `PromptBuilder` with a replaceable
`identity` slot, file-based identity (FEAT-321), composite skill bundles with tenant shadowing (FEAT-707), a YAML
`BotConfig` registry, an ADR decision plane (FEAT-578), GraphIndex L2 retrieval (FEAT-435), bookstore cards with
digests, per-agent OTEL attribution — but no contract that turns them into a reusable expert. Each domain agent
(contracts, legal) is hand-built in code: identity is a verbatim system prompt, knowledge is loaded with no declared
order, budget or provenance, and governance rules live nowhere. The KB path that exists is retrieval-only
(`AbstractBot.knowledge_bases`, priority-sorted, activated per question by `KBSelector`) and has not been touched in
180 days. Without a declarative bundle, a deterministic and budgeted knowledge load order, and an additive rules
chain, every new expert re-invents the same plumbing and none of them behave the same way across `sdd-proposal`,
`sdd-spec` and a construction flow.

### Goals

- **G1 — Declarative bundle.** An expert is a directory `AGENTS_DIR/experts/<slug>/` with `expert.yaml`, an
  `identity/` directory (FEAT-321 five-file layout), optional `persona.md` (documentation only), `knowledge/`
  (Tier 1), `rules/governance.md` and optional `adr/`, discovered by presence, validated with Pydantic, registered
  into `AgentRegistry` without any code change per expert.
- **G2 — Two-tier knowledge with shadowing.** Tier 1 ships with the bundle; Tier 2 lives in the workspace
  (`AGENTS_DIR/experts/<slug>/tenants/<tenant>/…`) and shadows Tier 1 by name with the same `global_only` lock
  semantics as skills.
- **G3 — Deterministic, budgeted resolution.** `KnowledgeResolver.resolve(expert, stage, workspace)` returns a
  serializable `KnowledgeContext` with a fixed layer order, per-layer `revision` (sha256) and `tokens`, a budget
  derived from the active model, and a trim order that never drops rules or identity — reproducible without an LLM.
- **G4 — Inline and retrieval modes.** Persona, rules, Tier-1/2 summaries and accepted ADRs are inline prompt
  layers (`literal=True`); wiki, bookstore, GraphIndex and the existing KB list are retrieval handles. Per U5 the
  legacy `knowledge_bases` search path is routed through the resolver as a `kb` retrieval source in this feature.
- **G5 — Governance rules chain.** Additive `ALWAYS`/`NEVER` rule sets org → team → project → expert (stage added in
  phase 4), countable, de-duplicable and testable; rules are never trimmed.
- **G6 — ADR as consumer and producer.** Accepted ADRs load inline through `DecisionService` with its token budget;
  an expert can propose a new ADR that is born `origin="inferred"`, `review_status="unreviewed"` and only a human
  review accepts it.
- **G7 — Mandatory wiki and bookstore access, no delegation.** Every manifest must declare a `wiki` source; the
  resolved toolkit set must include `LLMWikiToolkit` and `BookstoreToolkit` and must exclude `spawn_sub_agent`;
  every loaded expert also carries a PBAC deny rule on `tool:spawn_sub_agent` (§8 Q3).
- **G8 — Attribution.** Every expert activation is attributed to the expert (not the conductor) via
  `agent_identity()` and `usage_attribution(run_id, "<stage>.<expert>")`; no new ContextVars.

### Non-Goals (explicitly out of scope)

- Stage YAML, the stage compiler, scope grid, dispatch modes (inline/subagent/pipeline/mob) and the generic gate
  host lifted from `ApprovalGate` (proposal phases 3–4; U4 decided the *direction*, not this spec).
- Delegation sections in `.claude/commands/sdd-spec.md` and its host twins (phase 3).
- `cve-analyst`, the `mvp`/`poc` grid, `ComponentCatalogue`, and the migration of `ContractsAgent` /
  `LegalLibrarianAgent` (phase 5). The bundle contract must *allow* code hooks (toolkit + answer gate) for them.
- A four-section `persona.md` **parser** — rejected by FEAT-321 and by U1: `persona.md` is documentation only.
- A new `AgentKind` on `BotConfig` or any change to `packages/ai-parrot/src/parrot/clients/base.py`
  (`tier` → model projection is resolved at manifest load into `ModelConfig`, never in the client).
- A tag filter inside `LLMWikiToolkit.query` — this feature binds a per-expert wiki **namespace**; tag/topics
  filtering is deferred (§8).
- A `.parrot/experts` root (rejected in U2), CVE feed ingestion, the admin UI for experts, multi-team mode.

---

## 2. Architectural Design

### Overview

A **bundle** is discovered by presence under `AGENTS_DIR/experts/<slug>/` (U2) by an `ExpertBundleLoader` modelled
on `SkillsDirectoryLoader` / `discover_skills_in_dir`: `expert.yaml` is parsed into an `ExpertManifest` (Pydantic,
`extra="forbid"`), the `identity/` directory is validated with `load_identity()` (FEAT-321), `knowledge/*.md` files
are token-counted and sha256-hashed, `rules/governance.md` is parsed into a `RuleSet` (only `ALWAYS …` / `NEVER …`
lines under `## Mandated` / `## Forbidden`). Tier-2 trees under `tenants/<tenant>/` are overlaid by an `ExpertView`
with the `SkillView` rules (tenant shadows by name; `global_only` entries cannot be shadowed). Manifest invariants
fail the bundle on load: `name == dir`, a duplicate name across bundles, a `knowledge` list without `source: wiki`,
a toolkit/tool list naming `spawn_sub_agent`, a `tier` that names a model.

An **`ExpertRegistry`** (U3: sibling of `AgentRegistry`, not a new `AgentKind`) owns the bundles and builds one
`ExpertAgent` per bundle — `class ExpertAgent(IdentityMixin, Agent)` with `enable_identity=True`,
`identity_dir=<bundle>/identity`, the manifest's toolkits resolved by name (always including `LLMWikiToolkit`
bound to the expert's wiki namespace and `BookstoreToolkit`), an `allowed_tools` allowlist that never contains
`spawn_sub_agent`, and `tier` projected to a `ModelConfig` through a small policy table (`judgment` / `balanced` /
`templated`). The registry registers the built instance into `AgentRegistry.register_instance()` with the tags
`expert` + `expert:<slug>` so an expert is *visible* (`get_bots_by_tag("expert")`) while *inert* until something
activates it.

The **`KnowledgeResolver`** is a pure function object: `resolve(expert, stage, workspace, *, model, counter)` walks
the fixed order — rules chain → Tier-1 shared → Tier-1 expert → Tier-2 shared → Tier-2 expert → accepted ADRs →
stage inputs (empty until phase 4) → retrieval handles — and returns a `KnowledgeContext` whose `layers[]` each carry
`layer`, `source`, `mode`, `revision` (sha256 of the bytes, or the ADR `content_fingerprint`, or a `WorkspacePin`
digest), `tokens` and `content` (inline) or `handle` (retrieval). The budget is `build_default_budget(model)`'s
`reserve_fixed` share for knowledge (default fraction configurable), trimming Tier-1 methodology before Tier-2 and
never touching `rules` or identity; every trimmed layer is listed in `trimmed[]`. Rendering is one literal layer per
inline group: `expert_rules` (new `LayerPriority.RULES = 12`) and `expert_knowledge` (replaces the
`knowledge_content` of `KNOWLEDGE_LAYER`), both `literal=True` because they are authored text.

The **KB fold-in** (U5) makes `AbstractBot._build_kb_context()` delegate to the resolver's `kb` source when the bot
carries a `knowledge_resolver`; the legacy branch stays intact for bots without one, so no existing agent changes
behaviour. `register_kb()` and `KBSelector` are kept as the implementation of that source.

**ADR**: the `adr` source calls `DecisionService.why()` / `for_symbol()` with `budget_tokens` and keeps only
`source_status == "accepted"` (and `review_status != "rejected"`) hits; production goes through
`DecisionService.generate(target)` → candidates with `origin="inferred"`, exposed to the expert as the
`expert_propose_adr` tool in `parrot_tools.experts`; acceptance is `DecisionService.review(ReviewRequest)` by a
human, never by the expert.

**Attribution**: `activate_expert(expert, *, run_id, stage)` is an async context manager stacking
`agent_identity(expert.name)` and `usage_attribution(run_id, f"{stage}.{expert.name}")`; it is the only entry point
the (future) stage conductor uses.

### Component Diagram
```
AGENTS_DIR/experts/<slug>/            AGENTS_DIR/governance/{org,team,project}.md
  expert.yaml  identity/  knowledge/  rules/governance.md  adr/  persona.md
        │                                   │
        ▼                                   ▼
ExpertBundleLoader ──▶ ExpertManifest ──▶ ExpertView (tenant overlay) ──▶ ExpertRegistry
   (M2)                  (M1)              (M2)                            (M2)
                                                                            │ builds
                                                                            ▼
                                   ExpertAgent(IdentityMixin, Agent) ◀── tier→ModelConfig, toolkits, allowlist
                                   (M3)        │                              (M10)
                                               │ knowledge_resolver
                                               ▼
   RulesChain (M8) ──▶ KnowledgeResolver (M4) ──▶ KnowledgeContext ──▶ render → PromptBuilder layers (M6)
                           │   sources (M5): bundled · workspace · adr · wiki · bookstore · graphindex · kb
                           │                    │        │       │        │           │          └─ AbstractBot._build_kb_context (M7)
                           │                    │        │       │        │           └─ RetrievalRequest/Budget (L2)
                           │                    │        │       │        └─ BookstoreToolkit (topics, scope)
                           │                    │        │       └─ LLMWikiToolkit (namespace)
                           │                    │        └─ DecisionService.why/for_symbol (accepted only)
                           └─ budget: build_default_budget(model) · tokens: get_default_counter()
   parrot_tools.experts.ExpertKnowledgeToolkit (M9): expert_knowledge_search · expert_propose_adr
   activate_expert(): agent_identity + usage_attribution (M3)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.skills.loader.SkillsDirectoryLoader` / `parsers.discover_skills_in_dir` | pattern (copied, not subclassed) | per-directory discovery, warn-and-skip on malformed bundles |
| `parrot.skills.tenancy.SkillView` / `RESERVED_TENANT_NAMES` | pattern + modifies | `ExpertView` mirrors tenant-over-global shadowing; `experts`, `knowledge`, `governance` added to the reserved set |
| `parrot.bots.mixins.identity.IdentityMixin` / `parrot.bots.prompts.identity.load_identity` | uses | `ExpertAgent` sets `enable_identity=True`, `identity_dir=<bundle>/identity`; loader validates the directory with `load_identity()` |
| `parrot.bots.prompts.builder.PromptBuilder` / `layers.PromptLayer`, `LayerPriority` | extends | new `RULES = 12` priority, `EXPERT_RULES_LAYER`, `EXPERT_KNOWLEDGE_LAYER` (both `literal=True`) |
| `parrot.registry.registry.AgentRegistry.register_instance` / `get_bots_by_tag` | uses | experts registered as instances tagged `expert`, `expert:<slug>` |
| `parrot.models.basic.ModelConfig` | uses | `tier` → `ModelConfig` projection at load |
| `parrot.bots.abstract.AbstractBot._build_kb_context` / `register_kb` / `knowledge_bases` | modifies | resolver-aware branch (U5) |
| `parrot.memory.compaction.budget.build_default_budget` / `resolve_window`; `compaction.tokens.get_default_counter` | uses | knowledge budget and token counting |
| `parrot.knowledge.wiki.decisions.service.DecisionService` (`why`, `for_symbol`, `generate`, `review`) | uses | ADR consumer + producer |
| `parrot_tools.wiki.toolkit.LLMWikiToolkit` | uses | mandatory wiki access bound to the expert namespace (`wiki_name=f"expert-{slug}"`) |
| `parrot.knowledge.bookstore.toolkit.BookstoreToolkit` | uses | mandatory bookstore access; `topics`/`scope` filtering in the adapter |
| `parrot.knowledge.retrieval` (`RetrievalRequest`, `RetrievalBudget`, `ContextBundle`) | uses | `graphindex` retrieval handle |
| `parrot.observability.context.agent_identity` / `usage_attribution` | uses | `activate_expert()` |
| `parrot.tools.spawn.SpawnSubAgentTool` (`name="spawn_sub_agent"`) | excludes | manifest validator + allowlist + PBAC deny rule (M10, §8 Q3) |
| `parrot.auth.models.PolicyRuleConfig` / `AgentRegistry.register_db_bot_policies` | extends / calls | optional `resource` field; the per-expert `tool:execute` deny on `tool:spawn_sub_agent` is loaded through the public DB-path registrar because `register_instance` registers no policies |

### Data Models
```python
# packages/ai-parrot/src/parrot/experts/models.py  (new)
class KnowledgeMode(str, Enum): INLINE = "inline"; RETRIEVAL = "retrieval"
class KnowledgeSourceKind(str, Enum):
    BUNDLED = "bundled"; WORKSPACE = "workspace"; WIKI = "wiki"; BOOKSTORE = "bookstore"
    GRAPHINDEX = "graphindex"; ADR = "adr"; KB = "kb"
class ExpertTier(str, Enum): JUDGMENT = "judgment"; BALANCED = "balanced"; TEMPLATED = "templated"

class KnowledgeSourceSpec(BaseModel):          # one `knowledge:` entry of expert.yaml
    model_config = ConfigDict(extra="forbid")
    source: KnowledgeSourceKind
    mode: KnowledgeMode
    scope: dict[str, list[str]] = Field(default_factory=dict)   # wiki/bookstore: {"topics": [...]}
    filter: dict[str, list[str]] = Field(default_factory=dict)  # adr: {"status": ["accepted"]}

class ExpertManifest(BaseModel):               # expert.yaml
    model_config = ConfigDict(extra="forbid")
    name: str; display_name: str; description: str
    tier: ExpertTier = ExpertTier.BALANCED
    toolkits: list[str] = Field(default_factory=list)
    tools_allow: list[str] = Field(default_factory=list)        # allowlist (no deny-list exists in parrot)
    knowledge: list[KnowledgeSourceSpec]
    capabilities: list[Literal["validate", "write", "review"]] = Field(default_factory=list)
    produces: list[str] = Field(default_factory=list)
    global_only: bool = False
    # validators: name is kebab-case; knowledge has a WIKI entry; "spawn_sub_agent" not in toolkits/tools_allow

class RuleSet(BaseModel):                      # rules/governance.md and AGENTS_DIR/governance/*.md
    layer: Literal["org", "team", "project", "expert", "stage"]
    source: Path; revision: str                 # sha256
    mandated: list[str]; forbidden: list[str]   # each starts with "ALWAYS " / "NEVER "

class KnowledgeLayer(BaseModel):
    layer: Literal["rules", "tier1_shared", "tier1_expert", "tier2_shared", "tier2_expert", "adr", "stage_input", "retrieval"]
    source: str; mode: KnowledgeMode; revision: str; tokens: int
    content: str | None = None                  # inline
    handle: dict[str, Any] | None = None        # retrieval (toolkit + scope, or a WorkspacePin)

class KnowledgeContext(BaseModel):
    expert: str; stage: str | None; budget_tokens: int
    layers: list[KnowledgeLayer]; trimmed: list[KnowledgeLayer]
    def inline_text(self, layer: str) -> str: ...

class ExpertBundle(BaseModel):                 # loader output
    manifest: ExpertManifest; root: Path; identity_dir: Path; persona_doc: Path | None
    knowledge_files: list[Path]; rules: RuleSet | None; adr_dir: Path | None; tenant: str | None = None
```

### New Public Interfaces
```python
from parrot.experts import ExpertRegistry, ExpertManifest, KnowledgeResolver, KnowledgeContext, activate_expert

registry = ExpertRegistry(agents_dir=AGENTS_DIR, agent_registry=agent_registry)
count = await registry.load()                       # discover AGENTS_DIR/experts/*, build + register ExpertAgents
expert = registry.get("cve-analyst", tenant="acme")  # ExpertAgent (tenant view applied)
ctx = await expert.knowledge_resolver.resolve(expert=expert.bundle, stage=None, workspace=registry.workspace,
                                              model=expert.model, counter=get_default_counter())
async with activate_expert(expert, run_id="run-1", stage="research"):
    answer = await expert.ask("…")                   # attributed to "cve-analyst", seat "research.cve-analyst"
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Manifest & models | yes | Pydantic v2, `extra="forbid"`, enums above, validators listed in §3 | — |
| M2: Bundle loader, view, registry | yes | copy of `discover_skills_in_dir` / `SkillView`; `register_instance(tags=…)`; reserved names | — |
| M3: ExpertAgent + activation | yes | `IdentityMixin` + `Agent` MRO, `enable_identity=True`, `identity_dir`; `agent_identity` + `usage_attribution` | — |
| M4: KnowledgeResolver / context | yes | order, budget source, trim order, revision rule fixed in §2 | — |
| M5: Knowledge source adapters | partly | protocol fixed; `adr`, `kb`, `bundled`, `workspace` are mechanical | `wiki`/`bookstore`/`graphindex` handle shape depends on toolkit construction wiring (server params) — thinking model decides |
| M6: Prompt rendering layers | yes | two literal layers, `RULES = 12`, replaces `knowledge_content` | — |
| M7: KB fold-in | no | — | touches `AbstractBot._build_kb_context` (248 KB file, no recent tests); thinking model pins behaviour first |
| M8: Rules chain | yes | grammar (`## Mandated`/`## Forbidden`, `ALWAYS`/`NEVER` lines), chain order, dedupe | — |
| M9: `parrot_tools.experts` toolkit | yes | two tools with fixed signatures; `DecisionService.generate` → candidates | — |
| M10: Tier policy, allowlist + PBAC deny | yes | policy table, `spawn_sub_agent` exclusion, `ModelConfig` output, `PolicyRuleConfig.resource` extension + `expert_policy_rules()` | — |
| M11: Docs | yes | `docs/experts/domain-experts.md` mirroring `docs/skills/per-tenant-skills.md` | — |

### Module 1: Manifest & models
- **Path**: `packages/ai-parrot/src/parrot/experts/__init__.py`, `packages/ai-parrot/src/parrot/experts/models.py`
- **Responsibility**: `ExpertManifest`, `KnowledgeSourceSpec`, `RuleSet`, `KnowledgeLayer`, `KnowledgeContext`,
  `ExpertBundle`, enums; the manifest invariants as Pydantic validators.
- **Depends on**: `pydantic` only (no parrot imports except typing helpers), so the models import without the LLM stack.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/experts/models.py  (new)
  SPAWN_TOOL_NAME: Final[str] = "spawn_sub_agent"   # verified: parrot/tools/spawn.py:128 (default name)

  class ExpertManifest(BaseModel):
      """Machine-read `expert.yaml`; `extra="forbid"`."""
      @field_validator("name")
      def _kebab(cls, v: str) -> str: """kebab-case, 2-64 chars; raises ValueError."""
      @model_validator(mode="after")
      def _invariants(self) -> "ExpertManifest":
          """Raises ValueError when: no `source: wiki` entry; SPAWN_TOOL_NAME in toolkits/tools_allow;
          `tier` value is not an ExpertTier (a model id is rejected by the enum)."""

  class KnowledgeContext(BaseModel):
      def inline_text(self, layer: str) -> str: """Concatenate `content` of inline layers named `layer`; '' when none."""
      def retrieval_handles(self) -> list[KnowledgeLayer]: """Layers with mode == RETRIEVAL."""
  ```

### Module 2: Bundle loader, tenant view and `ExpertRegistry`
- **Path**: `packages/ai-parrot/src/parrot/experts/loader.py`, `packages/ai-parrot/src/parrot/experts/view.py`,
  `packages/ai-parrot/src/parrot/experts/registry.py`; modifies `packages/ai-parrot/src/parrot/skills/tenancy.py:23`
- **Responsibility**: discover `AGENTS_DIR/experts/<slug>/` bundles (and `tenants/<t>/` overlays), validate, build
  `ExpertAgent`s (M3) and register them into `AgentRegistry`; strict duplicate rule (fail, unlike `register()`).
- **Depends on**: M1, M3, M10; `parrot.skills.tenancy.validate_tenant_id`, `secure_path`; `AgentRegistry.register_instance`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/experts/loader.py  (new)
  EXPERTS_DIRNAME: Final[str] = "experts"
  MANIFEST_FILENAME: Final[str] = "expert.yaml"

  def parse_expert_bundle(bundle_dir: Path, *, tenant: str | None = None) -> ExpertBundle:
      """Parse one bundle. Raises ExpertBundleError when expert.yaml is missing/invalid, when
      manifest.name != bundle_dir.name, when identity/ has no readable field
      (load_identity verified: parrot/bots/prompts/identity.py:51), or when any identity file contains a
      `$` placeholder (IDENTITY_LAYER is string.Template-substituted, layers.py:152-162 — S3)."""

  def discover_expert_bundles(directory: Path, logger: logging.Logger = _LOGGER) -> list[ExpertBundle]:
      """Non-recursive; sorted entries; a subdir without expert.yaml is ignored; malformed bundles are
      logged and skipped (mirror of discover_skills_in_dir, verified: parrot/skills/parsers.py:181)."""

  # packages/ai-parrot/src/parrot/experts/view.py  (new)
  class ExpertView:
      """Tenant overlay: tenant bundle shadows the global bundle of the same name unless the global is
      `global_only` (dropped with a warning) — SkillView semantics (verified: parrot/skills/tenancy.py:164)."""
      def __init__(self, globals_: Sequence[ExpertBundle], tenant: Sequence[ExpertBundle], *, tenant_id: str | None): ...
      def resolve(self, name: str) -> ExpertBundle | None: ...
      @property
      def shadowing(self) -> dict[str, str]: """name -> tenant path that shadows it."""

  # packages/ai-parrot/src/parrot/experts/registry.py  (new)
  class ExpertRegistry:
      """Owns bundles and the ExpertAgents built from them; registers them into AgentRegistry."""
      def __init__(self, *, agents_dir: Path, agent_registry: "AgentRegistry", workspace: Path | None = None) -> None: ...
      async def load(self) -> int:
          """Discover AGENTS_DIR/experts, build one ExpertAgent per bundle, call
          agent_registry.register_instance(name, agent, tags={"expert", f"expert:{name}"})
          (verified: parrot/registry/registry.py:633). Raises DuplicateExpertError on a repeated name.
          Before building the agent, probes the bundle's wiki namespace through WikiSource.probe(); an
          unresolvable or EMPTY `expert-<slug>` store rejects the bundle — not registered, logged at ERROR,
          report()["skipped"] gets {"path", "reason": "empty-wiki-namespace"} — and loading continues with
          the next bundle (§8 Q2: fail at load). After register_instance(), pushes the non-delegation PBAC
          rule with agent_registry.register_db_bot_policies(name, expert_policy_rules(bundle.manifest))
          (verified public: registry.py:507; register_instance itself never registers policies — only
          register() calls _collect_and_register_policies, registry.py:631) — §8 Q3."""
      def get(self, name: str, *, tenant: str | None = None) -> "ExpertAgent": """KeyError when unknown."""
      def names(self) -> list[str]: ...
      def report(self) -> dict[str, Any]:
          """{"loaded": [...], "skipped": [{"path", "reason"}], "shadowing": {name: tenant_path}} — S1."""

  # packages/ai-parrot/src/parrot/skills/tenancy.py  (modifies :23-37)
  RESERVED_TENANT_NAMES = frozenset({..., "experts", "knowledge", "governance"})   # three names added
  ```

### Module 3: `ExpertAgent` and activation scope
- **Path**: `packages/ai-parrot/src/parrot/experts/agent.py`, `packages/ai-parrot/src/parrot/experts/activation.py`
- **Responsibility**: the runtime agent type an expert bundle produces; the attribution context manager.
- **Depends on**: M1, M4, M10; `IdentityMixin` (verified `parrot/bots/mixins/identity.py:40`), `Agent`
  (verified `parrot/bots/agent.py:1576`), `agent_identity`/`usage_attribution` (verified `parrot/observability/context.py:86,162`).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/experts/agent.py  (new)
  class ExpertAgent(IdentityMixin, Agent):   # IdentityMixin verified: parrot/bots/mixins/identity.py:40
      """Agent configured from an ExpertBundle: enable_identity=True, identity_dir=<bundle>/identity."""
      enable_identity: bool = True
      bundle: ExpertBundle
      knowledge_resolver: "KnowledgeResolver"
      def __init__(self, bundle: ExpertBundle, *, resolver: "KnowledgeResolver", model_config: ModelConfig,
                   toolkits: Sequence[AbstractToolkit], allowed_tools: Sequence[str], **kwargs: Any) -> None:
          """Sets identity_dir (IdentityMixin reads it: identity.py:60,119) before super().__init__."""
      async def configure(self, *args: Any, **kwargs: Any) -> None:
          """super().configure(); await self._configure_identity() (verified identity.py:130);
          resolve KnowledgeContext and install the rendered layers (M6)."""

  # packages/ai-parrot/src/parrot/experts/activation.py  (new)
  @asynccontextmanager
  async def activate_expert(expert: ExpertAgent, *, run_id: str | None, stage: str | None) -> AsyncIterator[ExpertAgent]:
      """Stack agent_identity(expert.bundle.manifest.name) and usage_attribution(run_id, f"{stage}.{name}")
      (verified: parrot/observability/context.py:86, :162); yields the expert."""
  ```

### Module 4: `KnowledgeResolver` and budget
- **Path**: `packages/ai-parrot/src/parrot/experts/knowledge/__init__.py`, `packages/ai-parrot/src/parrot/experts/knowledge/resolver.py`, `packages/ai-parrot/src/parrot/experts/knowledge/budget.py`
- **Responsibility**: the deterministic order, token accounting, budget and trim; pure (no I/O beyond reading files
  and calling source adapters), reproducible without an LLM.
- **Depends on**: M1, M5, M8; `build_default_budget`/`resolve_window` (verified `parrot/memory/compaction/budget.py:81,61`),
  `get_default_counter` (verified `parrot/memory/compaction/tokens.py:89`), `TokenCounter.count` (tokens.py:30-35).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/experts/knowledge/resolver.py  (new)
  LAYER_ORDER: Final[tuple[str, ...]] = ("rules", "tier1_shared", "tier1_expert", "tier2_shared", "tier2_expert", "adr", "stage_input", "retrieval")
  TRIM_ORDER: Final[tuple[str, ...]] = ("tier1_shared", "tier1_expert", "adr", "tier2_shared", "tier2_expert")  # never rules

  class KnowledgeResolver:
      """Pure resolver; sources are injected (M5)."""
      def __init__(self, sources: Sequence["KnowledgeSource"], *, counter: TokenCounter | None = None) -> None: ...
      async def resolve(self, expert: ExpertBundle, stage: str | None, workspace: Path | None, *,
                        model: str | None, budget_tokens: int | None = None) -> KnowledgeContext:
          """budget_tokens defaults to knowledge_budget(model). Returns layers in LAYER_ORDER with
          per-layer revision+tokens; trims per TRIM_ORDER until sum(inline tokens) <= budget; rules
          and stage_input are never trimmed; trimmed layers are returned in `trimmed`."""

  # packages/ai-parrot/src/parrot/experts/knowledge/budget.py  (new)
  KNOWLEDGE_FRACTION: Final[float] = 0.15
  def knowledge_budget(model: str | None, *, fraction: float = KNOWLEDGE_FRACTION) -> int:
      """int(resolve_window(model) * fraction) (verified: parrot/memory/compaction/budget.py:61)."""
  def sha256_revision(data: bytes) -> str: """hex sha256 — the `revision` of file-backed layers."""
  ```

### Module 5: Knowledge source adapters
- **Path**: `packages/ai-parrot/src/parrot/experts/knowledge/sources/{__init__,base,bundled,workspace,adr,wiki,bookstore,graphindex,kb}.py`
- **Responsibility**: one adapter per `KnowledgeSourceKind`, each producing `KnowledgeLayer`s for its mode.
- **Depends on**: M1, M4; `DecisionService` (verified `parrot/knowledge/wiki/decisions/service.py:96,193,276`),
  `LLMWikiToolkit` (verified `parrot_tools/wiki/toolkit.py:48`), `BookstoreToolkit` (verified
  `parrot/knowledge/bookstore/toolkit.py:29`), `RetrievalRequest`/`RetrievalBudget` (verified
  `parrot/knowledge/retrieval/__init__.py:18-66`), `AbstractBot.knowledge_bases` (verified `parrot/bots/abstract.py:583`).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/experts/knowledge/sources/base.py  (new)
  class KnowledgeSource(Protocol):
      kind: KnowledgeSourceKind
      async def layers(self, spec: KnowledgeSourceSpec, bundle: ExpertBundle, *, workspace: Path | None,
                       counter: TokenCounter) -> list[KnowledgeLayer]:
          """Inline sources return content+tokens+revision; retrieval sources return a `handle` and tokens=0."""

  # sources/adr.py — consumer side
  class ADRSource:
      def __init__(self, service: DecisionService) -> None: ...   # verified: decisions/service.py:96
      async def layers(...) -> list[KnowledgeLayer]:
          """Calls service.why(question=bundle.manifest.description, budget_tokens=<spec budget>) (service.py:276)
          and keeps hits whose record.source_status in spec.filter["status"] (default ["accepted"]),
          record.review_status != "rejected", and — when spec.filter["links"] is set — at least one
          record.links target matches (DecisionRecord verified: decisions/models.py:172; no tags field — S6);
          revision = record.content_fingerprint."""

  # sources/wiki.py — retrieval handle only
  class WikiSource:
      def __init__(self, toolkit: LLMWikiToolkit, *, namespace: str) -> None: ...   # namespace = f"expert-{slug}"
      async def layers(...) -> list[KnowledgeLayer]:
          """handle = {"toolkit": "wiki", "wiki_name": namespace, "scope": spec.scope, "documents": int}; raises
          ExpertKnowledgeError when the namespace store cannot be resolved (toolkit._store_for, toolkit.py:215)
          AND when it resolves but holds zero documents (§8 Q2: fail at load — never a warning)."""
      async def probe(self) -> int:
          """Document count of the namespace store, no LLM call; raises ExpertKnowledgeError on an unresolvable
          store. ExpertRegistry.load() calls it per bundle and treats 0 as a rejection (S10, §8 Q2)."""

  # sources/kb.py — U5 fold-in
  class LegacyKBSource:
      def __init__(self, bot: "AbstractBot") -> None: ...
      async def layers(...) -> list[KnowledgeLayer]:
          """handle = {"toolkit": "kb", "names": [kb.name for kb in bot.knowledge_bases]} (abstract.py:583);
          the search itself stays in AbstractBot._build_kb_context (M7)."""
  ```

### Module 6: Prompt rendering layers
- **Path**: `packages/ai-parrot/src/parrot/experts/knowledge/render.py`; modifies `packages/ai-parrot/src/parrot/bots/prompts/layers.py:27` (enum) and appends two layer constants after `KNOWLEDGE_LAYER` (`layers.py:191`)
- **Responsibility**: turn a `KnowledgeContext` into literal prompt layers and install them on the agent's builder.
- **Depends on**: M4; `PromptLayer` (verified `layers.py:51`, `literal` at :78), `LayerPriority` (verified `layers.py:22-32`),
  `PromptBuilder.add` (verified `builder.py:200-240`).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/bots/prompts/layers.py  (modifies :27 — add one member after KNOWLEDGE)
  class LayerPriority(IntEnum):
      ...
      RULES = 12          # new: after IDENTITY (10), before PRE_INSTRUCTIONS (15)
  EXPERT_RULES_LAYER = PromptLayer(name="expert_rules", priority=LayerPriority.RULES,
                                   phase=RenderPhase.CONFIGURE, template="", literal=True)       # new
  EXPERT_KNOWLEDGE_LAYER = PromptLayer(name="expert_knowledge", priority=LayerPriority.KNOWLEDGE,
                                       phase=RenderPhase.CONFIGURE, template="", literal=True)   # new

  # packages/ai-parrot/src/parrot/experts/knowledge/render.py  (new)
  def render_rules(ctx: KnowledgeContext) -> str: """<governance_rules>…</governance_rules> from layer 'rules'."""
  def render_knowledge(ctx: KnowledgeContext) -> str: """<expert_knowledge> per-layer sections with source+revision."""
  def install_layers(builder: PromptBuilder, ctx: KnowledgeContext) -> PromptBuilder:
      """Works on builder.clone() (never the caller's instance — S2; clone verified: builder.py:35-362);
      adds EXPERT_RULES_LAYER / EXPERT_KNOWLEDGE_LAYER with rendered literal templates and removes the default
      'knowledge' layer so content is not projected twice (builder.remove verified: builder.py:200-240);
      returns the new builder."""
  ```

### Module 7: KB fold-in (U5)
- **Path**: modifies `packages/ai-parrot/src/parrot/bots/abstract.py:3889` (`_build_kb_context`) and `:1189` (`register_kb`)
- **Responsibility**: route the legacy KB search through the resolver's `kb` handle when a resolver is present;
  keep the legacy branch byte-for-byte for bots without one.
- **Depends on**: M5 (`LegacyKBSource`), M4.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/bots/abstract.py  (modifies :3889-3950)
  async def _build_kb_context(self, question: str, user_id: Optional[str] = None, session_id: Optional[str] = None,
                              ctx: Optional[RequestContext] = None) -> Tuple[str, Dict[str, Any]]:  # verified: abstract.py:3889
      """New first branch: resolver = getattr(self, "knowledge_resolver", None); if resolver is not None and
      resolver.has_handle("kb"): return await resolver.search_kb(self, question, k=5) — same return shape
      (kb_context: str, metadata: {"activated_kbs": [...]}). Otherwise the existing body runs unchanged."""

  def register_kb(self, kb: AbstractKnowledgeBase):   # verified: abstract.py:1189 — unchanged signature
      """Unchanged; additionally invalidates a cached KnowledgeContext on the resolver when present."""
  ```

### Module 8: Governance rules chain
- **Path**: `packages/ai-parrot/src/parrot/experts/rules.py`
- **Responsibility**: parse rule files, resolve the additive chain org → team → project → expert (→ stage, phase 4),
  de-duplicate, count; rules are never trimmed.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/experts/rules.py  (new)
  GOVERNANCE_DIRNAME: Final[str] = "governance"          # AGENTS_DIR/governance/{org,team,project}.md
  RULE_LAYERS: Final[tuple[str, ...]] = ("org", "team", "project", "expert", "stage")

  def parse_rules(path: Path, *, layer: str) -> RuleSet:
      """Grammar: '## Mandated' section lines starting 'ALWAYS ', '## Forbidden' lines starting 'NEVER ';
      any other non-empty line raises RuleSyntaxError (no free prose)."""
  def resolve_chain(workspace: Path | None, bundle: ExpertBundle, *, stage_rules: RuleSet | None = None) -> list[RuleSet]:
      """Additive: a wider layer is never removed by a narrower one; exact-duplicate lines are deduplicated
      keeping the widest layer; returns RuleSets in RULE_LAYERS order (missing files skipped)."""
  def rules_to_layer(chain: Sequence[RuleSet], counter: TokenCounter) -> KnowledgeLayer: """layer='rules', mode=INLINE."""
  ```

### Module 9: `parrot_tools.experts` toolkit (ADR producer, knowledge search)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/experts/__init__.py`, `packages/ai-parrot-tools/src/parrot_tools/experts/toolkit.py`
- **Responsibility**: the expert-facing tools: search across the context's retrieval handles; propose an ADR.
- **Depends on**: M4, M5; `AbstractToolkit` (core), `DecisionService.generate` (verified `service.py:389`),
  `DecisionService.review` (verified `service.py:473`, human-only — not exposed as a tool).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-tools/src/parrot_tools/experts/toolkit.py  (new)
  class ExpertKnowledgeToolkit(AbstractToolkit):
      name = "experts"; tool_prefix = "expert"
      def __init__(self, context: KnowledgeContext, *, wiki: LLMWikiToolkit, bookstore: BookstoreToolkit,
                   decisions: DecisionService | None = None, **kwargs: Any) -> None: ...
      async def knowledge_search(self, question: str, top_k: int = 8) -> dict[str, Any]:
          """Fan out over ctx.retrieval_handles(): wiki.query(wiki_name=handle['wiki_name'], question=…)
          (verified: parrot_tools/wiki/toolkit.py:373), bookstore.search(query, max_books=3)
          (verified: bookstore/toolkit.py:195); results carry source + revision."""
      async def propose_adr(self, target: str, rationale: str) -> dict[str, Any]:
          """decisions.generate(target) (service.py:389); returns candidate ids with origin='inferred',
          review_status='unreviewed'; raises ExpertCapabilityError when 'write' not in manifest.capabilities."""
  ```

### Module 10: Tier policy, tool allowlist and PBAC non-delegation rule
- **Path**: `packages/ai-parrot/src/parrot/experts/policy.py`; modifies `packages/ai-parrot/src/parrot/auth/models.py:32-160` (`PolicyRuleConfig`)
- **Responsibility**: `tier` → `ModelConfig`; the effective toolkit set (mandatory wiki + bookstore added, `spawn_sub_agent` excluded); the allowlist handed to `ExpertAgent`; the PBAC deny rule every expert registers (§8 Q3). The `PolicyRuleConfig` change is additive: a new optional `resource` field; when it is `None`, `to_resource_policy()` output is byte-identical to today (pinned test).
- **Depends on**: M1; `ModelConfig` (verified `parrot/models/basic.py:40`); `SPAWN_TOOL_NAME`; `PolicyRuleConfig` (verified `parrot/auth/models.py:32`, `to_resource_policy` at `:108`).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/experts/policy.py  (new)
  DEFAULT_TIER_POLICY: Final[dict[ExpertTier, dict[str, Any]]]   # provider/model/temperature per tier; overridable via conf
  def model_config_for(tier: ExpertTier, *, overrides: Mapping[str, Any] | None = None) -> ModelConfig: ...   # verified: parrot/models/basic.py:40
  MANDATORY_TOOLKITS: Final[tuple[str, ...]] = ("LLMWikiToolkit", "BookstoreToolkit")
  def effective_toolkits(manifest: ExpertManifest) -> list[str]: """manifest.toolkits ∪ MANDATORY_TOOLKITS, ordered, deduped."""
  def effective_allowlist(manifest: ExpertManifest, discovered: Sequence[str]) -> list[str]:
      """discovered tool names ∩ (tools_allow or all) minus {SPAWN_TOOL_NAME}; raises ExpertPolicyError if the
      result would include SPAWN_TOOL_NAME (defense in depth over the manifest validator)."""
  SPAWN_DENY_PRIORITY: Final[int] = 100   # above operator YAML (>= 20): the invariant is NOT operator-overridable
  def expert_policy_rules(manifest: ExpertManifest) -> list[dict[str, Any]]:
      """[{"action": "tool:execute", "effect": "deny", "resource": f"tool:{SPAWN_TOOL_NAME}",
          "priority": SPAWN_DENY_PRIORITY, "description": f"expert {manifest.name}: no delegation (FEAT-778)"}]
      — dict shape accepted by parse_bot_permissions (agent_guard.py:73) and matched by the TOOL_CALL check
      (resource_type=TOOL, resource_name=tool_name, action="tool:execute": guardrails/builtin/pbac.py:278,
      auth/resolver.py:326)."""

  # packages/ai-parrot/src/parrot/auth/models.py  (modifies PolicyRuleConfig, :32)
  class PolicyRuleConfig(BaseModel):
      ...                                                     # existing fields unchanged
      resource: Optional[str] = Field(default=None, description="Explicit resource id (e.g. 'tool:spawn_sub_agent'); None keeps agent:<name>")
      def to_resource_policy(self, agent_name: str) -> dict:
          """resources = [self.resource] if self.resource else [f"agent:{agent_name}"] (:153); the policy
          `name` embeds the resource when set so two rules for one agent never collide; every other key unchanged."""
  ```

### Module 11: Documentation
- **Path**: `docs/experts/domain-experts.md`
- **Responsibility**: bundle layout, manifest reference, load order and trim rules, rules grammar, tenant shadowing,
  ADR consume/produce flow, the `persona.md`-is-documentation rule, what phases 3–5 add later.
- **Depends on**: all modules (written last).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_manifest_requires_wiki_source` | M1 | manifest without `source: wiki` is rejected |
| `test_manifest_rejects_spawn_tool` | M1 | `spawn_sub_agent` in `toolkits`/`tools_allow` raises |
| `test_manifest_tier_rejects_model_id` | M1 | `tier: gpt-x` is a validation error |
| `test_discover_ignores_dirs_without_manifest` | M2 | mirror of `test_discover_composite` for experts |
| `test_bundle_name_must_match_dir` | M2 | `expert.yaml` name ≠ dir → skipped with warning |
| `test_duplicate_expert_fails_load` | M2 | two bundles with one name → `DuplicateExpertError` |
| `test_tenant_shadows_global_unless_global_only` | M2 | `ExpertView` semantics equal to `SkillView` |
| `test_reserved_names_include_experts` | M2 | `experts`, `knowledge`, `governance` are reserved tenant ids |
| `test_registry_registers_tagged_instance` | M2 | `AgentRegistry.get_bots_by_tag("expert")` returns the expert |
| `test_registry_pushes_deny_rule_to_evaluator` | M2 | a fake PDP evaluator receives one policy dict with `effect="deny"`, `actions=["tool:execute"]`, `resources=["tool:spawn_sub_agent"]` per loaded expert via `register_db_bot_policies` |
| `test_expert_agent_uses_bundle_identity_dir` | M3 | `IdentityMixin` reads `<bundle>/identity`, not the class module dir |
| `test_activate_expert_attribution` | M3 | `current_agent_name`/`current_seat` inside the scope, restored after |
| `test_resolver_layer_order_is_fixed` | M4 | `LAYER_ORDER` honoured regardless of source registration order |
| `test_resolver_trims_methodology_before_tier2_never_rules` | M4 | trim order + `trimmed[]` reporting |
| `test_resolver_is_deterministic` | M4 | same inputs → identical serialized `KnowledgeContext` (no LLM) |
| `test_knowledge_budget_from_model_window` | M4 | `knowledge_budget` uses `resolve_window` |
| `test_adr_source_filters_accepted_only` | M5 | proposed/rejected/superseded records excluded |
| `test_wiki_source_namespace_handle` | M5 | handle carries `wiki_name="expert-<slug>"` |
| `test_render_installs_literal_layers` | M6 | `expert_rules` priority 12, `literal=True`, default `knowledge` layer removed |
| `test_build_kb_context_legacy_path_unchanged` | M7 | bot without resolver → identical output to pre-change (pinned fixture) |
| `test_build_kb_context_delegates_to_resolver` | M7 | bot with resolver → `resolver.search_kb` called, same return shape |
| `test_rules_grammar_rejects_prose` | M8 | free text line → `RuleSyntaxError` |
| `test_rules_chain_is_additive_and_deduped` | M8 | org rule survives a narrower layer; duplicate kept once |
| `test_propose_adr_requires_write_capability` | M9 | `ExpertCapabilityError` without `write` |
| `test_effective_allowlist_never_contains_spawn` | M10 | defense in depth |
| `test_effective_toolkits_add_mandatory` | M10 | wiki + bookstore always present |
| `test_policy_rule_resource_override` | M10 | `PolicyRuleConfig(resource="tool:spawn_sub_agent")` → `resources=["tool:spawn_sub_agent"]`; without `resource` the dict equals a pinned pre-change fixture (AC21) |
| `test_expert_policy_rules_deny_spawn` | M10 | exactly one rule: `effect="deny"`, `action="tool:execute"`, `resource="tool:spawn_sub_agent"`, `priority=100` |
| `test_dollar_placeholders_stay_literal` | M2/M6 | `$name` in a rules/knowledge file survives `configure()`; `$` in an identity file is rejected at load (S3) |
| `test_wiki_source_unresolvable_and_empty_both_raise` | M5 | unresolvable namespace and zero-document namespace both raise `ExpertKnowledgeError`; a populated one returns `handle["documents"] > 0` (S10, §8 Q2) |
| `test_registry_rejects_empty_wiki_namespace` | M2 | bundle whose `expert-<slug>` store is empty is absent from `names()` and present in `report()["skipped"]` with reason `empty-wiki-namespace`; sibling bundles still load |
| `test_registry_report_lists_skipped_and_shadowed` | M2 | `ExpertRegistry.report()` names skipped bundles with reasons and tenant shadows (S1) |

### Integration Tests
| Test | Description |
|---|---|
| `test_bundle_to_prompt_roundtrip` | fixture bundle → `ExpertRegistry.load()` → `ExpertAgent.configure()` → rendered system prompt contains identity, rules and Tier-1 summary in order, with revisions |
| `test_tenant_overlay_changes_knowledge_not_rules` | tenant Tier-2 file shadows Tier-1 by name; org rules unchanged |
| `test_adr_consume_then_propose` | accepted ADR appears inline; `propose_adr` yields an `inferred`/`unreviewed` candidate that does **not** appear inline until reviewed |
| `test_concurrent_activations_do_not_share_builders` | two `activate_expert()` scopes run concurrently on two experts; each rendered prompt and each `current_agent_name` stay isolated (S2/S10) |

### Validation Contract

tests:
- packages/ai-parrot/tests/bots/test_identity_mixin.py
- packages/ai-parrot/tests/unit/test_skill_tenant_wiring.py
- tests/unit/test_skills_directory_loader.py
- packages/ai-parrot/tests/registry/test_yaml_roundtrip.py
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py
- packages/ai-parrot/tests/bots/test_knowledge_index_flags.py
markers: none

> New test files land under `packages/ai-parrot/tests/experts/` and
> `packages/ai-parrot-tools/tests/experts/`; `/sdd-task` appends them to this list once their node ids are frozen.

### Test Data / Fixtures
```python
@pytest.fixture
def expert_bundle(tmp_path: Path) -> Path:
    """AGENTS_DIR/experts/sample-expert/ with expert.yaml (wiki + bundled + adr sources), identity/{role,goal}.md,
    knowledge/method.md, rules/governance.md ('## Mandated\nALWAYS cite sources\n## Forbidden\nNEVER delegate'),
    persona.md (ignored by the loader), plus tenants/acme/knowledge/method.md shadowing Tier 1."""

@pytest.fixture
def governance_dir(tmp_path: Path) -> Path:
    """AGENTS_DIR/governance/{org,team,project}.md with one ALWAYS/NEVER each; org duplicates a project rule."""

@pytest.fixture
def decision_service_stub() -> DecisionService:
    """In-memory DecisionService with one accepted, one proposed and one rejected DecisionRecord."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC1 — `ExpertRegistry.load()` discovers every `AGENTS_DIR/experts/<slug>/expert.yaml`, skips malformed bundles with a warning, and **fails** (raises) on a duplicate expert name.
- [ ] AC2 — A manifest is rejected when its `knowledge` list has no `source: wiki`, when `spawn_sub_agent` appears in `toolkits`/`tools_allow`, when `tier` is not one of `judgment|balanced|templated`, or when `name` ≠ directory name.
- [ ] AC3 — `ExpertAgent` loads identity from `<bundle>/identity/` through `IdentityMixin` (five-file layout); `persona.md` is never read by the loader (test asserts it is absent from the prompt).
- [ ] AC4 — `KnowledgeResolver.resolve()` is deterministic: two runs over the same bundle/workspace produce byte-identical serialized `KnowledgeContext`, with no LLM client constructed.
- [ ] AC5 — Layers are emitted in `LAYER_ORDER`; when over budget the resolver trims in `TRIM_ORDER`, never trims `rules`, and lists every trimmed layer in `trimmed[]`.
- [ ] AC6 — Every inline layer carries `revision` (sha256 of the file bytes, or the ADR `content_fingerprint`) and `tokens` computed with `get_default_counter()`.
- [ ] AC7 — Tier-2 (`tenants/<t>/`) files shadow Tier-1 by name; a `global_only` Tier-1 entry cannot be shadowed (tenant file dropped with a warning) — identical semantics to `SkillView`.
- [ ] AC8 — The rules chain is additive org → team → project → expert, deduplicated, and rendered as the `expert_rules` layer at `LayerPriority.RULES == 12` with `literal=True`; a prose line in a rules file is a `RuleSyntaxError`.
- [ ] AC9 — The `adr` source includes only records with `source_status == "accepted"` and `review_status != "rejected"`; `expert_propose_adr` yields `origin="inferred"`, `review_status="unreviewed"` candidates and requires the `write` capability.
- [ ] AC10 — `effective_toolkits()` always includes `LLMWikiToolkit` (bound to `wiki_name="expert-<slug>"`) and `BookstoreToolkit`; `effective_allowlist()` never contains `spawn_sub_agent`.
- [ ] AC11 — `AbstractBot._build_kb_context()` output for a bot **without** a resolver is unchanged (pinned by a fixture test); with a resolver it delegates to the resolver's `kb` handle and returns the same `(str, {"activated_kbs": [...]})` shape.
- [ ] AC12 — Inside `activate_expert()`, `current_agent_name` is the expert name and `current_seat` is `"<stage>.<expert>"`; both are restored on exit.
- [ ] AC13 — `experts`, `knowledge`, `governance` are rejected by `validate_tenant_id()`.
- [ ] AC14 — `ruff check` passes on all new/modified files; the Validation Contract tests plus the new `tests/experts/` suites pass with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`.
- [ ] AC15 — `docs/experts/domain-experts.md` documents layout, manifest, load/trim order, rules grammar, shadowing and the ADR flow.
- [ ] AC16 — No change to `packages/ai-parrot/src/parrot/clients/base.py`; no new `AgentKind`; no new ContextVar.
- [ ] AC17 — Bundle-authored text is never template-substituted: `$name`/`$role` written in a rules or knowledge file appear verbatim in the built prompt, and an identity file containing a `$` placeholder makes the bundle fail to load with a clear error (S3).
- [ ] AC18 — Two concurrent `activate_expert()` scopes on different experts never share a `PromptBuilder` nor leak `current_agent_name`/`current_seat` into each other (S2/S10).
- [ ] AC19 — `ExpertRegistry.load()` rejects (never registers) a bundle whose `expert-<slug>` wiki namespace is unresolvable **or holds zero documents**; the rejection is logged at ERROR and appears in `report()["skipped"]` with reason `empty-wiki-namespace`; sibling bundles still load; the probe makes no LLM call (§8 Q2).
- [ ] AC20 — For every loaded expert, `AgentRegistry.register_db_bot_policies()` receives exactly one rule `{effect: deny, action: tool:execute, resource: tool:spawn_sub_agent, priority: 100}`; with no PDP evaluator it returns `0` and the allowlist exclusion (AC10) still holds (§8 Q3).
- [ ] AC21 — `PolicyRuleConfig` gains an optional `resource` field; `to_resource_policy()` for every existing rule (no `resource`) is byte-identical to the pre-change output (pinned fixture), and `tests/auth/test_policy_rules_integration.py` passes unchanged.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor** — verified against `b9502bfe3` (dev, 2026-10-30) with the FEAT-778
> research probes (`sdd/state/FEAT-778/citation_checks.md`, 163 checks, 0 stale) plus the reads listed here.

### Verified Imports
```python
from parrot.bots.agent import Agent                                   # verified: parrot/bots/agent.py:1576
from parrot.bots.mixins.identity import IdentityMixin                  # verified: parrot/bots/mixins/identity.py:40
from parrot.bots.prompts.identity import load_identity, IdentityFields, IDENTITY_FILES   # verified: identity.py:51,32,27
from parrot.bots.prompts.builder import PromptBuilder                  # verified: parrot/bots/prompts/builder.py:35
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase, KNOWLEDGE_LAYER, IDENTITY_LAYER  # verified: layers.py:51,22,35,191,152
from parrot.registry.registry import AgentRegistry, BotConfig, PromptConfig, AgentKind   # verified: registry.py:302,256,243,55
from parrot.models.basic import ModelConfig, ToolConfig               # verified: parrot/models/basic.py:40,33
from parrot.conf import AGENTS_DIR                                     # verified: parrot/conf.py:181
from parrot.skills.tenancy import RESERVED_TENANT_NAMES, TENANTS_DIRNAME, validate_tenant_id, tenant_skills_dir, SkillView  # verified: tenancy.py:23,38,42,54,164
from parrot.skills.parsers import discover_skills_in_dir, parse_skill_directory   # verified: parsers.py:181,151
from parrot.skills.loader import SkillsDirectoryLoader                 # verified: parrot/skills/loader.py:26
from parrot.skills.models import SkillDefinition                        # verified: parrot/skills/models.py:68
from parrot.memory.compaction.budget import build_default_budget, resolve_window, MODEL_WINDOWS   # verified: budget.py:81,61,43
from parrot.memory.compaction.models import ContextBudget              # verified: compaction/models.py:161
from parrot.memory.compaction.tokens import get_default_counter, TokenCounter   # verified: tokens.py:89,30
from parrot.knowledge.wiki.decisions.service import DecisionService    # verified: decisions/service.py:96
from parrot.knowledge.wiki.decisions.models import DecisionRecord, EvidenceRef, ReviewRequest, DecisionConfig   # verified: models.py:172,107,299,63
from parrot.knowledge.retrieval import RetrievalRequest, RetrievalBudget, ContextBundle, SourceDigest   # verified: retrieval/__init__.py:18-66
from parrot.knowledge.bookstore.toolkit import BookstoreToolkit        # verified: bookstore/toolkit.py:29
from parrot.knowledge.bookstore.models import BookCard                 # verified: bookstore/models.py:152
from parrot.observability.context import agent_identity, usage_attribution, current_agent_name, current_seat   # verified: context.py:86,162,67-82,156-162
from parrot.tools.spawn import SpawnSubAgentTool                       # verified: parrot/tools/spawn.py:88
from parrot.stores.kb.abstract import AbstractKnowledgeBase            # verified: parrot/stores/kb/abstract.py:7
from parrot_tools.wiki.toolkit import LLMWikiToolkit                   # verified: parrot_tools/wiki/toolkit.py:48
from parrot.auth.models import PolicyRuleConfig                        # verified: parrot/auth/models.py:32 (re-exported by parrot.auth, __init__.py:49)
from parrot.auth.agent_guard import parse_bot_permissions              # verified: parrot/auth/agent_guard.py:73
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/bots/mixins/identity.py
class IdentityMixin:                                                   # line 40
    enable_identity: bool = False                                      # line 59
    identity_dir: Union[str, Path, None] = None                        # line 60
    def __init__(self, *args: Any, **kwargs: Any) -> None:             # line 65 — loads identity BEFORE super().__init__
    def _resolve_identity_dir(self) -> Path:                           # line 119 — falls back to <class module dir>/identity
    async def _configure_identity(self) -> None:                       # line 130
    def _build_prompt(self, *args: Any, **kwargs: Any):                # line 202 — hot-reload seam
    def _reload_identity(self, fields: IdentityFields) -> None:        # line 222

# packages/ai-parrot/src/parrot/bots/prompts/identity.py
IDENTITY_FILES: tuple[str, ...] = ("role", "goal", "capabilities", "backstory", "rationale")   # line 27
def load_identity(directory: Union[str, Path], *, escape_placeholders: bool = False) -> IdentityFields:   # line 51

# packages/ai-parrot/src/parrot/bots/prompts/layers.py
class LayerPriority(IntEnum):                                          # line 22
    IDENTITY = 10; PRE_INSTRUCTIONS = 15; SECURITY = 20; KNOWLEDGE = 30; USER_SESSION = 40
    TOOLS = 50; OUTPUT = 60; BEHAVIOR = 70; CUSTOM = 80                # lines 24-32
class PromptLayer:                                                     # line 51 (dataclass)
    literal: bool = False                                              # line 78
IDENTITY_LAYER = PromptLayer(name="identity", priority=LayerPriority.IDENTITY, phase=RenderPhase.CONFIGURE, ...)  # line 152
KNOWLEDGE_LAYER = PromptLayer(name="knowledge", ... template="...$knowledge_content...",
                              condition=lambda ctx: bool(ctx.get("knowledge_content", "").strip()))   # lines 191-198

# packages/ai-parrot/src/parrot/bots/prompts/builder.py
class PromptBuilder:                                                   # line 35
    def __init__(self, layers: Optional[List[PromptLayer]] = None, *, prompt_caching: bool = False)   # line 50
    @classmethod def default(cls) -> PromptBuilder                     # line 67
    @classmethod def from_system_prompt(cls, system_prompt: str) -> PromptBuilder   # line 168
    def add(self, layer: PromptLayer) -> PromptBuilder                 # ~line 200 — add or replace by name
    def replace(self, name: str, layer: PromptLayer) -> PromptBuilder  # line 224 — KeyError when name missing
    def build(self, context: Dict[str, Any]) -> str                    # line 288

# packages/ai-parrot/src/parrot/registry/registry.py
class AgentKind(str, Enum): LOCAL, A2A, SQUAWK                         # line 55
class BotMetadata:                                                     # line 68
class PromptConfig(BaseModel): preset, remove, add, customize          # line 243
class PolicyRuleConfig(BaseModel): action: str, effect: Literal["allow","deny"]="allow", groups: Optional[list[str]]=None, roles: Optional[list[str]]=None, priority: int=10, description, conditions   # parrot/auth/models.py:32 — NO `resource` field today (M10 adds it)
    def to_resource_policy(self, agent_name: str) -> dict   # models.py:108 — resources hard-coded to [f"agent:{agent_name}"] at :153
class AgentRegistry:
    def register_db_bot_policies(self, name: str, permissions: "dict | list | None") -> int   # registry.py:507 — public; parses via parse_bot_permissions, loads into self._evaluator; returns 0 when PBAC is disabled
    def _collect_and_register_policies(self, name, factory, bot_config) -> None   # registry.py:423 — PRIVATE, called only from register() (:631), never from register_instance()
class BotConfig(BaseModel): name, class_name, module, enabled, origin, tools, toolkits, mcp_servers, model, system_prompt, prompt, tags, priority, policies, kind, endpoint, contract_categories   # line 256
class AgentRegistry:                                                   # line 302
    def register(self, name: str, factory: Type[AbstractBot], *, singleton=False, tags=None, priority=0, dependencies=None, replace=False, at_startup=False, startup_config=None, bot_config=None, roost=None, **kwargs) -> None   # line 570 — WARNS on duplicate
    def register_instance(self, name: str, instance: AbstractBot, *, tags: Optional[Iterable[str]] = None, priority: int = 0, replace: bool = False) -> None   # line 633 — WARNS on duplicate; TypeError if not AbstractBot
    def unregister(self, name: str) -> bool                            # line 671
    def _apply_prompt_config(bot: AbstractBot, prompt_config: PromptConfig) -> None   # line 841 (static)
    def load_agent_definitions(self, definitions_dir: Optional[Path] = None) -> int   # line 1003
    def load_agent_definition_file(self, yaml_file: Path) -> bool      # line 1025
    def register_remote(self, config: BotConfig) -> BotMetadata        # line 1522
    def get_bots_by_tag(self, tag: str) -> List[BotMetadata]           # line 1565

# packages/ai-parrot/src/parrot/skills/tenancy.py
RESERVED_TENANT_NAMES: frozenset[str] = frozenset({"skills","learned","tenants","prompts","queries","kb","documents","flows","routes","_drafts","_shared"})   # lines 23-37
TENANTS_DIRNAME: Final[str] = "tenants"                                # line 38
def validate_tenant_id(value: str) -> str                              # line 42 — rejects RESERVED_TENANT_NAMES (line 49)
def tenant_skills_dir(agent_root: Path, tenant: str) -> Path           # line 54
class SkillView:                                                       # line 164

# packages/ai-parrot/src/parrot/skills/parsers.py
def parse_skill_directory(skill_dir: Path) -> SkillDefinition          # line 151
def discover_skills_in_dir(directory: Path, logger: logging.Logger = _LOGGER, exclude_names: Iterable[str] = ()) -> List[SkillDefinition]   # line 181

# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin, EventEmitterMixin, ToolInterface, VectorInterface, ABC):   # line 216
    self.knowledge_bases: List[AbstractKnowledgeBase] = []             # line 583 (in __init__)
    def register_kb(self, kb: AbstractKnowledgeBase)                   # line 1189 — append + sort by priority desc
    async def configure_kb(self)                                       # line 1577
    self.kb_selector = KBSelector(llm_client=self._llm, min_confidence=0.6, kbs=self.knowledge_bases)   # line 1753
    async def _get_kb_context(self, query: str, k: int = 5) -> Tuple[List[Dict], Dict]   # line 3868
    async def _build_kb_context(self, question: str, user_id: Optional[str] = None, session_id: Optional[str] = None, ctx: Optional[RequestContext] = None) -> Tuple[str, Dict[str, Any]]   # line 3889; selector/activation block 3911-3950

# packages/ai-parrot/src/parrot/bots/stores/local.py
class LocalKBMixin:                                                    # line 13 — loads AGENTS_DIR/<agent_name>/kb/
    async def configure_local_kb(self) -> None                         # line 60

# packages/ai-parrot/src/parrot/memory/compaction/budget.py / tokens.py / models.py
MODEL_WINDOWS: Dict[str, int]                                          # budget.py:43
def resolve_window(model: Optional[str]) -> int                        # budget.py:61
def build_default_budget(model: Optional[str], *, max_turns: Optional[int] = None) -> ContextBudget   # budget.py:81
class ContextBudget: window, reserve_output, reserve_fixed, high_watermark, ...   # models.py:161
class TokenCounter(Protocol): def count(self, text: str) -> int        # tokens.py:30-35
def get_default_counter() -> TokenCounter                              # tokens.py:89

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py / models.py
class DecisionService:                                                 # service.py:96
    async def for_symbol(self, symbol: str, *, include_history: bool = False, limit: int = 10, budget_tokens: int = 3000) -> DecisionDossier   # line 193
    async def why(self, question: str, *, include_history: bool = False, limit: int = 10, budget_tokens: int = 3000) -> DecisionDossier   # line 276
    async def generate(self, target: str) -> GenerationResult          # line 389 — candidates origin="inferred"
    async def review(self, request: ReviewRequest) -> DecisionRecord   # line 473 — attributed, revision-checked
class DecisionRecord(_Strict): decision_id, revision, source_status: Literal["unknown","proposed","accepted","rejected","deprecated","superseded"], origin: Literal["documented","inferred"], review_status: Literal["unreviewed","accepted","rejected"], evidence, links, review_history, content_fingerprint   # models.py:172-194
class ReviewRequest(_Strict): expected_revision: int                   # models.py:299

# packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py
class LLMWikiToolkit(AbstractToolkit):                                 # line 48 — tools are wiki_<method>
    def __init__(self, pageindex_toolkit, graphindex_toolkit, okf_toolkit, config: WikiConfig, agent_id: str = "agent", store: Optional[BaseWikiStore] = None, confine_sources: bool = False, **kwargs)   # line 82
    def _store_for(self, wiki_name: str) -> BaseWikiStore              # line 215
    async def query(self, wiki_name: str, question: str, file_answer: bool = False, mode: str = "combined") -> dict[str, Any]   # line 373 — NO tag filter

# packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py / models.py
class BookstoreToolkit(AbstractToolkit): name = "bookstore"; tool_prefix = "bookstore"   # toolkit.py:29
    def __init__(self, bookstore: Bookstore, **kwargs)                 # line 40
    async def catalog_search(self, query: str, top_k: int = 8) -> list[dict[str, Any]]   # line 43
    async def search(self, query: str, book_ids: Optional[list[str]] = None, max_books: int = 3, expand_related: bool = False) -> dict[str, Any]   # line 195
class BookCard(BaseModel): book_id, topics: list[str], summary, toc_digest, scope: Literal["project","global"], source_path, source_sha256, card_origin, community_id   # models.py:152-180

# packages/ai-parrot/src/parrot/observability/context.py
current_agent_name, current_tenant: ContextVar[Optional[str]]          # lines 67-82
def agent_identity(name: Optional[str]) -> Iterator[None]              # line 86 (contextmanager)
current_run_id, current_seat: ContextVar[Optional[str]]                # lines 156-162
def usage_attribution(run_id: Optional[str], seat: Optional[str] = None) -> Iterator[None]   # line 162

# packages/ai-parrot/src/parrot/tools/spawn.py
class SpawnSubAgentTool(AbstractTool):                                 # line 88
    def __init__(self, bot_manager, owner_id: str, *, allowed_tools: Optional[List[str]] = None, name: str = "spawn_sub_agent", description=None, routing_meta=None)   # lines 122-131
    def _compute_effective_tools(self, requested: List[str]) -> List[str]   # line 164 — empty allowlist passes everything through

# packages/ai-parrot/src/parrot/models/basic.py
class ToolConfig(BaseModel)                                            # line 33
class ModelConfig(BaseModel)                                           # line 40
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ExpertRegistry.load` | `AgentRegistry.register_instance(name, instance, tags=…)` | method call | `registry/registry.py:633` |
| `ExpertRegistry.names` / visibility | `AgentRegistry.get_bots_by_tag("expert")` | method call | `registry/registry.py:1565` |
| `ExpertAgent` | `IdentityMixin.identity_dir`, `_configure_identity()` | class attr + awaited call | `bots/mixins/identity.py:60,130` |
| `parse_expert_bundle` | `load_identity(directory)` | function call | `bots/prompts/identity.py:51` |
| `ExpertView` | `SkillView` semantics (copied) | pattern | `skills/tenancy.py:164` |
| `tenancy.RESERVED_TENANT_NAMES` | `validate_tenant_id` | frozenset membership | `skills/tenancy.py:23,49` |
| `install_layers` | `PromptBuilder.add` / `remove` | method call | `bots/prompts/builder.py:200-240` |
| `knowledge_budget` | `resolve_window(model)` | function call | `memory/compaction/budget.py:61` |
| `KnowledgeResolver` | `get_default_counter().count(text)` | protocol call | `memory/compaction/tokens.py:89,35` |
| `ADRSource` | `DecisionService.why` / `for_symbol` | async call | `knowledge/wiki/decisions/service.py:276,193` |
| `ExpertKnowledgeToolkit.propose_adr` | `DecisionService.generate(target)` | async call | `service.py:389` |
| `WikiSource` / `knowledge_search` | `LLMWikiToolkit._store_for`, `.query(wiki_name, question)` | method calls | `parrot_tools/wiki/toolkit.py:215,373` |
| `BookstoreSource` / `knowledge_search` | `BookstoreToolkit.catalog_search`, `.search` | async calls | `knowledge/bookstore/toolkit.py:43,195` |
| `GraphIndexSource` | `RetrievalRequest`, `RetrievalBudget` | model construction | `knowledge/retrieval/__init__.py:18-66` |
| `LegacyKBSource` / `_build_kb_context` | `AbstractBot.knowledge_bases`, `_get_kb_context` | attribute + async call | `bots/abstract.py:583,3868,3889` |
| `activate_expert` | `agent_identity`, `usage_attribution` | context managers | `observability/context.py:86,162` |
| `model_config_for` | `ModelConfig(...)` | model construction | `models/basic.py:40` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.experts`~~ / ~~`parrot_tools.experts`~~ — no such packages today (created by M1–M10).
- ~~`spawn_agent`~~ / ~~`spawn_ephemeral`~~ as a tool name — the registered name is `spawn_sub_agent` (`tools/spawn.py:128`); the strings only appear in `memory/compaction/policies.py`.
- ~~`tools_deny`~~, ~~`denied_tools`~~, ~~`disallowed_tools`~~, ~~`tool_blocklist`~~, ~~`exclude_tools`~~ — no deny-list field exists anywhere in `parrot/`; gating is `allowed_tools` allowlists plus PBAC policies.
- ~~`PolicyRuleConfig.resource`~~ — no such field today (`parrot/auth/models.py:32-160`); M10 adds it. A rule declared via `BotConfig.policies` / `policy_rules` can only target `agent:<name>` until then.
- ~~`AgentRegistry.register_instance(..., policies=...)`~~ — `register_instance` has no policy parameter and registers no rules; use `register_db_bot_policies` (public) after it.
- ~~`AgentKind.EXPERT`~~ — not added (U3); `AgentKind` is `{LOCAL, A2A, SQUAWK}`.
- ~~`LayerPriority.RULES`~~, ~~`EXPERT_RULES_LAYER`~~, ~~`EXPERT_KNOWLEDGE_LAYER`~~ — do not exist yet (M6 adds them).
- ~~`DecisionRecord.tags`~~ — ADR records have no tags/components field; filter by `source_status`, `review_status`, `links`, `evidence`.
- ~~`LLMWikiToolkit.query(..., tags=...)`~~ — `query` takes `wiki_name, question, file_answer, mode` only.
- ~~`.parrot/experts/`~~, ~~`.parrot/knowledge/`~~, ~~`.parrot/memory/{org,team,project}.md`~~ — no such conventions; `.parrot/` is only used for `crew_wiki`.
- ~~`AbstractClient.reasoning_effort`~~ / ~~`model_tier`~~ — only `_lightweight_model` (`clients/base.py:309`) exists, and the file is off-limits.
- ~~`SpawnSubAgentTool` nesting-depth guard~~ — none exists; exclusion is the only control (see §8 Q3).
- ~~`AgentRegistry.register_expert`~~ — not a method; use `register_instance`.
- ~~`knowledge_resolver` attribute on `AbstractBot`~~ — does not exist today; M7 reads it with `getattr(self, "knowledge_resolver", None)`, set only on `ExpertAgent`.
- ~~`persona.md` parser~~ in `parrot.bots.prompts.identity` — `load_identity` reads only `IDENTITY_FILES`.

### Edit Sites (Blueprint Anchors)

Verified against: `b9502bfe3`

- `packages/ai-parrot/src/parrot/auth/models.py:153` — anchor `"resources": [f"agent:{agent_name}"],` → M10 replaces with the `self.resource` fallback; field block ends before `def to_resource_policy` (`:108`).

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/experts/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/experts/models.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/experts/loader.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/experts/view.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/experts/registry.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/experts/agent.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/experts/activation.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/experts/policy.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/experts/rules.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/experts/knowledge/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/experts/knowledge/resolver.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/experts/knowledge/budget.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/experts/knowledge/render.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/experts/knowledge/sources/{__init__,base,bundled,workspace,adr,wiki,bookstore,graphindex,kb}.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/experts/{__init__,toolkit}.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/skills/tenancy.py` | MODIFY | `RESERVED_TENANT_NAMES: frozenset[str] = frozenset(` | `tenancy.py:23` | 1 |
| `packages/ai-parrot/src/parrot/bots/prompts/layers.py` | MODIFY | `    KNOWLEDGE = 30` | `layers.py:27` | 1 |
| `packages/ai-parrot/src/parrot/bots/prompts/layers.py` | MODIFY (append after the constant block) | `KNOWLEDGE_LAYER = PromptLayer(` | `layers.py:191` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `    async def _build_kb_context(` | `abstract.py:3889` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `    def register_kb(self, kb: AbstractKnowledgeBase):` | `abstract.py:1189` | 1 |
| `docs/experts/domain-experts.md` | CREATE | — | — | — |
| `packages/ai-parrot/tests/experts/**` , `packages/ai-parrot-tools/tests/experts/**` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Discovery** copies `discover_skills_in_dir` (sorted entries, non-recursive, warn-and-skip) — do not subclass the skills loader; experts are not skills.
- **Shadowing** copies `SkillView` (tenant first, unshadowed globals, `global_only` locks); tenant ids go through `validate_tenant_id` and `secure_path`.
- **Identity** reuses FEAT-321 end to end: `enable_identity=True`, explicit `identity_dir`, `_configure_identity()` after `super().configure()` (the `SkillRegistryMixin` / `EpisodicMemoryMixin` wiring pattern), pristine-clone hot reload untouched.
- **Authored text is literal**: every rules/knowledge layer is `PromptLayer(literal=True)` (FEAT-707), never `$`-substituted.
- **Budget** derives from `resolve_window(model)`; token counts come from `get_default_counter()` so experts and compaction agree on the tokenizer.
- **ADR reads are LLM-free** (`DecisionService.why/for_symbol`); only `generate()` may call a model, and only behind the `write` capability.
- **Toolkits ship from `parrot_tools`** (`parrot_tools.experts`); core gets no agent-facing tool code.
- **Pydantic v2 everywhere**, `extra="forbid"` on manifests, Google docstrings, `self.logger`, async I/O, no `print`.
- **No modification** of `clients/base.py`; `tier` → `ModelConfig` lives in `experts/policy.py`.

### Known Risks / Gotchas
- **`SPAWN_DENY_PRIORITY = 100` breaks the stated convention** that code rules (`priority=10`) sit below operator YAML (`>= 20`, `models.py:38-39`). Deliberate: the non-delegation invariant must survive an operator `tool:*` allow. Document it in M11 and in the `PolicyRuleConfig` docstring; never lower it.
- **`register_instance` does not register policies**; the deny rule only reaches the evaluator through `register_db_bot_policies`, which returns `0` when the registry has no PDP (`_evaluator is None`, `registry.py:417`). The allowlist exclusion (AC10) is the layer that still holds in that case — tests must cover both.
- **Fail-at-load wiki probe needs a reachable store**: `ExpertRegistry.load()` now performs a store call per bundle (`WikiSource.probe()`); an unreachable wiki backend rejects every expert. Surface the count in `report()["skipped"]` and log once per load, not per bundle.
- **`registry.py` is a collision hotspot** (FEAT-746/747 review fixes landed 2026-10-30). This spec touches it only through `register_instance()` calls, never edits it; if a conflict appears anyway, rebase, do not resolve by hand.
- **Duplicate semantics differ**: `AgentRegistry.register_instance` *warns* on a duplicate; `ExpertRegistry.load` must *fail* before calling it (AC1) — check `name in agent_registry._registered_agents` is private; use `get_metadata(name)`/`names()` from the public surface instead (verify in `/sdd-task`).
- **`_build_kb_context` has no recent tests** (file dormant 180 days). M7 lands behind a pinned fixture test of the legacy output (AC11) **before** the delegation branch is added; the legacy branch stays byte-for-byte.
- **Identity directory resolution**: `IdentityMixin._resolve_identity_dir()` (identity.py:119) falls back to the class module directory — `ExpertAgent` must set `identity_dir` *before* `IdentityMixin.__init__` runs (it is read in `__init__`, identity.py:65-70); confirm the attribute is honoured first in that method during `/sdd-task`.
- **Never mutate a shared builder** (S2): `install_layers` clones; `ExpertAgent` owns its builder. Inline projection into a conductor is phase 4.
- **Single identity slot**: an expert's identity *replaces* the conductor's; stacking two experts inline is a phase-4 concern. `expert_rules`/`expert_knowledge` are separate layer names so they can coexist with any identity.
- **Wiki scoping** is by namespace only; the manifest's `scope.topics` is honoured by the bookstore adapter and recorded (not enforced) by the wiki adapter until a tag filter exists (§8 Q2).
- **Reserved names**: adding `experts`, `knowledge`, `governance` to `RESERVED_TENANT_NAMES` rejects tenants with those ids — check existing tenant trees before merge (`grep -r tenants/ AGENTS_DIR`).
- **Vocabulary collisions**: `tier` is also the HITL escalation vocabulary and `domain` names the ontology defaults — keep `ExpertTier` qualified and avoid `domain` in module names.
- **`spawn_sub_agent` exclusion is allowlist-based**; `SpawnSubAgentTool._compute_effective_tools` passes everything through when its allowlist is empty, so `effective_allowlist()` must never be empty when the tool is discoverable (AC10).
- **Contracts/legal migrations** need code hooks (`ContractsAnswerService` gate) — the bundle format must not forbid an `agent_class` override later; keep `ExpertAgent` subclassable (no `final`).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2` (already a dependency) | manifest and context models |
| `pyyaml` | already a dependency (registry YAML definitions) | `expert.yaml` |
| `python-frontmatter` | already a dependency (skills parsers) | optional frontmatter on `knowledge/*.md` |
| `tiktoken` | already a dependency (compaction tokens / skills parsers) | token counts via `get_default_counter()` |

---

## 8. Open Questions

> Resolved items are carried from the proposal's Phase-5 Q&A (2026-10-30); unresolved items are spec-level with the default this spec adopts unless overridden before `/sdd-task`.

- [x] U1 — Persona contract — *Resolved in proposal*: Both — identity/ five files feed the prompt layer; `persona.md` is kept as human-readable documentation only. → §2 Overview, §3 M2/M3, AC3.
- [x] U2 — Bundle location — *Resolved in proposal*: `AGENTS_DIR/experts/<slug>` — workspace bundles beside agents; Tier 2 via `tenants/<t>/experts` shadowing, same rules as skills (`global_only` locks). → §3 M2, AC7, AC13.
- [x] U3 — Registry integration — *Resolved in proposal*: Sibling `ExpertManifest` + `ExpertRegistry` — own Pydantic manifest and loader that registers a configured agent into `AgentRegistry`; decoupled from the FEAT-746/747 churn; strict duplicate rule stays local. → §3 M2, AC1, §6 Does-NOT-Exist (`AgentKind.EXPERT`).
- [x] U4 — Stage gates — *Resolved in proposal*: Lift `ApprovalGate` into `flows/core` — generic gate host with open `GateKind`; dev_loop becomes a consumer. → Non-Goals (phase 4; direction recorded, not implemented here).
- [x] U5 — Phase-1 blast radius — *Resolved in proposal*: Replace in phase 1 — the KB path becomes a `mode: retrieval` source of the resolver now (higher blast radius in `abstract.py` accepted). → §3 M5 `LegacyKBSource`, M7, AC11.
- [x] Q1 — Per-layer budget policy — *Resolved 2026-10-30*: keep the single pool, `KNOWLEDGE_FRACTION = 0.15` of `resolve_window(model)`, trimmed by `TRIM_ORDER`; no per-layer quotas and no tier scaling. → §3 M4, AC5.
- [x] Q2 — Wiki minimum scope — *Resolved 2026-10-30*: **fail at load**. `ExpertRegistry.load()` probes the `expert-<slug>` namespace store per bundle; an unresolvable **or empty** store rejects the bundle (not registered, logged at ERROR, listed in `report()["skipped"]` with reason `empty-wiki-namespace`); the other bundles still load. Onboarding documents to the wiki is therefore a precondition for an expert to exist. Tag/topics filtering inside `LLMWikiToolkit.query` stays deferred. → §3 M2, M5, AC19.
- [x] Q3 — Non-delegation defense in depth (codex S7) — *Resolved 2026-10-30*: **allowlist + PBAC deny**, no nesting guard. Verified before deciding: `PolicyRuleConfig.to_resource_policy()` always emits `resources=["agent:<name>"]` (`parrot/auth/models.py:153`), so a per-tool deny is not expressible today, and `AgentRegistry.register_instance()` never registers policy rules (only `register()` does, `registry.py:631`). M10 therefore (a) adds an optional `resource` field to `PolicyRuleConfig` and (b) emits `{action: "tool:execute", effect: "deny", resource: "tool:spawn_sub_agent"}` per expert, which `ExpertRegistry.load()` pushes through the public `AgentRegistry.register_db_bot_policies()` (`registry.py:507`). The `SpawnSubAgentTool` owner/nesting guard is **rejected** for this feature (phase-4 brainstorm). → §3 M2, M10, AC20–AC21.
- [x] Q4 — Governance file location — *Resolved 2026-10-30*: `AGENTS_DIR/governance/{org,team,project}.md`; `.parrot/memory/*.md` is not read. → §3 M8, AC8, AC13.
- [x] Q5 — ADR inline cap — *Adopted by spec, confirmed 2026-10-30*: `DecisionService.why(budget_tokens=3000, limit=10)` per source call; filtering by `source_status`/`review_status` plus the optional `filter.links` match (S6); no tags exist. → §3 M5, AC9.
- [ ] Q6 — Promoted rules persistence/audit, contributions storage, scope grid, `tier` → seat/OTEL attribute, expert memory and migration order — deferred to the phases 3–5 brainstorm (not blocking this spec). Design constraint carried from codex S9 for the U4 gate lift: extract a gate *protocol* with string identifiers plus a compatibility adapter for persisted `ApprovalGate` envelopes; never import dev-loop Literals into the expert runtime, never duplicate `parrot/human`. — *Owner: follow-up brainstorm*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration doc** (never over this spec).
> Model: `gpt-5.6-luna` (codex-cli 0.166.0, reasoning high, 117 s) · Status: completed
> · Transcript: `sdd/state/FEAT-778/design_research/` (brief, suggestions.json, triage.md, run.json)
> All 38 `affected_paths` passed containment and existence checks.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Sibling `ExpertDirectoryLoader` + `ExpertRegistry`, strict manifest, explicit duplicate/shadowing report (architecture) | CONFIRM | Matches U3; `ExpertView.shadowing` and `ExpertRegistry.report()` make the duplicate/shadow outcome inspectable | §3 M2 |
| S2 | Activation must clone a pristine builder and never mutate a shared bot; do not claim multi-expert inline composition in phase 1 (api) | CONFIRM | Here an expert is its own `ExpertAgent`; `install_layers` works on `builder.clone()`; inline-into-conductor and multi-expert stacking are explicitly phase 4 | §2 Overview, §3 M6, §7 |
| S3 | Force all bundle-authored text through `literal=True`; `load_identity()` returns unescaped `$` content that `IDENTITY_LAYER` substitutes (risk) | CONFIRM | Rules/knowledge layers are literal; identity files containing `$` placeholders are rejected at bundle load and a regression test pins it | §3 M2, §4, AC17 |
| S4 | Add the resolver *beside* the KB path; keep `register_kb`/`KBSelector` until parity is proven (alternative) | REJECT | Contradicts the proposal's U5 answer ("replace in phase 1"); the spec already keeps the legacy branch byte-for-byte for bots without a resolver and pins it (AC11) — the reviewer's mitigation without reversing the user's decision | — |
| S5 | `KnowledgeContext` must be structured, attributable and budget-aware (api) | CONFIRM | Already the `KnowledgeLayer`/`KnowledgeContext` contract; `revision` mandatory on every layer, `trimmed[]` serialized | §2 Data Models, AC5, AC6 |
| S6 | v1 scope = exact wiki namespace + accepted-ADR filtering by `links` + bookstore `topics`; keep write/review out of the resolver (api) | CONFIRM | `ADRSource` gains `filter.links`; wiki namespace-only; bookstore `topics`; `propose_adr` lives in the toolkit | §3 M5, M9; §8 Q2, Q5 |
| S7 | Enforce non-delegation in tool authorization (allowlist + PBAC denial) and a nesting/owner guard (risk) | CONFIRM (partial) | Escalated to the user on 2026-10-30, who adopted allowlist + PBAC deny (`PolicyRuleConfig.resource` extension, per-expert `tool:execute` deny) and rejected the `SpawnSubAgentTool` nesting guard for this feature (phase-4 brainstorm) | §3 M2, M10; AC20–AC21; §8 Q3 |
| S8 | Defer stage binding; do not extend `AgentDefinition`/`CrewDefinition`; specify an `ExpertStageNode` compiler later (architecture) | CONFIRM | Identical to Non-Goals | §1 Non-Goals |
| S9 | Future generic gate = protocol with string ids + compatibility adapter for persisted `ApprovalGate` envelopes; never import dev-loop Literals (architecture) | CONFIRM (phase-4 guidance) | Consistent with U4; recorded for the follow-up brainstorm | §8 Q6 |
| S10 | Negative isolation and concurrency tests as release gates (testing) | CONFIRM | Added concurrency, missing-scope-vs-empty and `$`-literal tests; the rest already existed | §4, AC17–AC18 |

Summary: **9** confirmed (S7 partial) · **1** rejected · **0** escalated (S7 resolved by the user on 2026-10-30).

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for FEAT-778 (`.claude/worktrees/feat-FEAT-778-domain-experts`); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (edges = imports):
  - M2 → M1 (`ExpertManifest`, `ExpertBundle`), M2 → M3 (builds `ExpertAgent`), M2 → M10 (`effective_toolkits`, `model_config_for`, `expert_policy_rules`), M2 → M5 (`WikiSource.probe`)
  - M3 → M1, M4 (`KnowledgeResolver` attribute), M6 (`install_layers` in `configure`)
  - M4 → M1, M5 (`KnowledgeSource` protocol), M8 (`rules_to_layer`)
  - M5 → M1, M4 (`KnowledgeLayer`); `sources/kb.py` ↔ M7 (M7 calls `resolver.search_kb`, M5 reads `bot.knowledge_bases`)
  - M6 → M1 (`KnowledgeContext`); M6 modifies `layers.py` (no other module touches it)
  - M7 → M4, M5
  - M8 → M1
  - M9 → M1, M4, M5 (`LLMWikiToolkit`, `BookstoreToolkit`, `DecisionService` are existing)
  - M10 → M1
  - M11 → all
  - Modules without an edge (M1 ∥ nothing; M6 ∥ M8 ∥ M10 once M1 exists; M5 ∥ M8; M9 ∥ M7) are expected to run concurrently.
- **Shared files**: none across modules — `skills/tenancy.py` (M2 only), `bots/prompts/layers.py` (M6 only), `bots/abstract.py` (M7 only), `auth/models.py` (M10 only), `parrot/experts/__init__.py` (exports added by M1, M2, M3, M4 — serialize those four tasks' edits to it or let M1 pre-declare the export list).
- **Exclusive resources**: none (no extension rebuild, no lockfile change, no migration).
- **Cross-feature dependencies**: none to merge first. **Risk**: FEAT-746/747 follow-ups on `registry.py` — this feature does not edit that file.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-30 | Jesus Lara (with Claude Fable 5.1) | Initial draft from FEAT-778 proposal (phases 1–2); codex design research folded (8 confirm / 1 reject / 1 escalate) |
| 0.2 | 2026-10-30 | Jesus Lara (with Claude Fable 5.1) | §8 Q1–Q5 resolved: Q2 wiki fail-at-load (M2/M5 probe, AC19); Q3 allowlist + PBAC deny (`PolicyRuleConfig.resource`, `expert_policy_rules`, `register_db_bot_policies`, AC20–AC21; S7 → confirm partial); Q1/Q4/Q5 defaults confirmed |
