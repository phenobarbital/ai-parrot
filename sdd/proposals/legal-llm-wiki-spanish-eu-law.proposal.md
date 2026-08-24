---
id: FEAT-449
title: "Legal LLM Wiki — Spanish + EU legislation and case law as a typed, temporally-valid knowledge graph with citable answers"
slug: legal-llm-wiki-spanish-eu-law
type: feature
mode: enrichment
status: review
source:
  kind: file
  jira_key: null
  jira_url: null
  file_path: sdd/proposals/claude_legal-wiki-design.md
  fetched_at: 2026-08-23
  summary_oneline: "Legal LLM Wiki on ai-parrot — Spanish/EU law as ArangoDB knowledge graphs with temporal validity and CENDOJ-backed citation verification"
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-449/
created: 2026-08-23
updated: 2026-08-23
---

# FEAT-449 — Legal LLM Wiki: Spanish + EU law as a typed, temporally-valid knowledge graph

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `file: sdd/proposals/claude_legal-wiki-design.md`
> **Audit**: [`sdd/state/FEAT-449/`](../state/FEAT-449/)

---

## 0. Origin

The source is not a ticket but a self-declared **design skeleton**, authored with
~20 reuse claims deliberately marked `⚠️ VERIFY` and six open questions. It asked,
in its own words, to be checked against the repo before a spec exists. Full text at
`sdd/state/FEAT-449/source.md`.

> Context: one or more "brains" (LLM Wikis) for a Spanish lawyer, fed with Spanish + EU
> legislation and case law, stored as knowledge graphs in ArangoDB via `GraphIndex`, with
> CENDOJ used only as a verification/enrichment toolkit. Goal: answers that are **citable
> against primary sources with temporal validity**, never model memory.
>
> Status: skeleton. Every `⚠️ VERIFY` must be grepped against `main` before `/sdd-proposal`.
> Items marked `[assumed]` are design choices pending discussion, not facts about the repo.

**Initial signals** (extracted, not interpreted):
- **Verbs**: create, ingest, traverse, route, ground, cite, verify — uniformly additive, no negation
- **Named entities**: GraphIndex, ArangoDB, CENDOJ, BOE, EUR-Lex/CELLAR, HUDOC, Tribunal Constitucional, KnowledgeRouter, GroundednessReport, AbstractToolkit, AgentCrew, PgVector, ECLI
- **Components / labels**: none (file source, not Jira)
- **Acceptance criteria provided**: no — but two spike checklists (OQ3 CENDOJ, OQ4 CELLAR) with explicit exit criteria
- **Self-declared open questions**: 6 (OQ1–OQ6), two marked "Closed" by the author

---

## 1. Synthesis Summary

A legal LLM Wiki fits ai-parrot's knowledge stack far better than the source assumed — the legal vocabulary, the deterministic traversals, the incremental sync and the read-only guarantee are all existing declarative machinery — but two of its stated 'closed' decisions are refuted, temporal validity remains wholly greenfield, and a parallel feature (FEAT-450) is already building the multi-brain layer it needs.

Concretely: **9 of 11** reuse-inventory claims verify against the repo, and round-two research
found four further pieces of existing machinery the source assumed it would have to build —
declarative `TraversalPattern` AQL templates (F018), a CRON delta-sync pipeline (F017),
read-only AQL enforcement (F019), and idempotent live collection provisioning (F016). Two
claims are refuted: `KnowledgeRouter` does not exist — routing belongs to `IntentRouterMixin`
(F005) — and the author's "Closed" OQ1 decision is not implementable, because GraphIndex has
no namespace concept and isolates one ArangoDB database per tenant (F002). A parallel
in-flight feature, FEAT-450 wiki-namespaces, explicitly targets this same lawyer multi-brain
use case (F014). Following Phase-5 decisions D1–D5, **v1 is now Sprint 1 only**: the BOE norms
graph with zero LLM, built on an ontology tenant, which isolates the one genuinely greenfield
component — the temporal-validity data model (F011).

---

## 2. Codebase Findings

> All entries are grounded in the 20 finding digests at `sdd/state/FEAT-449/findings/`.
> Each cites the finding ID(s) that justify its inclusion. No fabricated paths or symbols.

### 2.1 Localization

