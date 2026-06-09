---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: Workday Knowledge Agent (3-edge program, routed)

**Date**: 2026-06-08
**Author**: Juan (from Jesus Lara's vision)
**Status**: exploration
**Recommended Option**: B (apply the approved FEAT-071 multi-mixin pattern to the Workday domain, staged)

> **Umbrella / program brainstorm.** This frames the whole vision; it does NOT
> replace [`workday-conversational-agent-telegram.brainstorm.md`](workday-conversational-agent-telegram.brainstorm.md),
> which stands as **Stage 1** of this program. This doc adds the program map and
> Stages 2–3, and records the decisions taken with Jesus on 2026-06-08.
>
> **Reference vision** (Jesus): a "3-edge" Workday agent that combines
> (1) a **graph/wiki knowledge base** of employee/HR knowledge,
> (2) a **Workday operations toolkit** that *knows who you are* (like `JiraToolkit`),
> (3) a **structured org ontology** (hierarchy, divisions, employment areas,
> managers, subordinates) — unified by an **IntentRouter** that discerns whether a
> question belongs to the KB, document RAG, the graph, or the ontology. It is a
> **parrot Agent that self-manages its own knowledge wiki** (replicating Karpathy's
> "LLM-Wiki" — see PR #931 — NOT a Claude-Code skills folder).

---

## Problem Statement

FEAT-230 (merged) gave us a homologated `WorkdayToolkit`. Stage 1 (the Telegram
brainstorm) adds session identity + a working "ask my PTO" agent. But Jesus's
actual target is bigger: a **knowledge-rich Workday agent** with three retrieval
"edges" plus intent routing, that doesn't just call Workday APIs but *understands
the organization* and *curates its own knowledge*.

**The key finding from investigation: every piece already exists in parrot, and
the exact composition is already specified and approved as FEAT-071** (the Gorilla
Sheds "advisor-ontologic-rag-agent"), which wires `IntentRouterMixin +
OntologyRAGMixin + EpisodicMemoryMixin + PageIndexRetriever + <domain toolkit> +
BaseBot`. PR #931's `WikiAgent` (`OntologyRAGMixin + BasicAgent` + PageIndex +
GraphIndex toolkits) is the same composition for a self-managing wiki. **So this
program is not net-new architecture — it is applying a proven, approved pattern to
the Workday domain**, with the org graph/ontology *seeded from Workday itself*.

**Affected users**: employees/managers (HR self-service that understands org
structure); the agents team (a reusable knowledge-agent composition).

**Why now**: the toolkit (FEAT-230) and all four knowledge subsystems (PageIndex,
GraphIndex, Ontology, IntentRouter) are built; what's missing is the domain wiring
+ the Workday→graph seeding + identity (Stage 1).

---

## Constraints & Requirements

- **C1 — Staged, not big-bang.** The IntentRouter only earns its place with ≥2
  retrieval sources to discriminate; the three edges have very different maturity.
  Deliver in stages, each on a proven foundation.
- **C2 — Two graph seed sources, both verified pipelines** (confirmed with Jesus):
  - **Org structure** ← **Workday** (Edge 3). Entities + edges (all fields verified
    present in the FEAT-230 composable models/operations):
    - **Worker** (`worker.py`) — `manager_id`/`direct_manager_id`,
      `supervisory_organization_id`, `cost_center_id`/`cost_center_name`/
      `cost_center_hierarchy_name`, `business_site_location_id`.
    - **Division / Supervisory Org** ← `get_organizations` (`Organization`).
    - **Department = Workday Cost Center** ← `get_cost_centers` (`CostCenter`).
    - **Location** ← `get_locations` (`Location`; has its own hierarchy via
      `superior_location_id` + `location_hierarchy`).
    - **Edges**: `reports_to` (manager_id), `member_of_division`
      (supervisory_organization_id), `belongs_to_department` (cost_center_id),
      `located_at` (business_site_location_id), plus `cost_center` and `location`
      hierarchies and `get_location_hierarchy_assignments` (org↔location links).
    Workday is both *query surface* and *graph data source* — no new source of truth.
  - **HR policies** ← **PDF → PageIndex → graph** (Edge 1): policies are delivered
    as **PDF**; ingest with `PageIndexToolkit.import_pdf` (TOC detection + per-node
    summaries), then **bridge the PageIndex tree into the graph** with the example's
    `graph_seed_from_tree` (DOCUMENT/SECTION nodes + CONTAINS edges). The LLM then
    enriches it with CONCEPT nodes/cross-links via GraphIndex write tools.
  Both sources land in the **same** GraphIndex/ArangoDB graph.
- **C3 — ArangoDB is available** (confirmed): GraphIndex/Ontology persistence
  (ArangoDB + pgvector) can be turned on; the ontology degrades gracefully when off.
- **C4 — The agent lives OUTSIDE the public ai-parrot repo** (carries forward C8
  from Stage 1): ai-parrot ships only generic framework pieces (toolkits, mixins,
  a Workday→graph seeder, the identity mechanism). The agent definition, prompts,
  ontology YAML, tenant config and `telegram_bots.yaml` are sensitive/company-
  specific → private repo (likely `navigator-plugins`, location TBD).
- **C5 — Identity & authorization reuse Stage 1's carril.** "Knows who you are" =
  `OntologyRAGMixin._get_permission_context()` → `_permission_context` →
  `toolkit._pre_execute` (the `JiraToolkit` precedent). The ontology's authorization
  layer and the toolkit's `_pre_execute` share this; "self + direct reports",
  fail-closed, applies to BOTH graph traversal and tool calls.
- **C6 — No core parrot modifications for the agent itself.** Like FEAT-071 and
  PR #931, the agent is composition over existing mixins/toolkits. The ONLY net-new
  framework code is a **Workday→graph seeder** (a `GraphIndexBuilder` extractor or
  equivalent) and possibly promoting the example's `build_graphindex_toolkit` glue.

---

## Options Explored

### Option A: Bespoke inline composition (clone the LLM-Wiki example for Workday)

Copy the `examples/knowledge_wiki` approach: wire PageIndex + GraphIndex (+ Ontology)
inline into a one-off Workday agent, seeding the graph by hand from Workday calls.

✅ **Pros:**
- Fastest to a demo; the example already shows the exact glue (`build_wiki_agent`).
- Zero framework change.

❌ **Cons:**
- One-off/inline glue (the example itself flags `build_graphindex_toolkit` as
  "glue the framework does not yet ship") → not reusable, drifts from FEAT-071.
- No IntentRouter (the example omits it); we'd re-invent routing ad hoc.
- Hand-seeding the org graph from Workday doesn't scale or refresh.

📊 **Effort:** Medium (deceptively — the demo is easy, production hardening isn't)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `ai-parrot[graphindex]`, `bm25s` | GraphIndex + BM25 | per the example's deps |

🔗 **Existing Code to Reuse:**
- `examples/knowledge_wiki/wiki.py` — `build_wiki_agent`, `build_graphindex_toolkit`, `graph_seed_from_tree`.

---

### Option B: Apply the approved FEAT-071 multi-mixin pattern to Workday, staged  ⭐

Build a `WorkdayAgent` by **the same composition FEAT-071 already approved** —
`IntentRouterMixin + OntologyRAGMixin + (EpisodicMemoryMixin) + PageIndexRetriever +
BaseBot` with the `WorkdayToolkit` attached — but **stage the edges**:

- **Stage 1** (= the Telegram brainstorm): Workday ops + session identity. Verify
  live (PTO), deliver over Telegram. *Edge 2.*
- **Stage 2**: seed a GraphIndex + Ontology of the org **from Workday** (workers,
  `manager_id`→`reports_to`, organizations→divisions), persisted to ArangoDB. The
  agent now answers structural questions ("who's my manager / in my division")
  with the **same identity/authorization carril**. *Edge 3 + base of Edge 1.*
- **Stage 3**: ingest the **HR policy PDF** via `PageIndexToolkit.import_pdf`,
  **bridge it into the graph** (`graph_seed_from_tree` → DOCUMENT/SECTION nodes,
  then LLM-curated CONCEPT cross-links), and **wire the IntentRouter** to route
  across ops / org-graph / policy-wiki. Router now has ≥3 sources to discriminate.
  *Edge 1 complete (PDF→PageIndex→graph) + routing.*

✅ **Pros:**
- Reuses an **approved, specified** composition (FEAT-071) — lowest architectural risk.
- Each stage ships user value and builds on a verified foundation; IntentRouter
  arrives only when it has something to route.
- The Workday→graph **seeder** becomes a reusable framework piece (an extractor),
  not throwaway glue.
- Identity/authorization is one mechanism across tools AND graph (C5).

❌ **Cons:**
- More upfront framing than a one-off demo; spans multiple specs/stages.
- Requires authoring an org **ontology** (entities/relationships) and a Workday
  **seeder** — real, non-trivial work in Stage 2.

📊 **Effort:** High (program), but Low–Medium per stage.

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `ai-parrot[graphindex]` | in-memory graph + FAISS | Stage 2/3 |
| ArangoDB (+ pgvector) | graph/ontology persistence | available (C3) |
| `bm25s` | PageIndex lexical search | Stage 3 |

🔗 **Existing Code to Reuse:**
- `sdd/specs/advisor-ontologic-rag-agent.spec.md` (FEAT-071) — **the canonical composition** to mirror.
- `parrot/bots/mixins/intent_router.py` — `IntentRouterMixin` + `configure_router`.
- `parrot/knowledge/ontology/mixin.py` — `OntologyRAGMixin.ontology_process` + `_get_permission_context`.
- `parrot/knowledge/graphindex/builder.py` — `GraphIndexBuilder.build(sources, ctx)` + pluggable extractors.
- `parrot_tools/.../workday/tool.py` — `WorkdayToolkit` (FEAT-230) as the domain toolkit + data source.

---

### Option C: "Lite" — ops + identity + PageIndex docs only; defer graph/ontology

Ship Stage 1 + a PageIndex HR-docs RAG, skip the GraphIndex/Ontology org model and
the IntentRouter (or use a trivial 2-way route). Add the graph/ontology later only
if structural questions prove valuable.

✅ **Pros:**
- Smallest scope; quickest to a useful "PTO + policy Q&A" assistant.
- No ArangoDB/ontology authoring needed initially.

❌ **Cons:**
- Drops exactly the differentiator Jesus emphasized (the org **ontology** —
  hierarchy/divisions/managers/subordinates).
- "Who's my manager / who reports to me" can't be answered structurally.
- Likely re-work later to retrofit the graph/ontology that Option B stages cleanly.

📊 **Effort:** Low–Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `bm25s` | PageIndex search | — |

🔗 **Existing Code to Reuse:**
- `parrot/knowledge/pageindex/` — `PageIndexToolkit` / `PageIndexRetriever`.

---

## Recommendation

**Option B.** Investigation showed the composition Jesus wants is **already
approved and specified (FEAT-071)** and **already demonstrated (PR #931)** — the
work is *applying* it to Workday, not designing it. Staging it (Edge 2 → Edge 3 +
graph → Edge 1 + router) retires risk in dependency order: you can't seed a
trustworthy org graph from a toolkit you haven't verified live (Stage 1's Phase 3),
and the router has nothing to route until ≥2 edges exist.

We accept that Option B is more framing than Option A's quick demo, and that Stage 2
requires authoring an org ontology + a Workday seeder. We reject A (throwaway glue,
no router, hand-seeding) and C (drops the org ontology, the thing Jesus most wants).

The single net-new *framework* piece worth promoting out of the example is a
**Workday→graph seeder** — modeled as a `GraphIndexBuilder` extractor
(`WorkdayExtractor`, alongside the existing code/loader/skill extractors) or, to
start, the direct-assembler path the wiki example uses fed from `WorkdayToolkit`
results. Everything else is composition.

---

## Feature Description

### User-Facing Behavior
An authenticated employee chats with one Workday agent that fluidly handles:
- **Operations** — "what's my PTO balance?", "request 2 days off" (Edge 2, Stage 1).
- **Org structure** — "who's my manager?", "who reports to me?", "who's in the
  Finance division?", "what department (cost center) am I in?", "who's at the
  Austin location?" — answered from the org graph/ontology (Edge 3, Stage 2:
  workers, divisions, **departments/cost-centers**, **locations**), scoped by
  identity (you only see self + your reports).
- **Policy/knowledge** — "how does carryover work for PTO?" — answered from the
  curated HR wiki with citations (Edge 1, Stage 3).
The IntentRouter decides which edge each question hits; the user never picks.

### Internal Behavior (high level)
- **Composition**: `WorkdayAgent(IntentRouterMixin, OntologyRAGMixin, BasicAgent)`
  with `WorkdayToolkit` (and later PageIndex/GraphIndex toolkits) attached — the
  FEAT-071 shape.
- **Seeding (two pipelines)**: (a) *Org* — a Workday→graph step extracts
  workers/orgs into `UniversalNode`/`UniversalEdge` (`reports_to`,
  `member_of_division`), embeds, persists to ArangoDB; the Ontology consumes it for
  entity-driven RAG (Stage 2). (b) *Policies* — the HR **PDF** is ingested by
  `PageIndexToolkit.import_pdf` into a tree, then bridged to the same graph via
  `graph_seed_from_tree` and enriched by the LLM (Stage 3).
- **Identity/authz (all stages)**: `_get_permission_context()` carries the SSO
  session's worker identity; the ontology authorization layer and the toolkit
  `_pre_execute` both enforce self + first-level direct reports, fail-closed.
- **Routing (Stage 3)**: `configure_router(...)` registers each edge as a
  `CapabilityEntry`; the router classifies (keyword fast-path → LLM) and dispatches.

### Edge Cases & Error Handling
- **Ontology off / ArangoDB unreachable** → `OntologyRAGMixin` degrades to
  `vector_only` / `not_configured`, never raises (verified behavior).
- **Stale org graph** → seeding is re-runnable (full rebuild or incremental
  `ingest_document`); define a refresh cadence in Stage 2.
- **No authenticated session** → no Workday/graph access (Stage 1 C4 carries over).
- **Router low confidence** → cascade to next strategy / HITL (router default).
- Identity/authorization denials are logged and never leak other workers' data.

---

## Capabilities

### New Capabilities
- `workday-org-graph-seeding`: a Workday→GraphIndex/Ontology seeder (extractor) that
  builds the employee org graph (hierarchy/divisions/managers/reports) in ArangoDB. *(Stage 2 spec)*
- `workday-knowledge-agent`: the composed `WorkdayAgent` (FEAT-071 pattern) wiring
  ops + org-graph/ontology + HR-wiki + IntentRouter — **defined in a private repo (C4)**;
  parrot side is the reusable framework enablement. *(Stage 3 spec; agent itself out of parrot)*

### Modified / Reused Capabilities
- `workday-conversational-agent-telegram` (Stage 1) — unchanged; this program's first stage.
- `advisor-ontologic-rag-agent` (FEAT-071) — reused as the composition template.
- `workday-tooling-composable-interface` (FEAT-230) — reused as domain toolkit + data source.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `WorkdayToolkit` (FEAT-230) | reuses / data-source | query surface AND graph seed source; identity via `_pre_execute` |
| `parrot/knowledge/graphindex/` | extends | new `WorkdayExtractor` (or direct-assembler seeder) for org data |
| `parrot/knowledge/ontology/` | depends on / extends | org ontology (YAML) authored; `OntologyRAGMixin` composed into the agent |
| `parrot/knowledge/pageindex/` | depends on | HR-docs wiki (Stage 3) |
| `parrot/bots/mixins/intent_router.py` | depends on | route ops / org-graph / wiki (Stage 3) |
| ArangoDB (+ pgvector) | depends on | graph/ontology persistence (available) |
| The agent definition + prompts + ontology YAML + `telegram_bots.yaml` | creates — **private repo, NOT parrot (C4)** | location TBD |

---

## Code Context

### Verified Codebase References

#### The canonical composition (template to mirror)
```python
# sdd/specs/advisor-ontologic-rag-agent.spec.md  (FEAT-071, status: approved)
# GorillaAdvisorBot composes (spec §2 component diagram, lines ~84-90):
#   ProductAdvisorMixin + OntologyRAGMixin + EpisodicMemoryMixin
#   + IntentRouterMixin + BaseBot, with PageIndexRetriever + WorkingMemoryToolkit
# => The Workday agent is this SAME shape with WorkdayToolkit as the domain tool.

# examples/knowledge_wiki/wiki.py  (PR #931 — self-managing wiki, no framework changes)
class WikiAgent(OntologyRAGMixin, BasicAgent): ...            # wiki.py:332 (make_wiki_agent_class)
def build_wiki_agent(*, name, llm, system_prompt, pi_toolkit, gi_toolkit,
                     tenant_manager=None, graph_store=None, vector_store=None,
                     cache=None, temperature=0.1, **kwargs): ...   # wiki.py:338
    tools = list(pi_toolkit.get_tools()) + list(gi_toolkit.get_tools())  # wiki.py:359
```

#### The four knowledge subsystems (all exist)
```python
# 1) PageIndex — parrot/knowledge/pageindex/
class PageIndexRetriever:  # retriever.py:11  (LLM tree-walk; from_json @156)
class PageIndexToolkit:    # toolkit.py  (create_tree/add_node/search; writable)
    async def import_file(self, ...)   # toolkit.py:538  (md/txt)
    async def import_pdf(self, pdf_path: str, ...)   # toolkit.py:557  <-- HR policy PDF ingest (TOC + summaries)
# Bridge tree -> graph (PR #931 example): graph_seed_from_tree(pi_toolkit, tree_name)
#   -> DOCUMENT/SECTION UniversalNodes + CONTAINS edges  (examples/knowledge_wiki/wiki.py:217)

# 2) GraphIndex — parrot/knowledge/graphindex/
class GraphIndexBuilder:                                       # builder.py:54
    async def build(self, sources: SourceConfig, ctx: TenantContext) -> BuildResult  # builder.py:122
    # pluggable extractors: CodeExtractor/LoaderExtractor/SkillExtractor (builder.py:30-32)
    async def ingest_document(self, uri: str, ctx: TenantContext) -> IngestResult     # incremental
# GraphIndexToolkit (parrot_tools) — 19 tools, 7 WRITE (create_concept/link_nodes/attach_summary/merge_nodes)
# UniversalNode(kind=DOCUMENT|SECTION|CONCEPT|SYMBOL) / UniversalEdge(kind=CONTAINS|REFERENCES|...)  (schema.py)

# 3) Ontology — parrot/knowledge/ontology/
class OntologyRAGMixin:                                        # mixin.py:79
    async def ontology_process(self, query, user_context, tenant_id, domain=None) -> ContextEnvelope  # mixin.py:164
    def _get_permission_context(self) -> dict[str, Any]        # mixin.py:140  <-- identity hook
class OntologyGraphStore:  # graph_store.py:33  (ArangoDB: initialize_tenant/traverse_aql/upsert_nodes)
class TenantOntologyManager:  # tenant.py  (get_merged_ontology)
# degrades: no tenant_manager -> "not_configured"; ArangoDB down -> "vector_only" (never raises)

# 4) IntentRouter — parrot/bots/mixins/intent_router.py
class IntentRouterMixin:                                       # intent_router.py:123
    def configure_router(self, config: IntentRouterConfig, registry: CapabilityRegistry) -> None  # :156
    async def conversation(self, question, ...) -> AIMessage   # intercepts to route first
# strategies: DATASET / VECTOR_SEARCH / TOOL_CALL / GRAPH_PAGEINDEX / FREE_LLM / MULTI_HOP
# CapabilityRegistry.register / build_index / retrieve  (registry.py)
```

#### Workday org-graph seed data (verified in the FEAT-230 composable)
```python
# Operations + models (parrot_tools/interfaces/workday/service.py _OPERATION_MODEL_MAP):
#   "get_organizations" -> Organization   (division / supervisory org)   service.py:98
#   "get_cost_centers"  -> CostCenter      (DEPARTMENT)                   service.py:100
#   "get_locations"     -> Location                                      service.py:96
#   "get_location_hierarchy_assignments" -> LocationHierarchyAssignmentsType  service.py:229
# Worker model fields driving edges (parrot_tools/interfaces/workday/models/worker.py):
#   manager_id / direct_manager_id (l.10/176)  -> reports_to
#   supervisory_organization_id (l.201)         -> member_of_division
#   cost_center_id / cost_center_hierarchy_name (l.196/198) -> belongs_to_department
#   business_site_location_id (l.167)           -> located_at
# Location.superior_location_id (location.py:24) -> location hierarchy edge
# Seeding uses the composable directly: await svc.fetch_models("get_cost_centers"), etc.
# (these are composable operations, broader than the 11 homologated agent tools)

#### Mixin composition is proven
```python
# Cooperative MRO works (verified):
class PandasAgent(IntentRouterMixin, BasicAgent): ...          # parrot/bots/data.py:459
class WikiAgent(OntologyRAGMixin, BasicAgent): ...             # examples/knowledge_wiki/wiki.py:332
# FEAT-071 stacks IntentRouterMixin + OntologyRAGMixin + ProductAdvisorMixin + BaseBot
# => WorkdayAgent(IntentRouterMixin, OntologyRAGMixin, BasicAgent) + WorkdayToolkit is valid.
```

#### Identity carril (Stage 1 ↔ ontology, same mechanism)
```python
# OntologyRAGMixin._get_permission_context() (mixin.py:140) -> ToolCallDispatcher passes
# _permission_context -> toolkit._pre_execute (toolkit.py:306; ALWAYS injected 174-179)
# Reference: JiraToolkit._pre_execute resolves per-user identity (jiratoolkit.py:866).
# UserInfo.search(query, user_id) returns associate_id AS employee_id AND manager_id
#   (parrot/stores/kb/user.py:43-53) -> worker_id resolution + direct-report check.
```

#### Related existing specs (ecosystem already built/approved)
```
FEAT-070 intent-router.spec.md / intent-router-mixin-embedding-routing.spec.md / router-based-adaptive-rag.spec.md
graphindex.spec.md / FEAT-190 signal-relevance / FEAT-191 louvain-communities / FEAT-192 toolkit-write-and-signals
ontological-graph-rag.spec.md / ontology-entity-extraction.spec.md / topic-authority-ontology.spec.md
pageindex-content-store-and-llm-wiki-foundations.spec.md / move-pageindex-kb.spec.md
advisor-ontologic-rag-agent.spec.md (FEAT-071)  <-- canonical multi-mixin agent
```

### Does NOT Exist (Anti-Hallucination)
- ~~a Workday→graph/ontology seeder/extractor~~ — none; Stage 2 must build one (model on `GraphIndexBuilder` extractors `builder.py:30-32`, or the direct-assembler path in `wiki.py:269` fed from `WorkdayToolkit`).
- ~~an org ontology (YAML) for employees/divisions/managers~~ — must be authored (Stage 2); it belongs in the private repo (C4).
- ~~`WikiAgent`/`build_wiki_agent` as framework API~~ — they live in `examples/knowledge_wiki/` (inline glue), NOT the framework; `build_graphindex_toolkit` is flagged as not-yet-shipped glue.
- ~~IntentRouter in PR #931's WikiAgent~~ — the wiki example does NOT use IntentRouter; routing is a Stage-3 addition.
- ~~a registered Workday agent anywhere~~ — confirmed none (parrot or navigator-plugins); created in the private repo (C4).

---

## Parallelism Assessment

- **Internal parallelism**: the program is **3 sequential stages** (Stage 1 → 2 → 3)
  by dependency (router needs ≥2 edges; graph needs verified toolkit). Within
  Stage 2, the **Workday→graph seeder** (framework, parrot) and the **org ontology
  authoring** (private repo) are largely independent and could be parallel.
- **Cross-feature independence**: depends on FEAT-230 (done), reuses FEAT-070/071
  and the graphindex/ontology/pageindex specs. The seeder shares
  `parrot/knowledge/graphindex/` with that subsystem's owners — coordinate.
- **Recommended isolation**: **mixed across stages** — one (or two) spec(s) per
  stage; Stage 1 = the existing Telegram brainstorm → its own spec.
- **Rationale**: staging keeps the security-sensitive identity work (Stage 1) and
  the data-modeling work (Stage 2) reviewable in isolation, and defers routing
  complexity until it pays off.

---

## Open Questions

- [x] Big-bang vs staged? — *Owner: Jesus*: staged (Stage 1 ops+identity → Stage 2 org graph/ontology → Stage 3 wiki+router).
- [x] Where does the graph/ontology data come from? — *Owner: Jesus*: TWO sources — org structure seeded from Workday (flowtask component + FEAT-230 tools); HR **policies delivered as PDF**, ingested via `PageIndex.import_pdf` then bridged to the graph (`graph_seed_from_tree`).
- [x] Is ArangoDB available? — *Owner: Jesus*: yes.
- [x] Relationship to yesterday's brainstorm? — *Owner: Jesus*: keep it as Stage 1; this umbrella references it (no merge into one spec).
- [x] Does the agent live in parrot? — *Owner: Jesus*: no (C4) — private repo, location TBD.
- [ ] Seeder shape: a reusable `WorkdayExtractor` for `GraphIndexBuilder`, vs. the direct-assembler path fed from `WorkdayToolkit` — *Owner: implementer (Stage 2 spec)*.
- [x] Org ontology scope/granularity — *Owner: Jesus*: entities = Worker, Division/Supervisory Org, **Department (= Workday Cost Center)**, **Location**; edges = reports_to, member_of_division, belongs_to_department, located_at, + cost-center & location hierarchies. (All backed by verified composable ops/models.)
- [ ] Graph refresh cadence (full rebuild vs incremental `ingest_document`) and where it runs (scheduler?) — *Owner: implementer (Stage 2)*.
- [ ] How many specs exactly: does Stage 2 split into "seeder (parrot)" + "ontology+agent (private)"? Decide at `/sdd-spec` time — *Owner: Juan*.
- [ ] Reuse vs promote: should `build_graphindex_toolkit`/`build_wiki_agent` be promoted from the example into the framework before building the Workday agent? — *Owner: Jesus/Juan*.
- [ ] Channels beyond Telegram (Slack/Teams) for the knowledge agent — *Owner: Jesus (later)*.