The code areas relevant to this request:

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py` | `GraphIndexToolkit` | 72 | agent-facing graph tools; ground_claim/traverse/find_references confirmed, plus write tools behind a _write_supported gate and graph_history/revert_write | F001 |
| 2 | `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py` | `TenantContext` | 406-421 | the ONLY multi-graph discriminator that exists: tenant_id + arango_db + pgvector_schema + merged ontology | F002 |
| 3 | `packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py` | `tenant factory` | 49-68 | constructs arango_db=f"db_{tenant_id}" — proves database-per-tenant isolation | F002 |
| 4 | `packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py` | `GraphIndexPersistence` | 1-26 | ArangoDB write path via OntologyGraphStore + pgvector embeddings; per-tenant commit collections | F002 |
| 5 | `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py` | `EntityDef` | 40-64 | declarative entity definition (collection, key_field, properties, vectorize, extend) — the extension point for legal collections | F003 |
| 6 | `packages/ai-parrot/src/parrot/knowledge/ontology/merger.py` | `OntologyMerger.merge` | 26-51 | merges ontology YAML files into a per-tenant MergedOntology | F003 |
| 7 | `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py` | `initialize_tenant` | 71 | auto-provisions Arango collections from entity/relation defs | F003 |
| 8 | `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/field_services.ontology.yaml` | `field_services ontology` | — | the only shipped domain ontology — direct template for a legal.ontology.yaml | F003 |
| 9 | `packages/ai-parrot/src/parrot/knowledge/graphindex/meta_ontology.py` | `KIND_TO_COLLECTION / EDGE_KIND_TO_COLLECTION` | 285-312 | GraphIndex's closed gi_* vocabulary (9 entities / 10 relations), documented as additive to tenant ontologies | F003 |
| 10 | `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py` | `IntentRouterMixin` | 123 | the actual router (datasets, tools, vector stores, graph sources) — the real target for the source's 'KnowledgeRouter' | F005 |
| 11 | `packages/ai-parrot/src/parrot/knowledge/ontology/intent.py` | `OntologyIntentResolver` | 1-14 | soft-deprecated dual-path (keyword fast path + LLM) resolver; must NOT be built on | F005 |
| 12 | `packages/ai-parrot/src/parrot/security/groundedness/policy.py` | `GroundednessReport` | 58 | the anti-hallucination report contract claimed by the source | F006 |
| 13 | `packages/ai-parrot/src/parrot/security/groundedness/scorer.py` | `GroundednessScorer.score` | 56-74 | deterministic (detection-only) groundedness scoring over an EvidenceIndex | F006 |
| 14 | `packages/ai-parrot/src/parrot/tools/manager.py` | `ToolManager.execute_tool` | 1519, 1573-1610 | the interception seam where a code-enforced CENDOJ call budget would live | F007 |
| 15 | `packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py` | `PBACToolCallGuardrail` | 1-14 | existing TOOL_CALL guardrail; runs first in execute_tool; ALLOW/DENY only, no counting | F007 |
| 16 | `packages/ai-parrot/src/parrot/bots/guardrails/base.py` | `GuardrailStage.TOOL_CALL` | 15-30 | the pre-execution stage a call-budget guardrail would register against | F007 |
| 17 | `packages/ai-parrot/src/parrot/tools/compression/budget.py` | `CircuitBreaker` | 195 | the repo's only CircuitBreaker — reference implementation for the CENDOJ breaker, but coupled to codec latency | F008 |
| 18 | `packages/ai-parrot/src/parrot/scheduler/__init__.py` | `schedule` | 1-20 | lazy shim; the @schedule decorator resolves into ai-parrot-server[scheduler] | F009 |
| 19 | `packages/ai-parrot/src/parrot/bots/flows/crew/tool_node.py` | `ToolNode` | 168 | deterministic tool step for the retrieval DAG in the source's 4.2 | F009 |
| 20 | `packages/ai-parrot/src/parrot/tools/vectorstoresearch.py` | `VectorStoreSearchTool` | 48 | PgVector chunk retrieval tool mounted per knowledge base | F009, F010 |
| 21 | `agents/security_advisor.py` | `SecurityAdvisor / _audit_citations` | 1-27, 424-433 | working precedent: read-only grounded agent, mandatory references, citations re-audited, unvalidated items routed to human review | F010 |
| 22 | `packages/ai-parrot/src/parrot/knowledge/graphindex/mixin.py` | `GraphMemoryMixin` | 30 | mounts a GraphIndex graph onto an agent as tools | F010 |
| 23 | `examples/knowledge_wiki/wiki.py` | `LLM Wiki example` | 1-24 | closest existing 'LLM Wiki' composition: PageIndex + GraphIndex + Ontology; degrades gracefully without ArangoDB | F010 |
| 24 | `packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py` | `AutonomousOrchestrator` | 231, 1400-1414 | the in-repo enqueue/resume primitive relevant to OQ6 (async lazy ingest); re-enqueue is explicitly non-idempotent | F011 |
| 25 | `packages/ai-parrot/src/parrot/interfaces/__init__.py` | `interfaces package` | 1-9 | mixins package — NOT a Pydantic contracts home; refutes the proposed parrot.interfaces.legal placement | F012 |
| 26 | `packages/ai-parrot/src/parrot/security/audit_ledger.py` | `AuditLedger / AuditLedgerEntry` | 80, 296 | attribution ledger for the CENDOJ 'attributable to a lawyer, not a crawler' requirement | F013 |
| 27 | `sdd/state/FEAT-450/source.md` | `FEAT-450 wiki-namespaces` | 1-40 | live parallel proposal federating N wiki stores behind ns::id; its Problem statement names the lawyer multi-brain case explicitly and includes an arangodb namespace kind keyed by database | F014 |
| 28 | `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py` | `ArangoDBWikiStore` | 160-175 | wiki plane already isolates one Arango database per wiki via a database constructor arg | F014 |
| 29 | `packages/ai-parrot/src/parrot/knowledge/wiki/models.py` | `WikiPageCategory / WikiSearchResult` | 25, 227-268 | the wiki plane's data model is pages+categories, with no entity/relation vocabulary for legal edges | F015 |
| 30 | `packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py` | `wiki ingest orchestrator` | 1-22 | already bridges the wiki plane into GraphIndex via sync_graph=True, making a layered architecture viable | F015 |
| 31 | `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py` | `ensure_collection / initialize_tenant` | 71, 462-488 | idempotent on-demand vertex/edge collection creation — legal collections can be added to a live tenant | F016 |
| 32 | `packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py` | `TenantOntologyManager` | 29, 167, 198, 208, 280-338 | templated tenant DB naming plus overlay/YAML-chain resolution — makes tenant-per-materia cheap and layerable | F016 |
| 33 | `packages/ai-parrot/src/parrot/knowledge/ontology/refresh.py` | `refresh pipeline / DiffResult` | 1-34 | existing CRON delta sync: EXTRACT/DIFF/APPLY(upsert+soft-delete)/REDISCOVER/SYNC pgvector/INVALIDATE — the BOE-EUR-Lex incremental sync the source planned to build | F017 |
| 34 | `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py` | `TraversalPattern` | 263-290 | declarative AQL template + bind vars + trigger_intents + authorization + post-traversal tool_call — makes article_in_force/case_chain/what_applies configuration | F018 |
| 35 | `packages/ai-parrot/src/parrot/knowledge/ontology/validators.py` | `AQL validators` | 1-28 | rejects mutation keywords, system collections and JS in graph queries — enforces read-only below the tool layer | F019 |
| 36 | `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py` | `GraphIndexBuilder / ingest_document` | 1-17, 353-390 | 6-stage pipeline with atomic per-document refresh via replace_document_slice — the mechanism for CENDOJ lazy ingest and consolidated re-ingest | F020 |
| 37 | `packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py` | `UniversalNode / NodeKind` | 143-171 | GraphIndex write path uses a CLOSED NodeKind enum with free-form metadata only in domain_tags — typed legal entities need the ontology write path instead | F020 |
| 38 | `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/loader.py` | `LoaderExtractor` | — | existing bridge from parrot_loaders output into the graph pipeline | F020 |

### 2.2 Constraints Discovered

Conventions, contracts, and existing machinery any solution must respect.

- **GraphIndex has no namespace concept; the only isolation unit is TenantContext, which allocates a separate ArangoDB database (and pgvector schema) per tenant.**
  *Implication*: The source's OQ1 'Closed: single Arango DB, GraphIndex namespaces over shared collections, tenancy as a second discriminator' is not implementable as written. Either legal materias become tenants (one DB each, inverting the OQ1 decision), or a namespace discriminator is new framework work.
  *Evidence*: F002

- **The graph entity/edge vocabulary is declarative YAML merged per tenant, with auto-provisioning of Arango collections and a shipped domain example.**
  *Implication*: The legal collections (norma, articulo, sentencia, modifica, deroga, cita...) are configuration, not a GraphIndex fork. This is the single largest de-risking of the design.
  *Evidence*: F003

- **No temporal-validity machinery exists anywhere in parrot/knowledge/ (2 grep hits, both unrelated).**
  *Implication*: versions[], article_in_force(as_of), per-version chunks and as_of-filtered vector retrieval are entirely new, with no pattern to copy. This is the design's hardest component and its correctness gate.
  *Evidence*: F011

- **The TOOL_CALL guardrail seam exists and runs first inside ToolManager.execute_tool, but zero counting/rate-limiting guardrails ship.**
  *Implication*: Code-enforced CENDOJ budgets are achievable as a new Guardrail subclass on an existing extension point — small, well-bounded new work, not a ToolManager change.
  *Evidence*: F007

- **A grounded, read-only, citation-audited advisory agent already exists end-to-end in agents/security_advisor.py, including a citation re-audit that gates automated action.**
  *Implication*: LegalAnswerAgent and the verified/pending_verification gate should extend a proven pattern rather than be designed fresh; note agents/ is gitignored and needs git add -f.
  *Evidence*: F010

- **The @schedule decorator lives in the ai-parrot-server[scheduler] satellite, reachable from core only via a lazy __getattr__ shim.**
  *Implication*: Daily BOE/EUR-Lex sync implies an ai-parrot-server dependency or an external scheduler calling an ingestion entrypoint; the spec must say which.
  *Evidence*: F009

- **parrot.interfaces is documented as a mixins package for bot functionality, not a home for domain data models.**
  *Implication*: CaseRef/CendojVerification/LegalAnswer belong in the toolkit tree (the source's own parrot_tools/legal/... layout), not at parrot.interfaces.legal.
  *Evidence*: F012

- **No legal-domain code exists in the repo; the commit titled 'new tooling for legal resources' added only the design document.**
  *Implication*: Nothing to reconcile or migrate — but also no partial head start, so every sprint in the roadmap is from zero.
  *Evidence*: F004

- **The repo's only CircuitBreaker is embedded in the compression codec latency router; there is no shared throttled HTTP client abstraction.**
  *Implication*: The CENDOJ shared client (semaphore pacing, Retry-After, 15-min breaker) is new infrastructure with one class worth studying, not inheriting.
  *Evidence*: F008

- **FEAT-450 wiki-namespaces is a live parallel proposal whose stated goal explicitly includes composing a lawyer's legislation/jurisprudence/own-cases brains behind ns::id routing, with an arangodb namespace kind keyed by database.**
  *Implication*: The brain-federation half of U1 is being solved concurrently. This feature should consume FEAT-450 rather than design its own multiplicity scheme — and should coordinate, since FEAT-450 v1 defers the intent-based router that the legal design's 4.1 assumes.
  *Evidence*: F014

- **The wiki plane models pages and categories, not typed entities, but its ingest orchestrator already mirrors nodes into GraphIndex via sync_graph=True.**
  *Implication*: A layered answer is available: wiki namespaces for brain selection and document ingest, GraphIndex+Ontology beneath for the typed legal graph. These are complementary, not a fork.
  *Evidence*: F015

- **Collections can be added to a live tenant idempotently via ensure_collection, and tenant database naming is a configurable template with overlay support.**
  *Implication*: Choosing tenant-per-materia is reversible and incremental; the 'wrong choice means migrate everything' fear is materially weaker than assumed.
  *Evidence*: F016

- **A six-stage CRON delta-sync pipeline already exists at the ontology layer (EXTRACT/DIFF/APPLY with soft-delete/REDISCOVER/SYNC embeddings/INVALIDATE).**
  *Implication*: boe_sync_consolidated(since) and the daily incremental sync are largely configuration of existing machinery, not new infrastructure.
  *Evidence*: F017

- **TraversalPattern expresses a named AQL template with bind variables, keyword fast-path triggers, declarative authorization and a post-traversal tool_call, loadable from ontology overlays.**
  *Implication*: The deterministic traversals in 3.4 become declarative config with as_of as a bind variable, and the CENDOJ verification step has a native hook — removing the query layer from the greenfield column.
  *Evidence*: F018

- **Graph queries are validated read-only at the AQL layer: mutations, system collections and JavaScript are rejected.**
  *Implication*: The read-only-agent invariant is enforced below the tool layer, so the source's separate writer/reader toolkit split may be unnecessary ceremony.
  *Evidence*: F019

- **There are two distinct write paths — GraphIndexBuilder writing UniversalNodes under a closed NodeKind enum, and the ontology EntityDef path writing arbitrary typed collections.**
  *Implication*: Typed legal entities require the ontology path, but the loader/embedding/incremental-refresh pipeline lives on the GraphIndex path. Reconciling the two is a design decision the source never considered and is now the sharpest open technical question.
  *Evidence*: F020, F003

### 2.3 Recent History (Relevant)

| Commit | When | Message | Touched files |
|--------|------|---------|---------------|
| `db9b32dff` | 2026-08-23 | new tooling for legal resources | `sdd/proposals/claude_legal-wiki-design.md` (289 insertions) — **document only, zero code** |
| `de08ac3e2` | 2026-08-23 | sdd: reserve 1 feature id(s) for wiki-namespaces | `sdd/tasks/.id_ledger.json` — FEAT-450, the parallel namespaces feature |

The commit whose message promised "new tooling for legal resources" added only the design
document that is this proposal's own source. There is no legal-domain code anywhere in
`packages/` — a grep for `cendoj|eurlex|celex|BOE-A-|ECLI:` returns zero matches (F004).
Absence of prior art is itself the finding: nothing to migrate, but no head start either.

---

## 3. Probable Scope

### What's New

- parrot_tools/legal/ids.py — ECLI/ROJ/BOE/CELEX regex + normalisation, shared by every legal toolkit
- parrot_tools/legal/{boe,eurlex,tc,hudoc,cendoj}/ — one AbstractToolkit per source
- legal.ontology.yaml — entity/relation defs AND the traversal patterns for article_in_force / case_chain / what_applies (declarative, per F018)
- The temporal-validity DATA MODEL: versions[] on articulo, per-version chunking, and the derived flag — still no in-repo precedent (F011)
- A counting Guardrail at GuardrailStage.TOOL_CALL enforcing per-execution CENDOJ call budgets
- A shared throttled CENDOJ HTTP client (process-level semaphore, jittered pacing, Retry-After, circuit breaker, immutable cache)
- LegalAnswer / LegalClaim / SourceRef contracts plus the retrieval-set post-check
- A reconciliation between the GraphIndex UniversalNode write path and the ontology EntityDef write path (F020)

### What Changes

- **`packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/`** — add legal.ontology.yaml alongside field_services.ontology.yaml  *Evidence*: F003
- **`packages/ai-parrot/src/parrot/bots/guardrails/builtin/`** — add a call-budget guardrail next to pbac.py/moderation.py  *Evidence*: F007
- **`packages/ai-parrot/src/parrot/knowledge/graphindex/`** — ONLY IF the namespace fork is chosen — add a namespace discriminator; otherwise untouched  *Evidence*: F002
- **`packages/ai-parrot/src/parrot/knowledge/ontology/refresh.py`** — configure legal sources into the existing delta-sync pipeline rather than writing a new sync  *Evidence*: F017
- **`packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py`** — potentially consume as the document/brain layer above the typed graph, per FEAT-450  *Evidence*: F015, F014

### What's Untouched (Non-Goals)

Explicitly out of scope, to prevent later scope creep:

- GraphIndexToolkit — its tool surface already covers the read path (F001)
- The groundedness subsystem — used as-is (F006)
- ToolManager.execute_tool — the guardrail seam is used, not modified (F007)
- IntentRouterMixin — configured, not forked (F005)
- Loaders — PDFMarkdownLoader/HTMLLoader/WebLoader/MarkdownLoader used as shipped (F009)
- ontology/validators.py — read-only AQL enforcement inherited as-is (F019)
- TraversalPattern machinery — authored against, not modified (F018)
- GraphIndexBuilder incremental refresh — configured via LoaderExtractor, not forked (F020)
- **Sprints 2–5 of the source roadmap** — case law bulk ingestion, the CENDOJ toolkit, the
  router and retrieval DAG, `LegalAnswer`, and LLM-extracted edges are all follow-up features,
  not this spec (D4).
- **Namespace routing** — deferred to FEAT-450 integration after v1 (D2).

### Patterns to Follow

- Grounded read-only agent with mandatory references and a citation re-audit gating automated action  *Evidence*: F010
- Declarative YAML domain ontology with auto-provisioned collections  *Evidence*: F003
- Deterministic ToolNode stages before any LLM node in the DAG  *Evidence*: F009
- Per-toolkit model modules rather than a central contracts package  *Evidence*: F012
- Declarative TraversalPattern with bind variables and trigger_intents instead of bespoke traversal code  *Evidence*: F018
- Atomic per-document refresh via replace_document_slice for lazy ingest  *Evidence*: F020

### Integration Risks

- 🔴 **HIGH** — Two incompatible write paths — GraphIndexBuilder's closed NodeKind enum vs the ontology's arbitrary typed collections — and the loader/embedding/incremental pipeline sits on the wrong one for typed legal entities  *Evidence*: F020, F003
- 🔴 **HIGH** — The temporal-validity DATA MODEL remains entirely greenfield and is the design's correctness gate; the EUR-Lex half rests on a diff-derived approximation the source itself flags as derived=true  *Evidence*: F011
- 🔴 **HIGH** — CENDOJ is the only verification path for Spanish ordinary case law and is an unsanctioned scrape with a captcha/429 posture; if unusable, the verified tier collapses to commercial backends or nothing  *Evidence*: F004, F008
- 🟡 **MEDIUM** — FEAT-450 is building the multi-brain layer concurrently and defers the intent router this design depends on; uncoordinated, the two features will duplicate or contradict each other  *Evidence*: F014
- 🟡 **MEDIUM** — A five-sprint roadmap with two blocking spikes is far past what a single spec should carry  *Evidence*: F004

---

## 4. Confidence Map

Every atomic claim in this proposal, with evidence and confidence. Readers can audit the
proposal by walking this table.

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | GraphIndexToolkit exists and exposes ground_claim, traverse and find_references under exactly those names | F001 | high | Direct grep on the class and all three method definitions with line numbers. |
| C2 | GraphIndex has no namespace mechanism; graph isolation is one ArangoDB database per tenant via TenantContext | F002 | high | Exhaustive case-insensitive grep of the package returned a single unrelated hit, and TenantContext.arango_db plus factory.py's db_{tenant_id} were read directly. |
| C3 | The legal entity/edge vocabulary can be added as a declarative YAML ontology without forking GraphIndex | F003 | high | EntityDef fields, OntologyMerger.merge(yaml_paths), initialize_tenant and a shipped domain ontology were each read directly. |
| C4 | No legal-domain code exists in the repo | F004 | high | Zero matches for the union of cendoj/eurlex/celex/BOE-A-/ECLI across all packages, plus the commit stat showing one doc-only file. |
| C5 | There is no KnowledgeRouter; routing belongs to IntentRouterMixin and the ontology resolver it replaced is soft-deprecated | F005 | high | No symbol match, plus the deprecation notice read verbatim in intent.py's docstring. |
| C6 | GroundednessReport and a deterministic groundedness scorer exist as a full subsystem | F006 | high | Class and method definitions located with line numbers; package contents listed. |
| C7 | Per-execution tool-call budgets can be enforced at GuardrailStage.TOOL_CALL, but no counting guardrail ships today | F007 | high | The seam was read in manager.py and pbac.py; the absence is a zero-count grep across the whole guardrails tree. |
| C8 | No temporal-validity or as-of machinery exists in the knowledge layer | F011 | high | Two grep hits across the entire subtree, both an unrelated local variable. |
| C9 | agents/security_advisor.py is a working precedent for the LegalAnswerAgent pattern including the verified/pending gate | F010 | high | Module docstring and _audit_citations docstring read directly; both describe mandatory references and routing unvalidated items to human review. |
| C10 | The @schedule decorator is only available with ai-parrot-server[scheduler] installed | F009 | high | The core scheduler package is a 38-line lazy shim whose _SERVER_CLASSES mapping and install hint were read in full. |
| C11 | parrot.interfaces is the wrong home for the legal Pydantic contracts | F012 | high | Package docstring defines it as mixins for bot functionality; contents are connection interfaces. |
| C12 | AuditLedger and permission_context can carry CENDOJ request attribution | F013 | medium | Both exist and permission_context demonstrably reaches ToolManager.execute_tool, but two distinct AuditLedger classes exist and neither was read in depth to confirm it fits per-tool-call attribution. |
| C13 | The autonomous orchestrator is the available primitive for OQ6's deferred lazy ingestion | F011 | medium | Enqueue/resume/re-enqueue exist in the server satellite, but it is designed for autonomous executions, not a general ingest queue, and re-enqueue is documented as non-idempotent. |
| C14 | The CENDOJ shared client must be built from scratch; only a codec-coupled CircuitBreaker exists to study | F008 | medium | The single CircuitBreaker was located and its purpose read, and no HTTP-facing usage was found — but absence of a throttled client rests on a filename/symbol search rather than an exhaustive audit. |
| C15 | Choosing the multiplicity model wrong is recoverable: collections are added to live tenants idempotently and tenant DB naming is templated | F016 | medium | ensure_collection and the templated db name were read directly; 'recoverable' still extrapolates beyond any migration tooling actually examined. |
| C16 | FEAT-450 wiki-namespaces is a live parallel proposal that explicitly targets the lawyer multi-brain use case and supports an arangodb namespace keyed by database | F014 | high | Its source.md and its own F015 finding were read directly, including the verbatim lawyer sentence. |
| C17 | The wiki plane cannot carry typed legal entities, but already bridges into GraphIndex via sync_graph=True | F015 | high | Both the models module and the ingest orchestrator's documented step 5 were read directly. |
| C18 | An incremental delta-sync pipeline with soft-delete and embedding sync already exists at the ontology layer | F017 | high | The six stages are enumerated verbatim in refresh.py's module docstring. |
| C19 | The deterministic legal traversals can be authored as declarative TraversalPatterns with as_of as a bind variable | F018 | medium | The TraversalPattern contract supports AQL templates with bind variables and a tool_call hook, but no temporal pattern was found in practice, so applicability to as_of resolution is inferred. |
| C20 | Read-only graph access is enforced at the AQL layer independently of tool-level guardrails | F019 | high | The mutation, system-collection and JS regexes were read directly in validators.py. |
| C21 | Typed legal entities require the ontology write path, while the loader/embedding/incremental pipeline runs on the GraphIndex UniversalNode path | F020, F003 | high | UniversalNode.kind is a closed NodeKind enum mapped to fixed gi_* collections, whereas EntityDef accepts arbitrary collections; both were read directly. |

Distribution: **16** high, **5** medium, **0** low.

`overall_confidence` is **medium**, capped by scope confidence rather than by evidence quality:
research was not truncated (26 files, 33 greps, 3 git — inside the `loose` budget), and every
localization entry traces to a direct grep or read performed this run. The ceiling reflects the
one component with no in-repo precedent (the temporal data model, C8) and the newly surfaced
two-write-path tension (C21).

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Given that FEAT-450 is already building wiki namespaces for exactly this multi-brain case (F014) and that typed legal entities need the ontology write path rather than the GraphIndex one (F020,C21), what is the substrate split?**
  *Resolved*: Layered: FEAT-450 wiki namespaces for brain selection and document ingest, with one ontology tenant per materia beneath carrying the typed legal graph. This inverts the source's OQ1 — isolation is a database per materia, not namespaces over shared collections.
  *Resolves claims*: C2, C16, C17, C21

- [x] **Should this feature block on FEAT-450, or proceed independently and integrate later?**
  *Resolved*: Proceed independently and integrate later. Build the typed legal graph on an ontology tenant now; adopt namespace routing when FEAT-450 lands. The integration seam is the wiki ingest sync_graph bridge.
  *Resolves claims*: C16

- [x] **Does the firm hold (or intend to buy) a vLex or Aranzadi licence?**
  *Resolved*: No commercial licence. CENDOJ is the only verification path for Spanish ordinary case law, so the OQ3 spike is blocking and the terms-of-use risk must be owned explicitly.
  *Resolves claims*: C4

- [x] **What is the v1 deliverable? The source's roadmap is five sprints with two blocking spikes, which is well past one spec.**
  *Resolved*: Sprint 1 only — the BOE norms graph with zero LLM: legal.ontology.yaml, BOE consolidated ingestion, versions[], and article_in_force as declarative TraversalPatterns, tested against known amendment chains.
  *Resolves claims*: —

- [x] **Will the deployment include ai-parrot-server, or is this a core-only install?**
  *Resolved*: Yes — ai-parrot-server is in the deployment, so @schedule and the autonomous orchestrator are available for daily sync and for deferred lazy ingest (OQ6).
  *Resolves claims*: C10, C13

### Decisions and their consequences

The five answers above collapse into five binding decisions:


**D1** (from U1) — Layered: FEAT-450 wiki namespaces for brain selection and document ingest, with one ontology tenant per materia beneath carrying the typed legal graph. This inverts the source's OQ1 — isolation is a database per materia, not namespaces over shared collections.

  - The source's OQ1 'Closed' decision is formally superseded — record the inversion in the spec.
  - Legal collections are provisioned per materia tenant via ensure_collection/initialize_tenant (F016).
  - The GraphIndex UniversalNode write path is NOT the store for typed legal entities; the ontology EntityDef path is (C21, F020).
  - *Evidence*: F002, F003, F014, F015, F016, F020

**D2** (from U6) — Proceed independently and integrate later. Build the typed legal graph on an ontology tenant now; adopt namespace routing when FEAT-450 lands. The integration seam is the wiki ingest sync_graph bridge.

  - No hard dependency on FEAT-450 for v1; namespace routing is a post-v1 integration.
  - Coordinate on FEAT-450's deferred intent router, which the legal design's 4.1 assumes.
  - v1 addresses a single materia, so brain federation is not yet on the critical path.
  - *Evidence*: F014, F015

**D3** (from U2) — No commercial licence. CENDOJ is the only verification path for Spanish ordinary case law, so the OQ3 spike is blocking and the terms-of-use risk must be owned explicitly.

  - The OQ3 CENDOJ spike is blocking for any 'verified' Spanish case-law tier.
  - The verify/search/fetch contract should still be written backend-agnostically so a licence can be adopted later without redesign.
  - Terms-of-use risk ownership must be stated in the spec (carried over from the displaced U5).
  - *Evidence*: F004, F008

**D4** (from U3) — Sprint 1 only — the BOE norms graph with zero LLM: legal.ontology.yaml, BOE consolidated ingestion, versions[], and article_in_force as declarative TraversalPatterns, tested against known amendment chains.

  - v1 excludes CENDOJ, case law, the router, and LegalAnswer — so D3's blocking spike does not block v1.
  - v1 targets the one genuinely greenfield component (the temporal data model, F011) while reusing TraversalPattern (F018) and refresh.py (F017).
  - Sprints 2-5 of the source roadmap become follow-up features, not this spec.
  - *Evidence*: F011, F017, F018

**D5** (from U4) — Yes — ai-parrot-server is in the deployment, so @schedule and the autonomous orchestrator are available for daily sync and for deferred lazy ingest (OQ6).

  - @schedule is available for daily BOE sync (F009); no external cron required.
  - OQ6 can resolve to deferred ingest via the autonomous orchestrator, noting its non-idempotent re-enqueue caveat (C13, F011).
  - v1 is zero-LLM and BOE-only, so OQ6 is not yet exercised.
  - *Evidence*: F009, F011

### Unresolved (defer to spec / implementation)

- [ ] **Who accepts the terms-of-use risk for automated CENDOJ access, and is there written
  authorization from the firm?** — *Owner*: tbd
  *Blocks*: any "verified" tier for Spanish ordinary case law (D3)
  *Plausible answers*: a) the firm accepts it, documented in the spec, with the human-paced
  posture as mitigation · b) legal review required before any spike runs · c) restrict
  verification to official bulk sources (TC, CJEU, HUDOC)
  *Note*: not blocking for v1, which is BOE-only and excludes case law (D4).

- [ ] **How are the two write paths reconciled?** — *Owner*: tbd
  *Blocks claims*: C21
  *Context*: typed legal entities need the ontology `EntityDef` path, but the loader,
  embedding and incremental-refresh pipeline lives on the GraphIndex `UniversalNode` path
  (F020). v1 is small enough to sidestep this, but the spec should state which path BOE
  ingestion uses and why.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-449`** — *Rationale*: All five unknowns are resolved and v1 is now scoped to a single self-contained deliverable (BOE norms graph, zero LLM) whose substrate, sequencing and deployment are all decided — the architectural fork that argued for brainstorming has been closed by D1 and D2.

Scope the spec to **D4 only** — the BOE norms graph, zero LLM:

1. `legal.ontology.yaml` declaring `norma`, `articulo`, `materia` entities and the
   `modifica` / `deroga` edges, following `field_services.ontology.yaml` (F003).
2. BOE consolidated ingestion configured into the existing `refresh.py` delta-sync
   pipeline rather than a bespoke sync (F017).
3. The `versions[]` embedded-history data model on `articulo` — the genuinely new
   part, with no precedent to copy (F011).
4. `article_in_force(as_of)` authored as a declarative `TraversalPattern` with `as_of`
   as a bind variable (F018).
5. Acceptance tested against known amendment chains (the source suggests LOPDGDD vs RGPD).

### Alternatives

- **`/sdd-brainstorm FEAT-449`** — if you want to reopen the substrate question that D1
  closed, or explore how to reconcile the two write paths before committing.
- **`/sdd-task FEAT-449`** — not appropriate: even the narrowed v1 spans an ontology
  definition, an ingestion path, a new data model and a traversal pattern.
- **Manual review** — not indicated; research was complete and lint passed.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-449/state.json` |
| Source (raw) | `sdd/state/FEAT-449/source.md` |
| Research plan | `sdd/state/FEAT-449/research_plan.json` (30 queries, 2 rounds) |
| Findings (digests) | `sdd/state/FEAT-449/findings/F001-*.md` … `F020-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-449/synthesis.json` |
| Synthesis reasoning | `sdd/state/FEAT-449/synthesis.thinking.md` |

**Budget consumed** (profile: `loose`):
- Files read: 26 / 100
- Grep calls: 33 / 60
- Git calls: 3 / 20
- Wiki queries: 9 (free, not budgeted)
- Max depth reached: 3 / 3
- Truncated: **no**

**Research rounds**: 2. Round one ran the 18 planned queries; the user declined the first
review gate and requested a refine round, adding 12 queries across four lanes (FEAT-450
overlap, tenant provisioning and migration cost, the AQL traversal surface, and the
ingestion/chunking path). Round two produced F014–F020 and materially changed the
recommendation.

**Mode determination**: `auto` → resolved to `enrichment` (uniformly additive verbs, no
negation, no defect described).

**Lint**: passed, 0 violations across both synthesis rounds (1 corrective iteration after
round two expanded the finding set).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara |
| FEAT-ID allocation | `scripts/sdd/reserve_ids.py` → commit `a234dfe1c` |
